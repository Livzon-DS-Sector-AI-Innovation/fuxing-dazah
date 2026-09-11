"""共享的批量翻译执行器：docx 与 PDF 两条流水线共用。

掩码 → 批量请求（顺序或线程池并发）→ 还原校验 → 结果消费，
worker 线程只做纯请求（translate_batch 无共享可变状态），
掩码还原与结果消费全部在主线程完成。

依赖翻译单元的最小接口：u.idx / u.text / u.lang / u.in_table / u.translation。
"""
from __future__ import annotations

from .mask import mask
from .translate import TranslationError

TARGET_LANG = {"zh2en": "英文（English）", "en2zh": "中文（简体中文）", "auto": "对方语言"}

# 翻译阶段内的进度权重：批次翻译占 0~0.9，占位符重译占 0.9~1.0。
# 重译单元少但每个一次请求，不留进度的话进度条会在尾部长时间不动（看起来像卡死）。
_BATCH_SHARE = 0.9


def _snippet(text: str, n: int = 36) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


def _where(unit) -> str:
    loc = "表格内" if unit.in_table else "正文"
    return f"#{unit.idx}（{loc}）「{_snippet(unit.text)}」"


def _date_style(u, s) -> str:
    """该段落译文行的日期格式。

    keep/iso 与方向无关；en 只在译入英文时生效、zh 只在译入中文时生效，
    方向不匹配时退回 keep（不转换）。
    """
    if s.date_format in ("keep", "iso"):
        return s.date_format
    target = {"zh2en": "en", "en2zh": "zh"}.get(s.direction, "en" if u.lang == "zh" else "zh")
    return s.date_format if s.date_format == target else "keep"


def translate_all(batches, translator, s, glossary, todo, pos_of, ctx, progress_cb=None) -> list:
    """执行全部翻译批次，填充 u.translation 与 ctx 标记，返回失败单元列表。

    mock 或 concurrency=1 时顺序执行；否则线程池并发。
    progress_cb(frac, message)：每完成一批回调一次，frac 为翻译阶段完成度 0.0~1.0。
    """
    from tqdm import tqdm

    def _prep(batch):
        masked_map = {u.idx: mask(u.text) for u in batch}
        items = [(u.idx, masked_map[u.idx].masked) for u in batch]
        # 相邻段落作为上下文提示，帮助模型保持术语与指代连贯
        first_pos = pos_of[id(batch[0])]
        prev_context = todo[first_pos - 1].text[:160] if first_pos > 0 else ""
        return items, masked_map, prev_context

    def _consume(batch, masked_map, results) -> list:
        """消费一批结果，返回占位符异常需重试的 [(unit, 上次译文)]。"""
        retry: list = []
        for u in batch:
            translated = results.get(u.idx, "")
            restored, anomalies = masked_map[u.idx].restore(translated, _date_style(u, s))
            if not translated.strip():
                ctx.add("无译文", _where(u))
            elif anomalies:
                retry.append((u, translated))
            else:
                u.translation = restored
        return retry

    def _fail(batch, e):
        for u in batch:
            ctx.add("翻译失败", f"{_where(u)}：{e}")

    def _retry_placeholder(retry_list: list, retry_progress=None) -> None:
        """占位符异常的单元各自重译一次（附明确指令），成功记提示、失败升硬性问题。

        与批次翻译同样并发：数字密集型文档（批号/规格/温度/日期都被掩码）攒下
        十几个异常单元很常见，串行重译等于在并发阶段跑完之后再挂一条几十分钟的
        尾巴，且全程占着引擎锁。请求仍在工作线程发出，掩码还原与 ctx 记录回主线程。
        """
        jobs = []
        for u, _bad_text in retry_list:
            m = mask(u.text)
            first_pos = pos_of[id(u)]
            prev = todo[first_pos - 1].text[:160] if first_pos > 0 else ""
            jobs.append((
                u, m,
                f"{prev}（重试提示：上一次译文丢失了占位符，本次所有 ⟦N⟧ 占位符必须原样保留在译文中）",
            ))

        def _send(job):
            u, m, note = job
            return translator.translate_batch(
                [(u.idx, m.masked)], TARGET_LANG[s.direction], s.doc_type,
                glossary.prompt_lines(u.lang), note,
            )

        def _consume_retry(job, translated) -> None:
            u, m, _ = job
            restored, anomalies = m.restore(translated, _date_style(u, s))
            if not translated.strip():
                ctx.add("无译文", _where(u))
            elif anomalies:
                ctx.add("占位符异常", f"{_where(u)}：重试后仍 " + "；".join(anomalies))
            else:
                u.translation = restored
                ctx.add("占位符重试成功", f"{_where(u)}：首次译文丢失占位符，单段重译通过，建议抽查")

        total = len(jobs)
        done = 0

        def _tick() -> None:
            nonlocal done
            done += 1
            if retry_progress:
                retry_progress(
                    _BATCH_SHARE + (1 - _BATCH_SHARE) * done / total,
                    f"重译占位符异常段落 {done}/{total}",
                )

        def _run(job, results=None, error=None) -> None:
            if error is not None:
                ctx.add("占位符异常", f"{_where(job[0])}：重试失败 {error}")
            else:
                _consume_retry(job, results.get(job[0].idx, ""))

        if s.concurrency <= 1 or total == 1:
            for job in jobs:
                try:
                    _run(job, results=_send(job))
                except TranslationError as e:
                    _run(job, error=e)
                _tick()
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=min(s.concurrency, total)) as pool:
            futures = {pool.submit(_send, job): job for job in jobs}
            for fut in as_completed(futures):
                job = futures[fut]
                try:
                    _run(job, results=fut.result())
                except TranslationError as e:
                    _run(job, error=e)
                _tick()

    if s.mock or s.concurrency <= 1:
        failed_units: list = []
        placeholder_retry: list = []
        total_batches = len(batches)
        done_batches = 0
        for batch in tqdm(batches, desc="翻译批次", unit="批",
                          disable=s.mock or progress_cb is not None):
            items, masked_map, prev_context = _prep(batch)
            try:
                results = translator.translate_batch(
                    items, TARGET_LANG[s.direction], s.doc_type,
                    glossary.prompt_lines(batch[0].lang), prev_context,
                )
            except TranslationError as e:
                failed_units.extend(batch)
                _fail(batch, e)
            else:
                placeholder_retry.extend(_consume(batch, masked_map, results))
            done_batches += 1
            if progress_cb:
                progress_cb(_BATCH_SHARE * (done_batches / total_batches if total_batches else 1.0),
                            f"翻译批次 {done_batches}/{total_batches}")
        if placeholder_retry and not s.mock:
            _retry_placeholder(placeholder_retry, progress_cb)
        return failed_units

    # 并发路径
    from concurrent.futures import ThreadPoolExecutor, as_completed

    failed_units: list = []
    placeholder_retry: list = []
    with ThreadPoolExecutor(max_workers=s.concurrency) as pool:
        futures = {}
        for batch in batches:
            items, masked_map, prev_context = _prep(batch)
            fut = pool.submit(
                translator.translate_batch, items, TARGET_LANG[s.direction], s.doc_type,
                glossary.prompt_lines(batch[0].lang), prev_context,
            )
            futures[fut] = (batch, masked_map)
        done_batches = 0
        for fut in tqdm(as_completed(futures), total=len(futures), desc="翻译批次", unit="批",
                        disable=progress_cb is not None):
            batch, masked_map = futures[fut]
            try:
                results = fut.result()
            except TranslationError as e:
                failed_units.extend(batch)
                _fail(batch, e)
            else:
                placeholder_retry.extend(_consume(batch, masked_map, results))
            done_batches += 1
            if progress_cb:
                progress_cb(_BATCH_SHARE * done_batches / len(futures),
                            f"翻译批次 {done_batches}/{len(futures)}")
    if placeholder_retry and not s.mock:
        _retry_placeholder(placeholder_retry, progress_cb)
    return failed_units

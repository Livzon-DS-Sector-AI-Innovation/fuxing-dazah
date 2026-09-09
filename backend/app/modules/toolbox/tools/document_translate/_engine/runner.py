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

    def _retry_placeholder(retry_list: list):
        """占位符异常的单元单独重译一次（附明确指令），成功记提示、失败升硬性问题。"""
        for u, bad_text in retry_list:
            m = mask(u.text)
            first_pos = pos_of[id(u)]
            prev = todo[first_pos - 1].text[:160] if first_pos > 0 else ""
            note = f"{prev}（重试提示：上一次译文丢失了占位符，本次所有 ⟦N⟧ 占位符必须原样保留在译文中）"
            try:
                results = translator.translate_batch(
                    [(u.idx, m.masked)], TARGET_LANG[s.direction], s.doc_type,
                    glossary.prompt_lines(u.lang), note,
                )
                translated = results.get(u.idx, "")
                restored, anomalies = m.restore(translated, _date_style(u, s))
                if not translated.strip():
                    ctx.add("无译文", _where(u))
                elif anomalies:
                    ctx.add("占位符异常", f"{_where(u)}：重试后仍 " + "；".join(anomalies))
                else:
                    u.translation = restored
                    ctx.add("占位符重试成功", f"{_where(u)}：首次译文丢失占位符，单段重译通过，建议抽查")
            except TranslationError as e:
                ctx.add("占位符异常", f"{_where(u)}：重试失败 {e}")

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
                progress_cb(done_batches / total_batches if total_batches else 1.0,
                            f"翻译批次 {done_batches}/{total_batches}")
        if placeholder_retry and not s.mock:
            _retry_placeholder(placeholder_retry)
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
                progress_cb(done_batches / len(futures), f"翻译批次 {done_batches}/{len(futures)}")
    if placeholder_retry and not s.mock:
        _retry_placeholder(placeholder_retry)
    return failed_units

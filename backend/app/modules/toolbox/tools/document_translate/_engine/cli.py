"""主流程编排：run_pipeline(Settings) 是核心入口，CLI 与 run.py 共用。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from docx import Document

from .config import Settings
from .extract import extract
from .glossary import Glossary, load_glossary
from .insert import (
    get_numbering_element,
    insert_bilingual,
    refuse_if_tracked_changes,
    replace_paragraph,
    set_update_fields,
)
from .runner import _where, translate_all
from .translate import LLMTranslator, MockTranslator, TranslationError, make_batches
from .verify import VerifyContext, check_structure, write_report


def run_pipeline(s: Settings, progress_cb=None) -> int:
    """执行完整翻译流程，返回退出码（0=正常，2=存在必须处理的问题）。

    progress_cb(percent, message)：可选进度回调，各阶段/每批次上报（0~100）。
    """
    input_path = Path(s.input)
    if not input_path.exists():
        print(f"错误：输入文件不存在 {input_path}", file=sys.stderr)
        return 2
    suffix = input_path.suffix.lower()
    if suffix == ".pdf":
        # PDF 流程：结构化抽取 → 领域预读 → 翻译 → 重排式 DOCX 输出
        from .pdf.pipeline import run_pdf_pipeline

        return run_pdf_pipeline(s)
    if suffix != ".docx":
        print("错误：仅支持 .docx / .pdf 文件", file=sys.stderr)
        return 2

    suffix = "_bilingual" if s.mode == "bilingual" else "_translated"
    output_path = Path(s.output) if s.output else input_path.with_name(input_path.stem + suffix + ".docx")
    if output_path.resolve() == input_path.resolve():
        print("错误：输出路径不能与输入相同", file=sys.stderr)
        return 2
    report_path = Path(s.report) if s.report else output_path.with_suffix(".report.md")

    glossary: Glossary = Glossary([])
    if s.glossary:
        try:
            glossary = load_glossary(s.glossary)
        except (ValueError, OSError) as e:
            print(f"错误：术语表加载失败：{e}", file=sys.stderr)
            return 2

    # ── 1. 载入与抽取 ─────────────────────────────────────────
    if progress_cb:
        progress_cb(3, "正在解析文档结构…")
    doc = Document(str(input_path))
    try:
        refuse_if_tracked_changes(doc)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2

    units, estats = extract(doc)
    numbering_el = get_numbering_element(doc)

    todo, skipped_by_direction = [], 0
    for u in units:
        if s.direction == "zh2en" and u.lang != "zh":
            u.reason, skipped_by_direction = "非中文段落（zh2en 模式跳过）", skipped_by_direction + 1
            continue
        if s.direction == "en2zh" and u.lang != "en":
            u.reason, skipped_by_direction = "非英文段落（en2zh 模式跳过）", skipped_by_direction + 1
            continue
        u.action = "translate"
        todo.append(u)

    print(f"段落抽取：共 {estats.total_paragraphs} 段（空段 {estats.empty}，"
          f"目录 {estats.toc_skipped}，文本框 {estats.textbox_skipped}，纯数字/符号 {estats.no_translatable_text}）"
          f"｜待翻译 {len(todo)} 段，方向不符跳过 {skipped_by_direction} 段")
    if progress_cb:
        progress_cb(8, f"段落抽取完成：共 {estats.total_paragraphs} 段，待翻译 {len(todo)} 段")

    ctx = VerifyContext(
        input_path=str(input_path), output_path=str(output_path),
        mode=s.mode, direction=s.direction, doc_type=s.doc_type, mock=s.mock,
        total_paragraphs_before=estats.total_paragraphs,
        stats={
            "文档总段落数": estats.total_paragraphs,
            "空段落": estats.empty,
            "目录段落（跳过，打开时更新域刷新）": estats.toc_skipped,
            "文本框内段落（v1 未翻译，需人工处理）": estats.textbox_skipped,
            "纯数字/符号段落（无需翻译）": estats.no_translatable_text,
            "含批注锚点段落（批注可能失效，建议检查）": estats.comment_refs,
            "待翻译段落": len(todo),
            f"方向不符跳过（{s.direction}）": skipped_by_direction,
        },
    )

    # ── 2. 翻译（掩码 → 批量请求 → 还原校验）──────────────────
    if s.mock:
        print("⚠️  MOCK 模式：不调用模型，译文=原文回显（用于流程自检）")
        translator = MockTranslator()
    else:
        if not s.api_key:
            print("错误：缺少 API Key。请在 config.json 中填写 api_key 字段", file=sys.stderr)
            return 2
        translator = LLMTranslator(s.api_base_url, s.api_key, s.model, max_retries=s.max_retries,
                                   thinking_level=s.thinking_level)

    batches = make_batches(todo, max_units=s.batch_size)
    pos_of = {id(u): i for i, u in enumerate(todo)}

    def _translate_progress(frac: float, message: str) -> None:
        if progress_cb:
            progress_cb(10 + int(75 * frac), message)

    failed_units = translate_all(batches, translator, s, glossary, todo, pos_of, ctx,
                                 progress_cb=_translate_progress if progress_cb else None)

    translated_units = [u for u in todo if u.translation]
    ctx.stats["翻译成功"] = len(translated_units)
    ctx.stats["翻译失败/未回写"] = len(todo) - len(translated_units)

    # 术语一致性（提示级）
    if not s.mock and glossary:
        for u in translated_units:
            for problem in glossary.check(u.text, u.translation, u.lang):
                ctx.add("术语不一致", f"{_where(u)}：{problem}")

    # ── 3. 回写 ───────────────────────────────────────────────
    if progress_cb:
        progress_cb(88, "正在回写译文…")
    written = 0              # 成功回写的段落数
    inserted_paragraphs = 0  # 实际新增的段落数（标题同段追加不算，供结构校验用）
    insert_notes: list[str] = []
    for u in translated_units:
        try:
            if s.mode == "bilingual":
                if insert_bilingual(u, u.translation, numbering_el, insert_notes) == "copy":
                    inserted_paragraphs += 1
                written += 1
            else:
                replace_paragraph(u, u.translation, insert_notes)
                written += 1
        except Exception as e:  # noqa: BLE001 —— 单段异常不影响整体交付
            ctx.add("回写失败", f"{_where(u)}：{e}")
    if s.mode == "bilingual":
        ctx.inserted_copies = inserted_paragraphs
    ctx.stats["成功回写"] = written
    for note in insert_notes:
        ctx.add("格式提示", note)

    # 格式拉平/域静态化提示（帮助人工定位抽查）
    for u in translated_units:
        if u.mixed_format:
            ctx.add("格式提示", f"{_where(u)}：段内混合字符格式，译文行已统一为首字符格式，建议抽查")
        if s.mode == "replace" and (u.has_field or u.has_hyperlink):
            ctx.add("格式提示", f"{_where(u)}：含域代码/超链接，替换模式下已静态化为纯文本，建议检查")
        if s.mode == "bilingual" and u.has_hyperlink:
            ctx.add("格式提示", f"{_where(u)}：原文含超链接，译文行为纯文本（原行链接保留）")

    # ── 4. 保存与校验 ─────────────────────────────────────────
    if progress_cb:
        progress_cb(93, "正在保存输出文件并校验…")
    set_update_fields(doc)
    doc.save(str(output_path))

    if progress_cb:
        progress_cb(97, "正在生成校验报告…")
    reopened = Document(str(output_path))
    structure_ok = check_structure(ctx, reopened)
    write_report(ctx, str(report_path))

    hard = sum(1 for f in ctx.flags if f.category in {"无译文", "占位符异常", "翻译失败", "回写失败", "结构校验失败"})
    warn = len(ctx.flags) - hard
    print(f"\n输出：{output_path}")
    print(f"报告：{report_path}")
    print(f"结构校验：{'通过' if structure_ok else '失败'}｜硬性问题 {hard} 项｜提示 {warn} 项")
    if hard:
        print("存在必须人工处理的段落，详见报告。", file=sys.stderr)
    if progress_cb:
        progress_cb(100, "翻译完成")
    return 2 if (hard or not structure_ok) else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="ai-translator",
        description="GMP 文档 Word 中英双语翻译（保持原格式输出）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input", help="输入 .docx（原格式翻译）或 .pdf（重排式翻译）文件")
    parser.add_argument("-o", "--output", help="输出文件路径（默认按模式自动命名）")
    parser.add_argument("--mode", choices=["bilingual", "replace"], default="bilingual",
                        help="bilingual=一行原文一行译文；replace=整段替换")
    parser.add_argument("--direction", choices=["auto", "zh2en", "en2zh"], default="auto",
                        help="auto=逐段自动判断方向")
    parser.add_argument("--doc-type", default="GMP 文件（批记录/工艺验证报告）", help="文档类型（作为翻译上下文）")
    parser.add_argument("--glossary", help="术语表 CSV（中文术语,English Term）")
    parser.add_argument("--api-base-url", default=os.environ.get("AI_TRANSLATOR_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                        help="OpenAI 兼容接口地址")
    parser.add_argument("--model", default=os.environ.get("AI_TRANSLATOR_MODEL", "glm-4.7"),
                        help="模型名称")
    parser.add_argument("--api-key",
                        help="API Key（CLI 备用入口用；日常请写在 config.json）")
    parser.add_argument("--batch-size", type=int, default=30, help="每次请求最大段落数")
    parser.add_argument("--max-retries", type=int, default=3, help="单批翻译失败重试次数")
    parser.add_argument("--concurrency", type=int, default=4, help="并发翻译请求数（限流时调小，1=顺序）")
    parser.add_argument("--thinking-level", choices=["low", "high", "max"], default="",
                        help="模型思考等级（空=服务端默认；low 最快）")
    parser.add_argument("--date-format", choices=["keep", "iso", "en", "zh"], default="keep",
                        help="译文行日期格式（keep=原样；仅日期，程序化转换不经模型）")
    parser.add_argument("--profile-pages", type=int, default=5,
                        help="（仅 PDF）翻译前先读前 N 页生成领域档案，注入翻译提示；0=关闭")
    parser.add_argument("--pages", default="",
                        help="（仅 PDF）只翻译指定页，如 \"1-20\" 或 \"6\"；空=全部。用于大文档先试译部分")
    parser.add_argument("--report", help="校验报告路径（默认 输出文件名.report.md）")
    parser.add_argument("--mock", action="store_true", help="离线测试模式：不调用模型，译文=原文回显")
    return parser.parse_args(argv)


def main(argv=None):
    """CLI 入口（备用）。日常使用建议 run.py + config.json。"""
    args = parse_args(argv)
    s = Settings(
        input=args.input,
        output=args.output or "",
        report=args.report or "",
        mode=args.mode,
        direction=args.direction,
        doc_type=args.doc_type,
        glossary=args.glossary or "",
        api_base_url=args.api_base_url,
        model=args.model,
        api_key=args.api_key or "",
        batch_size=args.batch_size,
        max_retries=args.max_retries,
        concurrency=args.concurrency,
        thinking_level=args.thinking_level,
        date_format=args.date_format,
        profile_pages=args.profile_pages,
        pages=args.pages,
        mock=args.mock,
    )
    return run_pipeline(s)


if __name__ == "__main__":
    raise SystemExit(main())

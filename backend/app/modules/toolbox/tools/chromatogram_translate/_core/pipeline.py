"""单文件与批量的翻译编排：前置检查 → 版式规划 → 渲染 → 三关校验。

前置检查 fail-loud 是本工具的安全底线：无文本层/非模板版式/无中文内容
都会明确标记失败或跳过，绝不静默输出原样副本。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pymupdf

from .geometry import page_geometry, page_vsegs
from .layout import PageData, build_ops, pass1_name_fs
from .profiles import EMPOWER_CN, Profile
from .render import Ops
from .spans import cjk_segments, collect_page, has_cjk
from .verify import verify_output

_FONT_FILE = Path(__file__).parent / "fonts" / "LiberationSans-Regular.ttf"
_font: pymupdf.Font | None = None


def _measure(text: str, fs: float = 1.0) -> float:
    global _font
    if _font is None:
        _font = pymupdf.Font(fontfile=str(_FONT_FILE))
    # pymupdf 的 Font.text_length 标注把 fontsize 写成 int，运行时接受 float
    return float(_font.text_length(text, fontsize=fs))  # pyright: ignore[reportArgumentType]


@dataclass
class FileResult:
    name: str
    pages: int = 0
    status: str = "ok"  # ok / failed / skipped
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    output: bytes | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def analyze(doc: pymupdf.Document, prof: Profile) -> tuple[list[PageData], str]:
    """逐页解析 span 与几何分区；返回 (PageData 列表, 失败原因或 "")。"""
    total_chars = 0
    for i in range(len(doc)):
        total_chars += len(cast(str, doc[i].get_text()).strip())
    if total_chars == 0:
        return [], (
            "未检测到文本层（可能为扫描件或文字被转成矢量轮廓的打印件），"
            "本工具仅支持带文本层的 PDF"
        )
    pd_list: list[PageData] = []
    for pno in range(len(doc)):
        page = doc[pno]
        spans = collect_page(page, pno)
        charts, tables = page_geometry(page, prof)
        pd_list.append(
            PageData(
                spans=spans,
                charts=charts,
                tables=tables,
                page_w=page.rect.width,
                vsegs=page_vsegs(page),
            )
        )
    if not any(has_cjk(s["text"]) for pd in pd_list for s in pd.spans):
        return [], "未检测到中文内容（文档可能已是英文）"
    if all(not pd.charts and not pd.tables for pd in pd_list):
        return [], "版式与 Empower 色谱报告模板不符（未检测到图区/数据表格）"
    return pd_list, ""


def translate_doc(
    doc: pymupdf.Document, terms: dict[str, str], prof: Profile
) -> tuple[bytes, Ops]:
    """对已打开的源文档执行版式规划与渲染；返回 (输出字节, 版式告警集)。
    注意：doc 会被原地修改（遮盖+回填），校验需由调用方用源文件另开比对。
    terms 必须已补齐（按整串与中文段两级校验）。"""
    pd_list, err = analyze(doc, prof)
    if err:
        raise ValueError(err)
    missing = {
        seg
        for pd in pd_list
        for s in pd.spans
        if has_cjk(s["text"])
        for seg in (
            []
            if s["text"].strip() in terms  # 整串命中即覆盖
            else {s["text"].strip(), *cjk_segments(s["text"])}
        )
        if has_cjk(seg) and seg not in terms
    }
    if missing:
        raise ValueError(f"词条缺失 {len(missing)} 条：{sorted(missing)[:3]}")
    name_fs = pass1_name_fs(pd_list, terms, prof, _measure)
    ops = build_ops(pd_list, terms, prof, name_fs, _measure)
    ops.render(doc, [pd.spans for pd in pd_list], str(_FONT_FILE))
    doc.subset_fonts()
    return bytes(doc.tobytes(garbage=3, deflate=True)), ops


def translate_file(
    path: Path,
    terms: dict[str, str],
    prof: Profile = EMPOWER_CN,
    display_name: str | None = None,
) -> FileResult:
    """单文件全流程（不含 LLM；terms 必须已补齐）。

    display_name：用户侧原始文件名（落盘路径是内部 uuid，产物与报告必须用
    原始名，否则用户拿到「uuid_英文.pdf」无法辨认）。"""
    shown = Path(display_name).name if display_name else path.name
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001 - pymupdf 对损坏文件的报错形态不定
        return FileResult(name=shown, status="failed", error=f"无法打开 PDF：{e}")
    try:
        pd_list, err = analyze(doc, prof)
        if err:
            status = "skipped" if "未检测到中文内容" in err else "failed"
            return FileResult(name=shown, pages=len(doc), status=status, error=err)
        out_bytes, ops = translate_doc(doc, terms, prof)
        # 渲染已原地改动 doc；三关校验用源文件重新打开比对
        src_doc = pymupdf.open(path)
        out_doc = None
        try:
            out_doc = pymupdf.open("pdf", out_bytes)
            vr = verify_output(src_doc, out_doc)
        finally:
            src_doc.close()
            if out_doc is not None:
                out_doc.close()
        if not vr.ok:
            return FileResult(
                name=shown,
                pages=len(doc),
                status="failed",
                error="；".join(vr.hard_errors),
                warnings=ops.warnings,
                stats=vr.stats,
            )
        return FileResult(
            name=shown,
            pages=len(doc),
            status="ok",
            warnings=ops.warnings,
            stats=vr.stats,
            output=out_bytes,
        )
    except ValueError as e:
        return FileResult(name=shown, pages=len(doc), status="failed", error=str(e))
    except Exception as e:  # noqa: BLE001
        return FileResult(
            name=shown, pages=len(doc), status="failed", error=f"翻译过程异常：{e}"
        )
    finally:
        doc.close()


def collect_all_span_texts(paths: list[Path]) -> list[tuple[str, str]]:
    """第一遍扫描：收集 (文件名, 全部 span 文本) 供批量词条补译去重。
    无法打开/无文本层的文件在此不拦截（第二遍会给出明确失败）。"""
    out: list[tuple[str, str]] = []
    for p in paths:
        try:
            doc = pymupdf.open(p)
        except Exception:  # noqa: BLE001
            continue
        try:
            for pno in range(len(doc)):
                page_dict = cast(dict[str, Any], doc[pno].get_text("dict"))
                for block in page_dict["blocks"]:
                    if block["type"] != 0:
                        continue
                    for line in block["lines"]:
                        for sp in line["spans"]:
                            out.append((p.name, sp["text"]))
        finally:
            doc.close()
    return out


def build_report(
    results: list[FileResult], ai_terms: dict[str, str], glossary_warnings: list[str]
) -> str:
    """批量 Markdown 校验报告（结果区直接渲染）。"""
    ok = [r for r in results if r.ok]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    lines: list[str] = ["# 色谱报告翻译校验报告", ""]
    lines.append(
        f"- 成功 {len(ok)} / 失败 {len(failed)} / 跳过 {len(skipped)}"
        f"（共 {len(results)} 个文件）"
    )
    if ai_terms:
        lines.append(f"- AI 补译词条 {len(ai_terms)} 条（建议人工确认后加入术语表）")
    lines.append("")

    lines += [
        "## 汇总",
        "",
        "| 文件 | 页数 | 结果 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        verdict = {"ok": "✅ 成功", "failed": "❌ 失败", "skipped": "⏭️ 跳过"}[r.status]
        note = r.error or (f"版式告警 {len(r.warnings)} 项" if r.warnings else "")
        note = note.replace("|", "\\|")
        lines.append(f"| {r.name} | {r.pages} | {verdict} | {note} |")
    lines.append("")

    for r in failed:
        lines += [f"## ❌ {r.name}", "", f"- 失败原因：{r.error}", ""]
        if r.warnings:
            lines += ["<details><summary>版式告警</summary>", ""]
            lines += [f"- {w}" for w in r.warnings] + ["", "</details>", ""]
    for r in ok:
        if not r.warnings:
            continue
        lines += [f"## ✅ {r.name}（版式告警供复核）", ""]
        lines += [f"- {w}" for w in r.warnings] + [""]

    if ai_terms:
        lines += [
            "## AI 补译词条（请人工确认）",
            "",
            "以下词条由模型补译，未经人工验收。建议核对无误后加入",
            "工具配置页的术语表，成为锁定术语：",
            "",
        ]
        lines += ["| 原文 | AI 译文 |", "| --- | --- |"]
        lines += [
            f"| {k.replace('|', '\\|')} | {v.replace('|', '\\|')} |"
            for k, v in sorted(ai_terms.items())
        ]
        lines.append("")
    if glossary_warnings:
        lines += ["## 术语表解析告警", ""] + [f"- {w}" for w in glossary_warnings]
    return "\n".join(lines)

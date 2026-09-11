"""vendor 引擎离线自检（mock 模式，不调模型）：docx / pdf 两条流水线 + 进度回调。

引擎自 ai_translator 项目原样拷贝（仅增加 progress_cb），此处验证其在
backend 环境下可完整跑通并产出翻译文件与报告。
"""

from pathlib import Path
from typing import Any

import pytest
from docx import Document

from app.modules.toolbox.tools.document_translate._engine.cli import run_pipeline
from app.modules.toolbox.tools.document_translate._engine.config import Settings
from app.modules.toolbox.tools.document_translate._engine.pdf.pipeline import (
    run_pdf_pipeline,
)


def make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_heading("Equipment Cleaning Procedure", level=1)
    doc.add_paragraph("The operator shall verify the cleanliness of the machine before starting production.")
    doc.add_paragraph("操作人员应在开始生产前确认设备已清洁。")
    doc.save(str(path))
    return path


def make_pdf(path: Path) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Validation Protocol", fontsize=16)
    page.insert_text(
        (72, 130),
        "This document describes the validation approach for the packaging line.",
        fontsize=11,
    )
    doc.save(str(path))
    doc.close()
    return path


def collect_progress() -> tuple[list[tuple[int, str]], Any]:
    seen: list[tuple[int, str]] = []

    def cb(percent: int, message: str) -> None:
        seen.append((percent, message))

    return seen, cb


def assert_progress_sequence(seen: list[tuple[int, str]]) -> None:
    """进度以低百分比开始、100 结束、单调不减，消息非空。"""
    assert seen, "进度回调未被调用"
    percents = [p for p, _ in seen]
    assert percents[0] <= 10
    assert percents[-1] == 100
    assert percents == sorted(percents)
    assert all(m for _, m in seen)


def test_docx_pipeline_mock(tmp_path: Path) -> None:
    src = make_docx(tmp_path / "protocol.docx")
    seen, cb = collect_progress()
    s = Settings(
        input=str(src), output=str(tmp_path / "out.docx"), report=str(tmp_path / "out.report.md"),
        mode="bilingual", direction="auto", glossary="", mock=True,
    )
    rc = run_pipeline(s, cb)

    assert rc == 0
    out = tmp_path / "out.docx"
    report = tmp_path / "out.report.md"
    assert out.exists() and report.exists()
    # 双语对照：输出段落数多于原文（插入了译文行）
    assert len(Document(str(out)).paragraphs) > len(Document(str(src)).paragraphs)
    assert "翻译校验报告" in report.read_text(encoding="utf-8")
    assert_progress_sequence(seen)


def test_docx_pipeline_mock_replace_mode(tmp_path: Path) -> None:
    src = make_docx(tmp_path / "protocol.docx")
    s = Settings(
        input=str(src), output=str(tmp_path / "out.docx"), report=str(tmp_path / "out.report.md"),
        mode="replace", direction="auto", glossary="", mock=True,
    )
    rc = run_pipeline(s, None)

    assert rc == 0
    # 整段替换：段落数与原文一致
    assert len(Document(str(tmp_path / "out.docx")).paragraphs) == len(Document(str(src)).paragraphs)


def test_docx_pipeline_rejects_unknown_suffix(tmp_path: Path) -> None:
    """引擎对 .docx/.pdf 之外的输入直接拒绝（退出码 2、无产物）。"""
    src = tmp_path / "data.xlsx"
    src.write_bytes(b"fake")
    s = Settings(input=str(src), glossary="", mock=True)
    rc = run_pipeline(s, None)
    assert rc == 2


def test_pdf_pipeline_mock(tmp_path: Path) -> None:
    pytest.importorskip("fitz")
    src = make_pdf(tmp_path / "validation.pdf")
    seen, cb = collect_progress()
    s = Settings(
        input=str(src), output=str(tmp_path / "out.docx"), report=str(tmp_path / "out.report.md"),
        mode="bilingual", direction="auto", glossary="", mock=True,
        profile_pages=0, pages="",
    )
    rc = run_pdf_pipeline(s, cb)

    assert rc == 0
    out = tmp_path / "out.docx"
    report = tmp_path / "out.report.md"
    assert out.exists() and report.exists()
    reopened = Document(str(out))
    assert reopened.paragraphs, "PDF 重排输出不应为空文档"
    assert "翻译校验报告" in report.read_text(encoding="utf-8")
    assert_progress_sequence(seen)

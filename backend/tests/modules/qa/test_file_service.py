"""QA 文件安全校验、私有存储和正文提取测试。"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import storage
from app.modules.qa import file_service


def test_validate_file_rejects_extension_mime_and_magic_mismatch() -> None:
    """拒绝不支持的扩展名、错误 MIME 和伪造文件魔数。"""
    with pytest.raises(file_service.FileValidationError):
        file_service.validate_file("report.exe", "application/octet-stream", b"MZ")

    with pytest.raises(file_service.FileValidationError):
        file_service.validate_file("report.pdf", "application/msword", b"%PDF-1.7")

    with pytest.raises(file_service.FileValidationError):
        file_service.validate_file("report.pdf", "application/pdf", b"not-a-pdf")


def test_validate_file_normalizes_filename_and_extension() -> None:
    """清理路径穿越文件名并统一返回不带点号的扩展名。"""
    name, extension, mime = file_service.validate_file(
        "../../批准文件.pdf", "application/pdf; charset=binary", b"%PDF-1.7\n"
    )

    assert name == "批准文件.pdf"
    assert extension == "pdf"
    assert mime == "application/pdf"


def test_store_file_uses_upload_subdir_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地开发存储落在 UPLOAD_DIR/qa 下，并支持读写回环。"""
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(
        file_service,
        "get_settings",
        lambda: SimpleNamespace(UPLOAD_DIR=str(upload_dir)),
    )
    monkeypatch.setattr(storage, "is_enabled", lambda: False)

    stored = file_service.store_file("approved.pdf", "application/pdf", b"%PDF-1.7\nbody")
    private_path = upload_dir / "qa" / stored.key

    assert private_path.is_file()
    assert file_service.read_file(stored.key) == (b"%PDF-1.7\nbody", "application/pdf")

    file_service.delete_file(stored.key)
    assert not private_path.exists()


def test_extract_doc_is_explicitly_unsupported() -> None:
    """旧版 DOC 只归档，不进入正文解析流程。"""
    status, segments = file_service.extract_text("doc", b"legacy binary")

    assert status == "unsupported"
    assert segments == []


def test_extract_docx_returns_paragraph_and_table_locations() -> None:
    """DOCX 正文同时提取段落和表格单元，并保留可读定位符。"""
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("第一段正文")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "表格正文"
    output = io.BytesIO()
    document.save(output)

    status, segments = file_service.extract_text("docx", output.getvalue())

    assert status == "ready"
    assert [(item.content, item.locator) for item in segments] == [
        ("第一段正文", "段落 1"),
        ("表格正文", "表格 1 / 单元格 1"),
    ]


def test_extract_pdf_marks_scan_without_text() -> None:
    """没有文本层的扫描 PDF 标记为 text_not_available 而不是伪造正文。"""
    fitz = pytest.importorskip("fitz")
    output = io.BytesIO()
    pdf = fitz.open()
    pdf.new_page()
    output.write(pdf.tobytes())
    pdf.close()

    status, segments = file_service.extract_text("pdf", output.getvalue())

    assert status == "text_not_available"
    assert segments == []

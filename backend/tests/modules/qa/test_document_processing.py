"""QA 原生解析与分块契约测试。"""

from __future__ import annotations

import io

from docx import Document

from app.modules.qa.document_processing import RawBlock, build_chunks, parse_document


def test_docx_preserves_body_interleaving_and_table_grid() -> None:
    document = Document()
    document.add_paragraph("段落一")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "编码"
    table.cell(0, 1).text = "名称"
    table.cell(1, 0).text = "P-01"
    table.cell(1, 1).text = "产品"
    document.add_paragraph("段落二")
    output = io.BytesIO()
    document.save(output)

    parsed = parse_document("docx", output.getvalue())

    assert parsed.status == "ready"
    assert [block.block_type for block in parsed.blocks] == [
        "paragraph",
        "table_header",
        "table_row",
        "paragraph",
    ]
    row = parsed.blocks[2]
    assert row.source_metadata["cells"][0]["column"] == 0
    assert row.source_metadata["cells"][1]["column"] == 1
    assert row.cell_index == 3
    assert row.source_metadata["is_header"] is False
    assert tuple(block.source_order for block in parsed.blocks) == (1, 2, 3, 4)


def test_chunk_rebuild_is_deterministic_and_maps_table_rows() -> None:
    document = Document()
    document.add_heading("SOP", level=1)
    for index in range(20):
        document.add_paragraph(f"步骤 {index}：确认物料编码 M-{index:02d}。")
    output = io.BytesIO()
    document.save(output)

    first = parse_document("docx", output.getvalue())
    second = parse_document("docx", output.getvalue())

    assert [chunk.content_hash for chunk in first.chunks] == [chunk.content_hash for chunk in second.chunks]
    assert all(chunk.char_count <= 4000 for chunk in first.chunks)
    assert set(order for chunk in first.chunks for order in chunk.raw_block_orders) == {
        block.source_order for block in first.blocks
    }
    assert all("raw_block_count" in chunk.metadata for chunk in first.chunks)


def test_chunk_respects_token_estimate_for_long_cjk_block() -> None:
    block = RawBlock("中" * 4000, "paragraph:1", 1)

    chunks = build_chunks([block])

    assert len(chunks) >= 2
    assert all(chunk.char_count <= 4000 for chunk in chunks)
    assert all(chunk.token_count <= 4096 for chunk in chunks)


def test_long_table_header_is_bounded_in_derived_chunks_but_kept_as_raw_evidence() -> None:
    blocks = [
        RawBlock("中" * 5000, "table:1/row:1", 1, "table_header", table_index=1),
        RawBlock("行" * 20, "table:1/row:2", 2, "table_row", table_index=1),
    ]

    chunks = build_chunks(blocks)

    assert chunks
    assert all(chunk.char_count <= 4000 and chunk.token_count <= 4096 for chunk in chunks)
    assert all(chunk.metadata.get("table_header_truncated") is True for chunk in chunks)
    assert any(1 in chunk.raw_block_orders for chunk in chunks)


def test_docx_preserves_horizontal_and_vertical_merge_metadata() -> None:
    document = Document()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "字段"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(1, 0).text = "合并字段"
    table.cell(1, 1).text = "第一行"
    table.cell(2, 1).text = "第二行"
    output = io.BytesIO()
    document.save(output)

    parsed = parse_document("docx", output.getvalue())

    continuation = parsed.blocks[2].source_metadata["cells"][0]
    assert continuation["v_merge"] == "continue"
    assert continuation["column"] == 0
    assert parsed.blocks[1].source_metadata["cells"][0]["v_merge"] == "restart"


def test_docx_marks_repeated_table_header_for_derived_deduplication() -> None:
    document = Document()
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "编码"
    table.cell(0, 1).text = "名称"
    table.cell(1, 0).text = "P-01"
    table.cell(1, 1).text = "产品一"
    table.cell(2, 0).text = "编码"
    table.cell(2, 1).text = "名称"
    output = io.BytesIO()
    document.save(output)

    parsed = parse_document("docx", output.getvalue())

    assert parsed.blocks[2].block_type == "table_header"
    assert parsed.blocks[2].source_metadata["is_repeated_header"] is True
    assert parsed.chunks[0].content.count("编码 | 名称") == 1
    assert 3 in parsed.chunks[0].metadata["omitted_raw_block_orders"]


def test_duplicate_table_header_keeps_raw_mapping_without_duplicate_text() -> None:
    blocks = [
        RawBlock("编码 | 名称", "table:1/row:1", 1, "table_header", table_index=1),
        RawBlock("P-01 | 产品", "table:1/row:2", 2, "table_row", table_index=1),
        RawBlock("编码 | 名称", "table:1/row:3", 3, "table_header", table_index=1),
        RawBlock("P-02 | 产品二", "table:1/row:4", 4, "table_row", table_index=1),
    ]

    chunks = build_chunks(blocks)

    assert len(chunks) == 1
    assert chunks[0].content.count("编码 | 名称") == 1
    assert 3 in chunks[0].metadata["omitted_raw_block_orders"]
    duplicate_offset = next(item for item in chunks[0].block_offsets if item[0] == 3)
    assert duplicate_offset[1] == duplicate_offset[2]


def test_scan_pdf_is_reserved_without_ocr() -> None:
    import fitz

    pdf = fitz.open()
    pdf.new_page()
    parsed = parse_document("pdf", pdf.tobytes())
    pdf.close()

    assert parsed.status == "text_not_available"
    assert parsed.chunks == ()
    assert parse_document("pdf", b"", mode="ocr").statistics["ocr_reserved"] is True


def test_pdf_two_columns_keep_column_reading_order_and_coordinates() -> None:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page(width=600, height=800)
    # 用独立的文本块并拉开纵向距离，避免 PyMuPDF 在生成测试 PDF 时把
    # 同一行的两栏合并成一个 block；真正要验证的是栏内/栏间排序契约。
    page.insert_text((50, 80), "LEFT-1", fontsize=11)
    page.insert_text((330, 250), "RIGHT-1", fontsize=11)
    page.insert_text((50, 420), "LEFT-2", fontsize=11)
    page.insert_text((330, 590), "RIGHT-2", fontsize=11)

    parsed = parse_document("pdf", pdf.tobytes())
    pdf.close()

    assert [block.content.splitlines()[0] for block in parsed.blocks] == [
        "LEFT-1",
        "LEFT-2",
        "RIGHT-1",
        "RIGHT-2",
    ]
    assert all(len(block.source_metadata["bbox"]) == 4 for block in parsed.blocks)
    assert all(block.source_metadata["reading_order"] == block.source_order for block in parsed.blocks)

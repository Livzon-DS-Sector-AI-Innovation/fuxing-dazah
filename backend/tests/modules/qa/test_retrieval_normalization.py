"""QA HTML/Markdown 派生检索文本的回归契约。"""

from __future__ import annotations

import hashlib

from app.modules.qa.document_processing import (
    RawBlock,
    build_chunks,
    parse_extracted_document,
)
from app.modules.qa.markdown_processing import (
    RETRIEVAL_TEXT_VERSION,
    normalize_retrieval_text,
)


def test_html_normalization_removes_markup_attributes_and_preserves_boundaries() -> None:
    raw = (
        '<p>设备 <strong class="label">R-101</strong></p>'
        '<p>状态 <a href="https://example.invalid">有效</a></p>'
        '<script>不应进入检索</script>'
    )

    normalized = normalize_retrieval_text(raw)

    assert normalized == "设备 R-101\n状态 有效"
    assert "<" not in normalized and ">" not in normalized
    assert "class=" not in normalized
    assert "https://" not in normalized
    assert "不应进入检索" not in normalized


def test_html_and_markdown_tables_keep_cell_and_row_boundaries() -> None:
    html = (
        '<table class="result"><thead><tr><th>编码</th><th>名称</th></tr></thead>'
        "<tbody><tr><td>R-101</td><td>反应釜</td></tr></tbody></table>"
    )
    markdown = "| 编码 | 名称 |\n| --- | --- |\n| R-101 | 反应釜 |"

    assert normalize_retrieval_text(html, block_type="table") == (
        "编码 | 名称\nR-101 | 反应釜"
    )
    assert normalize_retrieval_text(markdown, block_type="table") == (
        "编码 | 名称\nR-101 | 反应釜"
    )
    assert normalize_retrieval_text(
        "<table><tr><td><p>A</p><p>B<br>C</p></td><td>D</td></tr></table>",
        block_type="table",
    ) == "A B\nC | D"


def test_code_and_formula_keep_angle_brackets_as_semantic_content() -> None:
    assert normalize_retrieval_text(
        "```xml\n<tag attr=\"value\">R-101</tag>\n```", block_type="code"
    ) == '<tag attr="value">R-101</tag>'
    assert normalize_retrieval_text("$$x < y$$", block_type="formula") == "x < y"


def test_code_chunk_uses_code_normalization_without_stripping_tags() -> None:
    parsed = parse_extracted_document(
        "```xml\n<tag attr=\"value\">R-101</tag>\n```\n"
    )

    assert parsed.chunks[0].retrieval_text == '<tag attr="value">R-101</tag>'


def test_empty_anchor_is_kept_as_raw_evidence_but_not_chunked() -> None:
    anchor = RawBlock(
        '<a id="_Toc123456"></a>',
        "md:line:1-1",
        1,
        "paragraph",
    )
    paragraph = RawBlock(
        '<p>正文包含设备编码 <strong>R-101</strong>。</p>',
        "md:line:2-2",
        2,
        "paragraph",
    )

    chunks = build_chunks([anchor, paragraph])

    assert anchor.content == '<a id="_Toc123456"></a>'
    assert anchor.retrieval_text == ""
    assert len(chunks) == 1
    assert chunks[0].raw_block_orders == (2,)
    assert chunks[0].retrieval_text == "正文包含设备编码 R-101。"

    parsed = parse_extracted_document(
        '<a id="_Toc123456"></a>\n\n<p>正文包含设备编码 '
        '<strong>R-101</strong>。</p>\n'
    )
    assert parsed.blocks[0].content == anchor.content
    assert parsed.blocks[0].retrieval_text == ""
    assert parsed.chunks[0].raw_block_orders == (2,)


def test_raw_hash_and_offsets_are_based_on_original_markup() -> None:
    raw = '<p>设备编码 <strong data-kind="code">R-101</strong></p>'
    block = RawBlock(raw, "md:line:1-1", 1, "paragraph")

    chunks = build_chunks([block])
    assert len(chunks) == 1
    chunk = chunks[0]

    assert block.content == raw
    assert block.text_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert chunk.content == raw
    assert chunk.content_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert chunk.retrieval_text == "设备编码 R-101"
    assert chunk.retrieval_text_hash == hashlib.sha256(
        chunk.retrieval_text.encode("utf-8")
    ).hexdigest()
    assert chunk.retrieval_text_hash != chunk.content_hash

    source_order, start, end = chunk.block_offsets[0]
    assert source_order == block.source_order
    assert chunk.content[start:end] == raw


def test_retrieval_text_version_is_explicit_for_derived_indexes() -> None:
    assert RETRIEVAL_TEXT_VERSION.startswith("qa-retrieval-text-")


def test_plain_text_angle_brackets_survive_as_content() -> None:
    """尖括号在正文里是语义：设备位号、低于检出限的写法、比较式。

    这些标识符正是 AI 实体抽取要抓的东西，被 HTMLParser 当未知标签删掉
    就再也检索不到了。
    """

    assert normalize_retrieval_text("设备 <R-101> 与 <R-102> 并列") == (
        "设备 <R-101> 与 <R-102> 并列"
    )
    assert normalize_retrieval_text("检测结果 <LOD 低于检出限") == (
        "检测结果 <LOD 低于检出限"
    )
    assert normalize_retrieval_text("残氧量 <B，且 B>C，符合标准") == (
        "残氧量 <B，且 B>C，符合标准"
    )


def test_unknown_angle_brackets_survive_inside_real_html() -> None:
    """进了 HTML 分支也不能把认不出的尖括号吃掉，已知标签照常剥。"""

    assert normalize_retrieval_text("<p>设备 <R-101> 并列运行</p>") == (
        "设备 <R-101> 并列运行"
    )
    assert normalize_retrieval_text(
        '<p>设备 <R-101> 与 <strong class="c">R-102</strong> 并列</p>'
    ) == "设备 <R-101> 与 R-102 并列"


def test_html_table_with_pipe_in_cell_is_not_read_as_markdown_table() -> None:
    """单元格里出现竖线时，HTML 表格不能被误判成 Markdown 表格。

    按 Markdown 拆会把 ``<tr><td>`` 原样带进检索文本——那正是这个特性
    要去掉的 MinerU HTML 噪声。
    """

    normalized = normalize_retrieval_text(
        "<tr><td>规格 | 型号</td><td>值</td></tr>\n"
        "<tr><td>A | B</td><td>25</td></tr>",
        block_type="table",
    )

    assert "规格 | 型号 | 值" in normalized
    assert "A | B | 25" in normalized
    assert "<" not in normalized and ">" not in normalized


def test_nested_table_keeps_outer_row_cell_boundary() -> None:
    """嵌套表格的 </tr> 只能收自己那层，不能清掉外层行的列分隔状态。"""

    assert normalize_retrieval_text(
        "<table><tr><td><table><tr><td>x</td></tr></table></td><td>y</td></tr></table>"
    ) == "x | y"


def test_unclosed_formula_delimiter_falls_back_to_paragraph() -> None:
    """孤立的 "$$" 不是公式，否则后面整篇文档会被吞成一个 formula 块。"""

    parsed = parse_extracted_document(
        "正文第一段。\n\n$$x = y\n\n# 后续标题\n\n后续正文段落内容。\n"
    )

    assert [block.block_type for block in parsed.blocks] == [
        "paragraph",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert parsed.blocks[2].content == "后续标题"
    assert parsed.blocks[3].heading_path == ("后续标题",)


def test_closed_formulas_are_still_recognized() -> None:
    """收窄未闭合分支不能把正常公式一起判掉。"""

    assert parse_extracted_document("$$\nx = y\n$$\n").blocks[0].block_type == "formula"
    assert parse_extracted_document("$$x = y$$\n").blocks[0].block_type == "formula"

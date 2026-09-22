"""QA 文档解析与确定性分块基础设施。

这一层只负责把原文件转换成可追溯的 raw block 和派生 chunk，不负责
AI、向量化或业务关联。raw block 保留原始证据；chunk 可以在解析版本
不变时被确定性重建，供后续 AI、embedding、检索和知识图谱消费者使用。

本期仅实现 ``native_text``。扫描 PDF/图片以后可以实现同一个解析器接口
并使用 ``ocr`` 模式，而不用改动下游数据契约。
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

PARSER_VERSION = "qa-native-text-v2"
CHUNK_VERSION = "qa-context-v1"
TARGET_CHARS = 3000
MAX_CHARS = 4000
MAX_TOKENS = 4096
# 表格上下文必须给数据行留出空间；raw block 不受此限制，完整表头仍会
# 被保存并通过 ``table_header_truncated`` 标记。否则一个异常的超长表头会
# 让每个行片段只剩几个 token，造成 chunk 数量和下游分析成本失控。
TABLE_HEADER_CONTEXT_CHARS = 1200
TABLE_HEADER_CONTEXT_TOKENS = 1200


@dataclass(slots=True, frozen=True)
class RawBlock:
    """一个不可变的原始证据块。

    ``source_metadata`` 是可扩展契约：PDF 坐标、DOCX 表格网格、样式和
    合并单元格信息都放在这里，避免以后为了 OCR/版面分析重做表结构。
    """

    content: str
    locator: str
    source_order: int
    block_type: str = "paragraph"
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    cell_index: int | None = None
    heading_path: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(slots=True, frozen=True)
class DocumentChunk:
    """由 raw block 派生的上下文块。"""

    chunk_order: int
    content: str
    raw_block_orders: tuple[int, ...]
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    source_start: int = 0
    source_end: int = 0
    char_count: int = 0
    token_count: int = 0
    content_hash: str = ""
    # (raw source_order, chunk 内字符起点, chunk 内字符终点)。重复表头等
    # 仅用于证据映射而未进入正文的 block 会得到零宽区间。
    block_offsets: tuple[tuple[int, int, int], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExtractionDocument:
    status: str
    blocks: tuple[RawBlock, ...]
    chunks: tuple[DocumentChunk, ...]
    parser_version: str = PARSER_VERSION
    chunk_version: str = CHUNK_VERSION
    mode: str = "native_text"
    statistics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _clean(value: str | None) -> str:
    if not value:
        return ""
    # 保留换行（表格/段落证据需要），只折叠横向空白。
    return re.sub(r"[ \t\r\f\v]+", " ", value).strip()


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _token_count(value: str) -> int:
    # 本期不绑定具体 tokenizer；这个稳定估算只用于限长/展示，后续可以
    # 在 chunk 运行中增加 tokenizer_version 并重建统计值。
    if not value:
        return 0
    return max(1, int(len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\w\s]", value)) * 1.05))


def _split_long_text(
    value: str,
    limit: int = MAX_CHARS,
    token_limit: int = MAX_TOKENS,
) -> list[str]:
    """按字符和稳定 token 估算同时限长，且优先在句末/换行处切分。"""

    if len(value) <= limit and _token_count(value) <= token_limit:
        return [value]
    pieces: list[str] = []
    rest = value
    separators = "。！？；\n.!?;"
    while rest:
        if len(rest) <= limit and _token_count(rest) <= token_limit:
            pieces.append(rest.strip())
            break
        # token 估算超限时先按比例缩小字符窗口；中文通常接近 1:1，
        # 拉丁字符/标点则保留一定余量，避免只看字符数产生超限 chunk。
        sample_length = min(limit, len(rest))
        estimated_tokens = max(1, _token_count(rest[:sample_length]))
        token_cut = int(sample_length * token_limit / estimated_tokens)
        cut_limit = max(1, min(sample_length, token_cut))
        if cut_limit >= len(rest):
            cut_limit = max(1, len(rest) - 1)
        cut = max(
            (rest.rfind(separator, 0, cut_limit) for separator in separators),
            default=-1,
        )
        if cut < int(cut_limit * 0.55):
            cut = cut_limit
        else:
            cut += 1
        piece = rest[:cut].strip()
        if not piece:
            # 防御连续空白导致的零长度循环。
            rest = rest[cut:].lstrip()
            continue
        pieces.append(piece)
        rest = rest[cut:].lstrip()
    return [piece for piece in pieces if piece]


def _table_header_context(value: str) -> tuple[str, bool]:
    """返回可安全复制到每个表格 chunk 的表头上下文。

    raw block 始终保留完整表头；派生层为表头和换行预留至少两个字符/估算
    token 的空间，避免极长表头与数据行拼接后突破 chunk 硬上限。
    """

    char_budget = max(1, min(MAX_CHARS - 2, TABLE_HEADER_CONTEXT_CHARS))
    token_budget = max(1, min(MAX_TOKENS - 2, TABLE_HEADER_CONTEXT_TOKENS))
    pieces = _split_long_text(value, char_budget, token_budget)
    context = pieces[0] if pieces else value[:char_budget]
    return context, context != value


def _heading_path_for(style_name: str, text: str, current: list[str]) -> tuple[str, ...]:
    match = re.search(r"(?:heading|标题)\s*([1-9][0-9]*)", style_name, re.I)
    if not match:
        return tuple(current)
    level = max(1, int(match.group(1)))
    del current[level - 1 :]
    current.append(text)
    return tuple(current)


def _xml_attr(element: Any, name: str) -> str | None:
    for key, value in element.attrib.items():
        if str(key).split("}")[-1] == name:
            return str(value)
    return None


def _xml_text(element: Any) -> str:
    """读取 DOCX XML 单元格文本，同时保留换行/制表符。"""

    paragraph_texts: list[str] = []
    paragraphs = [
        node for node in element.iter() if str(node.tag).split("}")[-1] == "p"
    ]
    containers = paragraphs or [element]
    for container in containers:
        parts: list[str] = []
        for node in container.iter():
            local = str(node.tag).split("}")[-1]
            if local == "t":
                parts.append(str(node.text or ""))
            elif local == "tab":
                parts.append("\t")
            elif local == "br":
                parts.append("\n")
        text = _clean("".join(parts))
        if text:
            paragraph_texts.append(text)
    return "\n".join(paragraph_texts)


def _paragraph_numbering(element: Any) -> dict[str, Any] | None:
    """读取段落的 w:numPr，兼容没有 List 样式名的自定义编号列表。"""

    level: str | None = None
    num_id: str | None = None
    for node in element.iter():
        local = str(node.tag).split("}")[-1]
        if local == "ilvl":
            level = _xml_attr(node, "val")
        elif local == "numId":
            num_id = _xml_attr(node, "val")
    if level is None and num_id is None:
        return None
    return {
        "level": int(level) if level and level.isdigit() else level,
        "num_id": int(num_id) if num_id and num_id.isdigit() else num_id,
    }


def _docx_blocks(data: bytes) -> list[RawBlock]:
    from docx import Document
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    blocks: list[RawBlock] = []
    body = document.element.body
    heading_path: list[str] = []
    paragraph_index = 0
    table_index = 0
    order = 0

    for child in body.iterchildren():
        tag = str(child.tag).split("}")[-1]
        if tag == "p":
            paragraph_index += 1
            paragraph = Paragraph(child, document)
            text = _clean(paragraph.text)
            if not text:
                continue
            style_name = str(getattr(paragraph.style, "name", "") or "")
            path = _heading_path_for(style_name, text, heading_path)
            is_heading = bool(re.search(r"(?:heading|标题)\s*[1-9]", style_name, re.I))
            numbering = _paragraph_numbering(child)
            is_list = (
                "list" in style_name.casefold()
                or "列表" in style_name
                or numbering is not None
            )
            block_type = "heading" if is_heading else ("list_item" if is_list else "paragraph")
            order += 1
            blocks.append(
                RawBlock(
                    content=text,
                    locator=f"paragraph:{paragraph_index}",
                    source_order=order,
                    block_type=block_type,
                    paragraph_index=paragraph_index,
                    heading_path=path,
                    source_metadata={
                        "style": style_name or None,
                        "numbering": numbering,
                    },
                )
            )
        elif tag == "tbl":
            table_index += 1
            # 不使用 ``python-docx row.cells`` 作为唯一来源：它会为合并
            # 单元格返回同一个 cell proxy，导致 vMerge continuation 被误报
            # 成 restart。直接读取 XML 才能保留真实网格与合并关系。
            row_elements = [
                node
                for node in child.iterchildren()
                if str(node.tag).split("}")[-1] == "tr"
            ]
            row_count = len(row_elements)
            grid_columns = 0
            header_normalized: str | None = None
            for grid in child.iterchildren():
                if str(grid.tag).split("}")[-1] == "tblGrid":
                    grid_columns = sum(
                        str(node.tag).split("}")[-1] == "gridCol"
                        for node in grid.iterchildren()
                    )
                    break
            max_columns = grid_columns
            table_cell_index = 0
            for row_index, row_element in enumerate(row_elements):
                cells: list[dict[str, Any]] = []
                values: list[str] = []
                column_index = 0
                row_cell_start = table_cell_index + 1
                for cell_element in row_element.iterchildren():
                    if str(cell_element.tag).split("}")[-1] != "tc":
                        continue
                    table_cell_index += 1
                    value = _xml_text(cell_element)
                    if value:
                        values.append(value)
                    tc_pr = next(
                        (
                            node
                            for node in cell_element.iterchildren()
                            if str(node.tag).split("}")[-1] == "tcPr"
                        ),
                        None,
                    )
                    grid_span = None
                    v_merge = None
                    if tc_pr is not None:
                        for node in tc_pr.iterchildren():
                            local = str(node.tag).split("}")[-1]
                            if local == "gridSpan":
                                grid_span = _xml_attr(node, "val")
                            elif local == "vMerge":
                                v_merge = _xml_attr(node, "val") or "continue"
                    span = int(grid_span) if grid_span and grid_span.isdigit() else 1
                    cells.append(
                        {
                        "row": row_index,
                        "column": column_index,
                        "cell_index": table_cell_index,
                            "text": value,
                            "grid_span": span if span > 1 else None,
                            "v_merge": v_merge,
                        }
                    )
                    column_index += span
                max_columns = max(max_columns, column_index)
                content = " | ".join(values)
                if not content:
                    continue
                normalized_content = _normal(content)
                is_header = row_index == 0
                repeated_header = bool(
                    row_index > 0
                    and header_normalized
                    and normalized_content == header_normalized
                )
                if is_header:
                    header_normalized = normalized_content
                order += 1
                blocks.append(
                    RawBlock(
                        content=content,
                        locator=f"table:{table_index}/row:{row_index + 1}",
                        source_order=order,
                        block_type=(
                            "table_header"
                            if is_header or repeated_header
                            else "table_row"
                        ),
                        table_index=table_index,
                        # raw block 表示整行；cell_index 兼容字段指向该行
                        # 的首个单元格，完整单元格序列仍保存在 metadata.cells。
                        cell_index=row_cell_start,
                        row_index=row_index,
                        heading_path=tuple(heading_path),
                        source_metadata={
                            "row": row_index,
                            "row_count": row_count,
                            "column_count": max_columns,
                            "cells": cells,
                            "is_header": is_header or repeated_header,
                            "is_repeated_header": repeated_header,
                        },
                    )
                )
            # ``python-docx`` table cells can contain paragraphs which are not
            # represented in document.paragraphs.  The row text above is the
            # canonical raw evidence; nested paragraphs are retained in cells.
    return blocks


def _pdf_reading_order(
    page_blocks: list[dict[str, Any]], page_width: float
) -> list[tuple[int, dict[str, Any]]]:
    """按页面版面把 PDF 文本块排序为可解释的阅读顺序。

    PyMuPDF 的 ``sort=True`` 对双栏页面通常按 y 坐标交错排序（左栏第一
    行、右栏第一行、左栏第二行……）。这里仅在检测到至少两组明显分离的
    窄栏时按“栏内自上而下、栏间从左到右”排序；普通单栏页面继续使用
    原始 y/x 顺序，避免对复杂版面过度猜测。跨页宽度块（标题、页眉、页脚
    或分节说明）作为栏区域边界保留在相应位置。
    """

    items: list[tuple[int, dict[str, Any], list[float]]] = []
    for index, block in enumerate(page_blocks):
        if block.get("type", 0) != 0:
            continue
        bbox = [float(value) for value in block.get("bbox", [0, 0, 0, 0])]
        if len(bbox) < 4:
            continue
        items.append((index, block, bbox))
    if len(items) < 2 or page_width <= 0:
        return [(index, block) for index, block, _ in sorted(items, key=lambda item: (item[2][1], item[2][0], item[0]))]

    spanning: list[tuple[int, dict[str, Any], list[float]]] = []
    narrow: list[tuple[int, dict[str, Any], list[float]]] = []
    for item in items:
        _, _, bbox = item
        width = max(0.0, bbox[2] - bbox[0])
        crosses_center = bbox[0] <= page_width * 0.18 and bbox[2] >= page_width * 0.82
        if width >= page_width * 0.65 or crosses_center:
            spanning.append(item)
        else:
            narrow.append(item)

    # 按 x 区间聚类；相邻块只要有少量水平间隙仍属于同一栏。
    clusters: list[list[tuple[int, dict[str, Any], list[float]]]] = []
    gap_limit = max(12.0, page_width * 0.04)
    for item in sorted(narrow, key=lambda value: (value[2][0], value[2][1], value[0])):
        if not clusters or item[2][0] > max(value[2][2] for value in clusters[-1]) + gap_limit:
            clusters.append([item])
        else:
            clusters[-1].append(item)
    clusters = [cluster for cluster in clusters if cluster]
    if len(clusters) < 2:
        return [
            (index, block)
            for index, block, _ in sorted(items, key=lambda item: (item[2][1], item[2][0], item[0]))
        ]
    clusters.sort(key=lambda cluster: min(item[2][0] for item in cluster))

    def emit_columns(
        values: list[tuple[int, dict[str, Any], list[float]]],
    ) -> list[tuple[int, dict[str, Any]]]:
        output: list[tuple[int, dict[str, Any]]] = []
        for cluster in clusters:
            for index, block, _ in sorted(
                (item for item in values if item in cluster),
                key=lambda item: (item[2][1], item[2][0], item[0]),
            ):
                output.append((index, block))
        return output

    if not spanning:
        return emit_columns(narrow)

    # 跨栏块切分栏区域：先输出上一个区域的栏内容，再输出边界块。
    ordered: list[tuple[int, dict[str, Any]]] = []
    remaining = list(narrow)
    boundary_y = float("-inf")
    for span in sorted(spanning, key=lambda item: (item[2][1], item[2][0], item[0])):
        before = [
            item
            for item in remaining
            if item[2][3] <= span[2][1] and item[2][1] >= boundary_y
        ]
        if before:
            ordered.extend(emit_columns(before))
            before_ids = {item[0] for item in before}
            remaining = [item for item in remaining if item[0] not in before_ids]
        ordered.append((span[0], span[1]))
        boundary_y = span[2][3]
    if remaining:
        ordered.extend(emit_columns(remaining))
    return ordered


def _pdf_blocks(data: bytes) -> list[RawBlock]:
    import fitz

    blocks: list[RawBlock] = []
    order = 0
    with fitz.open(stream=data, filetype="pdf") as pdf:
        for page_number, page in enumerate(pdf, start=1):
            page_dict = page.get_text("dict", sort=False)
            page_height = float(page.rect.height or 0)
            page_blocks = page_dict.get("blocks", [])
            ordered_blocks = _pdf_reading_order(page_blocks, float(page.rect.width or 0))
            for block_index, block in ordered_blocks:
                lines: list[str] = []
                span_count = 0
                line_metadata: list[dict[str, Any]] = []
                for line in block.get("lines", []):
                    text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
                    if text.strip():
                        lines.append(text.strip())
                    span_count += len(line.get("spans", []))
                    line_metadata.append(
                        {
                            "bbox": [float(value) for value in line.get("bbox", [0, 0, 0, 0])],
                            "spans": [
                                {
                                    "text": str(span.get("text", "")),
                                    "bbox": [float(value) for value in span.get("bbox", [0, 0, 0, 0])],
                                    "font": span.get("font"),
                                    "size": span.get("size"),
                                }
                                for span in line.get("spans", [])
                            ],
                        }
                    )
                content = _clean("\n".join(lines))
                if not content:
                    continue
                bbox = [float(value) for value in block.get("bbox", [0, 0, 0, 0])]
                top_margin = page_height * 0.1 if page_height else 0
                bottom_margin = page_height * 0.9 if page_height else 0
                likely_header_footer = bool(
                    page_height and (bbox[1] <= top_margin or bbox[3] >= bottom_margin)
                )
                order += 1
                blocks.append(
                    RawBlock(
                        content=content,
                        locator=f"page:{page_number}/block:{block_index + 1}",
                        source_order=order,
                        block_type="pdf_block",
                        page_number=page_number,
                        source_metadata={
                            "bbox": bbox,
                            "block_index": block_index,
                            "line_count": len(lines),
                            "span_count": span_count,
                            "lines": line_metadata,
                            "reading_order": order,
                            "boilerplate_candidate": likely_header_footer,
                            "page_width": float(page.rect.width),
                            "page_height": page_height,
                        },
                    )
                )
    return blocks


def _make_chunk(
    order: int,
    blocks: list[RawBlock],
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    omitted_block_orders: set[int] | None = None,
    block_fragments: list[tuple[int, str]] | None = None,
) -> DocumentChunk:
    content = content.strip()
    pages = [block.page_number for block in blocks if block.page_number is not None]
    headings = blocks[-1].heading_path if blocks else ()
    offsets: list[tuple[int, int, int]] = []
    cursor = 0
    omitted = omitted_block_orders or set()
    mapped_orders: set[int] = set()

    def append_offset(source_order: int, fragment: str) -> None:
        nonlocal cursor
        if source_order in omitted:
            # 该 raw block 仍属于 chunk 的证据映射，但其正文在派生层被
            # 去重（典型是重复表头），因此不伪造一个可能指向另一段文本
            # 的位置；下游可凭 raw block id 回到完整证据。
            offsets.append((source_order, cursor, cursor))
            mapped_orders.add(source_order)
            return
        needle = fragment.strip()
        position = content.find(needle, cursor) if needle else cursor
        if position < 0 and needle:
            position = content.find(needle)
        if position < 0:
            position = cursor
        end = min(len(content), position + len(needle))
        offsets.append((source_order, position, end))
        cursor = max(cursor, end)
        mapped_orders.add(source_order)

    # ``build_chunks`` 传入的是实际进入当前派生 chunk 的 block 片段，
    # 因此一个超过上限的 raw block 被拆成多个 chunk 时，偏移仍能指向
    # 各自的片段，而不是拿完整 raw 文本去做必然失败的 find。
    if block_fragments is not None:
        for source_order, fragment in block_fragments:
            append_offset(source_order, fragment)
    for block in blocks:
        if block.source_order in mapped_orders:
            continue
        append_offset(block.source_order, block.content)
    derived_metadata: dict[str, Any] = {
        "raw_block_count": len(blocks),
        "contains_table": any(
            block.block_type in {"table_header", "table_row"} for block in blocks
        ),
        "boilerplate_candidate": any(
            bool(block.source_metadata.get("boilerplate_candidate")) for block in blocks
        ),
        "boilerplate_block_count": sum(
            bool(block.source_metadata.get("boilerplate_candidate")) for block in blocks
        ),
    }
    if omitted:
        derived_metadata["omitted_raw_block_orders"] = sorted(omitted)
    if metadata:
        derived_metadata.update(metadata)
    return DocumentChunk(
        chunk_order=order,
        content=content,
        raw_block_orders=tuple(dict.fromkeys(block.source_order for block in blocks)),
        heading_path=headings,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        source_start=blocks[0].source_order if blocks else 0,
        source_end=blocks[-1].source_order if blocks else 0,
        char_count=len(content),
        token_count=_token_count(content),
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        block_offsets=tuple(offsets),
        metadata=derived_metadata,
    )


def build_chunks(blocks: list[RawBlock]) -> list[DocumentChunk]:
    """按标题/段落/表格边界确定性构建上下文块。"""

    chunks: list[DocumentChunk] = []
    current_blocks: list[RawBlock] = []
    current_parts: list[str] = []
    current_fragments: list[tuple[int, str]] = []
    current_omitted: set[int] = set()
    current_table: int | None = None
    table_header: str | None = None
    table_header_block: RawBlock | None = None
    table_header_truncated = False

    def flush() -> None:
        nonlocal current_blocks, current_parts, current_fragments, current_omitted, current_table, table_header, table_header_block, table_header_truncated
        if current_parts:
            metadata = (
                {"table_header_truncated": True}
                if table_header_truncated
                else None
            )
            chunks.append(
                _make_chunk(
                    len(chunks),
                    current_blocks,
                    "\n".join(current_parts),
                    omitted_block_orders=current_omitted,
                    block_fragments=current_fragments,
                    metadata=metadata,
                )
            )
        current_blocks = []
        current_parts = []
        current_fragments = []
        current_omitted = set()
        current_table = None
        table_header = None
        table_header_block = None
        table_header_truncated = False

    for block in blocks:
        is_table = block.block_type in {"table_header", "table_row"}
        # 标题是稳定的语义边界；标题本身与后续内容放在同一块。
        if block.block_type == "heading" and current_parts:
            flush()
        if is_table:
            if current_table != block.table_index:
                flush()
                current_table = block.table_index
                table_header = None
                table_header_block = None
                table_header_truncated = False
            if block.block_type == "table_header":
                normalized = _normal(block.content)
                duplicate = table_header is not None and normalized == _normal(table_header)
                if duplicate:
                    # raw block 仍映射到当前 chunk，但派生正文不再重复表头。
                    current_blocks.append(block)
                    current_omitted.add(block.source_order)
                    continue
                table_header, table_header_truncated = _table_header_context(block.content)
                table_header_block = block
            part = table_header if block.block_type == "table_header" and table_header else block.content
        else:
            if current_table is not None:
                flush()
            part = block.content

        piece_limit = MAX_CHARS
        piece_token_limit = MAX_TOKENS
        if is_table and table_header and current_parts:
            # 表格每个派生 chunk 都要带表头；为行正文预留表头字符，避免
            # “表头 + 4000 字符行”突破 chunk 上限。
            piece_limit = max(1, MAX_CHARS - len(table_header) - 1)
            piece_token_limit = max(1, MAX_TOKENS - _token_count(table_header) - 1)
        for piece in _split_long_text(part, piece_limit, piece_token_limit):
            candidate = "\n".join([*current_parts, piece]).strip()
            if current_parts and (
                len(candidate) > MAX_CHARS or _token_count(candidate) > MAX_TOKENS
            ):
                # 表格行不能单独成为无表头上下文；新 chunk 先复制表头。
                header_text = table_header
                header_block = table_header_block
                header_was_truncated = table_header_truncated
                flush()
                if is_table and header_text and header_text != piece:
                    current_table = block.table_index
                    table_header = header_text
                    table_header_block = header_block
                    table_header_truncated = header_was_truncated
                    current_parts.append(header_text)
                    if header_block:
                        current_blocks.append(header_block)
                        current_fragments.append((header_block.source_order, header_text))
            current_parts.append(piece)
            current_blocks.append(block)
            current_fragments.append((block.source_order, piece))
            if len("\n".join(current_parts)) >= TARGET_CHARS and not is_table:
                flush()
        # 表格只在下一行会超过 MAX_CHARS 时切块；这样每个派生表格
        # chunk 都能携带表头，避免孤立行上下文。最后由循环结束统一 flush。
    flush()
    return chunks


def parse_document(
    extension: str,
    data: bytes,
    *,
    mode: str = "native_text",
) -> ExtractionDocument:
    """解析 PDF/DOCX，并返回 raw block + chunk。

    ``ocr`` 模式是预留契约，本期明确返回 ``text_not_available``，避免
    把扫描件误判为空文档；后续 OCR 实现可直接替换这个分支。
    """

    ext = extension.lower().lstrip(".")
    if mode not in {"native_text", "ocr"}:
        return ExtractionDocument("unsupported", (), (), mode=mode, error="不支持的解析模式")
    if mode == "ocr":
        return ExtractionDocument("text_not_available", (), (), mode=mode, statistics={"ocr_reserved": True})
    if ext not in {"pdf", "docx"}:
        return ExtractionDocument("unsupported", (), (), statistics={"extension": ext})
    try:
        blocks = _pdf_blocks(data) if ext == "pdf" else _docx_blocks(data) if ext == "docx" else []
    except Exception as exc:  # 由 service 持久化错误，不把原文/响应写日志
        return ExtractionDocument("failed", (), (), error=str(exc)[:2000])
    if not blocks:
        return ExtractionDocument(
            "text_not_available",
            (),
            (),
            statistics={"extension": ext, "block_count": 0},
        )
    chunks = build_chunks(blocks)
    statistics = {
        "extension": ext,
        "block_count": len(blocks),
        "chunk_count": len(chunks),
        "char_count": sum(len(block.content) for block in blocks),
        "table_block_count": sum(block.block_type.startswith("table") for block in blocks),
        "pdf_block_count": sum(block.block_type == "pdf_block" for block in blocks),
    }
    return ExtractionDocument("ready", tuple(blocks), tuple(chunks), statistics=statistics)

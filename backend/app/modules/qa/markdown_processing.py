"""MinerU Markdown AST 与结构化结果的保守归一化。

Markdown 始终作为完整正文基准；只有可识别且覆盖正文的 JSON 才替代它，
否则保留 Markdown 节点，仅将可明确匹配的 JSON 位置附加为来源信息。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock

from app.modules.qa.document_processing import RawBlock

# ``RawBlock.content`` 始终是 MinerU 的原始证据。检索和 embedding 消费的
# 文本需要另行归一化；版本号写入 metadata/下游 hash，便于以后调整规则后
# 只重建派生文本，不重新调用远程解析器。
RETRIEVAL_TEXT_VERSION = "qa-retrieval-text-v1"


_BLOCK_HTML_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "summary",
    "ul",
}
_IGNORED_HTML_TAGS = {"script", "style", "noscript", "template", "svg"}
_TABLE_HTML_TAGS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "col",
}
_INLINE_HTML_TAGS = {
    "a",
    "b",
    "br",
    "cite",
    "code",
    "del",
    "em",
    "font",
    "i",
    "img",
    "ins",
    "kbd",
    "mark",
    "q",
    "s",
    "samp",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
    "var",
}
_KNOWN_HTML_TAGS = (
    _BLOCK_HTML_TAGS | _IGNORED_HTML_TAGS | _TABLE_HTML_TAGS | _INLINE_HTML_TAGS
)

_HTML_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)[\s/>]")
_HTML_TABLE_TAG_RE = re.compile(
    r"</?(?:table|thead|tbody|tfoot|tr|td|th|caption)[\s/>]", re.IGNORECASE
)


def _looks_like_html(value: str) -> bool:
    """只有出现认得的 HTML 标签时，才把这段文本当 HTML 处理。

    纯文本里的尖括号是语义不是标记——设备位号 ``设备 <R-101> 与 <R-102> 并列``、
    低于检出限的 ``<LOD`` 写法、``<B，且 B>C`` 这种比较——交给 HTMLParser
    会被当作未知标签整段删掉，而这些标识符恰恰是 AI 实体抽取要抓的东西。
    宁可漏剥一层标签，也不能删正文。
    """

    return any(
        match.group(1).casefold() in _KNOWN_HTML_TAGS
        for match in _HTML_TAG_RE.finditer(value)
    )


def _collapse_retrieval_whitespace(value: str) -> str:
    """折叠横向空白，保留结构性换行。"""

    value = unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in value.split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if compact and not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False
    while compact and not compact[-1]:
        compact.pop()
    return "\n".join(compact).strip()


class _RetrievalHTML(HTMLParser):
    """把 HTML 转为面向检索的可读文本。

    这里只保留可见数据和表格行列边界，不保留标签、属性、样式或链接
    地址。表格单元格用 `` | `` 分隔，行用换行分隔，避免直接去标签后把
    ``<td>A</td><td>B</td>`` 拼成 ``AB``。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._table_depth = 0
        self._cell_depth = 0
        # 每个 <tr> 压一层栈：这一行是否已经输出过单元格，以及进入该行时的
        # 单元格深度。嵌套表格里的 </tr> 只弹自己那层，不会把外层的列分隔
        # 状态一并清掉——平铺计数器做不到这点，会把外层的后续单元格粘成一片。
        self._row_has_cell: list[bool] = []
        self._row_cell_depth: list[int] = []

    def _append(self, value: str) -> None:
        if self._ignored_depth or not value:
            return
        self.parts.append(value)

    def _newline(self) -> None:
        if self._ignored_depth:
            return
        if self._cell_depth:
            # ``<td><p>A</p></td>`` 中的段落边界不应打断列分隔；单元格
            # 自身已经通过 `` | `` 表示结构，单元格内换行仅由 ``<br>``
            # 显式产生。
            if self.parts and self.parts[-1] not in {" ", "\n"}:
                self.parts.append(" ")
            return
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in _IGNORED_HTML_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag not in _KNOWN_HTML_TAGS:
            # 认不出的尖括号是正文本身。HTMLParser 的宽容解析会把它当标签
            # 吞掉——``<LOD 低于检出限`` 这种没闭合的写法，连后面的 ``</p>``
            # 一起当属性吃掉。宁可留下尖括号，也不能删正文。
            self._append(self.get_starttag_text() or "")
            return
        if tag == "table":
            self._table_depth += 1
            self._newline()
        elif tag == "tr":
            self._row_has_cell.append(False)
            self._row_cell_depth.append(self._cell_depth)
            self._newline()
        elif tag in {"td", "th"} and self._row_has_cell:
            if self._row_has_cell[-1]:
                self._append(" | ")
            self._row_has_cell[-1] = True
            self._cell_depth += 1
        elif tag == "br":
            if self._cell_depth:
                self._append("\n")
            else:
                self._newline()
        elif tag == "img":
            alt = next((value for key, value in attrs if key.casefold() == "alt"), None)
            if alt:
                self._append(alt)
        elif tag in _BLOCK_HTML_TAGS:
            self._newline()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in _IGNORED_HTML_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if tag in {"td", "th"} and self._cell_depth:
            self._cell_depth -= 1
        elif tag == "tr" and self._row_has_cell:
            self._row_has_cell.pop()
            # \u5c11\u5199 </td> \u7684\u7578\u5f62\u884c\u4e5f\u5728\u8fd9\u91cc\u6536\u53e3\uff0c\u6df1\u5ea6\u4e0d\u4f1a\u88ab\u5e26\u8fdb\u4e0b\u4e00\u884c\u3002
            self._cell_depth = self._row_cell_depth.pop()
            self._newline()
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            self._newline()
        elif tag in _BLOCK_HTML_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = data.replace("\u00a0", " ")
        if value:
            self._append(value)

    def text(self) -> str:
        return _collapse_retrieval_whitespace("".join(self.parts))


def _split_markdown_table_row(line: str) -> list[str]:
    """拆分简单 Markdown 表格行，支持反斜杠转义的竖线。"""

    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value:
        if char == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
            continue
        if char == "\\" and not escaped:
            escaped = True
            current.append(char)
            continue
        escaped = False
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _markdown_table_text(value: str) -> str | None:
    # HTML 表格的单元格里只要有一个竖线，就会被误判成 Markdown 表格并按行
    # 拆开——拆完标签还在，等于把 ``<tr><td>`` 原样写进检索文本。这不是
    # Markdown 表格，交回 _RetrievalHTML。
    if _HTML_TABLE_TAG_RE.search(value):
        return None
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 2 or not any("|" in line for line in lines):
        return None
    rows: list[str] = []
    found_table = False
    for index, line in enumerate(lines):
        cells = _split_markdown_table_row(line)
        if len(cells) < 2:
            return None
        if index == 1 and all(re.fullmatch(r":?-{1,}:?", cell.replace(" ", "")) for cell in cells):
            found_table = True
            continue
        found_table = True
        rows.append(" | ".join(cell.replace(r"\|", "|") for cell in cells))
    return "\n".join(rows) if found_table and rows else None


def _normalize_markdown_inline(value: str) -> str:
    # 先处理链接/图片，避免把 URL、图片路径送进检索；保留 alt/text。
    value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"!?\[([^\]]*)\]\[[^\]]*\]", r"\1", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value)
    value = re.sub(r"^\s*>\s?", "", value)
    value = re.sub(r"^\s*(?:[-+*]|\d+[.)])\s+", "", value)
    # 只移除成对的强调标记；下划线常出现在设备/物料标识中，不能全局删。
    value = re.sub(r"(?<!\w)(\*{1,3}|_{1,3})(?=\S)(.+?)(?<!\s)\1", r"\2", value)
    return value


def normalize_retrieval_text(
    text: str,
    *,
    block_type: str = "paragraph",
    source_metadata: dict[str, Any] | None = None,
) -> str:
    """生成用于关键词检索和 embedding 的可读文本。

    该函数是纯函数且不改变 ``text``。原始 Markdown/HTML 应继续保存到
    raw segment/chunk；调用方可用 :data:`RETRIEVAL_TEXT_VERSION` 参与派生
    hash。表格优先保留列分隔和行边界，空 anchor 等没有可见文字的块返回
    空字符串。
    """

    if not text or not text.strip():
        return ""
    if block_type == "code":
        # 代码中的 ``<tag>`` 是语义，不应被当作 HTML 节点移除；只去掉
        # Markdown 围栏，保留代码本身供精确检索和 embedding 使用。
        lines = text.splitlines()
        if lines and re.match(r"^\s*(```|~~~)", lines[0]):
            lines = lines[1:]
        if lines and re.match(r"^\s*(```|~~~)\s*$", lines[-1]):
            lines = lines[:-1]
        return _collapse_retrieval_whitespace("\n".join(lines))
    if block_type == "formula":
        # 数学表达式中的尖括号同样不能按 HTML 清理；保留表达式内容，
        # 去除仅用于 Markdown 展示的成对围栏。
        value = text.strip()
        if value.startswith("$$") and value.endswith("$$"):
            value = value[2:-2]
        elif value.startswith("\\[") and value.endswith("\\]"):
            value = value[2:-2]
        return _collapse_retrieval_whitespace(value)
    if block_type in {"table", "table_header", "table_row"}:
        markdown_table = _markdown_table_text(text)
        if markdown_table is not None:
            return _collapse_retrieval_whitespace(
                "\n".join(
                    _normalize_markdown_inline(line)
                    for line in markdown_table.splitlines()
                )
            )
    if not _looks_like_html(text):
        # 没有标签就不是 HTML。这些尖括号是正文本身（设备位号、<LOD 检出限
        # 写法、<B，且 B>C 这类比较），送进 HTMLParser 会被当未知标签整段删掉。
        return _collapse_retrieval_whitespace(
            "\n".join(
                _normalize_markdown_inline(line)
                for line in text.replace(" ", " ").splitlines()
            )
        )
    parser = _RetrievalHTML()
    parser.feed(text)
    parser.close()
    value = parser.text()
    # HTMLParser 对没有标签的 Markdown 文本会原样回调数据；统一处理
    # Markdown 链接/列表/强调，兼容 MinerU 混排结果。
    if value:
        value = "\n".join(_normalize_markdown_inline(line) for line in value.splitlines())
    return _collapse_retrieval_whitespace(value)


def _formula_rule(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    line = state.src[state.bMarks[start] + state.tShift[start] : state.eMarks[start]].strip()
    if not line.startswith(("$$", "\\[")):
        return False
    opener = "$$" if line.startswith("$$") else "\\["
    closer = "$$" if opener == "$$" else "\\]"
    next_line = start + 1
    if not (len(line) > len(opener) and line.endswith(closer)):
        while next_line < end:
            value = state.src[state.bMarks[next_line] : state.eMarks[next_line]].strip()
            next_line += 1
            if value.endswith(closer):
                break
        else:
            # 找不到闭合定界符就不是公式，退回普通段落。
            # 以前这里不管找没找到都把 token.map 拉到文末：一个孤立的 "$$"
            # （MinerU 对没闭合的行间公式就会吐这个，正文里出现字面量 "$$"
            # 也一样）会把后面整篇文档吞成一个 formula 块，标题层级和 chunk
            # 边界全丢。silent 探测走同一条判断，否则段落终止规则会与实际
            # 解析结果打架。
            return False
    if silent:
        return True
    token = state.push("formula", "math", 0)
    token.block = True
    token.map = [start, next_line]
    token.content = state.getLines(start, next_line, state.blkIndent, False)
    state.line = next_line
    return True


def _parser() -> MarkdownIt:
    parser = MarkdownIt("commonmark").enable("table")
    parser.block.ruler.before("fence", "formula", _formula_rule, {"alt": ["paragraph"]})
    return parser


class _HTMLTables(HTMLParser):
    """读取 AST HTML block 中的外层表格区间，保留合并单元格原文。"""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.line_offsets = [0]
        for line in text.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line))
        self.depth = 0
        self.start = 0
        self.spans: list[tuple[int, int]] = []
        self.feed(text)
        if self.depth:
            self.spans.append((self.start, len(text)))

    def _position(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if not self.depth:
                self.start = self._position()
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.spans.append((self.start, self._position() + len("</table>")))


def markdown_blocks(markdown: str) -> list[RawBlock]:
    """用 Markdown AST 识别标题、完整列表、代码、公式及表格。"""

    lines = markdown.splitlines(keepends=True)
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))
    tokens = _parser().parse(markdown)
    blocks: list[RawBlock] = []
    headings: list[tuple[int, str]] = []
    table_index = 0
    consumed_until = 0

    def add(
        content: str,
        block_type: str,
        start: int,
        end: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        nonlocal table_index
        if not content.strip():
            return
        if block_type == "table":
            table_index += 1
        metadata: dict[str, Any] = {
            "source_format": "markdown",
            "line_start": start + 1,
            "line_end": end,
            "char_start": line_offsets[start],
            "char_end": line_offsets[min(end, len(lines))],
        }
        if extra:
            metadata.update(extra)
        blocks.append(RawBlock(
            content=content.strip(),
            locator=f"md:line:{start + 1}-{end}",
            source_order=len(blocks) + 1,
            block_type=block_type,
            table_index=table_index if block_type == "table" else None,
            heading_path=tuple(title for _, title in headings),
            source_metadata=metadata,
        ))

    for index, token in enumerate(tokens):
        if token.map is None or token.nesting == -1 or token.level != 0:
            continue
        start, end = token.map
        if start < consumed_until:
            continue
        consumed_until = end
        raw = "".join(lines[start:end])
        kind = token.type
        if kind == "heading_open":
            level = int(token.tag[1:])
            title = tokens[index + 1].content
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            # 标题正文与 DOCX/PDF 标题保持同一语义格式；原始 ``#`` 仍可
            # 通过 source_metadata 的行/字符区间回到完整 Markdown。
            add(title, "heading", start, end, {"level": level, "title": title, "markdown_source": raw})
        elif kind == "table_open":
            add(raw, "table", start, end, {"table_atomic": True, "table_format": "markdown"})
        elif kind in {"fence", "code_block"}:
            add(raw, "code", start, end, {"language": token.info.strip() or None})
        elif kind == "formula":
            add(raw, "formula", start, end)
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            item_ranges = [
                item.map for item in tokens[index + 1 :]
                if item.type == "list_item_open" and item.level == 1
                and item.map is not None and start <= item.map[0] < end
            ]
            if item_ranges:
                for item_start, item_end in item_ranges:
                    add(
                        "".join(lines[item_start:item_end]),
                        "list_item",
                        item_start,
                        item_end,
                        {"list_item_lines": [item_start, item_end]},
                    )
            else:
                add(raw, "list", start, end, {"list_item_lines": item_ranges})
        elif kind == "html_block":
            cursor = 0
            for table_start, table_end in _HTMLTables(raw).spans:
                add(raw[cursor:table_start], "paragraph", start, end)
                add(raw[table_start:table_end], "table", start, end, {
                    "table_atomic": True, "table_format": "html",
                    "char_start": line_offsets[start] + table_start,
                    "char_end": line_offsets[start] + table_end,
                })
                cursor = table_end
            add(raw[cursor:], "paragraph", start, end)
        elif kind == "blockquote_open":
            add(raw, "quote", start, end)
        elif kind == "hr":
            add(raw, "separator", start, end)
        else:
            add(raw, "paragraph", start, end)
    return blocks


def _value_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _value_text(item)))
    if not isinstance(value, dict):
        return ""
    for key in ("table_body", "html", "text", "content", "latex", "markdown"):
        text = _value_text(value.get(key))
        if text:
            return text
    spans = value.get("spans")
    if isinstance(spans, list):
        return "".join(_value_text(span) for span in spans)
    for key in ("lines", "blocks", "list_items", "children"):
        text = _value_text(value.get(key))
        if text:
            return text
    return ""


def _page(node: dict[str, Any], inherited: int | None) -> int | None:
    value = node.get("page_idx")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value + 1
    for key in ("page_number", "page_no"):
        value = node.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return inherited


def _level(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0:
        return int(value.strip())
    return None


def structured_blocks(payload: Any) -> tuple[list[RawBlock], bool]:
    """只遍历已知 MinerU 内容容器；第二个值表示是否存在未知节点。"""

    blocks: list[RawBlock] = []
    headings: list[tuple[int, str]] = []
    table_index = 0
    unknown = False
    aliases = {
        "text": "paragraph", "paragraph": "paragraph", "title": "heading",
        "heading": "heading", "section_header": "heading", "table": "table",
        "table_body": "table", "html_table": "table", "list": "list",
        "list_item": "list", "code": "code", "equation": "formula",
        "interline_equation": "formula", "formula": "formula", "quote": "quote",
        "image": "image",
    }

    def visit(node: Any, page_number: int | None = None, path: str = "$") -> None:
        nonlocal unknown, table_index
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, page_number, f"{path}[{index}]")
            return
        if not isinstance(node, dict):
            if isinstance(node, str) and node.strip():
                unknown = True
            return
        page_number = _page(node, page_number)
        kind = str(node.get("type") or node.get("block_type") or "").lower()
        if kind in {"discarded", "page", "pdf_page", "metadata"}:
            for key, value in node.items():
                if key in {"type", "block_type", "metadata"}:
                    continue
                if isinstance(value, (dict, list)):
                    visit(value, page_number, f"{path}.{key}")
            return
        if kind:
            block_type = aliases.get(kind)
            if block_type is None:
                unknown = True
                return
            text = _value_text(node).strip()
            if block_type == "image":
                caption = _value_text(node.get("img_caption") or node.get("image_caption"))
                footnote = _value_text(node.get("img_footnote") or node.get("image_footnote"))
                image_path = node.get("img_path")
                text = "\n\n".join(part for part in (
                    f"![{caption}]({image_path})" if image_path else caption, footnote
                ) if part)
            elif block_type == "table":
                caption = _value_text(node.get("table_caption"))
                footnote = _value_text(node.get("table_footnote"))
                text = "\n\n".join(part for part in (caption, text, footnote) if part)
            level = _level(node.get("text_level", node.get("heading_level", node.get("level"))))
            if level is not None and block_type == "paragraph":
                block_type = "heading"
            if not text:
                unknown = True
                return
            if block_type == "heading":
                text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text).strip()
                level = level if level is not None else 1
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, text))
            if block_type == "table":
                table_index += 1
            metadata: dict[str, Any] = {
                "source_format": "structured_json", "json_type": kind, "json_path": path,
            }
            for key in ("bbox", "polygon", "page_idx", "page_size", "page_width", "page_height", "index", "id", "text_level"):
                if key in node:
                    metadata[key] = node[key]
            if block_type == "heading":
                metadata.update(level=level, title=text)
            if block_type == "table":
                metadata["table_atomic"] = True
            blocks.append(RawBlock(
                content=text, locator=f"json:{path}"[:255], source_order=len(blocks) + 1,
                block_type=block_type, page_number=page_number,
                table_index=table_index if block_type == "table" else None,
                heading_path=tuple(title for _, title in headings), source_metadata=metadata,
            ))
            return
        # 同一包装层可能同时存在 preproc_blocks 和 para_blocks，只读取最
        # 接近最终阅读顺序的一个容器，避免一段正文被重复收入。
        for key in ("content_list", "pdf_info", "pages", "para_blocks", "blocks", "preproc_blocks", "content", "data"):
            if isinstance(node.get(key), (dict, list)):
                visit(node[key], page_number, f"{path}.{key}")
                return
        unknown = True

    visit(payload)
    return blocks, unknown


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _content_words(text: str) -> Counter[str]:
    # 比较可见正文，不让 HTML 标签、Markdown 分隔符及图片路径造成
    # “JSON 缺正文”的误判。这是保守覆盖校验，不负责解析结构。
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    parser = _VisibleText()
    parser.feed(text)
    visible = unescape(" ".join(parser.parts))
    return Counter(re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9_]+", visible.casefold()))


def select_blocks(markdown: str, structured: Any = None) -> tuple[list[RawBlock], dict[str, Any]]:
    md_blocks = markdown_blocks(markdown)
    if structured is None:
        return md_blocks, {"source_format": "markdown", "structured_status": "absent"}
    json_blocks, unknown = structured_blocks(structured)
    md_words = sum((_content_words(block.content) for block in md_blocks), Counter())
    json_words = sum((_content_words(block.content) for block in json_blocks), Counter())
    covers_text = all(json_words[word] >= count for word, count in md_words.items())
    covers_tables = sum(block.block_type == "table" for block in json_blocks) >= sum(
        block.block_type == "table" for block in md_blocks
    )
    if json_blocks and not unknown and covers_text and covers_tables:
        return json_blocks, {"source_format": "structured_json", "structured_status": "complete"}
    if not md_blocks:
        # 没有 Markdown 可回退时，未知 JSON 不能当成完整文档成功返回。
        return [], {"source_format": "structured_json", "structured_status": "unsupported"}
    # 覆盖不足时保留全部 MD，只对明确匹配的节点附加页码和原始坐标。
    # 单向游标同时约束重复正文的对应顺序，不凭相似度猜测页码。
    next_json = 0
    enriched: list[RawBlock] = []
    for block in md_blocks:
        words = _content_words(block.content)
        matched: RawBlock | None = None
        if words:
            for index in range(next_json, len(json_blocks)):
                candidate = json_blocks[index]
                if words == _content_words(candidate.content):
                    matched = candidate
                    next_json = index + 1
                    break
        if matched:
            metadata = dict(block.source_metadata)
            metadata["structured_source"] = matched.source_metadata
            if "bbox" in matched.source_metadata:
                metadata["bbox"] = matched.source_metadata["bbox"]
            block = replace(block, page_number=matched.page_number, source_metadata=metadata)
        enriched.append(block)
    return enriched, {
        "source_format": "markdown", "structured_status": "fallback",
        "structured_unknown_nodes": unknown,
    }

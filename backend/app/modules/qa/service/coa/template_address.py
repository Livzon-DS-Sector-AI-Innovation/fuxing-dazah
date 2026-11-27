"""COA docx 模板编址与写入——AI 标注与回填共用的坐标系统。

docx 里每个可以写文字的段落编一个稳定地址（数据位）：

- 正文段落 ``P3``；页眉/页脚段落 ``H.P1`` / ``F.P0``
- 表格 ``T1``、行 ``T1.R6``、格子按**表格网格列** ``T1.R6.G4``、格内段落
  ``T1.R6.G4.p0``；嵌套表格 ``T1.R6.G4.T0.R0.G0.p0``、文本框 ``B0.P0``

格子按网格列而不是「行内第几格」编号：行内格子数不一致时（多一格、少跨一列）
结果列在所有行里仍是同一个列号——实测按序号编号会把值标到标准列。

写入是跨 run 的原位替换：Word/WPS 会把一段文字拆成多个 run，值两侧的排版
空白留在原处（整段重写会把它们吃掉）。半角 ``<`` 等字符由 XML 库自动转义，
不需要像 Jinja 模板那样先换成全角。
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

_W_P = qn("w:p")
_W_TBL = qn("w:tbl")
_W_TR = qn("w:tr")
_W_TC = qn("w:tc")
_W_T = qn("w:t")
_W_R = qn("w:r")
_W_BR = qn("w:br")
_W_CR = qn("w:cr")
_W_TAB = qn("w:tab")
_W_TXBX = qn("w:txbxContent")
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

PART_TITLES = {"document": "正文", "header": "页眉", "footer": "页脚"}
_RESULT_HEADER_RE = re.compile(r"结果|Results?")
# 标题行一类的占位值：XXXXXXXX / ____ / 一串数字
_INLINE_VALUE_RE = re.compile(r"[XxＸｘ×＊*＿_—–-]{3,}|\d{4,}[A-Za-z0-9_-]*")
# Word 的段落对齐（w:jc）→ CSS text-align；左对齐（start/left）与没写一样，不映射
_ALIGN = {
    "center": "center",
    "right": "end",
    "end": "end",
    "both": "justify",
    "distribute": "justify",
}


class TemplateDocError(ValueError):
    """模板文件无法按 docx 解析（加密、损坏或不是 docx）。"""


class SlotMismatchError(ValueError):
    """标注记录的位置/原文在当前模板里找不到（模板文件与标注不一致）。"""


@dataclass
class Slot:
    """一个可以写文字的段落。"""

    sid: str
    element: Any  # lxml w:p
    part: str  # document / header / footer
    table: str | None = None
    row: str | None = None
    cell: str | None = None
    col: int | None = None  # 网格列号；表格外为 None
    span: int = 1
    vmerge: str | None = None  # 纵向合并：restart / cont
    hmerge: str | None = None  # 横向合并（旧式 hMerge，不带 gridSpan）：restart / cont
    text: str = ""  # 展示文本：w:t 文字，换行记作 \n

    @property
    def in_table(self) -> bool:
        return self.table is not None


@dataclass
class Cell:
    sid: str
    col: int
    span: int
    vmerge: str | None
    hmerge: str | None
    paragraphs: list[Slot] = field(default_factory=list)


@dataclass
class Row:
    sid: str
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    sid: str
    rows: list[Row] = field(default_factory=list)
    # 网格各列宽度（缇）：预览按真实比例画列；文件里没写列宽时为空
    col_widths: list[int] = field(default_factory=list)

    @property
    def ncols(self) -> int:
        return max((c.col + c.span for r in self.rows for c in r.cells), default=0)


@dataclass
class Container:
    """正文/页眉/页脚/文本框：一组有序的段落与表格。"""

    part: str
    sid: str | None = None  # 文本框才有
    title: str | None = None
    blocks: list[Any] = field(default_factory=list)  # Slot | Table | Container


# ─────────────────────── 文本工具 ───────────────────────


def _blocks(container: Any) -> Iterator[Any]:
    """容器下的块级元素（段落/表格），穿过 sdt 与 AlternateContent 外壳。"""
    for child in container:
        if child.tag in (_W_P, _W_TBL):
            yield child
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _blocks(content)
        elif child.tag == f"{{{_MC}}}AlternateContent":
            choice = child.find(f"{{{_MC}}}Choice")
            if choice is not None:
                yield from _blocks(choice)


def _own_nodes(p: Any) -> list[Any]:
    """段落自己的文字类节点（w:t / w:br / w:cr / w:tab）。

    嵌套段落（文本框里的段落）的文字归它自己；属性块（pPr/rPr，含制表位定义）
    里没有正文。
    """
    out: list[Any] = []

    def rec(el: Any) -> None:
        for child in el:
            if child.tag in (_W_P, qn("w:pPr"), qn("w:rPr")):
                continue
            if child.tag in (_W_T, _W_BR, _W_CR, _W_TAB):
                out.append(child)
            else:
                rec(child)

    rec(p)
    return out


def _text_nodes(p: Any) -> list[Any]:
    return [n for n in _own_nodes(p) if n.tag == _W_T]


def flat_text(p: Any) -> str:
    """只由 w:t 拼出的段落文字——写入函数的坐标系（不含换行/制表符）。"""
    return "".join(str(n.text or "") for n in _text_nodes(p))


def display_text(p: Any) -> str:
    """展示文本：换行记作 \\n、制表符记作 \\t。"""
    parts: list[str] = []
    for n in _own_nodes(p):
        if n.tag == _W_T:
            parts.append(str(n.text or ""))
        elif n.tag in (_W_BR, _W_CR):
            parts.append("\n")
        else:
            parts.append("\t")
    return "".join(parts)


def squash(text: str) -> str:
    """去掉全部空白，用于「当前值是否相同」的比较。"""
    return "".join(text.split())


def locate(flat: str, sample: str) -> str | None:
    """在段落文字里按「忽略空白」找到 sample，返回它实际占的那段原文。

    值两侧的排版空白不算进返回值，值内部的空白保留；找不到返回 None。
    """
    needle = squash(sample.replace("⏎", ""))
    if not needle:
        return None
    kept = [i for i, ch in enumerate(flat) if not ch.isspace()]
    stripped = "".join(flat[i] for i in kept)
    pos = stripped.find(needle)
    if pos < 0:
        return None
    return flat[kept[pos] : kept[pos + len(needle) - 1] + 1]


def is_placeholder(text: str) -> bool:
    """XXXXXXXX / ____ / ×××× 这类占位值。"""
    return bool(text.strip()) and bool(_INLINE_VALUE_RE.fullmatch(text.strip()))


def guess_inline_value(text: str) -> str | None:
    """段落里夹在固定文字中间的值（标题行的流水号）：最后一个占位符或数字串。

    整段就是值时返回 None（调用方按整格替换处理）。
    """
    matches = _INLINE_VALUE_RE.findall(text)
    if not matches:
        return None
    value = matches[-1]
    return None if squash(text) == squash(value) else value


# ─────────────────────── 模板文档 ───────────────────────


def _grid_widths(table_el: Any) -> list[int]:
    """表格网格各列的宽度（缇）。

    Word/WPS 写出的表格都带 ``w:tblGrid`` 列宽；个别生成器不写或写成 0，
    这时整张表按「列宽未知」处理（返回空），写坏的单列按其它列的最小宽度补。
    """
    grid_el = table_el.find(qn("w:tblGrid"))
    if grid_el is None:
        return []
    raw: list[int | None] = []
    for col in grid_el.findall(qn("w:gridCol")):
        try:
            width = int(float(col.get(qn("w:w"))))
        except (TypeError, ValueError):
            width = 0
        raw.append(width if width > 0 else None)
    valid = [width for width in raw if width is not None]
    if not valid:
        return []
    return [width if width is not None else min(valid) for width in raw]


def _align(p: Any) -> str | None:
    """段落对齐方式（CSS text-align 的值）：预览照原样排——结果列的值大多是居中的。

    没写对齐或就是左对齐时返回 None，网格数据里就不带这个键。
    """
    ppr = p.find(qn("w:pPr"))
    jc = ppr.find(qn("w:jc")) if ppr is not None else None
    value = jc.get(qn("w:val")) if jc is not None else None
    return _ALIGN.get(value or "")


def _align_json(slot: Slot) -> dict[str, str]:
    align = _align(slot.element)
    return {"align": align} if align else {}


def _open(data: bytes) -> Any:
    try:
        return Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — 加密/损坏/非 docx 统一成一个口径
        raise TemplateDocError(
            "模板文件无法读取（可能已加密或不是有效的 docx），请解密后重新上传"
        ) from exc


def _mark(slot: Slot) -> str:
    return (
        (f"〖跨{slot.span}列〗" if slot.span > 1 else "")
        + ("〖同上〗" if slot.vmerge == "cont" else "")
        + ("〖左格续〗" if slot.hmerge == "cont" else "")
    )


def _disp(text: str) -> str:
    return text.replace("\n", "⏎").replace("\t", " ")


def _cell_lines(cell: Cell) -> str:
    parts = [
        f"[{s.sid}]{_mark(s)}{_disp(s.text) or '(空)'}" for s in cell.paragraphs
    ]
    return " ⏎ ".join(parts) if parts else "(空)"


def _block_lines(blocks: list[Any]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        if isinstance(block, Slot):
            if block.text.strip():
                lines.append(f"[{block.sid}] {_disp(block.text)}")
        elif isinstance(block, Table):
            lines.append(f"表格 {block.sid}（{len(block.rows)} 行）：")
            for row in block.rows:
                cells = " ｜ ".join(_cell_lines(c) for c in row.cells)
                lines.append(f"  行：{cells}")
        else:  # 文本框
            lines.append(f"文本框 {block.sid}：")
            lines.extend(f"  {ln}" for ln in _block_lines(block.blocks))
    return lines


class TemplateDoc:
    """一份 docx 的带地址视图；AI 标注、人工核对、回填都基于它。"""

    def __init__(self, data: bytes) -> None:
        self._document = _open(data)
        self.slots: list[Slot] = []
        self.by_id: dict[str, Slot] = {}
        self.tables: list[Table] = []
        self.containers: list[Container] = []
        self._build()

    # ── 构建 ──

    def _add(self, sid: str, element: Any, part: str, **meta: Any) -> Slot:
        slot = Slot(sid=sid, element=element, part=part, **meta)
        slot.text = display_text(element)
        self.slots.append(slot)
        self.by_id[sid] = slot
        return slot

    def _build(self) -> None:
        body = Container(part="document", title=PART_TITLES["document"])
        self._container(self._document.element.body, "", body)
        self.containers.append(body)
        # 多节文档可能有多份不同的页眉/页眉部件（首页/奇偶页）：各自成段，
        # 第二份起地址前缀带序号（H2.P0）；多节共用同一部件时只取一次
        seen: set[int] = set()
        counts = {"header": 0, "footer": 0}
        for rel in self._document.part.rels.values():
            if rel.reltype == RT.HEADER:
                part, letter = "header", "H"
            elif rel.reltype == RT.FOOTER:
                part, letter = "footer", "F"
            else:
                continue
            element = rel.target_part.element
            if element is None or id(element) in seen:
                continue
            seen.add(id(element))
            counts[part] += 1
            nth = counts[part]
            prefix = f"{letter}." if nth == 1 else f"{letter}{nth}."
            title = PART_TITLES[part] if nth == 1 else f"{PART_TITLES[part]}{nth}"
            container = Container(part=part, title=title)
            self._container(element, prefix, container)
            self.containers.append(container)

    def _container(self, container_el: Any, prefix: str, owner: Container) -> None:
        p_idx = t_idx = 0
        for block in _blocks(container_el):
            if block.tag == _W_P:
                owner.blocks.append(
                    self._add(f"{prefix}P{p_idx}", block, owner.part)
                )
                p_idx += 1
            else:
                table = Table(sid=f"{prefix}T{t_idx}")
                self._table(block, table, owner.part)
                self.tables.append(table)
                owner.blocks.append(table)
                t_idx += 1
        self._textboxes(container_el, prefix, owner)

    def _table(self, table_el: Any, table: Table, part: str) -> None:
        table.col_widths = _grid_widths(table_el)
        for r, tr in enumerate(table_el.findall(_W_TR)):
            row = Row(sid=f"{table.sid}.R{r}")
            table.rows.append(row)
            grid_col = 0
            for tc in tr.findall(_W_TC):
                span, vmerge, hmerge = 1, None, None
                tc_pr = tc.find(qn("w:tcPr"))
                if tc_pr is not None:
                    gs = tc_pr.find(qn("w:gridSpan"))
                    span = int(gs.get(qn("w:val"))) if gs is not None else 1
                    vm = tc_pr.find(qn("w:vMerge"))
                    if vm is not None:
                        vmerge = "restart" if vm.get(qn("w:val")) == "restart" else "cont"
                    hm = tc_pr.find(qn("w:hMerge"))
                    if hm is not None:
                        hmerge = "restart" if hm.get(qn("w:val")) == "restart" else "cont"
                cell = Cell(
                    sid=f"{row.sid}.G{grid_col}",
                    col=grid_col,
                    span=span,
                    vmerge=vmerge,
                    hmerge=hmerge,
                )
                row.cells.append(cell)
                p_idx = nested_idx = 0
                for block in _blocks(tc):
                    if block.tag == _W_P:
                        sid = f"{cell.sid}.p{p_idx}"
                        cell.paragraphs.append(
                            self._add(
                                sid,
                                block,
                                part,
                                table=table.sid,
                                row=row.sid,
                                cell=cell.sid,
                                col=grid_col,
                                span=span,
                                vmerge=vmerge,
                                hmerge=hmerge,
                            )
                        )
                        p_idx += 1
                    else:
                        nested = Table(sid=f"{cell.sid}.T{nested_idx}")
                        self._table(block, nested, part)
                        self.tables.append(nested)
                        nested_idx += 1
                grid_col += span

    def _textboxes(self, container_el: Any, prefix: str, owner: Container) -> None:
        count = 0
        for tx in container_el.iter(_W_TXBX):
            # iter() 会把容器自己也枚举出来（递归进来时容器就是文本框内容）
            if tx is container_el:
                continue
            # AlternateContent 的 Fallback 里是同一份内容；嵌套文本框交给外层递归
            if self._wrapped(tx, container_el):
                continue
            box = Container(part=owner.part, sid=f"{prefix}B{count}")
            self._container(tx, f"{prefix}B{count}.", box)
            owner.blocks.append(box)
            count += 1

    @staticmethod
    def _wrapped(tx: Any, stop: Any) -> bool:
        cur = tx.getparent()
        while cur is not None and cur is not stop:
            if cur.tag == _W_TXBX or cur.tag == f"{{{_MC}}}Fallback":
                return True
            cur = cur.getparent()
        return False

    # ── 视图 ──

    def addressed(self) -> str:
        """给模型的带地址文本：每个数据位一个方括号地址。"""
        lines: list[str] = []
        for container in self.containers:
            block_lines = _block_lines(container.blocks)
            if not block_lines:
                continue
            lines.append(f"【{container.title or container.part}】")
            lines.extend(block_lines)
        return "\n".join(lines)

    def grid(self) -> list[dict[str, Any]]:
        """给前端的网格数据：按原文顺序列出段落与表格（含跨列/跨行标记、列宽）。"""

        def block_json(blocks: list[Any]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for block in blocks:
                if isinstance(block, Slot):
                    out.append(
                        {"type": "p", "sid": block.sid, "text": block.text, **_align_json(block)}
                    )
                elif isinstance(block, Table):
                    out.append(
                        {
                            "type": "table",
                            "sid": block.sid,
                            "ncols": block.ncols,
                            **({"col_widths": block.col_widths} if block.col_widths else {}),
                            "rows": [
                                {
                                    "sid": row.sid,
                                    "cells": [
                                        {
                                            "sid": c.sid,
                                            "col": c.col,
                                            "span": c.span,
                                            "vmerge": c.vmerge,
                                            "hmerge": c.hmerge,
                                            "paras": [
                                                {"sid": s.sid, "text": s.text, **_align_json(s)}
                                                for s in c.paragraphs
                                            ],
                                        }
                                        for c in row.cells
                                    ],
                                }
                                for row in block.rows
                            ],
                        }
                    )
                else:
                    out.append(
                        {
                            "type": "textbox",
                            "sid": block.sid,
                            "blocks": block_json(block.blocks),
                        }
                    )
            return out

        return [
            {
                "part": c.part,
                "title": c.title or c.part,
                "sid": c.sid,
                "blocks": block_json(c.blocks),
            }
            for c in self.containers
        ]

    def result_columns(self) -> dict[str, int]:
        """项目表的结果列：首行表头里含「结果/Results」的格子的网格列号。"""
        out: dict[str, int] = {}
        for table in self.tables:
            if not table.rows:
                continue
            for cell in table.rows[0].cells:
                head = "".join(s.text for s in cell.paragraphs)
                if _RESULT_HEADER_RE.search(head):
                    out[table.sid] = cell.col
                    break
        return out

    def resolve(self, sid: str) -> Slot | None:
        """宽松匹配地址：表格格子必须带段号，正文/页眉段落的段号可带可不带。"""
        candidate = str(sid).strip()
        if candidate in self.by_id:
            return self.by_id[candidate]
        extended = f"{candidate}.p0"
        if extended in self.by_id:
            return self.by_id[extended]
        stripped = re.sub(r"\.p\d+$", "", candidate)
        if stripped != candidate and stripped in self.by_id:
            return self.by_id[stripped]
        return None

    def row_context(self, slot: Slot, exclude_cell: str | None = None) -> str:
        """所在行里除指定格以外的文字（项目名、标准），人工核对时看「是不是这一行」。

        跨行合并的大类格（性状/鉴别…）只在第一行有文字，续行的空格用合并起点
        那一行的文字代替——提取出的项目名常带着大类名（「纯度 DBM-A0」）。
        """
        if slot.table is None or slot.row is None:
            return ""
        table = next((t for t in self.tables if t.sid == slot.table), None)
        if table is None:
            return ""
        index = next((i for i, r in enumerate(table.rows) if r.sid == slot.row), None)
        if index is None:
            return ""
        parts: list[str] = []
        for cell in table.rows[index].cells:
            if cell.sid == exclude_cell:
                continue
            texts = [" ".join(s.text.split()) for s in cell.paragraphs if s.text.strip()]
            if not texts and cell.vmerge == "cont":
                origin = self._merge_origin(table, index, cell.col)
                if origin is not None:
                    texts = [" ".join(s.text.split()) for s in origin.paragraphs if s.text.strip()]
            parts.extend(t for t in texts if t)
        return " ｜ ".join(parts)

    @staticmethod
    def _merge_origin(table: Table, row_index: int, col: int) -> Cell | None:
        for row in reversed(table.rows[:row_index]):
            above = next((c for c in row.cells if c.col == col), None)
            if above is None:
                continue
            return above if above.vmerge == "restart" else None
        return None

    # ── 写入 ──

    @staticmethod
    def _ensure_text_node(p: Any) -> Any:
        nodes = _text_nodes(p)
        if nodes:
            return nodes[0]
        runs = [n for n in p if n.tag == _W_R]
        if runs:
            return _append(runs[0], _W_T)
        run = _append(p, _W_R)
        p_pr = p.find(qn("w:pPr"))
        r_pr = p_pr.find(qn("w:rPr")) if p_pr is not None else None
        if r_pr is not None:
            run.append(deepcopy(r_pr))  # 继承段落标记的字体
        return _append(run, _W_T)

    def write(self, sid: str, mode: str, old: str, new: str) -> None:
        """把数据位里的 ``old`` 换成 ``new``；``new`` 里的换行写成 Word 换行符。

        mode="replace"：整段内容就是值（空格或整格文字），重写整段并保留值两侧
        的排版空白；mode="inplace"：值夹在固定文字中间，只替换 ``old`` 那一段。
        """
        slot = self.by_id.get(sid)
        if slot is None:
            raise SlotMismatchError(f"数据位 {sid} 在模板中不存在")
        if mode == "replace":
            self._write_replace(slot.element, old, new)
        else:
            self._write_inplace(slot.element, old, new)
        slot.text = display_text(slot.element)

    def _write_replace(self, p: Any, old: str, new: str) -> None:
        nodes = _own_nodes(p)
        texts = [n for n in nodes if n.tag == _W_T]
        target = texts[0] if texts else self._ensure_text_node(p)
        for node in nodes:
            if node.tag != _W_T:
                node.getparent().remove(node)  # 原有的换行/制表符随旧值一起走
        for node in texts:
            if node is not target:
                node.text = ""
        prefix = old[: len(old) - len(old.lstrip())] if old.strip() else ""
        suffix = old[len(old.rstrip()) :] if old.strip() else ""
        target.text = f"{prefix}{new}{suffix}"
        self._expand_breaks(target)

    def _write_inplace(self, p: Any, old: str, new: str) -> None:
        nodes = _text_nodes(p)
        if not nodes:
            nodes = [self._ensure_text_node(p)]
        texts = [str(n.text or "") for n in nodes]
        joined = "".join(texts)
        start = joined.find(old)
        if start < 0:
            raise SlotMismatchError("标注记录的原文在模板中找不到")
        end = start + len(old)
        cursor = 0
        first = True
        for node, text in zip(nodes, texts, strict=True):
            s, e = cursor, cursor + len(text)
            cursor = e
            if e <= start or s >= end:
                continue
            local_s, local_e = max(start, s) - s, min(end, e) - s
            if first:
                node.text = f"{text[:local_s]}{new}{text[local_e:]}"
                self._expand_breaks(node)
                first = False
            else:
                node.text = f"{text[:local_s]}{text[local_e:]}"

    @staticmethod
    def _expand_breaks(node: Any) -> None:
        """把文字节点里的 \\n 展开成 <w:br/>（同一个 run 内，字体不变）。"""
        text = str(node.text or "")
        node.set(_XML_SPACE, "preserve")
        if "\n" not in text:
            return
        parts = text.split("\n")
        node.text = parts[0]
        parent = node.getparent()
        index = parent.index(node) + 1
        for part in parts[1:]:
            parent.insert(index, parent.makeelement(_W_BR, {}))
            index += 1
            following = parent.makeelement(_W_T, {})
            following.text = part
            following.set(_XML_SPACE, "preserve")
            parent.insert(index, following)
            index += 1

    def snapshot(self) -> dict[str, str]:
        return {s.sid: flat_text(s.element) for s in self.slots}

    def bytes(self) -> bytes:
        buf = io.BytesIO()
        self._document.save(buf)
        return buf.getvalue()


def _append(parent: Any, tag: str) -> Any:
    node = parent.makeelement(tag, {})
    parent.append(node)
    return node

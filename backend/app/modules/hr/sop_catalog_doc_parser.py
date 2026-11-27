"""SOP 目录 Word 文档（GMP 文件目录 .docx）解析。

入平台的数据文件统一用 .docx（系统不处理旧版 .doc）。人事手里的 SOP 目录是
中英对照的 GMP 文件目录 Word 文档：
- 表头合并行是大分类（如「岗位职责：提炼工程三部」）
- 数据行四列：序号 / 文件名称（中英双语两段） / 文件编号 / 生效日期
口径（2026-11-26 与人事对齐）：
- 文件行只取中文文件名 → file_name
- SOP 编号截断到版本号之前（SOP.01.3701.002 → SOP.01.3701）→ sop_number
- 大分类整行 → category；部门从大分类冒号后推导，无冒号回退上传文件名括号内「-」尾段
"""

from __future__ import annotations

import io
import re
import zipfile

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 版本号 = 编号末尾「.三位数字」段（SOP.01.3701.002 → SOP.01.3701；SOP.01.3701 本身不动）
_VERSION_TAIL_RE = re.compile(r"^(.+)\.\d{3}$")
# 编号 cell：字母开头的点分数字串，或三段以上纯数字点分（SOP.01.3701.002 / 01.3701.002）
_NUMBER_CELL_RE = re.compile(r"^[A-Za-z]{2,}[A-Za-z]*[.\d]*\d$|^\d+(?:\.\d+){2,}$")
# 序号 cell：1~3 位纯数字（01 / 1）
_INDEX_CELL_RE = re.compile(r"^\d{1,3}$")
_DATE_LIKE_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")
_HEADER_CELLS = {
    "序号", "no.", "文件名称", "document name", "文件编号", "document no.",
    "生效日期", "effective date", "标准文件", "standard document",
}


def parse_catalog_document(content: bytes, filename: str = "") -> list[dict[str, str | None]]:
    """GMP 文件目录 Word 文档（.docx）→ SOP 目录条目列表。

    条目字段：category / file_name / sop_number / department（file_name 必有，其余可为 None）。
    """
    if not _is_docx(content):
        raise ValueError("仅支持 .docx 格式的 GMP 文件目录文档；旧版 .doc 请用 Word 另存为 .docx 后重试")
    entries = _walk_cells(_docx_cells(content), filename)
    if not entries:
        raise ValueError("未从文档中解析出目录条目，请确认为 GMP 文件目录格式")
    return entries


# ── cell 文本提取 ──

def _is_docx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return "word/document.xml" in zf.namelist()
    except Exception:
        return False


def _docx_cells(content: bytes) -> list[str]:
    """docx → 表格 cell 文本扁平序列；合并单元格的相邻重复 cell 去重。"""
    from docx import Document

    doc = Document(io.BytesIO(content))
    cells: list[str] = []
    for table in doc.tables:
        for row in table.rows:
            texts = [_norm_cell(c.text) for c in row.cells]
            cells.extend(t for i, t in enumerate(texts) if i == 0 or t != texts[i - 1])
    return cells


# ── cell 序列 → 目录条目 ──

def _norm_cell(text: str) -> str:
    return text.replace("\r\n", "\r").replace("\n", "\r").replace("\x0b", "\r").strip()


def _is_header_cell(cell: str) -> bool:
    return any(p.strip().lower() in _HEADER_CELLS for p in cell.split("\r"))


def _chinese_text(cell: str) -> str:
    """cell 内多段落取含中文的段落（中英对照目录：中文行才是文件名/分类）。"""
    paras = [p.strip() for p in cell.split("\r") if p.strip()]
    for p in paras:
        if _CJK_RE.search(p):
            return p
    return paras[0] if paras else ""


def _truncate_version(raw: str) -> str:
    m = _VERSION_TAIL_RE.match(raw)
    return m.group(1) if m else raw


def _derive_department(category: str, filename: str) -> str | None:
    """大分类「岗位职责：提炼工程三部」→ 冒号后缀；无冒号回退文件名括号「xxx-部门」尾段。"""
    if "：" in category or ":" in category:
        tail = re.split(r"[：:]", category, 1)[1].strip()
        if tail:
            return tail[:128]
    m = re.search(r"[(（]([^)）]+)[)）]", filename)
    if m and "-" in m.group(1):
        tail = m.group(1).rsplit("-", 1)[-1].strip()
        if tail:
            return tail[:128]
    return None


def _next_meaningful(cells: list[str], start: int) -> int | None:
    for j in range(start, len(cells)):
        if cells[j]:
            return j
    return None


def _walk_cells(cells: list[str], filename: str) -> list[dict[str, str | None]]:
    """扁平 cell 序列按锚点走读：序号 cell → 中文名称 cell → 编号 cell 收敛成一条。

    不重建行结构，锚点配对对空 cell 稳健；无序号的行用「中文 cell 紧跟编号 cell」兜底。
    """
    entries: list[dict[str, str | None]] = []
    category: str | None = None
    department: str | None = None
    i = 0
    while i < len(cells):
        cell = cells[i]
        if not cell or _is_header_cell(cell) or _DATE_LIKE_RE.search(cell):
            i += 1
            continue
        compact = re.sub(r"\s+", "", cell)
        if _INDEX_CELL_RE.match(compact):
            # 序号 cell：其后第一个中文 cell 是文件名，再后第一个编号 cell 是编号
            j = _next_meaningful(cells, i + 1)
            if j is not None and _CJK_RE.search(cells[j]) and not _DATE_LIKE_RE.search(cells[j]):
                name = _chinese_text(cells[j])
                k = _next_meaningful(cells, j + 1)
                if name and k is not None and _NUMBER_CELL_RE.match(re.sub(r"\s+", "", cells[k])):
                    entries.append({
                        "category": category,
                        "file_name": name,
                        "sop_number": _truncate_version(re.sub(r"\s+", "", cells[k])),
                        "department": department,
                    })
                    i = k + 1
                    continue
            i += 1
            continue
        if _NUMBER_CELL_RE.match(compact) or not _CJK_RE.search(cell):
            i += 1
            continue
        # 无序号锚定的中文 cell：紧跟编号 cell 则按数据行取，否则视为大分类行
        name = _chinese_text(cell)
        j = _next_meaningful(cells, i + 1)
        if j is not None and _NUMBER_CELL_RE.match(re.sub(r"\s+", "", cells[j])):
            entries.append({
                "category": category,
                "file_name": name,
                "sop_number": _truncate_version(re.sub(r"\s+", "", cells[j])),
                "department": department,
            })
            i = j + 1
            continue
        if "：" in cell or ":" in cell:
            category = name
            department = _derive_department(category, filename)
        i += 1
    return entries

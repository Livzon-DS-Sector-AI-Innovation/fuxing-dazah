"""PDF 结构化抽取：标题/段落/表格识别，页眉页脚与草案行号剥离。

面向 Word 导出的文字版 PDF（ICH/EMA/FDA 等国外法规文件的标准形态），
不做 OCR——扫描版直接报错。PDF 是打印坐标流，无法原位回写译文，
因此抽取目标是"结构重建"：标题（带层级）/ 段落 / 表格，供后续重排输出。

抽取管线（两遍扫描）：
  第一遍（全局）：正文左边界、跨页重复的页眉/页脚词、每页表格 bbox、
                  各字号行距众数（段落切分阈值的数据来源）
  第二遍（逐页）：行装配（同基线 span 合并，剔页眉页脚/左边距行号/表格内文本/目录页）
                  → 行距/字号/缩进规则重组段落 → 跨页句子保守合并
                  → 标题分类（整段粗体 + 字号/编号深度）→ 生成翻译单元
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extract import detect_lang

# 图片块区域渲染分辨率（输出 DOCX 中的嵌入图清晰度）
_IMAGE_DPI = 200

# 草案行号/页码等纯数字词的判定
_PURE_DIGIT = re.compile(r"^\d+$")
# 目录页特征：点导引线 + 行尾页码，如 "8.1 PURPOSE ...... 24"
_TOC_LINE = re.compile(r"\.{4,}\s*\d+\s*$")
# 标题开头的章节编号："1 "、"3.4.3 "、"2.2.1Selection"
_SECTION_NUM = re.compile(r"^(\d+(?:\.\d+)*)")
_ANNEX_HEAD = re.compile(r"^(Annex|ANNEX)\b")
# 附录内部标签："A3-1"（页脚页面标签 / 小节编号前缀）
_ANNEX_LABEL = re.compile(r"^[A-Z]\d+-\d+$")
# 附录小节编号，如 "A1-3.1.2"
_ANNEX_SECTION = re.compile(r"^([A-Z]\d+-\d+(?:\.\d+)*)")
# 脚注/编号条目起始："1 For testing..."、"2 For a full design..."
_ITEM_START = re.compile(r"^\d{1,2}\s+\S")
# 行尾数字范围断词："2-" + "8℃"
_HYPHEN_NUM = re.compile(r"\d-$")


@dataclass
class PDFUnit:
    """一个待翻译单元。与 docx 流水线的 Unit 接口兼容
    （runner.translate_all 依赖 idx/text/lang/in_table/translation）。"""

    idx: int
    text: str
    lang: str = "other"          # zh / en / other
    is_heading: bool = False
    in_table: bool = False
    page: int = 0                # 1-based
    action: str = "skip"         # translate / skip
    reason: str = ""
    translation: str = ""


@dataclass
class Block:
    """文档块，重排输出 DOCX 的依据。_size/_bold/_y 为分类用中间属性。"""

    kind: str                    # "heading" / "para" / "table" / "image"
    page: int
    text: str = ""               # heading / para
    level: int = 0               # heading 级别（1 最高）
    rows: list = field(default_factory=list)          # table: list[list[str|None]]
    cell_units: list = field(default_factory=list)    # table: [(r, c, PDFUnit)]
    unit: PDFUnit | None = None  # heading / para 的翻译单元
    image_bytes: bytes = b""     # image: 渲染后的 PNG
    image_w_pt: float = 0.0      # image: 原始显示宽度（pt，用于按比例定宽）
    _y: float = 0.0
    _size: float = 11.0
    _bold: bool = False


@dataclass
class PDFExtractStats:
    total_pages: int = 0
    processed_pages: int = 0
    toc_pages: int = 0
    tables: int = 0
    headings: int = 0
    paragraphs: int = 0
    cells: int = 0
    images: int = 0
    line_numbers_stripped: int = 0
    pages_with_header_stripped: int = 0
    cross_page_merges: int = 0
    body_font_size: float = 0.0


@dataclass
class _Line:
    """装配后的一个可视行（同基线 span 已按 x 排序合并）。"""

    page: int
    y: float
    x: float
    size: float
    bold: bool
    text: str


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _in_table_area(x: float, y: float, table_bboxes: list) -> bool:
    """点是否落在表格区域内（bbox 四周内缩 3pt，避免贴边的表标题/脚注误伤）。"""
    for x0, y0, x1, y1 in table_bboxes:
        if x0 + 3 <= x <= x1 - 3 and y0 + 3 <= y <= y1 - 3:
            return True
    return False


def _join_para_text(lines: list[_Line]) -> str:
    """行 → 段落文本。行尾连字符直接拼接（Word 导出断词），其余以空格相连。"""
    parts: list[str] = []
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if parts and parts[-1].endswith("-") and (t[:1].islower() or _HYPHEN_NUM.search(parts[-1]) and t[:1].isdigit()):
            parts[-1] += t
        else:
            parts.append(t)
    return _norm(" ".join(parts))


def extract_pdf(path: str, page_range: tuple[int, int] | None = None):
    """抽取 PDF 结构。page_range 为 1-based 闭区间（None=全部页）。

    返回 (blocks, units, stats)：blocks 为文档顺序的结构块（含未翻译元素），
    units 为可翻译单元（段落/标题/非空表格单元格）。
    """
    import pymupdf

    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("PDF 已加密，无法处理")
    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("PDF 无页面")

    if page_range:
        first = max(0, page_range[0] - 1)
        last = min(page_range[1], total_pages)
        if first >= last:
            raise ValueError(f"页码范围无效：{page_range}（文档共 {total_pages} 页）")
    else:
        first, last = 0, total_pages
    page_nos = list(range(first, last))

    stats = PDFExtractStats(total_pages=total_pages, processed_pages=len(page_nos))

    # ── 第一遍：全局指标 ────────────────────────────────────────
    all_words = {}
    x0_counter: dict[int, int] = {}
    for pno in page_nos:
        words = doc[pno].get_text("words")
        all_words[pno] = words
        for w in words:
            if _PURE_DIGIT.match(w[4].strip()):
                continue
            key = round(w[0])
            x0_counter[key] = x0_counter.get(key, 0) + 1
    if not x0_counter:
        raise ValueError("PDF 无文本层（疑似扫描件），请先做 OCR。本工具只处理文字版 PDF")
    body_left = max(x0_counter.items(), key=lambda kv: kv[1])[0]
    margin_cut = body_left - 15  # 行号列判定阈值（正文左边界左侧 15pt）

    # 页眉/页脚词：顶部/底部区域按"出现页数"投票（词级，兼容分节交替页眉）
    page_h = doc[page_nos[0]].rect.height
    header_cut, footer_cut = page_h * 0.11, page_h * 0.90
    header_word_pages: dict[str, set] = {}
    footer_word_pages: dict[str, set] = {}
    for pno in page_nos:
        for w in all_words[pno]:
            t = w[4].strip()
            if not t or _PURE_DIGIT.match(t) or w[0] < margin_cut:
                continue
            if w[1] < header_cut:
                header_word_pages.setdefault(t, set()).add(pno)
            elif w[1] > footer_cut:
                footer_word_pages.setdefault(t, set()).add(pno)
    min_pages = max(3, int(len(page_nos) * 0.4))
    header_words = {t for t, pgs in header_word_pages.items() if len(pgs) >= min_pages}
    footer_words = {t for t, pgs in footer_word_pages.items() if len(pgs) >= min_pages}

    # 每页表格（bbox + 单元格）
    page_tables: dict[int, list] = {}
    for pno in page_nos:
        try:
            tabs = doc[pno].find_tables()
        except Exception:  # noqa: BLE001 —— 单页表格识别失败不阻断整体
            continue
        tables = []
        for t in tabs.tables:
            rows = t.extract()
            if not rows or len(rows[0]) < 2:
                continue  # 单列"表格"多为误检
            tables.append((t.bbox, rows))
        if tables:
            page_tables[pno] = tables
            stats.tables += len(tables)

    # 行距众数（同页相邻、同字号同粗细的可视行）——段落切分阈值的数据来源
    _raw_lines = {pno: _collect_lines(doc[pno], pno, margin_cut, stats) for pno in page_nos}
    gap_counter: dict[int, dict[float, int]] = {}
    for pno in page_nos:
        lines = _raw_lines[pno]
        for a, b in zip(lines, lines[1:]):
            if abs(a.size - b.size) < 0.4 and a.bold == b.bold:
                c = gap_counter.setdefault(round(a.size), {})
                g = round(b.y - a.y, 1)
                c[g] = c.get(g, 0) + 1

    # 页眉/页脚整行投票：分节交替页眉（如附录页的附录名行）只覆盖部分页面，
    # 词级投票抓不到，按"整行文本在 ≥5 页顶部/底部重复"补充认定
    header_line_pages: dict[str, set] = {}
    footer_line_pages: dict[str, set] = {}
    for pno in page_nos:
        for ln in _raw_lines[pno]:
            t = _norm(ln.text)
            if not t or _PURE_DIGIT.match(t):
                continue
            if ln.y < header_cut:
                header_line_pages.setdefault(t, set()).add(pno)
            elif ln.y > footer_cut:
                footer_line_pages.setdefault(t, set()).add(pno)
    line_min_pages = max(5, int(len(page_nos) * 0.05))
    header_lines = {t for t, pgs in header_line_pages.items() if len(pgs) >= line_min_pages}
    footer_lines = {t for t, pgs in footer_line_pages.items() if len(pgs) >= line_min_pages}

    def _gap_break(size: float, gap: float) -> bool:
        """行距超过该字号的段落间距阈值 → 切段。"""
        c = gap_counter.get(round(size))
        if c and sum(c.values()) >= 10:
            mode = max(c.items(), key=lambda kv: kv[1])[0]
            return gap > mode * 1.3 + 1
        return gap > size * 2.3  # 样本不足时的保守估计（11pt→25.3，段间 27 可分）

    # ── 第二遍：逐页装配 ────────────────────────────────────────
    blocks: list[Block] = []
    for pno in page_nos:
        page = doc[pno]
        lines = _raw_lines[pno]

        # 目录页：点导引线行占比高 → 整页跳过（重排版式下页码引用无意义）
        toc_lines = sum(1 for ln in lines if _TOC_LINE.search(ln.text))
        if lines and toc_lines >= 8 and toc_lines / len(lines) >= 0.2:
            stats.toc_pages += 1
            continue

        # 页眉/页脚/页码剔除 + 表格内文本剔除
        kept: list[_Line] = []
        header_stripped = False
        table_bboxes = [t[0] for t in page_tables.get(pno, [])]
        for ln in lines:
            t = _norm(ln.text)
            if ln.y < header_cut:
                if _PURE_DIGIT.match(t) or t in header_lines or (t and all(wd in header_words for wd in t.split())):
                    header_stripped = True
                    continue
            if ln.y > footer_cut:
                if _PURE_DIGIT.match(t) or t in footer_lines or (t and all(wd in footer_words for wd in t.split())):
                    continue
            # 附录页码标签（"A1-12"）位于标准页脚区上方，按模式 + 底部区域剥离
            if ln.y > page_h * 0.85 and _ANNEX_LABEL.match(t):
                continue
            if _in_table_area(ln.x + 20, ln.y + 4, table_bboxes):
                continue
            kept.append(ln)
        if header_stripped:
            stats.pages_with_header_stripped += 1

        blocks.extend(_assemble_paras(kept, pno + 1, _gap_break))
        for bbox, rows in page_tables.get(pno, []):
            # 单元格内换行是排版产物，统一为空格（单元格作为整体翻译）
            norm_rows = [[(_norm(str(c)) if c else None) for c in row] for row in rows]
            blocks.append(Block(kind="table", page=pno + 1, rows=norm_rows, _y=bbox[1]))

        # 图片块：不翻译，按原位置嵌入输出文档。
        # 区域渲染为 PNG（而非抽取原始图片流）——正确处理透明蒙版，
        # 且所见即所得；矢量绘图（表格边框等）不属于图片块。
        for info in page.get_image_info():
            x0, y0, x1, y1 = info["bbox"]
            if x1 - x0 < 12 or y1 - y0 < 12:
                continue  # 图标/分隔线类微图，不值得占一个块
            try:
                pix = page.get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), dpi=_IMAGE_DPI)
                blocks.append(Block(kind="image", page=pno + 1, _y=y0,
                                    image_bytes=pix.tobytes("png"), image_w_pt=x1 - x0))
                stats.images += 1
            except Exception:  # noqa: BLE001 —— 单张图渲染失败不阻断整体，跳过并少计
                continue

    # 页内阅读顺序（表格按 bbox 纵坐标与正文穿插）
    blocks.sort(key=lambda b: (b.page, b._y))

    # 跨页断句合并（保守：仅正文段，前段无终结标点且后段小写开头）
    stats.cross_page_merges = _merge_cross_page(blocks)

    # ── 标题分类 + 翻译单元 ─────────────────────────────────────
    size_votes: dict[float, int] = {}
    for b in blocks:
        if b.kind == "para":
            size_votes[b._size] = size_votes.get(b._size, 0) + len(b.text)
    body_size = max(size_votes.items(), key=lambda kv: kv[1])[0] if size_votes else 11.0
    stats.body_font_size = round(body_size, 1)

    units: list[PDFUnit] = []
    idx = 0
    for b in blocks:
        if b.kind == "table":
            for r, row in enumerate(b.rows):
                for c, cell in enumerate(row):
                    text = _norm(str(cell)) if cell else ""
                    if not text:
                        continue
                    lang = detect_lang(text)
                    if lang == "other":
                        continue  # 纯数字/符号单元格，无需翻译
                    idx += 1
                    u = PDFUnit(idx=idx, text=text, lang=lang,
                                in_table=True, page=b.page)
                    b.cell_units.append((r, c, u))
                    units.append(u)
                    stats.cells += 1
            continue
        if b.kind == "image":
            continue  # 图片不翻译，仅按位置嵌入
        is_head, level = _classify_heading(b, body_size)
        if is_head:
            b.kind, b.level = "heading", level
            stats.headings += 1
        else:
            stats.paragraphs += 1
        lang = detect_lang(b.text)
        if lang == "other":
            continue  # 纯符号/数字段，无翻译价值
        idx += 1
        u = PDFUnit(idx=idx, text=b.text, lang=lang, is_heading=is_head, page=b.page)
        b.unit = u
        units.append(u)

    return blocks, units, stats


def _collect_lines(page, pno: int, margin_cut: float, stats: PDFExtractStats) -> list[_Line]:
    """页 → 可视行列表：同基线 span 按 x 排序合并，剔左边距行号。"""
    spans = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                t = s["text"]
                if not t.strip():
                    continue
                # 左边距行号：x 在正文左边界左侧且为纯数字（ICH 草案征询意见的定位行号）
                if s["bbox"][0] < margin_cut and _PURE_DIGIT.match(t.strip()):
                    stats.line_numbers_stripped += 1
                    continue
                x0, y0, x1, _ = s["bbox"]
                spans.append((y0, x0, x1, s["size"], bool(s["flags"] & 16), t))
    spans.sort(key=lambda v: (v[0], v[1]))

    lines: list[_Line] = []
    group: list = []  # 当前可视行的 span 组
    group_y = 0.0
    for y, x0, x1, size, bold, t in spans:
        if group and abs(y - group_y) > 0.5 * max(size, group[-1][3]) + 1.5:
            lines.append(_make_line(pno, group))
            group = []
        if not group:
            group_y = y
        group.append((y, x0, x1, size, bold, t))
    if group:
        lines.append(_make_line(pno, group))
    return [ln for ln in lines if ln.text]


def _make_line(pno: int, group: list) -> _Line:
    group = sorted(group, key=lambda v: v[1])  # 按 x 排序，消除上标先序问题
    text = ""
    for i, (_, x0, x1, _, _, t) in enumerate(group):
        if i and x0 - group[i - 1][2] > 1.5:
            text += " "  # span 间空隙（Word 制表符/大间距），补回分隔空格
        text += t
    return _Line(page=pno + 1, y=group[0][0], x=min(g[1] for g in group),
                 size=max(g[3] for g in group), bold=all(g[4] for g in group), text=text.strip())


def _assemble_paras(lines: list[_Line], page_label: int, gap_break) -> list[Block]:
    """行 → 段落块。切分依据：字号/粗细变化、行距阈值、项目符号、顶格编号条目。"""
    blocks: list[Block] = []
    cur: list[_Line] = []
    cur_x0 = 0.0

    def _flush():
        nonlocal cur, cur_x0
        if not cur:
            return
        text = _join_para_text(cur)
        if text:
            blocks.append(Block(
                kind="para", page=page_label, text=text,
                _y=cur[0].y, _size=max(ln.size for ln in cur), _bold=all(ln.bold for ln in cur),
            ))
        cur = []
        cur_x0 = 0.0

    for ln in lines:
        if cur:
            prev = cur[-1]
            gap = ln.y - prev.y
            # 顶格编号条目（脚注/编号列表）：当前行回到段落左边界，且上一行是缩进续行
            starts_item = ln.x <= cur_x0 + 3 and prev.x > cur_x0 + 4 and bool(_ITEM_START.match(ln.text))
            if (
                abs(ln.size - prev.size) > 0.4
                or ln.bold != prev.bold
                or ln.text.startswith("•")
                or gap_break(prev.size, gap)
                or starts_item
            ):
                _flush()
        if not cur:
            cur_x0 = ln.x
        cur.append(ln)
    _flush()
    return blocks


def _merge_cross_page(blocks: list[Block]) -> int:
    """跨页断句合并：前段无终结标点 + 后段小写开头 + 字号一致 → 并入前段。"""
    merged = 0
    i = 0
    while i < len(blocks) - 1:
        a, b = blocks[i], blocks[i + 1]
        if (
            a.kind == "para" and b.kind == "para"
            and b.page == a.page + 1
            and abs(a._size - b._size) <= 0.4
            and a.text[-1:] not in ".;:?!。；：？！"
            and b.text[:1].islower()
        ):
            a.text = a.text + " " + b.text
            blocks.pop(i + 1)
            merged += 1
            continue
        i += 1
    return merged


def _classify_heading(b: Block, body_size: float) -> tuple[bool, int]:
    """段落块 → (是否标题, 级别)。

    标题判定：整段粗体，且满足字号放大 / 章节编号开头 / Annex 开头 / 全大写之一。
    级别：编号深度优先（"1"→1，"1.1"→2，"1.1.1"→3），其次字号档位。
    """
    text = b.text
    if len(text) > 300 or not b._bold:
        return False, 0
    big = b._size >= body_size + 0.5
    m = _SECTION_NUM.match(text)
    letters = [ch for ch in text if ch.isalpha()]
    upper_ratio = (sum(1 for ch in letters if ch.isupper()) / len(letters)) if letters else 0
    is_head = (
        big
        or bool(m)
        or bool(_ANNEX_HEAD.match(text))
        or (upper_ratio >= 0.9 and len(letters) >= 6)
        or (big and len(text) <= 12)  # 封面短标题，如 "Q1"
    )
    if not is_head:
        return False, 0
    if m and not _ANNEX_HEAD.match(text):
        return True, min(m.group(1).count(".") + 1, 4)
    ma = _ANNEX_SECTION.match(text)
    if ma:  # 附录小节："A1-3"→2、"A1-3.1"→3、"A1-3.1.1"→4
        return True, min(2 + ma.group(1).count("."), 4)
    if b._size >= 16 or big:
        return True, 1
    return True, 2

"""安全模块文档解析器 — PDF/DOCX/TXT 文本提取 + 垃圾检测。

不使用平台层的 DocumentParser（pypdf 对中文 CMap 字体 PDF 解析失败
产生二进制垃圾）。直接使用 PyMuPDF (fitz) 作为主解析引擎，对中文 PDF
支持远优于 pypdf。

解析链条（按优先级）：
  PDF → PyMuPDF (fitz) → pdfplumber → MarkItDown → 空（报告错误）
  DOCX → python-docx
  TXT → 直接读取

自查自纠机制：
  is_text_garbled()  — 全文级垃圾检测（用于解析后校验）
  is_chunk_valid()   — 逐 chunk 质量校验（用于分块后校验）
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 常量 ──

# 有效内容的最低字符数（低于此值认为解析失败）
_MIN_CHARS = 50

# ── PDF 垃圾检测（与 document_loader._is_parsed_text_valid 一致）──

_PDF_BINARY_MARKERS = frozenset({
    "endstream", "endobj", "/Type/Font", "/Subtype/", "/BaseFont/",
    "/Encoding/", "/FontDescriptor", "/FirstChar", "/WinAnsiEncoding",
    "/ABCDEE+", "<< /Length", "xref", "trailer", "startxref", "%%EOF",
})

_CMAP_GLYPH_RE = re.compile(r"/G\d+[A-Z]?")


def is_text_garbled(text: str) -> bool:
    """检查解析文本是否为 PDF 二进制垃圾。

    满足以下任一条件视为垃圾：
    1. 3+ 个 PDF 结构标记
    2. 5+ 个 CMap glyph 引用
    3. 可读字符比例 < 15%
    """
    if not text:
        return True

    # 短文本不一定是垃圾——可能只是短标题/条款摘要
    # 仅当短文本包含可疑标记时才视为垃圾
    if len(text) < _MIN_CHARS:
        # 快速扫描是否有 PDF/CMap 痕迹
        has_pdf_marker = any(m in text for m in _PDF_BINARY_MARKERS)
        if has_pdf_marker:
            return True
        if _CMAP_GLYPH_RE.search(text):
            return True
        # 短文本但全是不可读字符 → 垃圾
        readable_short = sum(
            1 for ch in text
            if ('一' <= ch <= '鿿' or 'a' <= ch.lower() <= 'z'
                or '0' <= ch <= '9')
        )
        return readable_short == 0

    # ── PDF 结构标记 ──
    marker_hits = sum(1 for m in _PDF_BINARY_MARKERS if m in text)
    if marker_hits >= 3:
        return True

    # ── CMap glyph 引用 ──
    glyph_count = len(_CMAP_GLYPH_RE.findall(text))
    if glyph_count >= 5:
        return True

    # ── 可读字符比例 ──
    # 先扫描是否存在异常字符（非 CJK、非 ASCII 可打印、非空白）
    # 仅当存在足够多异常字符时才做比例检查，避免短中文文本误判
    sample = text[:5000]
    non_printable = 0
    readable = 0
    total_non_space = 0
    for ch in sample:
        cp = ord(ch)
        is_readable = (
            '一' <= ch <= '鿿'
            or '　' <= ch <= '〿'
            or '＀' <= ch <= '￯'
            or 'a' <= ch.lower() <= 'z'
            or '0' <= ch <= '9'
            or ch in ' \t\n\r.,;:!?()[]{}<>/\\-+=@#$%^&*_|~`\'"·—…'
        )
        if is_readable:
            readable += 1
        else:
            non_printable += 1

        if cp > 32:  # 不计空白字符
            total_non_space += 1

    # 仅当存在异常字符（≥5 个非可打印字节）时才用全量比例检查
    if non_printable >= 5:
        ratio = readable / len(sample) if sample else 0
        return ratio < 0.15

    # 否则检查非空白字符中可读比例（防止短中文标题被误判）
    if total_non_space > 0:
        ratio_ns = readable / total_non_space
        return ratio_ns < 0.10

    return False  # 纯空白文本无内容，但不算垃圾


# ── 逐 chunk 质量校验（自查自纠 Layer 2）──

# 可接受的短 chunk 模式：章节标题、条款编号
_VALID_SHORT_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千\d]+章"),   # 第X章
    re.compile(r"^第[一二三四五六七八九十百千\d]+节"),   # 第X节
    re.compile(r"^第[一二三四五六七八九十百千\d]+条"),   # 第X条
    re.compile(r"^\d+\.\d+"),                           # 编号 1.1
    re.compile(r"^[§§]\d+"),                             # §1
]

_MIN_CHUNK_CHARS = 15  # 低于此且不匹配短模式 → 视为低质量


def is_chunk_valid(chunk_text: str) -> bool:
    """逐 chunk 质量校验 — 阻止垃圾 chunks 入库。

    这是自查自纠的第二道防线（第一道是全文级的 is_text_garbled）。
    在 chunk 生成后、入库前调用，拒绝以下类型：
    - PDF 二进制残留
    - CMap glyph 引用
    - 单字符/空内容
    - 极短文本但非章节标题

    Returns:
        True 如果 chunk 质量合格可以入库
    """
    if not chunk_text or len(chunk_text.strip()) < 2:
        return False

    # ── 快速 PDF 标记扫描 ──
    pdf_hits = sum(1 for m in _PDF_BINARY_MARKERS if m in chunk_text)
    if pdf_hits >= 1:  # 单个 chunk 中出现任何 PDF 标记都不正常
        return False

    # ── CMap glyph 检测 ──
    if _CMAP_GLYPH_RE.search(chunk_text):
        return False

    # ── 非 ASCII 非 CJK 字节检测 ──
    # 检测 Latin-1/Central European 解码残留（PDF 二进制垃圾的典型特征）
    text = chunk_text.strip()
    non_ascii_non_cjk = 0
    cjk_chars = 0
    ascii_alpha = 0
    for ch in text:
        cp = ord(ch)
        if cp > 127:
            if ('一' <= ch <= '鿿' or '　' <= ch <= '〿'
                    or '＀' <= ch <= '￯' or ch in '·—…'):
                cjk_chars += 1
            else:
                non_ascii_non_cjk += 1
        elif 'a' <= ch.lower() <= 'z':
            ascii_alpha += 1

    # 3+ 非可打印高位字节 且 几乎没有 CJK 内容 → 垃圾
    if non_ascii_non_cjk >= 3 and cjk_chars < 10:
        return False

    # ── 极短 chunk 检查 ──
    text = chunk_text.strip()
    if len(text) < _MIN_CHUNK_CHARS:
        # 短 chunk 必须是合法的章节/条款标题，或包含足够的中文内容
        is_header = any(p.match(text) for p in _VALID_SHORT_PATTERNS)
        if not is_header:
            # 允许：短但包含 50%+ 中文字符
            cjk_count = sum(1 for ch in text if '一' <= ch <= '鿿')
            if cjk_count < max(3, len(text) * 0.5):
                return False

    # ── 可读比例检查（放宽版，专用于 chunk 级别）──
    sample = text[:1000]
    readable = 0
    total = 0
    for ch in sample:
        cp = ord(ch)
        if cp <= 32:
            continue  # 跳过空白
        total += 1
        if ('一' <= ch <= '鿿' or 'a' <= ch.lower() <= 'z'
                or '0' <= ch <= '9'
                or ch in '.,;:!?()[]{}<>/\\-+=@#$%^&*_|~`\'"·—…　〿＀￯'):
            readable += 1

    if total > 10:
        ratio = readable / total
        if ratio < 0.30:  # chunk 级别用更严格的比例
            return False

    return True


def validate_chunks(chunks: list, logger_instance=None) -> tuple[list, int]:
    """过滤无效 chunks，返回 (有效chunks, 被拒绝数)。

    用于在 chunk 生成后、入库前做最后一道把关。
    调用方应记录被拒绝的数量并告警。

    Args:
        chunks: ChunkSpec 列表
        logger_instance: 可选的 logger

    Returns:
        (valid_chunks, rejected_count)
    """
    valid: list = []
    rejected = 0
    for c in chunks:
        if is_chunk_valid(c.text):
            valid.append(c)
        else:
            rejected += 1
            if logger_instance:
                logger_instance.warning(
                    "Chunk rejected by quality guard: index=%d preview=%s",
                    c.index, c.text[:60].replace("\n", " "),
                )
    return valid, rejected


# ═══════════════════════════════════════════════════════════════
# 文档解析器
# ═══════════════════════════════════════════════════════════════


class SafetyDocumentParser:
    """安全模块自主文档解析器。

    不依赖平台层 DocumentParser（pypdf 对 CMap 中文 PDF 支持差），
    直接使用 PyMuPDF (fitz) + pdfplumber 双引擎解析。

    用法:
        text = SafetyDocumentParser.extract_text("/path/to/doc.pdf")
        if is_text_garbled(text):
            raise RuntimeError("解析结果疑似二进制垃圾")
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}

    @staticmethod
    def extract_text(file_path: str, max_chars: int = 100000) -> str:
        """从文件中提取纯文本。

        Args:
            file_path: 文件路径
            max_chars: 最大字符数（超出截断）

        Returns:
            提取的纯文本

        Raises:
            RuntimeError: 所有解析引擎均失败
        """
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf":
            text = SafetyDocumentParser._extract_pdf(file_path, max_chars)
        elif ext == ".docx":
            text = SafetyDocumentParser._extract_docx(file_path)
        elif ext == ".doc":
            text = SafetyDocumentParser._extract_doc_ole(file_path)
        elif ext in (".xlsx", ".xls"):
            text = SafetyDocumentParser._extract_xlsx(file_path)
        elif ext in (".txt", ".md"):
            text = SafetyDocumentParser._extract_txt(file_path)
        else:
            raise RuntimeError(f"不支持的文件格式: {ext}")

        # 截断
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n...（文档过长，已截断）"

        result = text.strip()
        if not result:
            raise RuntimeError(f"解析结果为空: {os.path.basename(file_path)}")

        return result

    # ── PDF 解析 ──

    @staticmethod
    def _extract_pdf(file_path: str, max_chars: int = 100000) -> str:
        """PDF 解析：PyMuPDF → pdfplumber → MarkItDown。

        逐引擎尝试，首个产生有效文本的引擎胜出。
        """
        fname = os.path.basename(file_path)

        # ── 引擎 1: PyMuPDF (fitz) — 对中文 CMap 字体支持最好 ──
        text = SafetyDocumentParser._pdf_via_pymupdf(file_path, max_chars)
        if text and not is_text_garbled(text):
            logger.info("PDF 解析成功 [PyMuPDF]: %s → %d chars", fname, len(text))
            return text
        if text:
            logger.warning(
                "PyMuPDF 解析结果疑似垃圾 (%d chars)，回退 pdfplumber: %s",
                len(text), fname,
            )

        # ── 引擎 2: pdfplumber — 对表格和结构化 PDF 友好 ──
        text = SafetyDocumentParser._pdf_via_pdfplumber(file_path, max_chars)
        if text and not is_text_garbled(text):
            logger.info("PDF 解析成功 [pdfplumber]: %s → %d chars", fname, len(text))
            return text
        if text:
            logger.warning(
                "pdfplumber 解析结果疑似垃圾 (%d chars)，回退 MarkItDown: %s",
                len(text), fname,
            )

        # ── 引擎 3: MarkItDown — 最后一次尝试 ──
        text = SafetyDocumentParser._pdf_via_markitdown(file_path, max_chars)
        if text and not is_text_garbled(text):
            logger.info("PDF 解析成功 [MarkItDown]: %s → %d chars", fname, len(text))
            return text

        raise RuntimeError(
            f"所有 PDF 解析引擎均失败: {fname} "
            f"(PyMuPDF/pdfplumber/MarkItDown 均无法提取有效文本)"
        )

    @staticmethod
    def _pdf_via_pymupdf(file_path: str, max_chars: int) -> str:
        """PyMuPDF (fitz) 解析 PDF。"""
        try:
            import fitz
        except ImportError:
            logger.debug("PyMuPDF (fitz) 未安装")
            return ""

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            logger.debug("PyMuPDF 无法打开: %s — %s", os.path.basename(file_path), e)
            return ""

        parts: list[str] = []
        try:
            for page in doc:
                # 优先 sort=True 保留阅读顺序
                t = page.get_text("text", sort=True)
                if t and t.strip():
                    parts.append(t.strip())
                    if sum(len(p) for p in parts) >= max_chars:
                        break
        finally:
            doc.close()

        return "\n\n".join(parts)

    @staticmethod
    def _pdf_via_pdfplumber(file_path: str, max_chars: int) -> str:
        """pdfplumber 解析 PDF。"""
        try:
            import pdfplumber
        except ImportError:
            logger.debug("pdfplumber 未安装")
            return ""

        parts: list[str] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t and t.strip():
                        parts.append(t.strip())
                        if sum(len(p) for p in parts) >= max_chars:
                            break
        except Exception as e:
            logger.debug("pdfplumber 解析失败: %s — %s", os.path.basename(file_path), e)
            return ""

        return "\n\n".join(parts)

    @staticmethod
    def _pdf_via_markitdown(file_path: str, max_chars: int) -> str:
        """MarkItDown 解析 PDF。"""
        try:
            from markitdown import MarkItDown
        except ImportError:
            logger.debug("MarkItDown 未安装")
            return ""

        try:
            md = MarkItDown(enable_plugins=False)
            result = md.convert(file_path)
            text = result.text_content
        except Exception as e:
            logger.debug("MarkItDown 转换失败: %s — %s", os.path.basename(file_path), e)
            return ""

        return text or ""

    # ── DOCX 解析 ──

    @staticmethod
    def _extract_docx(file_path: str) -> str:
        """python-docx 解析 DOCX（段落 + 表格）。"""
        try:
            from docx import Document
        except ImportError:
            raise RuntimeError("python-docx 未安装")

        doc = Document(file_path)
        parts: list[str] = []

        # 按文档顺序遍历 body，段落与表格交错保留阅读顺序
        try:
            body = doc.element.body
        except Exception:
            body = None

        if body is not None:
            from docx.table import Table as _DocxTable
            from docx.text.paragraph import Paragraph as _DocxParagraph

            for child in body.iterchildren():
                if child.tag.endswith("}p"):
                    p = _DocxParagraph(child, doc)
                    t = p.text.strip()
                    if t:
                        parts.append(t)
                elif child.tag.endswith("}tbl"):
                    tbl = _DocxTable(child, doc)
                    parts.append(SafetyDocumentParser._extract_docx_table(tbl))
        else:
            # 回退：仅段落 + 表格（无法保序）
            for p in doc.paragraphs:
                if p.text and p.text.strip():
                    parts.append(p.text.strip())
            for tbl in doc.tables:
                parts.append(SafetyDocumentParser._extract_docx_table(tbl))

        return "\n".join(p for p in parts if p)

    @staticmethod
    def _extract_docx_table(table) -> str:
        """将 docx 表格提取为文本行（合并单元格去重，保持行列结构）。"""
        if table is None:
            return ""
        rows: list[str] = []
        for row in table.rows:
            seen: set[str] = set()
            cells: list[str] = []
            for cell in row.cells:
                text = cell.text.strip().replace("\n", " ")
                if text and text not in seen:
                    seen.add(text)
                    cells.append(text)
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    # ── 旧版 .doc 解析 ──

    @staticmethod
    def _extract_doc_ole(file_path: str) -> str:
        """olefile 解析旧版 .doc（OLE2 格式）。"""
        try:
            import olefile
        except ImportError:
            raise RuntimeError("olefile 未安装")

        ole = olefile.OleFileIO(file_path)
        if not ole.exists("WordDocument"):
            ole.close()
            raise RuntimeError("不是有效的 .doc 文件")

        stream = ole.openstream("WordDocument")
        data = stream.read()
        ole.close()

        if len(data) < 12:
            raise RuntimeError(".doc 文件过短")

        flags = int.from_bytes(data[10:12], "little")
        is_unicode = bool(flags & 0x0100)

        text_data = data[0x0100:]
        encoding = "utf-16-le" if is_unicode else "cp1252"
        raw = text_data.decode(encoding, errors="replace")

        # 只保留可打印字符
        cleaned: list[str] = []
        for ch in raw:
            cp = ord(ch)
            if cp in (0x0A, 0x0D, 0x09):
                cleaned.append(ch)
            elif cp < 0x20:
                cleaned.append(" ")
            elif cp == 0xFFFD:
                continue
            else:
                cleaned.append(ch)
        return "".join(cleaned)

    # ── XLSX 解析 ──

    @staticmethod
    def _extract_xlsx(file_path: str) -> str:
        """openpyxl 解析 Excel。"""
        try:
            import openpyxl
        except ImportError:
            raise RuntimeError("openpyxl 未安装")

        wb = openpyxl.load_workbook(file_path, data_only=True)
        parts: list[str] = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"## {sheet_name}")
            for row in ws.iter_rows(values_only=True):
                row_str = "\t".join(
                    str(cell) if cell is not None else "" for cell in row
                )
                if row_str.strip():
                    parts.append(row_str)
        wb.close()
        return "\n".join(parts)

    # ── TXT 解析 ──

    @staticmethod
    def _extract_txt(file_path: str) -> str:
        """直接读取文本文件。"""
        # 尝试多种编码
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                with open(file_path, encoding=enc) as f:
                    text = f.read()
                if text.strip():
                    return text
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise RuntimeError(f"无法识别文本编码: {os.path.basename(file_path)}")

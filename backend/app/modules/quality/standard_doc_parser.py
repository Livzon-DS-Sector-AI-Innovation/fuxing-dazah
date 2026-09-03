"""质量标准文档解析器：.doc/.docx → 文档头 + 标准项目行。

结构依据真实样例（SOP.02.3292.003 盐酸万古霉素内控质量标准）：
- 文件头：文件编号 / 产品名称 / 产品代码 / 产品代号 / 规格 / 有效期 / 生效日期 / 版本
- 质量标准表：序号 → 检验项目(大类) → 子项目行
  每行：[子项目名] [合格标准文本(可跨行)] [SOP号] [方法来源]

过滤规则：合格标准为纯文字（无数字）的子项目不收录（不参与判定）。
数值标准结构化：≤3.0% → operator=≤, limit_max=3.0；≥91.0% → operator=≥,
limit_min=91.0；2.5～4.5 → limit_min=2.5, limit_max=4.5。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SOP_RE = re.compile(r"SOP\.\d{2}\.\d{3,4}(?:\.\d{3})?", re.IGNORECASE)
NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


@dataclass
class ParsedStandardItem:
    seq: int | None = None
    category: str | None = None
    item_name: str = ""
    sop_no: str = ""
    standard_text: str = ""
    operator: str | None = None
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = None
    remark: str | None = None


@dataclass
class ParsedStandardDoc:
    file_no: str = ""
    product_name: str = ""
    product_code: str | None = None
    product_internal_code: str | None = None
    specification: str | None = None
    valid_years: str | None = None
    effective_date: str | None = None
    version: str | None = None
    items: list[ParsedStandardItem] = field(default_factory=list)


def extract_text(file_bytes: bytes, filename: str) -> str:
    """提取文档文本：.docx 用 python-docx；.doc 用系统转换工具链。"""
    if filename.lower().endswith(".docx"):
        from io import BytesIO

        from docx import Document

        doc = Document(BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    # .doc 旧格式：textutil(macOS) → antiword → catdoc → 纯文本尝试
    import asyncio
    import os
    import shutil
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        text = ""
        if shutil.which("textutil"):
            out_path = tmp_path + ".txt"
            proc = asyncio.create_subprocess_exec(
                "textutil", "-convert", "txt", tmp_path, "-output", out_path,
                stdout=asyncio.PIPE, stderr=asyncio.PIPE,
            )
            asyncio.get_event_loop().run_until_complete(proc.communicate())
            if proc.returncode == 0 and os.path.exists(out_path):
                with open(out_path) as f:
                    text = f.read()
            if os.path.exists(out_path):
                os.unlink(out_path)
        if not text and shutil.which("antiword"):
            proc = asyncio.create_subprocess_exec(
                "antiword", tmp_path, stdout=asyncio.PIPE, stderr=asyncio.PIPE,
            )
            stdout, _ = asyncio.get_event_loop().run_until_complete(proc.communicate())
            if proc.returncode == 0:
                text = stdout.decode("utf-8", errors="ignore")
        if not text and shutil.which("catdoc"):
            proc = asyncio.create_subprocess_exec(
                "catdoc", tmp_path, stdout=asyncio.PIPE, stderr=asyncio.PIPE,
            )
            stdout, _ = asyncio.get_event_loop().run_until_complete(proc.communicate())
            if proc.returncode == 0:
                text = stdout.decode("utf-8", errors="ignore")
        return text
    finally:
        os.unlink(tmp_path)


async def extract_text_async(file_bytes: bytes, filename: str) -> str:
    import asyncio

    return await asyncio.to_thread(extract_text, file_bytes, filename)


def _parse_header(text: str, doc: ParsedStandardDoc) -> None:
    """解析文件头字段（正则提取，宽松匹配）。"""
    patterns = [
        (r"(SOP\.\d{2}\.\d{3,4}\.\d{3})", "file_no"),
        (r"产品代码[:：]\s*(\S+)", "product_internal_code"),
        (r"产品代号[:：]\s*(\S+)", "product_code"),
        (r"产品规格[:：]\s*(.+)", "specification"),
        (r"有\s*效\s*期[:：]\s*(.+)", "valid_years"),
        (r"生\s*效\s*日\s*期[:：]?\s*(\d{4}\s*年\s*\d{2}\s*月\s*\d{2}\s*日)", "effective_date"),
        (r"版本号\s*\n\s*日\s*期\s*\n\s*变更说明\s*\n\s*(\S+)", "version"),
        (r"通用名[:：]\s*(.+)", "product_name"),
    ]
    for pattern, attr in patterns:
        m = re.search(pattern, text)
        if m and not getattr(doc, attr):
            val = re.sub(r"\s+", "", m.group(1)).strip() if attr == "effective_date" else m.group(1).strip()
            setattr(doc, attr, val)
    # 文件编号兜底：文本中首个 SOP.\d{2}.\d+（可能被拆行）
    if not doc.file_no:
        m = re.search(r"SOP\.\d{2}\.\d{3,4}\.\d{3}", text)
        if m:
            doc.file_no = m.group(0)


def _structure_numeric(standard_text: str) -> tuple[str | None, float | None, float | None]:
    """数值标准结构化：≤3.0% / ≥91.0% / 2.5～4.5 / ＜0.25EU/mg → (op, min, max)。"""
    nums = NUM_RE.findall(standard_text)
    if not nums:
        return None, None, None
    values = [float(n) for n in nums]
    if "～" in standard_text or "~" in standard_text or "-" in standard_text:
        # 范围（负数标准罕见，按 ～ 优先）
        if len(values) >= 2:
            return "范围", min(values[:2]), max(values[:2])
        return None, None, None
    if "≥" in standard_text or "＞" in standard_text:
        return "≥", values[0], None
    if "＜" in standard_text or "<" in standard_text:
        return "<", None, values[0]
    if "＞" in standard_text or ">" in standard_text:
        return ">", values[0], None
    # 默认 ≤
    return "≤", None, values[0]


def parse_standard_doc(text: str) -> ParsedStandardDoc:
    """解析质量标准全文 → 文档头 + 项目行（纯文字标准行过滤）。"""
    doc = ParsedStandardDoc()
    _parse_header(text, doc)

    lines = [ln.strip() for ln in text.split("\n")]
    i = 0
    current_seq: int | None = None
    current_category: str | None = None
    while i < len(lines):
        ln = lines[i]
        if not ln:
            i += 1
            continue
        # 序号：独立数字行
        if ln.isdigit() and 1 <= int(ln) <= 60:
            current_seq = int(ln)
            i += 1
            continue
        # SOP 号行：上一行是标准文本，SOP 号属于它
        if SOP_RE.match(ln) and len(ln) < 40:
            i += 1
            continue
        # 项目大类判定：紧跟序号后的非标准行（无数字、非 SOP、非来源）
        if current_seq is not None and not NUM_RE.search(ln) and not SOP_RE.search(ln):
            current_category = ln
            # 处理被拆行的大类名（如「鉴」「别」两行）
            if i + 1 < len(lines) and lines[i + 1] and len(lines[i + 1]) <= 4 and not NUM_RE.search(lines[i + 1]) and not SOP_RE.search(lines[i + 1]):
                current_category = ln + lines[i + 1]
                i += 1
            i += 1
            continue
        # 子项目行：标准文本含数字 → 尝试组装 [子项名][标准][SOP][来源]
        i += 1

    # 简化解析策略：文本已展开为一行一单元格，按连续块组装项目行
    return _parse_table_blocks(doc, lines)


def _parse_table_blocks(doc: ParsedStandardDoc, lines: list[str]) -> ParsedStandardDoc:
    """围绕 SOP 号行组装项目行：SOP 前一行(多行)为标准文本、更前为子项名，
    SOP 后一行短文本为方法来源。序号/大类尽量从上下文推断。"""
    n = len(lines)
    # 序号行索引（独立数字行 1-60）
    seq_of: dict[int, int] = {}
    last_seq = None
    for j, ln in enumerate(lines):
        if ln.isdigit() and 1 <= int(ln) <= 60:
            last_seq = int(ln)
        seq_of[j] = last_seq

    for j, ln in enumerate(lines):
        m = SOP_RE.search(ln)
        if not m:
            continue
        sop = m.group(0)
        # 向前找标准文本（含数字或运算符的行，可跨行合并最多 3 行）
        std_lines = []
        k = j - 1
        while k >= 0 and len(std_lines) < 3:
            prev = lines[k]
            if not prev:
                k -= 1
                continue
            if (NUM_RE.search(prev) or any(op in prev for op in ("≤", "≥", "＜", "＞", "～", "<", ">", "~", "-"))) and not SOP_RE.search(prev):
                std_lines.insert(0, prev)
                k -= 1
            else:
                break
        standard_text = " ".join(std_lines).strip()
        if not standard_text:
            continue
        op, mn, mx = _structure_numeric(standard_text)
        if op is None:
            continue
        # 子项名 = 标准文本更前面最近的非空短行（非数字序号）
        item_name = ""
        kk = k
        while kk >= 0:
            cand = lines[kk]
            if cand and not cand.isdigit() and not SOP_RE.search(cand) and len(cand) < 40 and not NUM_RE.search(cand):
                item_name = cand
                break
            kk -= 1
        # 方法来源 = SOP 后一行短文本
        source = None
        nxt = lines[j + 1].strip() if j + 1 < n else ""
        if nxt and not SOP_RE.search(nxt) and len(nxt) < 30 and not NUM_RE.search(nxt):
            source = nxt
        item = ParsedStandardItem(
            seq=seq_of.get(j),
            category=None,
            item_name=item_name or standard_text[:20],
            sop_no=sop,
            standard_text=standard_text,
            operator=op,
            limit_min=mn,
            limit_max=mx,
            method_source=source,
        )
        if item_name.endswith("*"):
            item.remark = "加*项目，每年仅检测1个批次"
            item.item_name = item_name.rstrip("*")
        doc.items.append(item)
        if len(doc.items) > 200:
            break
    return doc

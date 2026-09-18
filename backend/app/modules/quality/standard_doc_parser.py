"""质量标准文档解析器：.doc/.docx → 文档头 + 标准项目行。

结构依据真实样本（盐酸万古霉素内控质量标准 USP/Ph.Eur. 双语表格）：
- 文件头：文件编号 / 产品名称(通用名) / 产品代码 / 产品代号 / 规格 / 有效期 / 生效日期 / 版本
- 质量标准表（表格逐格提取为行，中英双语交替）：
  序号 → 检验项目(大类，中/英) → 子项目(中/英) → 合格标准(中/英，可多行) → SOP号 → 方法来源
- 双语特点：中文与英文可能同行（"鉴别Identification"）或分两行；英文标准可能折行；
  杂质块（有关物质）无 SOP 号锚，按数值标准行补收。

过滤规则：纯文字标准（无数字）保留——operator/limit 为空，由人工判定。
数值标准结构化：≤3.0% → operator=≤, limit_max=3.0；≥91.0% → operator=≥,
limit_min=91.0；2.5～4.5 → limit_min=2.5, limit_max=4.5。

解析结果仅供「导入确认弹窗」草稿使用，人工校正后落库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SOP_RE = re.compile(r"SOP\.\d{2}\.\d{3,4}(?:\.\d{3})?", re.IGNORECASE)
NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
_OPERATORS = ("≤", "≥", "＜", "＞", "～", "<", ">", "~")


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

    # .doc 旧格式：textutil(macOS) → antiword → catdoc（同步 subprocess，线程安全）
    import os
    import shutil
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        text = ""
        if shutil.which("textutil"):
            out_path = tmp_path + ".txt"
            r = subprocess.run(
                ["textutil", "-convert", "txt", tmp_path, "-output", out_path],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and os.path.exists(out_path):
                with open(out_path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            if os.path.exists(out_path):
                os.unlink(out_path)
        if not text and shutil.which("antiword"):
            r = subprocess.run(["antiword", tmp_path], capture_output=True, timeout=60)
            if r.returncode == 0:
                text = r.stdout.decode("utf-8", errors="ignore")
        if not text and shutil.which("catdoc"):
            r = subprocess.run(["catdoc", tmp_path], capture_output=True, timeout=60)
            if r.returncode == 0:
                text = r.stdout.decode("utf-8", errors="ignore")
        return text
    finally:
        os.unlink(tmp_path)


async def extract_text_async(file_bytes: bytes, filename: str) -> str:
    import asyncio

    return await asyncio.to_thread(extract_text, file_bytes, filename)


def _parse_header(text: str, doc: ParsedStandardDoc) -> None:
    """解析文件头字段（正则提取，宽松匹配）。

    兼容两种排版：「标签：值」同行，与「标签\\n值」换行（表格逐行提取时常见）。
    """
    patterns = [
        (r"产品名称[:：][ \t]*(.+)", "product_name"),
        (r"产品名称[:：]?[ \t]*\n[ \t]*([^\n]+)", "product_name"),
        (r"通用名[:：][ \t]*(.+)", "product_name"),
        (r"产品代码[:：][ \t]*(\S+)", "product_internal_code"),
        (r"产品代码[:：]?[ \t]*\n[ \t]*([^\n]+)", "product_internal_code"),
        (r"产品代号[:：][ \t]*(\S+)", "product_code"),
        (r"产品代号[:：]?[ \t]*\n[ \t]*([^\n]+)", "product_code"),
        (r"产品规格[:：][ \t]*(.+)", "specification"),
        (r"产品规格[:：]?[ \t]*\n[ \t]*([^\n]+)", "specification"),
        (r"有\s*效\s*期[:：][ \t]*(.+)", "valid_years"),
        (r"有\s*效\s*期[:：]?[ \t]*\n[ \t]*([^\n]+)", "valid_years"),
        (r"生\s*效\s*日\s*期[:：]?[ \t]*(\d{4}\s*年\s*\d{2}\s*月\s*\d{2}\s*日)", "effective_date"),
        (r"生\s*效\s*日\s*期[:：]?[ \t]*\n[ \t]*(\d{4}\s*年\s*\d{2}\s*月\s*\d{2}\s*日)", "effective_date"),
        # 文件编号：优先「文件编号」标签换行排版（文档尾页），避免误抓取样操作规程编号
        (r"文\s*件\s*编\s*号[:：]?[ \t]*\n[ \t]*(SOP\.\d{2}\.\d{3,4}\.\d{3})", "file_no"),
    ]
    # 换行排版下「产品名称」的下一行可能仍是表头标签（标签列排成一列时），过滤明显误抓
    _label_guard = re.compile(
        r"^(文件编号|产品代码|产品代号|产品规格|规格|有效期|生效日期|版本|通用名|变更说明|SOP\.\d{2})"
    )
    for pattern, attr in patterns:
        m = re.search(pattern, text)
        if m and not getattr(doc, attr):
            val = m.group(1).strip()
            if attr in ("effective_date", "product_name"):
                val = re.sub(r"\s+", "", val)
            if attr == "product_name" and _label_guard.match(val):
                continue
            setattr(doc, attr, val)
    # 文件编号兜底：优先 SOP.02 段号（标准文件编号段），避免误抓取样规程/方法 SOP 号
    if not doc.file_no:
        for m in re.finditer(r"SOP\.\d{2}\.\d{3,4}\.\d{3}", text):
            if m.group(0).startswith("SOP.02"):
                doc.file_no = m.group(0)
                break
        if not doc.file_no:
            m = re.search(r"SOP\.\d{2}\.\d{3,4}\.\d{3}", text)
            if m:
                doc.file_no = m.group(0)
    # 版本号：文件历史表按版本倒序排列，取最后一次匹配（当前版本）
    _ver_hist = re.compile(r"版本号\s*\n\s*日\s*期\s*\n\s*变更说明\s*\n\s*(\S+)")
    m_all = list(_ver_hist.finditer(text))
    if m_all:
        doc.version = m_all[-1].group(1)
    # 版本兜底：历史表多版本时（001…007），取最后一个独立三位数行（当前版本）
    bare3 = [ln.strip() for ln in text.split("\n") if re.fullmatch(r"\d{3}", ln.strip())]
    if len(bare3) > 1:
        doc.version = bare3[-1]


def _structure_numeric(standard_text: str) -> tuple[str | None, float | None, float | None]:
    """数值标准结构化：≤3.0% / ≥91.0% / 2.5～4.5 / ＜0.25IU/mg → (op, min, max)。

    必须含运算符才结构化——文字标准中的附带数字（如「乙醇（96%）」）不当作限度。
    """
    if not any(op in standard_text for op in _OPERATORS):
        return None, None, None
    nums = NUM_RE.findall(standard_text)
    if not nums:
        return None, None, None
    values = [float(n) for n in nums]
    if "～" in standard_text or "~" in standard_text or "-" in standard_text:
        # 范围（负数标准罕见，按 ～ 优先）
        if len(values) >= 2:
            return "范围", min(values[:2]), max(values[:2])
        return None, None, None
    if "≥" in standard_text:
        return "≥", values[0], None
    if "＜" in standard_text or "<" in standard_text:
        return "<", None, values[0]
    if "＞" in standard_text or ">" in standard_text:
        return ">", values[0], None
    # 默认 ≤
    return "≤", None, values[0]


def parse_standard_doc(text: str) -> ParsedStandardDoc:
    """解析质量标准全文 → 文档头 + 项目行（文字标准保留，人工判定）。"""
    doc = ParsedStandardDoc()
    _parse_header(text, doc)

    lines = [ln.strip() for ln in text.split("\n")]
    _parse_table_blocks(doc, lines)
    return doc


def _has_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def _is_seq_line(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 60


def _has_op(s: str) -> bool:
    return any(op in s for op in _OPERATORS)


# 方法来源的常见写法（反向扫描大类时防止把上一项目的来源误当大类）
_SOURCE_JUNK = {"内部", "In-house", "质量标准", "质量标准："}
# 来源行前缀：如 USP<197>、Ph.Eur.(2.9.19)、内部、In-house——来源行即使含运算符
# （USP<197> 的「<」）也不得当作数值标准参与解析
_SOURCE_LIKE_RE = re.compile(r"^(USP|Ph\.Eur|EP|CP|IP|BP|JP|ChP|In-house|内部)(?=[\s<(<（]|$)")
# 质量标准表的表头词（孤儿项目检测时排除）
_TABLE_HEADER_JUNK = {"序号", "检验项目", "合格标准", "检验方法", "方法来源", "日期", "版本号", "变更说明"}


def _parse_table_blocks(doc: ParsedStandardDoc, lines: list[str]) -> None:
    """真实双语表格两遍组装：

    Pass A：以 SOP 号行为锚——反向收集合格标准（数值标准可多行；文字标准=中文一行+英文尾行）
    → 子项目（跳过纯英文行取最近中文行）→ 大类；正向收集方法来源。
    Pass B：无 SOP 锚的数值标准行（有关物质杂质块、共用 SOP 的追加条件行）按相同反向规则补收。

    段落边界：自「质量标准：」起，至「备注」或公司落款止。
    """
    n = len(lines)
    start = 0
    for i, ln in enumerate(lines):
        if ln in ("质量标准：", "质量标准"):
            start = i
            break
    end = n
    for i in range(start, n):
        if lines[i].startswith("备注") or "丽珠集团" in lines[i]:
            end = i
            break

    seq_of: dict[int, int | None] = {}
    last_seq = None
    for j in range(start, end):
        if _is_seq_line(lines[j]):
            last_seq = int(lines[j])
        seq_of[j] = last_seq

    anchors: list[tuple[int, ParsedStandardItem]] = []  # (锚行索引, 项目)
    std_consumed: set[int] = set()

    def _emit(anchor: int, seq: int | None, item_name: str,
              std_text: str, sop: str, source: str | None) -> None:
        it = ParsedStandardItem(
            seq=seq, category=None, item_name=item_name, sop_no=sop,
            standard_text=std_text, method_source=source,
        )
        op, mn, mx = _structure_numeric(std_text)
        it.operator, it.limit_min, it.limit_max = op, mn, mx
        if it.item_name.endswith("*"):
            it.remark = "加*项目，每年仅检测1个批次"
            it.item_name = it.item_name.rstrip("*")
        anchors.append((anchor, it))

    def _backward_item(start_k: int) -> tuple[str, int]:
        """从 k 反向找子项目：优先取最近中文行；若无中文（如纯 ASCII 的「pH」），
        取最近的短 ASCII 字母行作候补。英文翻译行在中文名之下，中文名优先命中。

        相邻的短中文行合并（≤4 字）——单元格换行把「万古霉」「素组分」拆成两行时
        还原为「万古霉素组分」；「性状」「外观」间有英文行分隔，不会被误合并。
        """
        k = start_k
        ascii_candidate: str | None = None
        ascii_idx: int = start_k
        while k >= start:
            if k in std_consumed:
                k -= 1
                continue
            s = lines[k]
            if not s or SOP_RE.search(s) or _is_seq_line(s):
                break
            if _has_op(s):
                break
            if _has_cjk(s):
                name = s
                k -= 1
                while (len(name) <= 8 and k >= start and lines[k]
                       and k not in std_consumed
                       and _has_cjk(lines[k]) and not _has_op(lines[k])
                       and not SOP_RE.search(lines[k]) and not _is_seq_line(lines[k])
                       and len(lines[k]) <= 4):
                    name = lines[k] + name
                    k -= 1
                return name, k
            if ascii_candidate is None and len(s) <= 6 and re.search(r"[A-Za-z]", s):
                ascii_candidate = s
                ascii_idx = k
            k -= 1
        if ascii_candidate:
            return ascii_candidate, ascii_idx - 1
        return "", start_k

    # ── Pass C（先行）：孤儿项目——单元格换行拆成多行的短中文名，且其标准无文本可提取
    #（如「万古霉素组分」→「万古霉」「素组分」+ Composition/Of vancomycin）。
    # 特点：≥2 行相邻短中文行后紧跟纯英文翻译行。单行中文+英文的「性状/Characters」
    # 是类别而非孤儿，不在此模式内。
    j = start
    while j < end:
        if j in std_consumed or not lines[j] or not _has_cjk(lines[j]):
            j += 1
            continue
        if (_has_op(lines[j]) or SOP_RE.search(lines[j]) or _is_seq_line(lines[j])
                or len(lines[j]) > 6 or "：" in lines[j] or lines[j] in _TABLE_HEADER_JUNK):
            j += 1
            continue
        run_start = j
        run_lines: list[str] = []
        while j < end and lines[j] and _has_cjk(lines[j]) and not _has_op(lines[j]) \
                and not SOP_RE.search(lines[j]) and not _is_seq_line(lines[j]) and len(lines[j]) <= 6:
            run_lines.append(lines[j])
            j += 1
        if len(run_lines) < 2:
            continue
        # 运行结束后必须是纯英文翻译行（否则是正常项目名的多行碎片，交由其他遍处理）
        k2 = j
        while k2 < end and lines[k2] and not _has_cjk(lines[k2]) and not SOP_RE.search(lines[k2]):
            k2 += 1
        if k2 == j:
            continue
        merged = "".join(run_lines)
        for x in range(run_start, k2):
            std_consumed.add(x)
        anchors.append((run_start, ParsedStandardItem(
            seq=seq_of.get(run_start), category=None, item_name=merged,
            sop_no="", standard_text="", method_source=None,
        )))

    # ── Pass A：SOP 锚 ──
    for j in range(start, end):
        ln = lines[j]
        m = SOP_RE.search(ln)
        if not m:
            continue
        sop = m.group(0)
        # 反向：英文尾行（文字标准的英文部分，可折行）
        k = j - 1
        eng: list[str] = []
        while k >= start:
            s = lines[k]
            if not s or _has_cjk(s) or _has_op(s) or SOP_RE.search(s) or _is_seq_line(s):
                break
            eng.insert(0, s)
            k -= 1
        # 数值标准块（运算符行，可多行）
        std_lines: list[str] = []
        while k >= start and lines[k] and _has_op(lines[k]) and not SOP_RE.search(lines[k]):
            std_lines.insert(0, lines[k])
            k -= 1
        if std_lines:
            std_text = " ".join(std_lines)
        elif eng or (k >= start and lines[k] and _has_cjk(lines[k])):
            cn = lines[k] if k >= start and lines[k] else ""
            std_text = " ".join(([cn] if cn else []) + eng)
            k -= 1
        else:
            continue
        item_name, k2 = _backward_item(k)
        if not item_name:
            continue
        # 方法来源：SOP 后短行（纯英文/编号，或「内部」类中文来源词；
        # USP<197> 这类含运算符的来源行按来源前缀识别，不当标准）
        src_parts: list[str] = []
        k3 = j + 1
        while k3 < end and len(src_parts) < 3:
            s = lines[k3]
            if not s or SOP_RE.search(s) or _is_seq_line(s):
                break
            if _SOURCE_LIKE_RE.match(s):
                src_parts.append(s)
                k3 += 1
                continue
            if _has_cjk(s) or _has_op(s):
                break
            src_parts.append(s)
            k3 += 1
        source = " ".join(src_parts).strip() or None
        # 标记已消耗行：自子项目起至来源扫描止（不含断点 k3 本身——断点若是运算符行，应留给 Pass B）
        for idx in range(max(start, k2 + 1), min(end, k3)):
            std_consumed.add(idx)
        std_consumed.add(j)
        _emit(j, seq_of.get(j), item_name, std_text, sop, source)

    # ── Pass B：无 SOP 锚的数值标准行（杂质块 / 共用 SOP 的追加条件）──
    j = start
    while j < end:
        if (not lines[j] or not _has_op(lines[j]) or j in std_consumed
                or _SOURCE_LIKE_RE.match(lines[j])):
            j += 1
            continue
        group_start = j
        std_lines = [lines[j]]
        j += 1
        while j < end:
            if j in std_consumed:
                # 已被 Pass A 消耗（如 pH 这类纯 ASCII 项目名），本组到此为止
                break
            s = lines[j]
            if _SOURCE_LIKE_RE.match(s):
                # 上一项目的来源行（如 USP<197>），不属于本组标准
                break
            if s and _has_op(s) and not SOP_RE.search(s):
                std_lines.append(s)
                j += 1
            elif s and not _has_cjk(s) and not SOP_RE.search(s):
                j += 1
            else:
                break
        group_end = j  # 不含
        std_text = " ".join(std_lines)
        item_name, k2 = _backward_item(group_start - 1)
        # 兜底：取文档顺序上前一个已组装项目的信息（如共用 SOP 的追加条件行）
        prev = None
        for a_idx, it in anchors:
            if a_idx < group_start:
                prev = it
            else:
                break
        if prev and not item_name:
            item_name = prev.item_name
        if not item_name:
            item_name = std_text[:20]
        # 无 SOP 的行继承同一序号段内最近项目的 SOP（有关物质块共用方法 SOP，
        # Word 合并单元格在文本提取中不重复出现）
        seq = seq_of.get(group_start)
        item_sop = ""
        if prev and prev.sop_no and prev.seq == seq:
            item_sop = prev.sop_no
        for x in range(group_start, group_end):
            std_consumed.add(x)
        _emit(group_end - 1, seq, item_name, std_text, item_sop, None)

    anchors.sort(key=lambda x: x[0])
    doc.items = [it for _, it in anchors]
    if len(doc.items) > 300:
        doc.items = doc.items[:300]

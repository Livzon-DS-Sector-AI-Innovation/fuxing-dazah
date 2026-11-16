"""COA docx 确定性解析：OOXML 表格合并语义还原。

「不规则单元格」= gridSpan（横向合并）+ vMerge（纵向合并），底层逻辑网格
恒定；主表不同段落的列边界不同（表头分组 ≠ 数据行分组），因此数据行按
物理单元格右锚定：末格=结果、倒数第二=标准、其余前缀格（大类分组）忽略。
文本会被任意碎片化到 run 级（如流水号 26081|215 两 run），必须段落级拼接。

纯标准库（zipfile + ElementTree），不依赖 python-docx。
"""

from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 右上角编号区：流水号（标题行尾独立数字串）与 COA 报告编号
_RE_SERIAL = re.compile(r"(?:CERTIFICATE OF ANALYSIS|检验报告单)\s+(\d{4,})\s*$")
_RE_SERIAL_ONLY = re.compile(r"^\d{4,}$")
_RE_REPORT_NO = re.compile(r"(?:COA\s*)?No\.?\s*[:：]?\s*([A-Za-z][A-Za-z0-9\-_/]{3,})")

# 批次信息表标签 → 本域字段
_BATCH_LABELS: dict[str, str] = {
    "product": r"品\s*名|产品名称|Product\s*Name",
    "batch_no": r"批\s*号|Batch\s*No",
    "mfg_date": r"生产日期|Mfg\.?\s*Date",
    "exp_date": r"有效期|失效日期|Exp\.?\s*Date",
    "packaging": r"包装规格|Packaging",
    "batch_size": r"批\s*量|Batch\s*Size",
    "storage": r"储存条件|贮存条件|Storage",
}
_LABEL_PATS = [(k, re.compile(p)) for k, p in _BATCH_LABELS.items()]

# 数值可带一次尾缀单位（其余形态一律按文字判定保留原文）
_UNIT_TAIL = (
    "%|ppm|ppb|µg/mg|μg/mg|ug/mg|eu/mg|cfu/g|cfu/ml|eu/ml|"
    "kg|mg|g|ml|l|cfu|eu|μm|um|nm|℃|°c"
)
_NUM_RE = re.compile(rf"^(?P<num>-?\d+(?:\.\d+)?)(?:\s*(?:{_UNIT_TAIL}))?$", re.I)
_NUM_IN_SPEC = re.compile(rf"(?P<num>-?\d+(?:\.\d+)?)(?:\s*(?:{_UNIT_TAIL}))?", re.I)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 同行混排拆分锚点：英文译名通常以「大写+小写」（Appearance/Vancomycin）
# 或「大写-小写」（N-nitroso）开头；中文名自身的拉丁片段（B/B1/RS/HPLC）
# 不匹配，因此能定位到译名真正的起点。
_EN_WORD = re.compile(r"[A-Z][a-z]|[A-Z]-[a-z]")


@dataclass
class CoaParsedItem:
    """docx 表2 一行检测项目：项目/标准/结果（原文+尽力解析）。

    大类（vMerge 分组列，如 性状/鉴别/万古霉素组分）不提取——多前缀格
    只取末格作项目名，其余（继承的分组单元格）忽略。
    """

    name_cn: str = ""  # 中文行优先；中英同行按译名词起点拆分
    name_en: str | None = None
    spec_text: str | None = None
    spec_min: float | None = None
    spec_max: float | None = None
    result: str | None = None
    value_num: float | None = None
    value_type: str = "text"  # number/text

    @property
    def name(self) -> str:
        """完整显示名：中文行为准（已含同行英文时即原文）。"""
        return self.name_cn

    @property
    def code(self) -> str:
        """项目匹配键：中英拼接后 NFKC 归一，仅留字母数字与 CJK，小写。"""
        return item_code(self.name_cn, self.name_en)


@dataclass
class CoaDocxParse:
    """一份 COA docx 的完整提取结果。"""

    batch_info: dict[str, str] = field(
        default_factory=dict
    )  # 原文（product/batch_no/…）
    serial_no: str | None = None
    report_no: str | None = None
    conclusion: str | None = None
    items: list[CoaParsedItem] = field(default_factory=list)
    # 解析建议（可能为 None，落库前人工确认）
    suggested_product_code: str | None = None  # report_no 中的字母段，如 HAF
    suggested_standard_code: str | None = None  # report_no 倒数第二个纯数字段，如 3205
    product_cn: str | None = None
    product_en: str | None = None
    mfg_date: date | None = None
    exp_date: date | None = None


# ─────────────────────── 基础文本工具 ───────────────────────


def _cell_text(tc: ET.Element) -> str:
    """单元格文本：段落间 \\n 连接（保留中英双行可分性），段内 run 拼接。"""
    paras = []
    for p in tc.iter(f"{W}p"):
        t = "".join(n.text for n in p.iter(f"{W}t") if n.text)
        paras.append(t.strip())
    return "\n".join(paras).strip()


def _para_text(p: ET.Element) -> str:
    return "".join(n.text for n in p.iter(f"{W}t") if n.text).strip()


def normalize(text: str) -> str:
    """全角→半角等归一（仅用于匹配/数值解析，原文永远保留）。"""
    return unicodedata.normalize("NFKC", text)


def item_code(name_cn: str, name_en: str | None = None) -> str:
    """项目稳定标识：中英拼接归一化，去空白与标点，小写。"""
    joined = normalize(f"{name_cn}{name_en or ''}")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", joined.lower())


def split_bilingual(text: str | None) -> tuple[str, str | None]:
    """中英拆分：多行按行判定（含 CJK=中文行）；单行混排按英文译名词起点拆。

    同行拆分锚点 = 最后一个 CJK 字符之后，第一个「大写+小写/大写-小写」
    英文词（Appearance / Vancomycin / N-nitroso）。中文名自身的拉丁片段
    （万古霉素B / 杂质B(B1+B2) / RS1 / HPLC）不匹配该模式，因此不会被
    误划入英文名。找不到锚点（纯中文/纯代号/全大写）时整行进 name_cn。
    """
    if not text:
        return "", None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cn = [ln for ln in lines if _CJK_RE.search(ln)]
    en = [ln for ln in lines if not _CJK_RE.search(ln)]
    if cn and en:
        return "\n".join(cn), "\n".join(en)
    if not cn and not en:
        return "", None
    # 单行/纯行：尝试同行拆分（中文段 + 紧跟的英文译名）
    joined = "\n".join(cn or en)
    cjk_positions = [m.start() for m in _CJK_RE.finditer(joined)]
    if cjk_positions:
        tail = joined[cjk_positions[-1] + 1:]
        m = _EN_WORD.search(tail)
        if m:
            name_cn = joined[: cjk_positions[-1] + 1 + m.start()].rstrip()
            name_en = tail[m.start():].strip()
            if name_cn and name_en:
                return name_cn, name_en
    # 纯中文 / 纯拉丁代号（RS1）/ 无锚点：整段进 cn（name 永远完整可显示）
    return joined, None


def parse_number(text: str | None) -> float | None:
    """结果数值解析：数字+可选单位尾缀；比较符/判定词一律 None（走文字）。"""
    if not text:
        return None
    s = normalize(text).strip().lower().replace(" ", "")
    if s.startswith(("<", ">", "≤", "≥", "＝")):
        return None
    m = _NUM_RE.match(s)
    if not m:
        return None
    try:
        return float(m.group("num"))
    except ValueError:
        return None


def parse_spec(text: str | None) -> tuple[float | None, float | None]:
    """标准限值解析：≤/<X→max、≥/>X→min、A～/—/-B→区间；解析不干净返回 (None,None)。"""
    if not text:
        return None, None
    s = normalize(text).strip().lower().replace(" ", "")
    s = s.replace("—", "-").replace("–", "-").replace("～", "~").replace("至", "~")
    m = re.match(r"^[<≤](?P<max>.+)$", s)
    if m:
        v = parse_number(m.group("max"))
        return (None, v) if v is not None else (None, None)
    m = re.match(r"^[>≥](?P<min>.+)$", s)
    if m:
        v = parse_number(m.group("min"))
        return (v, None) if v is not None else (None, None)
    m = re.match(
        rf"^(?P<a>[0-9.]+(?:{_UNIT_TAIL})?)~(?P<b>[0-9.]+(?:{_UNIT_TAIL})?)$", s
    )
    if m:
        a, b = parse_number(m.group("a")), parse_number(m.group("b"))
        if a is not None and b is not None:
            return a, b
    return None, None


def parse_date_text(text: str | None) -> date | None:
    """2026.07.29 / 2026-07-29 / 2026/7/9 → date。"""
    if not text:
        return None
    s = normalize(text).strip()
    m = re.search(r"(\d{4})[.\-/年](\d{1,2})[.\-/月](\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ─────────────────────── 表格网格还原 ───────────────────────


def _physical_rows(tbl: ET.Element) -> list[list[str]]:
    """每行的物理单元格文本序列；vMerge continue 继承 restart 的文本。

    不做 gridSpan 展开——数据行语义按物理格右锚定。
    """
    vopen: dict[int, str] = {}
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{W}tr"):
        cells: list[str] = []
        col = 0
        for tc in tr.findall(f"{W}tc"):
            tcpr = tc.find(f"{W}tcPr")
            span, vm = 1, None
            if tcpr is not None:
                gs = tcpr.find(f"{W}gridSpan")
                if gs is not None:
                    span = int(gs.get(f"{W}val") or 1)
                vme = tcpr.find(f"{W}vMerge")
                if vme is not None:
                    vm = vme.get(f"{W}val") or "continue"
            txt = _cell_text(tc)
            if vm == "continue":
                txt = vopen.get(col, "")
            elif vm == "restart":
                for c in range(col, col + span):
                    vopen[c] = txt
            cells.append(txt)
            col += span
        rows.append(cells)
    return rows


def _collapse(cells: list[str]) -> list[str]:
    """gridSpan/标签收割产生的同文本重复 → 压缩回唯一序列。"""
    out: list[str] = []
    for c in cells:
        if c and (not out or out[-1] != c):
            out.append(c)
    return out


# ─────────────────────── 表角色识别与收割 ───────────────────────


def _harvest_numbers(parse: CoaDocxParse, paragraphs: list[str]) -> None:
    for t in paragraphs:
        m = _RE_SERIAL.search(t)
        if m:
            parse.serial_no = parse.serial_no or m.group(1)
        elif _RE_SERIAL_ONLY.match(t):
            parse.serial_no = parse.serial_no or t
        m = _RE_REPORT_NO.search(t)
        if m:
            parse.report_no = parse.report_no or m.group(1)


def _harvest_batch_info(parse: CoaDocxParse, rows: list[list[str]]) -> None:
    for row in rows:
        flat = _collapse([c for c in row if c.strip()])
        for i, cell in enumerate(flat):
            for key, pat in _LABEL_PATS:
                if key in parse.batch_info or not pat.search(cell):
                    continue
                rest = flat[i + 1 :]
                rest = rest[
                    : next(
                        (
                            j
                            for j, v in enumerate(rest)
                            if any(p.search(v) for _, p in _LABEL_PATS)
                        ),
                        len(rest),
                    )
                ]
                if rest:
                    parse.batch_info[key] = rest[0]


def _harvest_items(parse: CoaDocxParse, rows: list[list[str]]) -> None:
    header_i = next(
        (
            i
            for i, r in enumerate(rows)
            if re.search(r"项目|Tests", "".join(r))
            and re.search(r"结果|Results", "".join(r))
        ),
        0,
    )
    for row in rows[header_i + 1 :]:
        cells = [c for c in row if c.strip()]
        if not cells:
            continue
        if re.search(r"结论|Conclusion", cells[0]):
            parse.conclusion = parse.conclusion or "\n".join(cells[1:])
            continue
        if len(cells) < 3:  # 数据行至少 项目+标准+结果 三格
            continue
        names = cells[:-2]
        spec_text, result = cells[-2], cells[-1]
        name_cn, name_en = split_bilingual(names[-1])
        spec_min, spec_max = parse_spec(spec_text)
        value_num = parse_number(result)
        # value_type：标准限可结构化或结果可数值化 → number，否则 text
        is_number = (
            spec_min is not None or spec_max is not None or value_num is not None
        )
        parse.items.append(
            CoaParsedItem(
                name_cn=name_cn,
                name_en=name_en,
                spec_text=spec_text or None,
                spec_min=spec_min,
                spec_max=spec_max,
                result=result or None,
                value_num=value_num,
                value_type="number" if is_number else "text",
            )
        )


def _suggest_codes(parse: CoaDocxParse) -> None:
    """从报告编号拆建议：COA-HAF-3205-006 → 产品码 HAF / 模板码 3205。"""
    if not parse.report_no:
        return
    segs = re.split(r"[-_/]", parse.report_no)
    # 排除报告类型前缀（COA）——它是编号格式的一部分，不是产品码
    alpha = [s for s in segs if s.isalpha() and s.upper() != "COA"]
    digits = [s for s in segs if s.isdigit()]
    if alpha:
        parse.suggested_product_code = alpha[0].upper()
    if len(digits) >= 2:
        parse.suggested_standard_code = digits[-2]
    elif digits:
        parse.suggested_standard_code = digits[-1]


def parse_docx(data: bytes) -> CoaDocxParse:
    """解析 COA docx 字节流（表1 基础信息 + 表2 检测项目 + 编号区段落）。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        hf_paras: list[str] = []
        for name in z.namelist():
            if re.fullmatch(r"word/(header|footer)\d*\.xml", name):
                hf_paras += [
                    _para_text(p) for p in ET.fromstring(z.read(name)).iter(f"{W}p")
                ]
    body = root.find(f"{W}body")
    if body is None:
        raise ValueError("docx 缺少正文 body")
    parse = CoaDocxParse()

    _harvest_numbers(parse, [_para_text(p) for p in body.findall(f"{W}p")])
    _harvest_numbers(parse, hf_paras)

    for tbl in body.findall(f"{W}tbl"):
        prows = _physical_rows(tbl)
        joined = "\n".join("\n".join(r) for r in prows)
        has_main_header = (
            re.search(r"项目|Tests", joined)
            and re.search(r"标准|Specifications", joined)
            and re.search(r"结果|Results", joined)
        )
        if not has_main_header and re.search(r"批\s*号|Batch\s*No", joined):
            _harvest_batch_info(parse, prows)
        elif has_main_header:
            _harvest_items(parse, prows)

    cn, en = split_bilingual(parse.batch_info.get("product"))
    parse.product_cn, parse.product_en = cn or None, en
    parse.mfg_date = parse_date_text(parse.batch_info.get("mfg_date"))
    parse.exp_date = parse_date_text(parse.batch_info.get("exp_date"))
    _suggest_codes(parse)
    return parse

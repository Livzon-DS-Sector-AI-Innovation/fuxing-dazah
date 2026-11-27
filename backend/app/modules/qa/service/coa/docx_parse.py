"""COA 解析域模型 + 确定性文本工具。

文档级提取走 ai_parse（DeepSeek 文档解析 + deepseek-flash，版式无关——
客户 COA 模板多达数百份，锚定规则无法泛化）。本模块只保留提取结果的
域模型与可复用的确定性工具：数值/限值/日期解析、中英双语拆分、项目
匹配键。数值语义必须由这些工具复算覆盖，不信任模型输出（防「＜1 → 1」
丢比较符、静默改写标点）。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

# 数值可带一次尾缀单位（其余形态一律按文字判定保留原文）
_UNIT_TAIL = (
    "%|ppm|ppb|µg/mg|μg/mg|ug/mg|eu/mg|cfu/g|cfu/ml|eu/ml|"
    "kg|mg|g|ml|l|cfu|eu|μm|um|nm|℃|°c"
)
_NUM_RE = re.compile(rf"^(?P<num>-?\d+(?:\.\d+)?)(?:\s*(?:{_UNIT_TAIL}))?$", re.I)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 同行混排拆分锚点：英文译名通常以「大写+小写」（Appearance/Vancomycin）
# 或「大写-小写」（N-nitroso）开头；中文名自身的拉丁片段（B/B1/RS/HPLC）
# 不匹配，因此能定位到译名真正的起点。
_EN_WORD = re.compile(r"[A-Z][a-z]|[A-Z]-[a-z]")


@dataclass
class CoaParsedItem:
    """一行检测项目：项目/标准/结果（中文原文+尽力解析；英文分列留底）。

    大类（跨行分组列，如 性状/鉴别/万古霉素组分）不是检测项目，不提取。
    """

    name_cn: str = ""  # 中文行优先；中英同行按译名词起点拆分
    name_en: str | None = None
    unit: str | None = None  # 检测单位：%/ppm/µg/mg 等（确定性剥取优先）
    spec_text: str | None = None  # 标准列中文原文（纯数值/单位原样保留）
    spec_en: str | None = None  # 标准列英文原句（留底）
    spec_min: float | None = None
    spec_max: float | None = None
    result: str | None = None  # 结果列（剥英文尾巴/尾缀单位后：＜1、1.7）
    result_en: str | None = None  # 结果列英文（留底）
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
class CoaParsedField:
    """批次信息区的一个字段标签（结构提取，模板通常无值）。

    key/field_type 由系统确定性生成（_build_parse），不信任模型：
    key 优先英文标签 snake_case，无英文用中文原文（产品内唯一即可）。
    """

    label_cn: str = ""
    label_en: str | None = None
    key: str = ""  # 阶段二按配置渲染提取 schema 的锚点
    field_type: str = "text"  # text/date
    value: str | None = None  # 值版提取才有（结构版模板通常无值）


@dataclass
class CoaDocxParse:
    """一份 COA 的完整提取结果。"""

    batch_info: dict[str, str] = field(
        default_factory=dict
    )  # 原文（product/batch_no/…）
    serial_no: str | None = None
    report_no: str | None = None
    items: list[CoaParsedItem] = field(default_factory=list)
    batch_fields: list[CoaParsedField] = field(default_factory=list)
    # 解析建议（可能为 None，落库前人工确认）
    suggested_product_code: str | None = None  # report_no 中的字母段，如 HAF
    suggested_standard_code: str | None = None  # report_no 去 COA 前缀整段，如 HAF-3205-006
    product_cn: str | None = None
    product_en: str | None = None
    mfg_date: date | None = None
    exp_date: date | None = None


# ─────────────────────── 基础文本工具 ───────────────────────


def normalize(text: str) -> str:
    """全角→半角等归一（仅用于匹配/数值解析，原文永远保留）。"""
    return unicodedata.normalize("NFKC", text)


# 匹配键落 coa_standard_items.code（64 列）。中英拼接的名字很容易超过：
# 英文复合名动辄七八十个字符，越界写库直接 500。超长时截前 56 字符并带全文摘要 8 位——
# 仍然确定，且只在结尾不同的两个长名字不会撞成同一个键；不超过 64 的结果与从前完全一致。
_CODE_MAX_LENGTH = 64
_CODE_HEAD_LENGTH = 56


def item_code(name_cn: str, name_en: str | None = None) -> str:
    """项目稳定标识：中英拼接归一化，去空白与标点，小写；超过列长时截断并带摘要后缀。"""
    joined = normalize(f"{name_cn}{name_en or ''}")
    code = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", joined.lower())
    if len(code) <= _CODE_MAX_LENGTH:
        return code
    digest = hashlib.blake2b(code.encode("utf-8"), digest_size=4).hexdigest()
    return f"{code[:_CODE_HEAD_LENGTH]}{digest}"


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
        tail = joined[cjk_positions[-1] + 1 :]
        m = _EN_WORD.search(tail)
        if m:
            name_cn = joined[: cjk_positions[-1] + 1 + m.start()].rstrip()
            name_en = tail[m.start() :].strip()
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


# 尾缀单位提取（原文匹配，不经 NFKC——保留 µ/μ 原写法）
_UNIT_SUFFIX_RE = re.compile(rf"-?\d+(?:\.\d+)?\s*({_UNIT_TAIL})\s*$", re.I)


def parse_unit(text: str | None) -> str | None:
    """文本末尾数字后的单位：≤3.0% → %、≥925µg/mg → µg/mg；无单位 → None。"""
    if not text:
        return None
    m = _UNIT_SUFFIX_RE.search(text.strip())
    return m.group(1) if m else None


# 结果值形态（剥完修饰后须长这样才认领剥离）：可选比较符 + 数字
_RESULT_VALUE_LIKE_RE = re.compile(r"^[<＜>＞≤≥＝~～]?\s*-?\d+(?:\.\d+)?$")
_RESULT_UNIT_TAIL_RE = re.compile(rf"\s*({_UNIT_TAIL})\s*$", re.I)


def strip_result_affixes(text: str | None) -> str | None:
    """结果列剥修饰：英文尾巴（符合规定 Conform → 符合规定）与尾缀单位
    （＜1cfu/g → ＜1、1091µg/mg → 1091）。

    守卫：剥单位后必须仍是数值形态（比较符+数字），否则保留原文——
    「白色粉末」这类描述、「USP trial」这类恰以单位字母结尾的英文都不动。
    单位语义归 item.unit 字段，标准列原文（spec_text 带单位）可溯。
    """
    if not text:
        return text
    s = text.strip()
    if _CJK_RE.search(s):
        cn, _en = split_bilingual(s)
        if cn:
            s = cn.strip()
    m = _RESULT_UNIT_TAIL_RE.search(s)
    if m:
        head = s[: m.start()].rstrip()
        if _RESULT_VALUE_LIKE_RE.match(head):
            return head
    return s


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

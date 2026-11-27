"""COA 模板的格式规则与配置偏差。

格式规则：登记的值 → 写进 docx 的文字（小数位、单位后缀、日期写法、判定词补英文）。
配置偏差：标注是针对「确认那一刻的字段配置」人工核对过的；之后配置变了（字段增删、
类型/单位改了），标注不会自己跟着变：这里对着当前配置把变化找出来，交给人工重新
核对（生成前拦住），不替人猜该怎么改。

真实模板大多还没填值（结果格是空的、标题行是 XXXXXXXX），所以格式规则先看
样例值，样例为空时用默认值，人工核对时可改。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.modules.qa.schemas.coa import check_date_pattern
from app.modules.qa.service.coa.template_address import squash
from app.modules.qa.service.coa.template_bind.fields import FieldDef

DEFAULTS: dict[str, Any] = {
    "decimals": 2,
    "verdict_bilingual": True,
    "joiner": "",
    "date_pattern": "%Y.%m.%d",
}

# 判定词英文：模板样例里学到的对照（binding.verdicts）优先，其次才是这张内置表
BUILTIN_VERDICTS: dict[str, str] = {
    "符合规定": "Conform",
    "不符合规定": "Does not conform",
    "未检出": "Not detected",
    "低于报告限": "Below reporting limit",
}

_DATE_PATTERNS = ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%d %b %Y", "%d %B %Y")
_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)(.*)")
_BILINGUAL_RE = re.compile(
    r"^(?P<cn>[^A-Za-z]*[一-鿿][^A-Za-z]*?)(?P<join>\n[ \t]*|[ \t]+)?(?P<en>[A-Za-z].*)$",
    re.S,
)


# ─────────────────────── 格式规则 ───────────────────────


def normalize_fmt(fmt: Mapping[str, Any]) -> dict[str, Any]:
    """格式规则规整为规范形态（只保留该类型用得到的键）。"""
    kind = str(fmt.get("kind") or "text")
    if kind == "number":
        decimals = fmt.get("decimals")
        decimals = DEFAULTS["decimals"] if decimals is None else int(decimals)
        number: dict[str, Any] = {
            "kind": "number",
            "decimals": min(6, max(0, decimals)),
            "suffix": str(fmt.get("suffix") or ""),
        }
        if fmt.get("bilingual"):  # 只在登记成文字（未检出）时用到
            number["bilingual"] = True
            joiner = fmt.get("joiner")
            number["joiner"] = joiner if joiner in ("", " ", "\n") else DEFAULTS["joiner"]
        return number
    if kind == "date":
        return {
            "kind": "date",
            "pattern": check_date_pattern(str(fmt.get("pattern") or DEFAULTS["date_pattern"])),
        }
    joiner = fmt.get("joiner")
    if joiner not in ("", " ", "\n"):
        joiner = DEFAULTS["joiner"]
    return {
        "kind": "text",
        "bilingual": bool(fmt.get("bilingual")),
        "joiner": joiner,
        "suffix": str(fmt.get("suffix") or ""),
    }


def match_date_pattern(sample: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        try:
            datetime.strptime(sample.strip(), pattern)
        except ValueError:
            continue
        return pattern
    return None


# 计数型限度（不得超过 5 个、≤6000 个/g、≤1000cfu/g）：结果是整数个数
_COUNT_SPEC_RE = re.compile(r"个|粒|cfu", re.I)


def _default_decimals(field: FieldDef) -> int:
    """空白模板的数值位数：结果是整数个数时取 0——计数型限度（不得超过 5 个、≤1000cfu/g），
    或限度都是「大的整数」（≥1050IU/mg、≤5000ppm）；其余取模板默认。

    计数型先判：这类标准的文字里常同时带百分比阈值（＞0.30%的杂质不得超过 5 个）。
    """
    spec = field.spec_text or ""
    if _COUNT_SPEC_RE.search(spec):
        return 0
    numbers = re.findall(r"\d+(?:\.\d+)?", spec)
    if numbers and all("." not in n and float(n) >= 10 for n in numbers):
        return 0
    return int(DEFAULTS["decimals"])


def bilingual_pair(text: str) -> tuple[str, str, str] | None:
    """「符合规定Conform」→ (符合规定, Conform, 连接符)；连接符保留模板里的换行/空格。"""
    match = _BILINGUAL_RE.match(text.strip())
    if not match:
        return None
    return match.group("cn").strip(), match.group("en").strip(), match.group("join") or ""


def infer_format(field: FieldDef, sample: str, slot_text: str) -> dict[str, Any]:
    """从样例值推格式规则；样例为空（模板没填）时用默认值。

    sample 可能带着值两侧的排版空白（整格记录），先去掉再判断。
    """
    sample = sample.strip()
    if field.kind == "batch":
        if field.field_type == "date":
            return {"kind": "date", "pattern": match_date_pattern(sample) or DEFAULTS["date_pattern"]}
        return {"kind": "text"}
    if not sample.strip():
        if field.value_type == "number":
            return {
                "kind": "number",
                "decimals": _default_decimals(field),
                "suffix": field.unit or "",
                "bilingual": bool(DEFAULTS["verdict_bilingual"]),
                "joiner": DEFAULTS["joiner"],
            }
        return {
            "kind": "text",
            "bilingual": bool(DEFAULTS["verdict_bilingual"]),
            "joiner": DEFAULTS["joiner"],
            "suffix": field.unit or "",
        }
    number = _NUMBER_RE.fullmatch(sample)
    if number and not re.search(r"[一-鿿]", sample):
        decimals = len(number.group(1).split(".")[1]) if "." in number.group(1) else 0
        return {"kind": "number", "decimals": decimals, "suffix": number.group(2).strip()}
    pair = bilingual_pair(slot_text)
    if pair:
        return {"kind": "text", "bilingual": True, "joiner": pair[2]}
    unit = field.unit or ""
    if unit and sample.strip().endswith(unit) and squash(sample) != squash(unit):
        return {"kind": "text", "suffix": unit}
    return {"kind": "text"}


# ─────────────────────── 标注与字段配置的偏差 ───────────────────────

# 配置值的展示写法（提示里用）
_CONFIG_VALUE_LABELS = {"number": "数值", "text": "文字", "date": "日期"}
_CONFIG_NAME_LABELS = {"unit": "单位", "value_type": "值类型", "type": "类型"}


def field_config(field: FieldDef) -> dict[str, Any]:
    """标注会用到的字段配置：批次字段看类型（决定日期怎么写），项目看单位和值类型。"""
    if field.kind == "batch":
        return {"type": field.field_type}
    return {"unit": field.unit, "value_type": field.value_type}


def _config_value(name: str, value: Any) -> str:
    """提示里的写法：单位原样，值类型/字段类型说中文，没有写「空」。"""
    if value is None or value == "":
        return "空"
    text = str(value)
    return text if name == "unit" else _CONFIG_VALUE_LABELS.get(text, text)


def _removed_label(key: str) -> str:
    """标注里没记名字的旧条目：批次字段还能从键上认，项目只剩一串 id。"""
    kind, _, name = key.partition(":")
    return name if kind == "batch" else "已移除的检测项目"


def binding_drift(
    fields: Sequence[FieldDef], binding: Mapping[str, Any]
) -> dict[str, Any] | None:
    """已确认的标注与当前字段配置的偏差；没有偏差返回 None。

    - removed：标注引用的字段/项目已被移除，那一条标注不再生效
    - added：确认之后新增、还没标注位置的字段（没经过人工过目）
    - changed：类型/单位变了的字段，已确认的格式规则要重新过目

    added 只有标注里记了字段清单（field_set）才认得出：早先的标注没记，
    按没有新增处理，重新保存一次就记上了。
    """
    current = {f.key: f for f in fields}
    removed: list[dict[str, str]] = []
    changed: list[dict[str, Any]] = []
    for entry in binding.get("fields", []):
        key = str(entry.get("field"))
        field = current.get(key)
        if field is None:
            removed.append(
                {"field": key, "label_cn": str(entry.get("label_cn") or _removed_label(key))}
            )
            continue
        saved = entry.get("config") or {}
        diffs = []
        for name, value in field_config(field).items():
            if name in saved and saved.get(name) != value:
                label = _CONFIG_NAME_LABELS.get(name, name)
                diffs.append(f"{label}：{_config_value(name, saved.get(name))} → {_config_value(name, value)}")
        if diffs:
            changed.append({"field": key, "label_cn": field.label_cn, "changes": diffs})
    recorded = binding.get("field_set")
    known = set(str(k) for k in recorded) if recorded is not None else None
    added = (
        [{"field": f.key, "label_cn": f.label_cn, "kind": f.kind} for f in fields if f.key not in known]
        if known is not None
        else []
    )
    if not (removed or added or changed):
        return None
    drift: dict[str, Any] = {"removed": removed, "added": added, "changed": changed}
    drift["lines"] = _drift_lines(drift)
    return drift


# 提示里最多逐条列出这么多变化，再多并成一句（整批替换项目时可能有几十处）
_DRIFT_LINE_LIMIT = 8


def _drift_lines(drift: Mapping[str, Any]) -> list[str]:
    """给人看的偏差条目：抽屉的提示和生成被拦时的报错共用同一套说法。

    要动手的排前面（改格式的、挑位置的），只是知会的排后面。
    """
    lines = [
        *[f"「{row['label_cn']}」的{'、'.join(row['changes'])}，格式要重新确认" for row in drift["changed"]],
        *[f"新增的「{row['label_cn']}」还没有标注位置" for row in drift["added"]],
        *[f"「{row['label_cn']}」已从标准里移除，它的标注不再生效" for row in drift["removed"]],
    ]
    if len(lines) > _DRIFT_LINE_LIMIT:
        return [*lines[:_DRIFT_LINE_LIMIT], f"……等共 {len(lines)} 处变化"]
    return lines

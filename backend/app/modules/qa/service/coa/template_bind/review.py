"""COA 模板标注的确定性校验与提案组装。

AI 只产提案。模型偶尔会把值归错字段（标题行流水号当成批号）或把值标到标准列
（行内格子数不一致时），这些靠不经过模型的确定性校验兜住并排到人工核对的最
前面；保存前必须人工过目（save_template_binding），回填只用保存后的标注、
不再经过模型。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.modules.qa.service.coa.template_address import (
    Slot,
    TemplateDoc,
    display_text,
    flat_text,
    guess_inline_value,
    locate,
    squash,
)
from app.modules.qa.service.coa.template_bind.fields import (
    TEMPLATE_EXCLUDED_BATCH_FIELDS,
    FieldDef,
    field_dict,
)
from app.modules.qa.service.coa.template_bind.formats import (
    DEFAULTS,
    bilingual_pair,
    binding_drift,
    infer_format,
    match_date_pattern,
)

FLAG_LABELS: dict[str, str] = {
    "not_in_result_column": "不在结果列",
    "item_outside_table": "不在表格里",
    "name_mismatch": "与所在行的项目名对不上",
    "label_mismatch": "与所在行的标签对不上",
    "sample_not_date": "日期字段的位置上不是日期",
    "sample_looks_date": "位置上是日期，但字段不是日期",
    "inconsistent_values": "多处位置的当前值不一致",
    "body_paragraph": "在正文/页眉段落里（非表格）",
    "multi_paragraph_cell": "同一格里绑定了多个段落",
    "ambiguous_sample": "当前值在段落里出现多次",
    "batch_unbound": "批次字段没有找到位置",
    "config_changed": "类型/单位变了，请确认格式",
}


@dataclass
class _Plan:
    field: FieldDef
    slot: Slot
    mode: str  # replace=整段就是值；inplace=值夹在固定文字中间
    sample: str  # 回填时被替换的原文（整格=整格文字含排版空白；空格=""）


def _similarity(a: str, b: str) -> float:
    na = re.sub(r"[\W_]+", "", a.lower())
    nb = re.sub(r"[\W_]+", "", b.lower())
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _core_tokens(text: str) -> set[str]:
    return set(re.findall(r"[0-9]+|[a-z]+", text.lower()))


def _cjk_tokens(text: str) -> set[str]:
    return set(re.findall(r"[一-鿿]", text))


def name_matches(names: tuple[str, ...], context: str, floor: float) -> bool:
    """名字与所在行对不对得上（中文名、英文名任一对上即可）。

    名字里的数字和字母必须全部出现在这段文字里——「杂质A-RRT约0.76」和
    「杂质C-RRT约1.86」整体很像，靠相似度分不出标到了哪一行。名字里没有字母
    数字（纯中文）才要求汉字全部出现：提取出的中文名与模板用词常有出入，带
    字母数字的以字母数字为准。英文名不要求必中——模型抄长英文词常掉字符。

    已知局限：几个项目的中文名完全相同（都叫「杂质」）且英文名也对不上时，
    这项检查分不出标到了哪一行，要靠人工核对。
    """
    names = tuple(name for name in names if name)
    if not names:
        return True
    context_core, context_cjk = _core_tokens(context), _cjk_tokens(context)
    for name in names:
        core, cjk = _core_tokens(name), _cjk_tokens(name)
        if core and core <= context_core:
            return True
        if not core and cjk and cjk <= context_cjk:
            return True
        if _similarity(name, context) >= floor:
            return True
    return False


def plan_slot(slot: Slot, sample: str) -> tuple[str, str]:
    """(数据位, 模型给的样例) → (替换方式, 回填时替换的原文)；与原文对不上抛 ValueError。"""
    flat = flat_text(slot.element)
    if sample.strip():
        old = locate(flat, sample)
        if old is None:
            raise ValueError(f"「{sample}」不在数据位 {slot.sid} 中（当前为「{flat[:40]}」）")
    elif flat.strip():
        raise ValueError(f"数据位 {slot.sid} 不是空格（当前为「{flat[:40]}」）")
    else:
        old = ""
    if squash(old) == squash(flat):
        return "replace", flat
    if flat.count(old) != 1:
        raise ValueError(f"「{old}」在数据位 {slot.sid} 中出现多次，无法确定替换哪一处")
    return "inplace", old


def derive_slot(slot: Slot, sample: str | None) -> tuple[str, str]:
    """人工确认的绑定 → (替换方式, 原文)。

    前端带了 sample 就按它定位（值夹在固定文字中间时必须带）；不带则表格格
    按整格，正文/页眉段落按占位符或数字串猜值本身，猜不出再按整段。
    """
    flat = flat_text(slot.element)
    if sample is not None and sample.strip():
        return plan_slot(slot, sample)
    if sample is not None and flat.strip():
        raise ValueError(f"数据位 {slot.sid} 不是空格，请指明要替换的文字")
    if sample is None and not slot.in_table:
        guess = guess_inline_value(flat)
        if guess is not None:
            return plan_slot(slot, guess)
    return "replace", flat


def result_residue(doc: TemplateDoc, bound: set[str]) -> list[dict[str, str]]:
    """结果列里没被绑定、又不是空的格子——填过值的模板上最可能残留旧结果。

    表头行（「结果Results」那一格）不算。
    """
    result_cols = doc.result_columns()
    header_sids = {
        s.sid for table in doc.tables if table.rows for c in table.rows[0].cells for s in c.paragraphs
    }
    residue: list[dict[str, str]] = []
    for slot in doc.slots:
        if (
            slot.table in result_cols
            and slot.col == result_cols[slot.table]
            and slot.sid not in bound
            and slot.sid not in header_sids
            and slot.text.strip()
        ):
            residue.append(
                {
                    "sid": slot.sid,
                    "text": slot.text.strip()[:60],
                    "context": doc.row_context(slot, exclude_cell=slot.cell)[:120],
                }
            )
    return residue


def assemble(
    doc: TemplateDoc,
    fields: list[FieldDef],
    ai_keys: Mapping[str, FieldDef],
    payload: Mapping[str, Any],
    *,
    fmt_override: Mapping[str, Mapping[str, Any]] | None = None,
    required_override: Mapping[str, bool] | None = None,
    static_slots: list[str] | None = None,
    verdicts_override: Mapping[str, str] | None = None,
    extra_flags: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """标注载荷 → 给人工核对的提案：每个字段的位置、原文、格式规则、校验标记。

    extra_flags：位置本身没问题、但要人看一眼的字段级标记（如确认后配置变了）。
    """
    owner: dict[str, FieldDef] = {}
    plans: list[_Plan] = []
    problems: list[str] = []
    for binding in payload.get("bindings", []):
        key = str(binding.get("field"))
        field = ai_keys.get(key)
        if field is None:
            # 品名/储存条件不回填：模型把它们当值绑上去是正常现象，不算问题
            if key.removeprefix("batch:") not in TEMPLATE_EXCLUDED_BATCH_FIELDS:
                problems.append(f"模型引用了清单外的字段 {key!r}，已忽略")
            continue
        for raw in binding.get("slots", []):
            slot = doc.resolve(str(raw.get("id", "")))
            if slot is None:
                problems.append(f"{key}：地址 {raw.get('id')!r} 在模板中不存在，已忽略")
                continue
            if slot.sid in owner:
                problems.append(
                    f"{key}：数据位 {slot.sid} 已绑定到 {owner[slot.sid].key}，已忽略"
                )
                continue
            try:
                mode, sample = plan_slot(slot, str(raw.get("sample") or ""))
            except ValueError as exc:
                problems.append(f"{key}：{exc}")
                continue
            owner[slot.sid] = field
            plans.append(_Plan(field, slot, mode, sample))

    result_cols = doc.result_columns()
    verdicts: dict[str, str] = {}
    field_rows: list[dict[str, Any]] = []
    for field in fields:
        mine = [p for p in plans if p.field.key == field.key]
        flags: list[str] = []
        cells = {p.slot.cell for p in mine}
        values = {squash(p.sample) for p in mine if squash(p.sample)}
        if len(cells) >= 2 and len(values) >= 2:
            flags.append("inconsistent_values")
        if any(sum(1 for p in mine if p.slot.cell == cell) >= 2 for cell in cells):
            flags.append("multi_paragraph_cell")
        if not mine and field.kind == "batch":
            flags.append("batch_unbound")
        slot_rows: list[dict[str, Any]] = []
        for plan in mine:
            slot, sample = plan.slot, plan.sample
            context = doc.row_context(slot, exclude_cell=slot.cell)
            slot_flags = _slot_flags(field, plan, context, result_cols)
            fmt: dict[str, Any] = (
                dict(fmt_override[slot.sid]) if fmt_override and slot.sid in fmt_override else {}
            )
            if not fmt:
                fmt = infer_format(
                    field,
                    sample,
                    display_text(slot.element) if plan.mode == "replace" else sample,
                )
            slot_rows.append(
                {
                    "sid": slot.sid,
                    "mode": plan.mode,
                    "sample": sample,
                    "fmt": fmt,
                    "context": context[:160],
                    "flags": slot_flags,
                }
            )
            flags.extend(f for f in slot_flags if f not in flags)
            if field.kind == "item":
                pair = bilingual_pair(sample)
                if pair:
                    verdicts.setdefault(pair[0], pair[1])
        required = (
            required_override.get(field.key, True)
            if required_override is not None
            else True
        )
        flags.extend(f for f in (extra_flags or {}).get(field.key, []) if f not in flags)
        field_rows.append(
            {
                **field_dict(field),
                "bound": bool(mine),
                "required": required,
                "slots": slot_rows,
                "flags": flags,
            }
        )

    unmapped: list[dict[str, str]] = []
    for key in payload.get("unmapped", []):
        field = ai_keys.get(str(key))
        if field is not None:
            unmapped.append({"field": field.key, "label_cn": field.label_cn, "kind": field.kind})
    if verdicts_override:
        verdicts = {**verdicts, **dict(verdicts_override)}
    static = [s for s in (static_slots or []) if s in doc.by_id]
    residue = result_residue(doc, set(owner))
    return {
        "defaults": dict(DEFAULTS),
        "verdicts": verdicts,
        "fields": field_rows,
        "static_slots": static,
        "residue": [r for r in residue if r["sid"] not in static],
        "ai_unmapped": unmapped,
        "problems": problems,
        "flag_labels": dict(FLAG_LABELS),
        "needs_review": sum(1 for row in field_rows if row["flags"]),
    }


def _slot_flags(
    field: FieldDef, plan: _Plan, context: str, result_cols: Mapping[str, int]
) -> list[str]:
    slot, sample = plan.slot, plan.sample
    flags: list[str] = []
    if field.kind == "item":
        if slot.table is None:
            flags.append("item_outside_table")
        else:
            if slot.table in result_cols and slot.col != result_cols[slot.table]:
                flags.append("not_in_result_column")
            if not name_matches((field.label_cn, field.label_en or ""), context, 0.8):
                flags.append("name_mismatch")
    elif not slot.in_table:
        # 标题行流水号是固定形态（提示词里写死了定义），不提醒；
        # 其他批次字段落在正文/页眉段落里才需要人看一眼
        if field.key != "batch:serial_no":
            flags.append("body_paragraph")
    else:
        if not name_matches((field.label_cn, field.label_en or ""), context, 0.6):
            flags.append("label_mismatch")
        looks_date = sample.strip() and match_date_pattern(sample) is not None
        if field.field_type == "date" and sample.strip() and not looks_date:
            flags.append("sample_not_date")
        if field.field_type != "date" and looks_date:
            flags.append("sample_looks_date")
    if plan.mode == "inplace" and flat_text(slot.element).count(sample) > 1:
        flags.append("ambiguous_sample")
    return flags


def describe_binding(
    doc: TemplateDoc,
    fields: list[FieldDef],
    binding: Mapping[str, Any],
    drift: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """已保存的标注 → 与提案同形的结构（重新打开核对/编辑时用）。

    确认之后类型/单位变了的字段带 config_changed 标记：格式规则是按原来的
    配置确认的，要人重新看一眼（标记要逐个确认才能保存）。
    """
    ai_keys = {f.key: f for f in fields}
    payload: dict[str, Any] = {"bindings": [], "unmapped": []}
    fmt_override: dict[str, Mapping[str, Any]] = {}
    required: dict[str, bool] = {}
    for entry in binding.get("fields", []):
        field = ai_keys.get(str(entry.get("field")))
        if field is None:
            continue  # 项目已从标准里移除：这一条不再生效（偏差里另有提示，回填时另有守卫）
        slots = [s for s in entry.get("slots", []) if str(s.get("sid")) in doc.by_id]
        for slot in slots:
            fmt_override[str(slot["sid"])] = slot.get("fmt") or {}
        payload["bindings"].append(
            {
                "field": field.key,
                "slots": [{"id": s["sid"], "sample": s.get("sample")} for s in slots],
            }
        )
        required[field.key] = bool(entry.get("required", True))
    if drift is None:
        drift = binding_drift(fields, binding)
    changed = drift["changed"] if drift else []
    return assemble(
        doc,
        fields,
        ai_keys,
        payload,
        fmt_override=fmt_override,
        required_override=required,
        static_slots=list(binding.get("static_slots") or []),
        verdicts_override=binding.get("verdicts") or {},
        extra_flags={str(row["field"]): ["config_changed"] for row in changed},
    )

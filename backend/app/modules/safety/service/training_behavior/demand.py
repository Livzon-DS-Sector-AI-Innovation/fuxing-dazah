"""链1：年度培训需求生成——五源取数 → AI 草案 → PG 草案表 → 采纳写台账。

数据流（DESIGN 二期 §4.1）：五源取数（四路 Bitable 直读 + 一路 PG）→ 汇报
文本 digest → AI(training_demand_generation, temp 0.2) → training_demand_drafts
（draft）→ 安环科评审（API 查询）→ 逐行采纳（写 Bitable 培训表计划行，
状态=未开始）/ 驳回。

关键口径：
- **草案不直接写 Bitable 培训表**——D3-05 完成率=非取消行中已完成/应完成，
  草案入表会污染分母；采纳时才写。
- 幂等：同 year 重新生成=全量替换 status=draft 的行（软删），adopted/rejected
  保留；采纳行状态推进后不可再采纳/驳回。
- 五源统计年=year-1（为 2027 出计划用 2026 证据，与提示词「本年度/上学年」
  语义一致）。
- 源1 读 hazard_id/identification（registry 实际登记的 kind；规格 §4.2 写的
  ledger 不存在，列名 岗位（人工）/不规范作业行为表现（人工）/现有管理控制
  措施（AI） 即规格所指三数据点——已按「规格与现实冲突先查代码事实」回报）。
- 源4 读 ragplus_doc_map（domain=regulation 且 status=active=收录完成）。
- 坑5 防脏选项：培训形式只写 线下/线上/实操 蓝本值，AI 给出未注册形式时
  不写该列、改记备注。

接缝（双接缝测试）：opener 替身注入 Bitable 客户端；ai_service 注入假服务。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_training_demand import (
    TrainingDemandError,
    TrainingDemandInput,
    TrainingDemandPlugin,
)
from app.modules.safety.models.knowledge import RagplusDocMap
from app.modules.safety.models.training_demand_draft import (
    STATUS_ADOPTED,
    STATUS_DRAFT,
    STATUS_LABELS,
    STATUS_REJECTED,
    TrainingDemandDraft,
)
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior.common import BJ_TZ, Opener
from app.modules.safety.service.training_behavior.seed_data import (
    HAZARD_CATEGORY_AI,
    HAZARD_DATE,
)

logger = logging.getLogger(__name__)

# 源1 hazard_id/identification（危险源辨识登记表）读列
_HID_POSITION = "岗位（人工）"
_HID_UNSAFE = "不规范作业行为表现（人工）"
_HID_CONTROLS = "现有管理控制措施（AI）"

# 源3 violation 读列（含违章日期做统计年过滤）
_VIOLATION_FIELDS = ("违章日期", "违章类别", "违章等级")

# 源5 training 读列（上年完成情况：完成率+考核薄弱）
_TRAINING_FIELDS = (
    "培训名称", "状态", "计划日期", "考核合格人数", "应到人数",
)

# digest 截断口径（规格 §4.2）
_HID_PER_POSITION_LIMIT = 5
_HID_TOTAL_LIMIT = 200
_STATS_TOP = 15
_REGULATION_LIMIT = 30

# 采纳写入映射（规格 §4.4）；培训形式蓝本值（坑5：不写未注册选项）
_TRAINING_FORMS = ("线下", "线上", "实操")
_PLANNED_STATUSES = ("未开始", "进行中", "已完成")
_POSITION_SPLIT_RE = re.compile(r"[、，,;；/]+")


class DemandStateError(ValueError):
    """草案状态流转非法（不存在/已采纳再操作等）。"""


# ═════════════════════════════ digest 组装（纯函数） ═════════════════════════════


def _bj_date(fields: dict[str, Any], name: str) -> date | None:
    dt = bd_fields.datetime_ms(fields, name)
    if dt is None:
        return None
    return dt.astimezone(BJ_TZ).date()


def _year_rows(
    records: list[dict[str, Any]], date_field: str, year: int
) -> list[dict[str, Any]]:
    """按日期列落在北京时区统计年内的行（无日期行不参与，与 D3 口径一致）。"""
    hits: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields") or {}
        d = _bj_date(fields, date_field)
        if d is not None and d.year == year:
            hits.append(record)
    return hits


def build_hazard_id_digest(
    records: list[dict[str, Any]],
    *,
    per_position_limit: int = _HID_PER_POSITION_LIMIT,
    total_limit: int = _HID_TOTAL_LIMIT,
) -> str:
    """危险源辨识行 → 岗位分组摘要（每岗位前 5 条行为，总 ≤200 行）。

    行格式：`- 不规范作业行为（现有管理控制：…）`，按岗位分组列出；无
    行为描述的行跳过（对 AI 无供给价值）。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for record in records:
        fields = record.get("fields") or {}
        if not (bd_fields.text(fields, _HID_UNSAFE) or "").strip():
            continue
        position = (bd_fields.text(fields, _HID_POSITION) or "").strip() or "（未填岗位）"
        if position not in grouped:
            grouped[position] = []
            order.append(position)
        grouped[position].append(record)

    lines: list[str] = []
    total = 0
    truncated = False
    for position in order:
        if total >= total_limit:
            truncated = True
            break
        rows = grouped[position][:per_position_limit]
        lines.append(f"【{position}】")
        for record in rows:
            if total >= total_limit:
                truncated = True
                break
            fields = record.get("fields") or {}
            behavior = (bd_fields.text(fields, _HID_UNSAFE) or "").strip()
            controls = (bd_fields.text(fields, _HID_CONTROLS) or "").strip()
            line = f"- {behavior}"
            if controls:
                line += f"（现有管理控制：{controls}）"
            lines.append(line)
            total += 1
    if not lines:
        return "（危险源辨识无可用的岗位行为记录）"
    if truncated:
        lines.append(f"（已达 {total_limit} 行上限，后续岗位截断）")
    return "\n".join(lines)


def build_hazard_stats(records: list[dict[str, Any]], *, year: int) -> str:
    """隐患类别（AI）计数 → TOP15 文本。"""
    hits = _year_rows(records, HAZARD_DATE, year)
    counter: Counter[str] = Counter()
    for record in hits:
        category = (bd_fields.select(record.get("fields") or {}, HAZARD_CATEGORY_AI) or "").strip()
        if category:
            counter[category] += 1
    if not counter:
        return f"{year} 年无隐患类别统计记录。"
    lines = [f"{year} 年隐患共 {sum(counter.values())} 条，TOP{min(_STATS_TOP, len(counter))} 类别："]
    for category, count in counter.most_common(_STATS_TOP):
        lines.append(f"- {category}：{count} 次")
    return "\n".join(lines)


def build_violation_stats(records: list[dict[str, Any]], *, year: int) -> str:
    """违章类别×等级计数 → TOP15 文本。"""
    hits = _year_rows(records, "违章日期", year)
    counter: Counter[str] = Counter()
    for record in hits:
        fields = record.get("fields") or {}
        category = bd_fields.select(fields, "违章类别") or "（未定性）"
        level = bd_fields.select(fields, "违章等级") or "（未定级）"
        counter[f"{category}（{level}）"] += 1
    if not counter:
        return f"{year} 年无违章档案统计记录。"
    lines = [f"{year} 年违章共 {sum(counter.values())} 条，TOP{min(_STATS_TOP, len(counter))} 类别×等级："]
    for key, count in counter.most_common(_STATS_TOP):
        lines.append(f"- {key}：{count} 次")
    return "\n".join(lines)


def build_regulation_list(rows: list[tuple[str, str | None]]) -> str:
    """PG 已收录法规 (title, file_name) → ≤30 条标题清单。"""
    if not rows:
        return "（本年度无新收录/修订法规记录）"
    lines = [f"本年度新收录/修订法规 {len(rows)} 部："]
    for title, _file_name in rows[:_REGULATION_LIMIT]:
        lines.append(f"- 《{title}》")
    if len(rows) > _REGULATION_LIMIT:
        lines.append(f"（仅列前 {_REGULATION_LIMIT} 部）")
    return "\n".join(lines)


def _int_text(fields: dict[str, Any], name: str) -> int | None:
    raw = bd_fields.text(fields, name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def build_last_year_summary(records: list[dict[str, Any]], *, year: int) -> str:
    """上学年完成率（计划日期锚定，D3-05 同口径）+ 考核薄弱主题。"""
    hits = [
        r for r in _year_rows(records, "计划日期", year)
        if bd_fields.select(r.get("fields") or {}, "状态") != "已取消"
    ]
    planned = [r for r in hits
               if bd_fields.select(r.get("fields") or {}, "状态") in _PLANNED_STATUSES]
    if not planned:
        return f"{year} 年无培训计划记录。"
    done = sum(1 for r in planned if bd_fields.select(r.get("fields") or {}, "状态") == "已完成")
    rate = round(done * 100 / len(planned))
    lines = [
        f"{year} 年计划 {len(planned)} 项（非取消），已完成 {done} 项，完成率 {rate}%。",
    ]
    weak: list[str] = []
    for r in planned:
        fields = r.get("fields") or {}
        expected = _int_text(fields, "应到人数")
        passed = _int_text(fields, "考核合格人数")
        if expected and passed is not None and passed < expected:
            name = (bd_fields.text(fields, "培训名称") or "（未命名培训）").strip()
            weak.append(f"{name}（合格 {passed}/应到 {expected}）")
    if weak:
        lines.append("考核薄弱（合格率<100%）：")
        lines.extend(f"- {w}" for w in weak[:_STATS_TOP])
    else:
        lines.append("考核薄弱（合格率<100%）：无（合格数均达应到或未填考核数）。")
    return "\n".join(lines)


# ═════════════════════════════ 五源取数 ═════════════════════════════


async def _read_source(
    open_client, domain: str, kind: str, field_names: tuple[str, ...], label: str
) -> list[dict[str, Any]] | None:
    """单源直读；未接入返回 None（降级占位），其它异常降级并告警不阻断。"""
    try:
        client = open_client(domain, kind)
        return await client.list_all_records(
            field_names=list(field_names), strict=True
        )
    except BitableConfigError as exc:
        logger.info("培训需求五源之%s未接入，降级: %s", label, exc)
        return None
    except Exception as exc:
        logger.warning("培训需求五源之%s读取失败，降级: %s", label, exc)
        return None


async def collect_five_sources(
    db: AsyncSession,
    opener: Opener,
    *,
    year: int,
) -> tuple[TrainingDemandInput, dict[str, int]]:
    """五源取数 → (digest 输入, 各源行数画像)。统计年=year-1。"""
    stats_year = year - 1

    hid_records = await _read_source(
        opener, "hazard_id", "identification",
        (_HID_POSITION, _HID_UNSAFE, _HID_CONTROLS), "危险源辨识",
    )
    hazard_records = await _read_source(
        opener, "hazard", "hazard", (HAZARD_CATEGORY_AI, HAZARD_DATE), "隐患统计",
    )
    violation_records = await _read_source(
        opener, "training_behavior", "violation", _VIOLATION_FIELDS, "违章统计",
    )
    training_records = await _read_source(
        opener, "training_behavior", "training", _TRAINING_FIELDS, "上学年培训",
    )

    reg_rows = await _fetch_regulations(db, year=stats_year)

    demand_input = TrainingDemandInput(
        hazard_id_digest=(
            build_hazard_id_digest(hid_records)
            if hid_records is not None else "（危险源辨识数据未接入）"
        ),
        hazard_stats=(
            build_hazard_stats(hazard_records, year=stats_year)
            if hazard_records is not None else "（隐患统计数据未接入）"
        ),
        violation_stats=(
            build_violation_stats(violation_records, year=stats_year)
            if violation_records is not None else "（违章档案数据未接入）"
        ),
        regulation_list=build_regulation_list(reg_rows),
        last_year_summary=(
            build_last_year_summary(training_records, year=stats_year)
            if training_records is not None else "（培训台账数据未接入）"
        ),
    )
    profile = {
        "hazard_id_rows": len(hid_records or []),
        "hazard_rows": len(hazard_records or []),
        "violation_rows": len(violation_records or []),
        "regulation_rows": len(reg_rows),
        "training_rows": len(training_records or []),
        "disconnected": sum(
            1 for r in (hid_records, hazard_records, violation_records, training_records)
            if r is None
        ),
    }
    return demand_input, profile


async def _fetch_regulations(
    db: AsyncSession, *, year: int
) -> list[tuple[str, str | None]]:
    """PG 源4：本年度收录完成的法规标题（ragplus_doc_map domain=regulation
    status=active=已入主检索库；created_at 北京时区落统计年）。"""
    start = datetime(year, 1, 1, tzinfo=BJ_TZ)
    end = datetime(year + 1, 1, 1, tzinfo=BJ_TZ)
    result = await db.execute(
        select(RagplusDocMap.title, RagplusDocMap.file_name)
        .where(
            RagplusDocMap.domain == "regulation",
            RagplusDocMap.status == "active",
            RagplusDocMap.is_deleted.is_(False),
            RagplusDocMap.created_at >= start,
            RagplusDocMap.created_at < end,
        )
        .order_by(RagplusDocMap.created_at.desc())
        .limit(_REGULATION_LIMIT)
    )
    return [(r.title or r.file_name or "（无标题）", r.file_name) for r in result.all()]


# ═════════════════════════════ 生成编排 ═════════════════════════════


async def generate_demand_drafts(
    db: AsyncSession,
    *,
    year: int,
    opener: Opener | None = None,
    ai_service: Any = None,
) -> dict[str, Any]:
    """五源取数 → AI 生成 → 草案行落库（替换同年旧草案，终态行保留）。"""
    open_client = opener or bd_reader.resolve_client
    if ai_service is None:
        from app.modules.safety.service.config import create_ai_service

        ai_service = create_ai_service("text")
    plugin = TrainingDemandPlugin(ai_service)

    demand_input, profile = await collect_five_sources(db, open_client, year=year)
    output = await plugin.generate(demand_input)

    result = await db.execute(
        update(TrainingDemandDraft)
        .where(
            TrainingDemandDraft.year == year,
            TrainingDemandDraft.status == STATUS_DRAFT,
            TrainingDemandDraft.is_deleted.is_(False),
        )
        .values(is_deleted=True)
    )
    replaced = int(result.rowcount or 0)

    for item in output.demands:
        db.add(TrainingDemandDraft(
            year=year,
            position=item.position,
            topic=item.topic,
            suggested_hours=item.suggested_hours,
            form=item.form,
            audience=item.audience,
            basis=item.basis,
            is_statutory_gap=item.is_statutory_gap,
            status=STATUS_DRAFT,
        ))
    await db.commit()
    logger.info(
        "培训需求草案生成：year=%s 新增 %s 条（替换旧草案 %s 条，断源 %s 个）",
        year, len(output.demands), replaced, profile["disconnected"],
    )
    return {
        "year": year,
        "summary": output.summary,
        "count": len(output.demands),
        "replaced": replaced,
        "statutory_notes": output.statutory_notes,
        "sources": profile,
    }


# ═════════════════════════════ 清单与采纳/驳回 ═════════════════════════════


def _draft_to_dict(draft: TrainingDemandDraft) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "year": draft.year,
        "position": draft.position,
        "topic": draft.topic,
        "suggested_hours": draft.suggested_hours,
        "form": draft.form,
        "audience": draft.audience,
        "basis": draft.basis,
        "is_statutory_gap": draft.is_statutory_gap,
        "status": draft.status,
        "status_label": STATUS_LABELS.get(draft.status, draft.status),
        "adopted_record_id": draft.adopted_record_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


async def list_drafts(
    db: AsyncSession,
    *,
    year: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """草案清单（法定缺口行在前，近似提示词的优先级排序）。"""
    stmt = (
        select(TrainingDemandDraft)
        .where(TrainingDemandDraft.is_deleted.is_(False))
        .order_by(
            TrainingDemandDraft.is_statutory_gap.desc(),
            TrainingDemandDraft.created_at,
            TrainingDemandDraft.id,
        )
    )
    if year is not None:
        stmt = stmt.where(TrainingDemandDraft.year == year)
    if status:
        if status not in STATUS_LABELS:
            raise DemandStateError(
                f"非法状态筛选: {status}（可选：draft/adopted/rejected）"
            )
        stmt = stmt.where(TrainingDemandDraft.status == status)
    result = await db.execute(stmt)
    return [_draft_to_dict(d) for d in result.scalars().all()]


def split_position(position: str) -> list[str]:
    """岗位串拆多选值（顿号/逗号/分号/斜杠分隔，去空去重保序）。"""
    parts: list[str] = []
    for raw in _POSITION_SPLIT_RE.split(position or ""):
        part = raw.strip()
        if part and part not in parts:
            parts.append(part)
    return parts


def build_adoption_fields(draft: TrainingDemandDraft) -> dict[str, Any]:
    """草案行 → Bitable 培训表计划行 fields（规格 §4.4 映射）。

    培训形式只写蓝本值 线下/线上/实操（坑5：单选列写未注册选项会自动扩
    选项）；AI 建议了未注册形式时不写该列，改在备注留痕供排课人参考。
    """
    fields: dict[str, Any] = {"状态": "未开始"}
    if draft.topic:
        fields["培训名称"] = draft.topic
    departments = split_position(draft.position)
    if departments:
        fields["组织部门"] = departments
    if draft.suggested_hours is not None:
        fields["培训学时"] = draft.suggested_hours
    form = draft.form if draft.form in _TRAINING_FORMS else None
    if form:
        fields["培训形式"] = form
    remark = f"依据：{draft.basis}；对象：{draft.audience}"
    if not form and draft.form:
        remark += f"；形式待定（AI建议：{draft.form}）"
    if draft.is_statutory_gap:
        remark = f"【法定缺口】{remark}"
    fields["备注"] = remark
    return fields


async def _get_live_draft(
    db: AsyncSession, draft_id: str, *, expected_status: str | None = None
) -> TrainingDemandDraft:
    try:
        object_id = uuid.UUID(draft_id)
    except ValueError as exc:
        raise DemandStateError(f"草案 id 非法: {draft_id}") from exc
    draft = await db.get(TrainingDemandDraft, object_id)
    if draft is None or draft.is_deleted:
        raise DemandStateError(f"草案不存在: {draft_id}")
    if expected_status and draft.status != expected_status:
        raise DemandStateError(
            f"草案状态为 {STATUS_LABELS.get(draft.status, draft.status)}，"
            f"仅 {STATUS_LABELS[expected_status]} 可执行本操作"
        )
    return draft


async def adopt_draft(
    db: AsyncSession,
    draft_id: str,
    *,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """采纳：先写 Bitable 培训表计划行，成功后置已采纳并回填 record_id。

    写序沿用一期「先外链后状态」：Bitable 失败→草案仍为 draft 可重试；
    Bitable 成功而 DB 失败→极小概率孤儿计划行，人工可见可删（草案仍
    draft，重试会再建一行——按名肉眼去重，接受此窗口）。
    """
    draft = await _get_live_draft(db, draft_id, expected_status=STATUS_DRAFT)
    fields = build_adoption_fields(draft)

    open_client = opener or bd_reader.resolve_client
    try:
        training_client = open_client("training_behavior", "training")
    except BitableConfigError as exc:
        raise DemandStateError(f"培训台账未接入，无法采纳: {exc}") from exc
    created = await training_client.create_record(fields=fields)
    record_id = str((created or {}).get("record_id") or "")

    draft.status = STATUS_ADOPTED
    draft.adopted_record_id = record_id or None
    await db.commit()
    logger.info("培训需求草案采纳：draft=%s → Bitable 行 %s", draft_id, record_id)
    return {"draft_id": str(draft.id), "adopted_record_id": record_id, "fields": fields}


async def reject_draft(db: AsyncSession, draft_id: str) -> dict[str, Any]:
    """驳回：draft → rejected（已采纳行不可驳回，台账行如需撤销走表上人工处理）。"""
    draft = await _get_live_draft(db, draft_id, expected_status=STATUS_DRAFT)
    draft.status = STATUS_REJECTED
    await db.commit()
    return {"draft_id": str(draft.id), "status": STATUS_REJECTED,
            "status_label": STATUS_LABELS[STATUS_REJECTED]}


__all__ = [
    "DemandStateError",
    "adopt_draft",
    "build_adoption_fields",
    "build_hazard_id_digest",
    "build_hazard_stats",
    "build_last_year_summary",
    "build_regulation_list",
    "build_violation_stats",
    "collect_five_sources",
    "generate_demand_drafts",
    "list_drafts",
    "reject_draft",
    "split_position",
    "TrainingDemandError",
]

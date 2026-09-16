"""智能中心服务（分期B）：预警规则 CRUD、异常检测引擎、补货建议。

规则先行：所有异常由确定性规则产生；LLM 仅用于解读文案（白名单校验 + 降级）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.warehouse.dashboard import (
    _material_stock_totals,
)
from app.modules.warehouse.models import (
    WarehouseAlertRecord,
    WarehouseAlertRule,
    WarehouseAlertRuleAudit,
    WarehouseMovement,
    WarehouseReplenishmentSuggestion,
    WarehouseStock,
)
from app.modules.warehouse.schemas import RuleUpdate
from app.platform.identity.models import User

CN_TZ = ZoneInfo("Asia/Shanghai")

RULE_NAMES: dict[str, str] = {
    "low_stock": "低库存预警",
    "zero_stock": "零库存预警",
    "idle": "呆滞预警",
    "expiry": "效期临期预警",
    "cover_days": "补货覆盖天数",
}

# ── 预警规则 ──


async def list_rules(db: AsyncSession) -> list[WarehouseAlertRule]:
    stmt = (
        select(WarehouseAlertRule)
        .where(WarehouseAlertRule.is_deleted.is_(False))
        .order_by(WarehouseAlertRule.rule_key)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_rule(db: AsyncSession, rule_key: str) -> WarehouseAlertRule:
    stmt = select(WarehouseAlertRule).where(
        WarehouseAlertRule.rule_key == rule_key,
        WarehouseAlertRule.is_deleted.is_(False),
    )
    rule = (await db.execute(stmt)).scalar_one_or_none()
    if rule is None:
        raise NotFoundException("预警规则", rule_key)
    return rule


async def update_rule(
    db: AsyncSession, rule_key: str, payload: RuleUpdate, user: User
) -> WarehouseAlertRule:
    rule = await get_rule(db, rule_key)
    before = {"threshold": rule.threshold, "enabled": rule.enabled}

    threshold_changed = payload.threshold is not None and payload.threshold != rule.threshold
    enabled_changed = payload.enabled is not None and payload.enabled != rule.enabled
    if not threshold_changed and not enabled_changed:
        return rule

    new_threshold = payload.threshold
    if new_threshold is not None:
        rule.threshold = new_threshold
    if enabled_changed:
        rule.enabled = bool(payload.enabled)
    rule.updated_by = user.id if user else None
    await db.flush()

    action = "disable" if enabled_changed and not rule.enabled else (
        "enable" if enabled_changed else "update"
    )
    after = {"threshold": rule.threshold, "enabled": rule.enabled}
    db.add(
        WarehouseAlertRuleAudit(
            rule_key=rule_key,
            action=action,
            before_json=before,
            after_json=after,
            operator_name=user.name if user else None,
            created_by=user.id if user else None,
        )
    )
    await db.flush()
    return rule


async def get_rule_audits(db: AsyncSession, rule_key: str, limit: int = 20) -> list[WarehouseAlertRuleAudit]:
    stmt = (
        select(WarehouseAlertRuleAudit)
        .where(WarehouseAlertRuleAudit.rule_key == rule_key)
        .order_by(WarehouseAlertRuleAudit.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_rule_threshold(db: AsyncSession, rule_key: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """读规则阈值；规则不存在或停用时回落默认值。"""
    stmt = select(WarehouseAlertRule).where(
        WarehouseAlertRule.rule_key == rule_key,
        WarehouseAlertRule.is_deleted.is_(False),
        WarehouseAlertRule.enabled.is_(True),
    )
    rule = (await db.execute(stmt)).scalar_one_or_none()
    if rule is None:
        return fallback
    merged = dict(fallback)
    merged.update(rule.threshold or {})
    return merged


# ── 异常检测引擎（Ticket 02） ──

ALERT_LEVEL_DEFAULT = "warning"


async def _rule_enabled(db: AsyncSession, rule_key: str) -> bool:
    stmt = select(WarehouseAlertRule.enabled).where(
        WarehouseAlertRule.rule_key == rule_key,
        WarehouseAlertRule.is_deleted.is_(False),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    return True if row is None else bool(row)


async def detect_low_stock(db: AsyncSession) -> list[dict[str, Any]]:
    return [
        {
            "material_id": mid,
            "material_code": row["code"],
            "material_name": row["name"],
            "detail": {
                "total_quantity": row["total_quantity"],
                "safety_stock": float(row["safety_stock"]),
            },
        }
        for mid, row in (await _material_stock_totals(db)).items()
        if row["safety_stock"]
        and row["safety_stock"] > 0
        and row["total_quantity"] < float(row["safety_stock"])
    ]


async def detect_zero_stock(db: AsyncSession) -> list[dict[str, Any]]:
    totals = await _material_stock_totals(db)
    return [
        {
            "material_id": mid,
            "material_code": row["code"],
            "material_name": row["name"],
            "detail": {"total_quantity": 0},
        }
        for mid, row in totals.items()
        if row["total_quantity"] == 0
    ]


async def _last_inbound_map(db: AsyncSession) -> dict[UUID, datetime]:
    stmt = (
        select(
            WarehouseMovement.material_id,
            func.max(WarehouseMovement.occurred_at).label("last_inbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "inbound",
        )
        .group_by(WarehouseMovement.material_id)
    )
    return {r.material_id: r.last_inbound for r in (await db.execute(stmt)).all()}


async def find_idle_materials(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    """呆滞：有库存且最近一次入库（无入库记录取物料创建时间）距今 >= days。"""
    totals = await _material_stock_totals(db)
    last_in = await _last_inbound_map(db)
    now = datetime.now(CN_TZ)
    result = []
    for mid, row in totals.items():
        if row["total_quantity"] <= 0:
            continue
        last = last_in.get(mid) or row["created_at"]
        if last is None:
            continue
        last_aware = last if last.tzinfo else last.replace(tzinfo=CN_TZ)
        idle_days = (now - last_aware.astimezone(CN_TZ)).days
        if idle_days >= days:
            result.append(
                {
                    "material_id": mid,
                    "material_code": row["code"],
                    "material_name": row["name"],
                    "detail": {"total_quantity": row["total_quantity"], "days_idle": idle_days},
                }
            )
    result.sort(key=lambda x: x["detail"]["days_idle"], reverse=True)
    return result


async def detect_expiry(db: AsyncSession, days: int) -> list[dict[str, Any]]:
    """临期批次：效期非空且距今 <= days，仍有库存。"""
    deadline = (datetime.now(CN_TZ) + timedelta(days=days)).date()
    stmt = (
        select(WarehouseStock)
        .where(
            WarehouseStock.is_deleted == False,  # noqa: E712
            WarehouseStock.quantity > 0,
            WarehouseStock.expiry_date.is_not(None),
            WarehouseStock.expiry_date <= deadline,
        )
        .order_by(WarehouseStock.expiry_date)
    )
    rows = (await db.execute(stmt)).scalars().all()
    result: list[dict[str, Any]] = []
    today = datetime.now(CN_TZ).date()
    for s in rows:
        if s.expiry_date is None:
            continue
        result.append(
            {
                "material_id": s.material_id,
                "material_code": s.material_code,
                "material_name": s.material_name,
                "batch_no": s.batch_no,
                "location_id": s.location_id,
                "location_code": s.location_code,
                "location_name": s.location_name,
                "detail": {
                    "expiry_date": s.expiry_date.isoformat(),
                    "quantity": float(s.quantity),
                    "days_left": (s.expiry_date - today).days,
                },
            }
        )
    return result


async def apply_alert_records(
    db: AsyncSession, rule_key: str, records: list[dict[str, Any]]
) -> int:
    """幂等写入 open 异常。

    - open 记录：刷新 detail/level；条件消除的自动解决（系统解决）
    - 手动解决的键（resolved_by 非空）：条件仍在也不复活
    - 系统自动解决的键：条件再现时重开
    """
    all_stmt = select(WarehouseAlertRecord).where(
        WarehouseAlertRecord.rule_key == rule_key,
        WarehouseAlertRecord.is_deleted == False,  # noqa: E712
    )
    all_rows = (await db.execute(all_stmt)).scalars().all()
    open_map = {(r.material_id, r.batch_no): r for r in all_rows if r.status == "open"}
    manual_resolved = {
        (r.material_id, r.batch_no)
        for r in all_rows
        if r.status == "resolved" and r.resolved_by is not None
    }
    auto_resolved_map = {
        (r.material_id, r.batch_no): r
        for r in all_rows
        if r.status == "resolved" and r.resolved_by is None
    }

    incoming_keys: set[tuple[UUID, str]] = set()
    for rec in records:
        key = (rec["material_id"], rec.get("batch_no", ""))
        incoming_keys.add(key)
        if key in manual_resolved:
            continue  # 管理员已处理，不复活
        row = open_map.get(key) or auto_resolved_map.get(key)
        if row is not None:
            row.status = "open"
            row.detail = rec["detail"]
            row.level = rec.get("level", ALERT_LEVEL_DEFAULT)
        else:
            db.add(
                WarehouseAlertRecord(
                    rule_key=rule_key,
                    level=rec.get("level", ALERT_LEVEL_DEFAULT),
                    status="open",
                    material_id=rec["material_id"],
                    material_code=rec["material_code"],
                    material_name=rec["material_name"],
                    batch_no=rec.get("batch_no", ""),
                    location_id=rec.get("location_id"),
                    location_code=rec.get("location_code"),
                    location_name=rec.get("location_name"),
                    detail=rec["detail"],
                )
            )
    now = datetime.now(CN_TZ)
    for key, row in open_map.items():
        if key not in incoming_keys:
            row.status = "resolved"
            row.resolved_at = now  # 系统解决，resolved_by 留空
    await db.flush()
    return len(records)


async def run_alert_scan(db: AsyncSession) -> dict[str, int]:
    """执行一次全量异常扫描（调用方负责提交事务）。"""
    counts: dict[str, int] = {}
    if await _rule_enabled(db, "low_stock"):
        counts["low_stock"] = await apply_alert_records(
            db, "low_stock", await detect_low_stock(db)
        )
    if await _rule_enabled(db, "zero_stock"):
        counts["zero_stock"] = await apply_alert_records(
            db, "zero_stock", await detect_zero_stock(db)
        )
    idle_days = int((await get_rule_threshold(db, "idle", {"days": 90}))["days"])
    if await _rule_enabled(db, "idle"):
        counts["idle"] = await apply_alert_records(
            db, "idle", await find_idle_materials(db, idle_days)
        )
    expiry_days = int((await get_rule_threshold(db, "expiry", {"days": 30}))["days"])
    if await _rule_enabled(db, "expiry"):
        counts["expiry"] = await apply_alert_records(
            db, "expiry", await detect_expiry(db, expiry_days)
        )
    return counts


async def run_intelligence_scan(db: AsyncSession) -> dict[str, int]:
    """手动/定时扫描统一入口：异常扫描 + 补货建议刷新。"""
    counts = await run_alert_scan(db)
    counts["replenishment_pending"] = await refresh_replenishment_suggestions(db)
    return counts


async def list_alert_records(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    rule_key: str | None = None,
    status: str | None = None,
) -> tuple[list[WarehouseAlertRecord], int]:
    stmt = select(WarehouseAlertRecord).where(
        WarehouseAlertRecord.is_deleted == False  # noqa: E712
    )
    if rule_key:
        stmt = stmt.where(WarehouseAlertRecord.rule_key == rule_key)
    if status:
        stmt = stmt.where(WarehouseAlertRecord.status == status)
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = (
        stmt.order_by(WarehouseAlertRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


async def resolve_alert_record(
    db: AsyncSession, record_id: UUID, user: User
) -> WarehouseAlertRecord:
    stmt = select(WarehouseAlertRecord).where(
        WarehouseAlertRecord.id == record_id,
        WarehouseAlertRecord.is_deleted == False,  # noqa: E712
    )
    record = (await db.execute(stmt)).scalar_one_or_none()
    if record is None or record.status != "open":
        raise NotFoundException("异常记录", str(record_id))
    record.status = "resolved"
    record.resolved_by = user.id if user else None
    record.resolved_at = datetime.now(CN_TZ)
    await db.flush()
    return record


async def _llm_summarize(prompt: str) -> str:
    """调用仓储 Agent LLM 网关生成解读（复用既有客户端与配置）。"""
    from app.modules.warehouse.agent.llm_client import get_llm_client

    client = get_llm_client()
    data = await client._post_chat(  # noqa: SLF001 — 同包内部复用
        {
            "model": client.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
    )
    return str(data["choices"][0]["message"]["content"])


async def get_alert_summary(db: AsyncSession, rule_key: str) -> dict[str, Any]:
    """某类异常的解读：优先 LLM，失败降级规则模板文案。"""
    name = RULE_NAMES.get(rule_key, rule_key)
    stmt = (
        select(WarehouseAlertRecord)
        .where(
            WarehouseAlertRecord.rule_key == rule_key,
            WarehouseAlertRecord.status == "open",
            WarehouseAlertRecord.is_deleted == False,  # noqa: E712
        )
        .order_by(WarehouseAlertRecord.created_at.desc())
        .limit(5)
    )
    items = list((await db.execute(stmt)).scalars().all())
    count_stmt = (
        select(func.count())
        .select_from(WarehouseAlertRecord)
        .where(
            WarehouseAlertRecord.rule_key == rule_key,
            WarehouseAlertRecord.status == "open",
            WarehouseAlertRecord.is_deleted == False,  # noqa: E712
        )
    )
    total = int((await db.execute(count_stmt)).scalar_one())
    items_desc = "；".join(
        f"{r.material_name}({(r.detail or {}).get('total_quantity', (r.detail or {}).get('days_left', '-'))})"
        for r in items
    )
    fallback = f"{name}：当前共 {total} 项未处理。{items_desc}"

    try:
        raw = await _llm_summarize(
            f"以下是仓储系统中「{name}」类异常的统计：共 {total} 项。"
            f"明细：{items_desc or '无'}。请用不超过 80 字的中文概括当前风险并给出一句话建议。"
        )
        return {
            "rule_key": rule_key,
            "text": raw.strip()[:300],
            "source": "llm",
            "open_count": total,
        }
    except Exception:  # noqa: BLE001 — LLM 故障降级为规则文案，永不抛出
        return {
            "rule_key": rule_key,
            "text": fallback,
            "source": "fallback",
            "open_count": total,
        }


# ── 补货建议引擎（Ticket 03） ──

REPLENISHMENT_WINDOW_DAYS = 30


async def refresh_replenishment_suggestions(db: AsyncSession) -> int:
    """按近 30 天出库消耗刷新补货建议。

    - pending 行：数值刷新；建议量 <= 0 的移除（软删）
    - handled/ignored 行：不覆盖
    - 新出现消耗的物料：插入 pending（建议量 > 0 才建）
    返回 pending 建议数。
    """
    cover_days = int((await get_rule_threshold(db, "cover_days", {"days": 14}))["days"])
    since = datetime.now(CN_TZ) - timedelta(days=REPLENISHMENT_WINDOW_DAYS)

    out_stmt = (
        select(
            WarehouseMovement.material_id,
            func.sum(WarehouseMovement.quantity).label("outbound"),
        )
        .where(
            WarehouseMovement.is_deleted == False,  # noqa: E712
            WarehouseMovement.direction == "outbound",
            WarehouseMovement.occurred_at >= since,
        )
        .group_by(WarehouseMovement.material_id)
    )
    outbound_map = {
        r.material_id: Decimal(str(r.outbound))
        for r in (await db.execute(out_stmt)).all()
    }

    totals = await _material_stock_totals(db)
    existing_stmt = select(WarehouseReplenishmentSuggestion).where(
        WarehouseReplenishmentSuggestion.is_deleted == False,  # noqa: E712
    )
    existing = {
        s.material_id: s for s in (await db.execute(existing_stmt)).scalars().all()
    }

    pending_count = 0
    for mid, row in totals.items():
        outbound = outbound_map.get(mid)
        if outbound is None or outbound <= 0:
            continue  # 无消耗 → 归呆滞口径，不生成建议
        avg_daily = (outbound / Decimal(REPLENISHMENT_WINDOW_DAYS)).quantize(
            Decimal("0.0001")
        )
        current = Decimal(str(row["total_quantity"]))
        days_cover = (
            (current / avg_daily).quantize(Decimal("0.01")) if avg_daily > 0 else None
        )
        suggested = max(
            Decimal("0"), (Decimal(cover_days) * avg_daily - current)
        ).quantize(Decimal("0.0001"))

        suggestion = existing.get(mid)
        if suggestion is None:
            if suggested <= 0:
                continue
            db.add(
                WarehouseReplenishmentSuggestion(
                    material_id=mid,
                    material_code=row["code"],
                    material_name=row["name"],
                    avg_daily_outbound=avg_daily,
                    days_cover=days_cover,
                    suggested_qty=suggested,
                    status="pending",
                )
            )
            pending_count += 1
        elif suggestion.status == "pending":
            if suggested <= 0:
                suggestion.is_deleted = True
                continue
            suggestion.avg_daily_outbound = avg_daily
            suggestion.days_cover = days_cover
            suggestion.suggested_qty = suggested
            pending_count += 1
        # handled/ignored：不覆盖
    return pending_count


async def list_replenishment_suggestions(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[WarehouseReplenishmentSuggestion], int]:
    stmt = select(WarehouseReplenishmentSuggestion).where(
        WarehouseReplenishmentSuggestion.is_deleted == False  # noqa: E712
    )
    if status:
        stmt = stmt.where(WarehouseReplenishmentSuggestion.status == status)
    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    stmt = (
        stmt.order_by(WarehouseReplenishmentSuggestion.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


async def set_suggestion_status(
    db: AsyncSession, suggestion_id: UUID, status: str, user: User
) -> WarehouseReplenishmentSuggestion:

    stmt = select(WarehouseReplenishmentSuggestion).where(
        WarehouseReplenishmentSuggestion.id == suggestion_id,
        WarehouseReplenishmentSuggestion.is_deleted == False,  # noqa: E712
    )
    suggestion = (await db.execute(stmt)).scalar_one_or_none()
    if suggestion is None:
        raise NotFoundException("补货建议", str(suggestion_id))
    if suggestion.status != "pending":
        raise AppException(
            status_code=400,
            message=f"仅待处理建议可流转，当前状态: {suggestion.status}",
        )
    suggestion.status = status
    suggestion.handled_by = user.id if user else None
    suggestion.handled_at = datetime.now(CN_TZ)
    await db.flush()
    return suggestion

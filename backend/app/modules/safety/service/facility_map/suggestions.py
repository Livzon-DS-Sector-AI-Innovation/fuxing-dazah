"""#2 地点→分区 AI 建议映射：批任务（收集→AI→落建议表）+ 确认流。

数据流（DESIGN v3 §12.1）：
    收集（复用 pins service 逐日聚合 unmapped，天然已减映射命中）
      → 减已映射（location_district_map，防收集后新灌）与已有建议行
        （pending/confirmed/ignored 任一存在即跳过——同文本不重复调 AI）
      → 20 条/批调 facility_map_suggest（temp 0.1）→ 全批落 pending 建议
      → 确认流：单条确认（写映射表 source='ai_confirmed'）/单条忽略/
        批量确认 high——映射资产只增不改，人工门在 API 侧。

接缝：pins_service（收集替身）与 ai_service（chat_parsed 替身）构造注入；
服务内 commit（生产口径），测试用隔离文本前缀+显式清行。
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_facility_map import (
    FacilityMapSuggestError,
    FacilityMapSuggestPlugin,
)
from app.modules.safety.models.location_district_map import LocationDistrictMap
from app.modules.safety.models.location_district_suggestion import (
    LocationDistrictSuggestion,
)
from app.modules.safety.service.facility_map.district_names import (
    DISTRICT_NAME_BY_ID,
)
from app.modules.safety.service.facility_map.service import (
    FacilityMapPinsService,
    bj_today,
    open_pins_service,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BATCH_SIZE",
    "DEFAULT_SCAN_DAYS",
    "SuggestionStateError",
    "collect_unmapped_texts",
    "confirm_high_confidence",
    "confirm_suggestion",
    "ignore_suggestion",
    "list_suggestions",
    "run_suggestion_scan",
]

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_IGNORED = "ignored"

BATCH_SIZE = 20
DEFAULT_SCAN_DAYS = 30


class SuggestionStateError(ValueError):
    """确认流前置条件不满足（行不存在/状态非 pending/无分区建议）。"""


# ═══════════════════════════ 收集（纯编排，替身注入） ═══════════════════════════


async def collect_unmapped_texts(
    *,
    days: int = DEFAULT_SCAN_DAYS,
    pins_service: FacilityMapPinsService | None = None,
    session: Any = None,
) -> dict[str, dict[str, Any]]:
    """近 N 天三源 unmapped 聚合：text → {count, kinds:set}。

    pins 的 unmapped 已按归一文本去重并减映射命中（mapping.py 两级匹配），
    这里只做跨日累计与 kinds 并集。
    """
    svc = pins_service if pins_service is not None else open_pins_service(session=session)
    today = bj_today()
    agg: dict[str, dict[str, Any]] = {}
    for offset in range(days - 1, -1, -1):
        payload = await svc.get_pins(today - timedelta(days=offset))
        for u in payload.get("unmapped") or []:
            entry = agg.setdefault(u["text"], {"count": 0, "kinds": set()})
            entry["count"] += int(u.get("count") or 0)
            entry["kinds"].update(u.get("kinds") or [])
    return agg


async def run_suggestion_scan(
    db: AsyncSession,
    *,
    days: int = DEFAULT_SCAN_DAYS,
    ai_service: Any = None,
    pins_service: FacilityMapPinsService | None = None,
) -> dict[str, Any]:
    """手动批处理入口：收集 → 过滤 → AI 分批 → 建议 pending 落表（一次 commit）。"""
    agg = await collect_unmapped_texts(days=days, pins_service=pins_service, session=db)

    map_texts = {
        text for (text,) in await db.execute(
            select(LocationDistrictMap.location_text).where(
                LocationDistrictMap.is_deleted.is_(False)
            )
        )
    }
    sugg_rows = await db.execute(
        select(
            LocationDistrictSuggestion.location_text,
            LocationDistrictSuggestion.status,
        ).where(LocationDistrictSuggestion.is_deleted.is_(False))
    )
    sugg_texts = {text for text, _ in sugg_rows.all()}

    candidates = sorted(
        (
            (text, v)
            for text, v in agg.items()
            if text not in map_texts and text not in sugg_texts
        ),
        key=lambda kv: (-kv[1]["count"], kv[0]),
    )

    if not candidates:
        return {
            "days": days,
            "unmapped_texts": len(agg),
            "candidates": 0,
            "batches": 0,
            "suggested": 0,
            "no_judgement": 0,
            "batch_id": None,
        }

    if ai_service is None:
        from app.modules.safety.service.config import create_ai_service

        ai_service = create_ai_service("text")
    plugin = FacilityMapSuggestPlugin(ai_service)

    from app.modules.safety.ai_audit import ai_audit_scope

    batch_id = uuid.uuid4().hex[:12]
    items = [(text, v["count"]) for text, v in candidates]
    rows: list[LocationDistrictSuggestion] = []
    no_judgement = 0
    with ai_audit_scope(
        scenario="facility_map_suggest",
        channel="system",
        extra={"entry": "suggestion_scan", "days": days, "candidates": len(items)},
    ):
        for start in range(0, len(items), BATCH_SIZE):
            chunk = items[start : start + BATCH_SIZE]
            suggestions = await plugin.suggest(chunk)
            by_text = {s.text: s for s in suggestions}
            for text, count in chunk:
                s = by_text.get(text)
                dist_id = s.dist_id if s else None
                if dist_id is None:
                    no_judgement += 1
                rows.append(LocationDistrictSuggestion(
                    location_text=text,
                    count=count,
                    kinds=sorted(agg[text]["kinds"]),
                    dist_id=dist_id,
                    confidence=s.confidence if s else "low",
                    reason=(
                        s.reason if s else "AI 未返回该条（按无法判断落 low）"
                    ),
                    batch_id=batch_id,
                    status=STATUS_PENDING,
                ))
    for row in rows:
        db.add(row)
    await db.commit()
    logger.info(
        "地点→分区建议扫描：近 %d 天 unmapped %d 文本，候选 %d，AI 建议 %d 条"
        "（无判断 %d），批次 %s",
        days, len(agg), len(items), len(rows), no_judgement, batch_id,
    )
    return {
        "days": days,
        "unmapped_texts": len(agg),
        "candidates": len(items),
        "batches": (len(items) + BATCH_SIZE - 1) // BATCH_SIZE,
        "suggested": len(rows),
        "no_judgement": no_judgement,
        "batch_id": batch_id,
    }


# ═══════════════════════════ 清单与确认流 ═══════════════════════════


def _suggestion_to_dict(row: LocationDistrictSuggestion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "location_text": row.location_text,
        "count": row.count,
        "kinds": row.kinds or [],
        "dist_id": row.dist_id,
        "dist_name": (
            DISTRICT_NAME_BY_ID.get(row.dist_id or "") if row.dist_id else None
        ),
        "confidence": row.confidence,
        "reason": row.reason,
        "batch_id": row.batch_id,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_suggestions(
    db: AsyncSession, *, status: str | None = None
) -> list[dict[str, Any]]:
    """建议清单（缺省 pending=确认页工作集；次数降序）。"""
    query = select(LocationDistrictSuggestion).where(
        LocationDistrictSuggestion.is_deleted.is_(False)
    )
    if status:
        query = query.where(LocationDistrictSuggestion.status == status)
    rows = (
        await db.execute(
            query.order_by(
                LocationDistrictSuggestion.count.desc(),
                LocationDistrictSuggestion.created_at,
            )
        )
    ).scalars().all()
    return [_suggestion_to_dict(r) for r in rows]


async def _get_pending(db: AsyncSession, suggestion_id: str) -> LocationDistrictSuggestion:
    row = (
        await db.execute(
            select(LocationDistrictSuggestion).where(
                LocationDistrictSuggestion.id == uuid.UUID(suggestion_id),
                LocationDistrictSuggestion.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise SuggestionStateError(f"建议不存在: {suggestion_id}")
    if row.status != STATUS_PENDING:
        raise SuggestionStateError(
            f"建议状态为 {row.status}，仅 pending 可操作"
        )
    return row


async def _upsert_map_row(
    db: AsyncSession, *, location_text: str, dist_id: str
) -> bool:
    """写映射资产（source='ai_confirmed'）；同文本已有活行则保留不动。

    返回是否新建（False=人工先行补过映射，仅置建议 confirmed）。
    """
    existing = (
        await db.execute(
            select(LocationDistrictMap.id).where(
                LocationDistrictMap.location_text == location_text,
                LocationDistrictMap.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(LocationDistrictMap(
        location_text=location_text, dist_id=dist_id, source="ai_confirmed"
    ))
    return True


async def confirm_suggestion(
    db: AsyncSession, suggestion_id: str
) -> dict[str, Any]:
    """单条确认：pending → 写 location_district_map（ai_confirmed）→ confirmed。"""
    row = await _get_pending(db, suggestion_id)
    if not row.dist_id:
        raise SuggestionStateError(
            "该条无分区建议（AI 未判断），请忽略；如需映射请在种子表人工补录"
        )
    map_created = await _upsert_map_row(
        db, location_text=row.location_text, dist_id=row.dist_id
    )
    row.status = STATUS_CONFIRMED
    await db.commit()
    logger.info(
        "地点建议确认：%s → 分区 %s（%s）",
        row.location_text, row.dist_id,
        "新建映射" if map_created else "映射已存在，保留",
    )
    return {
        "id": str(row.id),
        "location_text": row.location_text,
        "dist_id": row.dist_id,
        "dist_name": DISTRICT_NAME_BY_ID.get(row.dist_id),
        "map_created": map_created,
    }


async def ignore_suggestion(
    db: AsyncSession, suggestion_id: str
) -> dict[str, Any]:
    """单条忽略：pending → ignored（下轮收集排除，永不再建议）。"""
    row = await _get_pending(db, suggestion_id)
    row.status = STATUS_IGNORED
    await db.commit()
    return {"id": str(row.id), "status": STATUS_IGNORED}


async def confirm_high_confidence(db: AsyncSession) -> dict[str, Any]:
    """批量确认全部 high 且有分区建议的 pending 行。"""
    rows = (
        await db.execute(
            select(LocationDistrictSuggestion).where(
                LocationDistrictSuggestion.is_deleted.is_(False),
                LocationDistrictSuggestion.status == STATUS_PENDING,
                LocationDistrictSuggestion.confidence == "high",
                LocationDistrictSuggestion.dist_id.is_not(None),
            )
        )
    ).scalars().all()
    confirmed = 0
    map_created = 0
    for row in rows:
        created = await _upsert_map_row(
            db, location_text=row.location_text, dist_id=row.dist_id or ""
        )
        row.status = STATUS_CONFIRMED
        confirmed += 1
        map_created += int(created)
    await db.commit()
    logger.info("地点建议批量确认 high：%d 条（新建映射 %d）", confirmed, map_created)
    return {"confirmed": confirmed, "map_created": map_created}

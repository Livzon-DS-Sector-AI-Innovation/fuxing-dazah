"""#4 岗位 AI 归一：批量归类（org_directory→九族）+ 人工确认/修正 + 族聚合。

数据流（DESIGN v3 §13.2，与 §12 同构但资产即中间表——org_post_families
既是 AI 归类落点也是确认后资产）：
    手动批量触发 → org_directory 唯一 postName（日级缓存载荷）
      → 候选=无行或有 ai 行（manual 行跳过，重跑不覆盖）
      → org_post_classify 分批（30/批）→ ai 行 upsert（新插/旧行覆盖族）
      → 确认页：按 AI 值确认（ai→manual）或改族后确认（→manual）
    消费：org-posts 响应挂 families 聚合（族×人数）；query_org_posts family 参数。

接缝：org_client 替身（list_org_users）与 ai_service 替身（chat_parsed）
构造注入；服务内 commit（生产口径），测试用隔离前缀+显式清行。
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_org_post_classify import (
    OrgPostClassifyPlugin,
)
from app.modules.safety.models.org_post_families import (
    POST_FAMILIES,
    SOURCE_AI,
    SOURCE_MANUAL,
    OrgPostFamily,
)
from app.modules.safety.service.org_directory import build_post_rows

logger = logging.getLogger(__name__)

__all__ = [
    "BATCH_SIZE",
    "FamilyStateError",
    "build_family_aggregation",
    "confirm_family",
    "family_map_for_posts",
    "list_families",
    "run_classify",
    "update_family",
]

BATCH_SIZE = 30


class FamilyStateError(ValueError):
    """确认/修正前置条件不满足（行不存在/族不在枚举）。"""


# ═══════════════════════════ 批量归类 ═══════════════════════════


async def run_classify(
    db: AsyncSession,
    *,
    org_client: Any = None,
    ai_service: Any = None,
) -> dict[str, Any]:
    """手动批处理入口：岗位字典 → AI 分批归类 → ai 行 upsert（一次 commit）。"""
    if org_client is None:
        from app.modules.safety.service.org_directory import _real_client

        org_client = _real_client()
    users = await org_client.list_org_users()
    posts = build_post_rows(users)  # [{post_name, dept_names, headcount}]
    post_names = [p["post_name"] for p in posts]

    existing = {
        row.post_name: row
        for row in (
            await db.execute(
                select(OrgPostFamily).where(OrgPostFamily.is_deleted.is_(False))
            )
        ).scalars().all()
    }
    # manual 行不覆盖；新岗位与 ai 行进候选
    candidates = [n for n in post_names if n not in existing or existing[n].source == SOURCE_AI]

    by_family: Counter[str] = Counter()
    inserted = updated = 0
    if candidates:
        if ai_service is None:
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")
        plugin = OrgPostClassifyPlugin(ai_service)

        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="org_post_classify",
            channel="system",
            extra={"entry": "org_post_classify", "candidates": len(candidates)},
        ):
            for start in range(0, len(candidates), BATCH_SIZE):
                chunk = candidates[start : start + BATCH_SIZE]
                items = await plugin.classify(chunk)
                by_name = {i.post_name: i for i in items}
                for name in chunk:
                    item = by_name.get(name)
                    if item is None:
                        continue  # AI 未返回（幻觉/截断）：新岗位不落行，ai 旧行保留
                    by_family[item.family] += 1
                    row = existing.get(name)
                    if row is None:
                        db.add(OrgPostFamily(
                            post_name=name,
                            family=item.family,
                            confidence=item.confidence,
                            note=item.note,
                            source=SOURCE_AI,
                        ))
                        inserted += 1
                    else:
                        row.family = item.family
                        row.confidence = item.confidence
                        row.note = item.note
                        updated += 1
        await db.commit()
    logger.info(
        "岗位族归类：字典 %d 岗，候选 %d，AI 归类 %d（新插 %d/覆盖 %d），manual 保留 %d",
        len(post_names), len(candidates), inserted + updated, inserted, updated,
        sum(1 for r in existing.values() if r.source == SOURCE_MANUAL),
    )
    return {
        "posts_total": len(post_names),
        "candidates": len(candidates),
        "batches": (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE if candidates else 0,
        "classified": inserted + updated,
        "inserted": inserted,
        "updated": updated,
        "manual_kept": sum(1 for r in existing.values() if r.source == SOURCE_MANUAL),
        "by_family": dict(by_family),
    }


# ═══════════════════════════ 清单与确认/修正 ═══════════════════════════


def _row_to_dict(row: OrgPostFamily) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "post_name": row.post_name,
        "family": row.family,
        "confidence": row.confidence,
        "note": row.note,
        "source": row.source,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_families(
    db: AsyncSession, *, source: str | None = None
) -> list[dict[str, Any]]:
    """归类清单（缺省全部；source='ai'=确认页工作集，updated_at 降序）。"""
    query = select(OrgPostFamily).where(OrgPostFamily.is_deleted.is_(False))
    if source:
        query = query.where(OrgPostFamily.source == source)
    rows = (
        (await db.execute(query.order_by(OrgPostFamily.updated_at.desc())))
        .scalars()
        .all()
    )
    return [_row_to_dict(r) for r in rows]


async def _get_row(db: AsyncSession, row_id: str) -> OrgPostFamily:
    row = (
        await db.execute(
            select(OrgPostFamily).where(
                OrgPostFamily.id == _uuid(row_id),
                OrgPostFamily.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise FamilyStateError(f"归类行不存在: {row_id}")
    return row


def _uuid(value: str):
    import uuid

    return uuid.UUID(value)


async def confirm_family(db: AsyncSession, row_id: str) -> dict[str, Any]:
    """按 AI 值确认：ai → manual（族不变，note 保留 AI 判断依据）。"""
    row = await _get_row(db, row_id)
    if row.source != SOURCE_AI:
        raise FamilyStateError(f"该行已是 manual（{row.family}），无需确认")
    row.source = SOURCE_MANUAL
    data = _row_to_dict(row)  # commit 前取值（async 会话 commit 后属性过期触发懒加载）
    await db.commit()
    return data


async def update_family(
    db: AsyncSession, row_id: str, *, family: str, note: str | None = None
) -> dict[str, Any]:
    """人工改族：family 必须在九族枚举；改后置 manual（重跑不覆盖）。"""
    if family not in POST_FAMILIES:
        raise FamilyStateError(
            f"非法岗位族: {family}（可选 {'/'.join(POST_FAMILIES)}）"
        )
    row = await _get_row(db, row_id)
    row.family = family
    if note is not None:
        row.note = note[:512]
    if row.source != SOURCE_MANUAL:
        row.note = f"人工修正（原 AI 归类保留于历史）：{row.note}"[:512]
    row.source = SOURCE_MANUAL
    data = _row_to_dict(row)  # 同上：commit 前取值
    await db.commit()
    return data


# ═══════════════════════════ 族聚合（消费方） ═══════════════════════════


async def family_map_for_posts(db: AsyncSession) -> dict[str, str]:
    """post_name → family（org-posts 聚合与 Agent 工具共用）。"""
    rows = (
        await db.execute(
            select(
                OrgPostFamily.post_name, OrgPostFamily.family
            ).where(OrgPostFamily.is_deleted.is_(False))
        )
    ).all()
    return {name: family for name, family in rows}


def build_family_aggregation(
    posts: list[dict[str, Any]], family_map: dict[str, str]
) -> list[dict[str, Any]]:
    """岗位字典行 × 族映射 → 族×人数聚合（未归类单列「未归类」）。"""
    agg: Counter[str] = Counter()
    for post in posts:
        family = family_map.get(post["post_name"], "未归类")
        agg[family] += int(post.get("headcount") or 0)
    return [
        {"family": family, "headcount": headcount}
        for family, headcount in sorted(
            agg.items(), key=lambda kv: (-kv[1], kv[0])
        )
    ]

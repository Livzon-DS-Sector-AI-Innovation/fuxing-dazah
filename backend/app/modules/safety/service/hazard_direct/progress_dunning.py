"""⑤ 未更新进展催办（周三 10:00）— 直读多维表格。

改造前：读 DB 的 ``supervision_progress_status`` 标记（由通报任务写入）→ 发卡。
改造后：从多维表格现算（``progress_track.compute_marks``，Redis 跟踪进展内容变化时间）→ 发卡。
卡片内「提交进展」仍直接回写多维表格（``progress_card.push_progress_note_to_bitable``）。

发送对象分类型：``ou_``（个人）= 一卡一隐患 DM 私发；``oc_``（群聊）= 群卡片。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.hazard_direct import (
    bitable_repo,
    bulletin,
    progress_track,
)

logger = logging.getLogger(__name__)

# 部门字段多值分隔符（一格填多个部门，如「设备工程部, 项目部」）
_DEPT_SPLIT = re.compile(r"[,，、;；/|]+")


async def _fetch_dunning_targets(client: Any) -> list[bitable_repo.HazardView]:
    """取候选：督办中（红色/一般预警）且未关闭、非整改中的记录。"""
    records = await bulletin._fetch_targets(client)  # noqa: SLF001 — 同包内复用过滤条件
    views: list[bitable_repo.HazardView] = []
    for rec in records:
        view = bitable_repo.to_view(rec)
        if view.rectification_status in ("closed", "in_progress"):
            continue
        if (view.department or "") in bulletin.EXCLUDED_DEPARTMENTS:
            continue
        if bitable_repo.is_audit_record(view.raw):
            continue  # 外审记录不跟进（当前主表不含，防御性过滤）
        desc = (view.description or "").strip()
        if not desc or desc == "待AI填写":
            continue
        views.append(view)
    return views


async def find_dunning_hazards() -> list[bitable_repo.HazardView]:
    """返回当前应催办的隐患（已标记「未更新进展」）。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    client = SafetyBitableClient()
    views = await _fetch_dunning_targets(client)
    if not views:
        return []
    marks = await progress_track.compute_marks(views)
    out: list[bitable_repo.HazardView] = []
    for view in views:
        status = marks.get(view.record_id)
        view.supervision_progress_status = status
        if status == progress_track.PROGRESS_STATUS_NOT_UPDATED:
            out.append(view)
    # 最旧的排前面（与旧实现一致）
    out.sort(key=lambda v: v.discovered_at or datetime.max.replace(tzinfo=UTC))
    return out


async def _resolve_officers(resolver: Any, department: str) -> list[Any]:
    """责任部门 → 分管安全员（可多个）。

    部门字段可能一格填了多个部门（如「设备工程部, 项目部」），此时逐个拆分尝试，
    把所有能映射到安全员的部门都收进来（按人去重）。
    """
    dept = (department or "").strip()
    if not dept:
        return []

    async def _one(name: str) -> Any:
        try:
            return await resolver.resolve_safety_officer(name)
        except Exception:
            logger.warning("分管安全员解析失败: dept=%s", name, exc_info=True)
            return None

    person = await _one(dept)
    if person:
        return [person]

    parts = [p.strip() for p in _DEPT_SPLIT.split(dept) if p.strip() and p.strip() != dept]
    out: list[Any] = []
    seen: set[str] = set()
    for part in parts:
        p = await _one(part)
        if p is None:
            continue
        key = p.user_id or p.open_id
        if key and key in seen:
            continue
        seen.add(key)
        out.append(p)
    if out:
        logger.info(
            "部门字段含多个部门，已拆分解析安全员: %r → %s",
            dept, [p.name for p in out],
        )
    return out


async def resolve_dunning_recipients(
    views: list[bitable_repo.HazardView],
) -> list[tuple[bitable_repo.HazardView, str, Any]]:
    """每条隐患 → [(view, 角色, ResolvedPerson)]，角色 ∈ {责任人, 分管安全员}。

    复用 ``IdentityResolver``（与隐患整改通知同一条解析链）：
      · 责任人   ← effective_responsible_person(dept, 整改责任人) → resolve_by_name
      · 分管安全员 ← resolve_safety_officer(dept)（按部门映射 DEPT_CONFIG 固定名单；
                     部门字段含多部门时逐个拆分，见 ``_resolve_officers``）

    去重规则：同一隐患同一人只保留一次；解析不到的人跳过（记 warning）。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.identity_resolver import IdentityResolver
    from app.modules.safety.service.responsible_mapping import (
        effective_responsible_person,
    )

    out: list[tuple[bitable_repo.HazardView, str, Any]] = []
    async with async_session_factory() as session:
        resolver = IdentityResolver(session)
        for view in views:
            seen: set[str] = set()
            resp_name = effective_responsible_person(
                view.department, view.rectification_responsible_person_name
            )
            officers = await _resolve_officers(resolver, view.department or "")
            if not officers:
                logger.warning(
                    "⑤ 部门未配置分管安全员，仅发责任人: hazard_no=%s dept=%r",
                    view.hazard_no, view.department,
                )
            for role, person in (
                (
                    "责任人",
                    await resolver.resolve_by_name(
                        resp_name or "", department_hint=view.department
                    ),
                ),
                *(("分管安全员", p) for p in officers),
            ):
                if person is None:
                    logger.warning(
                        "⑤ 收件人解析失败: hazard_no=%s role=%s dept=%s",
                        view.hazard_no, role, view.department,
                    )
                    continue
                key = person.user_id or person.open_id
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append((view, role, person))
    return out


async def send_progress_dunning_dynamic() -> dict[str, Any]:
    """一卡一隐患，私发给每条隐患的「责任人 + 分管安全员」。"""
    from app.modules.safety.feishu.notification import send_user_card
    from app.modules.safety.feishu.progress_card import build_progress_card

    views = await find_dunning_hazards()
    stats: dict[str, Any] = {
        "total": len(views), "sent": 0, "skipped": 0, "errors": 0,
        "marked": len(views), "recipients": 0,
    }
    if not views:
        logger.info("⑤ 当前无「未更新进展」隐患，不发卡")
        return stats

    plan = await resolve_dunning_recipients(views)
    stats["recipients"] = len({(p.user_id or p.open_id) for _, _, p in plan})
    logger.info(
        "⑤ 动态收件人: 隐患=%d 收件人次=%d 去重人数=%d",
        len(views), len(plan), stats["recipients"],
    )

    # @ 提及用「安全应用作用域」open_id（跨应用修正，见 feishu/mention.py）
    from app.modules.safety.feishu import mention

    mention_ids = await mention.resolve_open_ids(p.name for _, _, p in plan)

    for view, role, person in plan:
        # open_id 按应用隔离：平台同步的 open_id 对安全应用会报 99992361 cross app，
        # 统一用租户级 user_id（identity.users.feishu_user_id）发送。
        receive_id = person.user_id or person.open_id
        id_type = "user_id" if person.user_id else "open_id"
        try:
            content, elements = build_progress_card(
                view, mention_ids.get(person.name, "")
            )
            ok = await send_user_card(
                open_id=receive_id,
                title="⏰ 督办催办 · 未更新进展",
                content=content,
                elements=elements,
                header_template="red",
                id_type=id_type,
            )
            if ok:
                stats["sent"] += 1
                logger.info(
                    "⑤ 催办卡片已发送: record_id=%s → %s(%s) id_type=%s",
                    view.record_id, person.name, role, id_type,
                )
            else:
                stats["skipped"] += 1
                logger.warning(
                    "⑤ 催办卡片发送失败: record_id=%s → %s(%s)",
                    view.record_id, person.name, role,
                )
        except Exception:
            stats["errors"] += 1
            logger.exception(
                "⑤ 催办卡片发送异常: record_id=%s → %s", view.record_id, person.name
            )

    logger.info(
        "⑤ 催办完成(动态名单): sent=%d skipped=%d errors=%d 收件人=%d",
        stats["sent"], stats["skipped"], stats["errors"], stats["recipients"],
    )
    return stats


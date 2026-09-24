"""⑤ 未更新进展催办（周三 10:00）— 直读多维表格。

改造前：读 DB 的 ``supervision_progress_status`` 标记（由通报任务写入）→ 发卡。
改造后：从多维表格现算（``progress_track.compute_marks``，Redis 跟踪进展内容变化时间）→ 发卡。
卡片内「提交进展」仍直接回写多维表格（``progress_card.push_progress_note_to_bitable``）。

发送对象分类型：``ou_``（个人）= 一卡一隐患 DM 私发；``oc_``（群聊）= 群卡片。

私发完成后，向当日「安全速递」总卡投递一个 ``progress_dunning`` 格子
（发到安全AI创新交流群），简报中注明已私发的对象与催办明细；
**0 命中时同样投递「今日无需催办」简报**（有无均报，口径对齐消防报警日报）。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
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
    views, _ = await find_dunning_overview()
    return views


async def find_dunning_overview() -> tuple[list[bitable_repo.HazardView], int]:
    """返回 (应催办隐患, 参与评估的督办候选数)，供速递报告引用。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    client = SafetyBitableClient()
    views = await _fetch_dunning_targets(client)
    if not views:
        return [], 0
    marks = await progress_track.compute_marks(views)
    out: list[bitable_repo.HazardView] = []
    for view in views:
        status = marks.get(view.record_id)
        view.supervision_progress_status = status
        if status == progress_track.PROGRESS_STATUS_NOT_UPDATED:
            out.append(view)
    # 最旧的排前面（与旧实现一致）
    out.sort(key=lambda v: v.discovered_at or datetime.max.replace(tzinfo=UTC))
    return out, len(views)


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
    """一卡一隐患，私发给每条隐患的「责任人 + 分管安全员」。

    0 命中时不发卡，但仍向「安全速递」总卡投递「今日无需催办」简报
    （有无均报，口径对齐消防报警日报）。
    """
    from app.modules.safety.feishu.notification import send_user_card
    from app.modules.safety.feishu.progress_card import build_progress_card

    views, candidates = await find_dunning_overview()
    stats: dict[str, Any] = {
        "total": len(views), "candidates": candidates,
        "sent": 0, "skipped": 0, "errors": 0,
        "marked": len(views), "recipients": 0,
    }
    if not views:
        logger.info("⑤ 当前无「未更新进展」隐患，不发卡（督办候选 %d 条）", candidates)
        # 0 命中也投速递格子（报告口径对齐消防报警日报：有无均报）
        try:
            stats["digest_upserted"] = await _upsert_dunning_digest(
                views, [], [], [], stats,
            )
        except Exception:
            stats["digest_upserted"] = False
            logger.exception("⑤ 催办简报投递安全速递异常（不影响私发结果）")
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

    sent_plan: list[tuple[bitable_repo.HazardView, str, Any]] = []
    failed_plan: list[tuple[bitable_repo.HazardView, str, Any]] = []

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
                sent_plan.append((view, role, person))
                logger.info(
                    "⑤ 催办卡片已发送: record_id=%s → %s(%s) id_type=%s",
                    view.record_id, person.name, role, id_type,
                )
            else:
                stats["skipped"] += 1
                failed_plan.append((view, role, person))
                logger.warning(
                    "⑤ 催办卡片发送失败: record_id=%s → %s(%s)",
                    view.record_id, person.name, role,
                )
        except Exception:
            stats["errors"] += 1
            failed_plan.append((view, role, person))
            logger.exception(
                "⑤ 催办卡片发送异常: record_id=%s → %s", view.record_id, person.name
            )

    logger.info(
        "⑤ 催办完成(动态名单): sent=%d skipped=%d errors=%d 收件人=%d",
        stats["sent"], stats["skipped"], stats["errors"], stats["recipients"],
    )

    # 私发完成后，催办简报（含已私发对象）投递「安全速递」总卡；
    # 失败只告警，不影响私发结果与任务状态。
    try:
        stats["digest_upserted"] = await _upsert_dunning_digest(
            views, plan, sent_plan, failed_plan, stats,
        )
    except Exception:
        stats["digest_upserted"] = False
        logger.exception("⑤ 催办简报投递安全速递异常（不影响私发结果）")
    return stats


def _hazard_label(view: bitable_repo.HazardView) -> str:
    return view.hazard_no or view.record_id


def _short(text: str | None, limit: int = 40) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _build_dunning_cell(
    views: list[bitable_repo.HazardView],
    plan: list[tuple[bitable_repo.HazardView, str, Any]],
    sent_plan: list[tuple[bitable_repo.HazardView, str, Any]],
    failed_plan: list[tuple[bitable_repo.HazardView, str, Any]],
    stats: dict[str, Any],
) -> Any:
    """催办简报格子：概览统计 + 已私发对象分组 + 催办明细 + 未送达提示。

    0 命中时渲染「今日无需催办」简报（有无均报，样式对齐消防报警日报格子）。
    """
    from app.modules.safety.feishu.daily_digest import DigestCell

    if not views:
        candidates = int(stats.get("candidates") or 0)
        if candidates:
            zone_text = "各督办隐患整改进展均正常更新，今日无需催办"
            detail_text = "督办范围内未发现「未更新进展」隐患，今日未私发催办卡片。"
        else:
            zone_text = "今日无督办中隐患，无需催办"
            detail_text = "当前无督办中（红色/一般预警且未关闭）隐患，今日未私发催办卡片。"
        return DigestCell(
            tag_color="orange",
            tag_text="进展催办",
            title="未更新进展催办",
            stats=f"督办中隐患 **{candidates}** 条 ｜ 未更新进展 **0** 项",
            zone=zone_text,
            detail=detail_text,
        )

    # 已成功私发的人 → 角色去重、催办隐患编号列表（按发送顺序）
    people: dict[str, dict[str, Any]] = {}
    for view, role, person in sent_plan:
        key = person.user_id or person.open_id or person.name
        entry = people.setdefault(
            key, {"name": person.name, "roles": [], "hazards": []},
        )
        if role not in entry["roles"]:
            entry["roles"].append(role)
        hazard = _hazard_label(view)
        if hazard not in entry["hazards"]:
            entry["hazards"].append(hazard)

    # 每条隐患的应收件人（解析成功的完整名单，与送达状态分开呈现）
    plan_by_view: dict[str, list[tuple[str, Any]]] = {}
    for view, role, person in plan:
        plan_by_view.setdefault(view.record_id, []).append((role, person))

    detail: list[str] = [f"**已私发对象（{len(people)} 人）**"]
    if people:
        for entry in people.values():
            detail.append(
                f"- {entry['name']}（{'/'.join(entry['roles'])}）："
                f"{'、'.join(entry['hazards'])}"
            )
    else:
        detail.append("- 无（全部发送失败或收件人解析失败）")

    detail.append("")
    detail.append(f"**催办明细（{len(views)} 项）**")
    for view in views:
        targets = plan_by_view.get(view.record_id, [])
        target_txt = " ｜ ".join(f"{role} {p.name}" for role, p in targets)
        if not target_txt:
            target_txt = "收件人解析失败"
        dept = (view.department or "").strip() or "未填部门"
        detail.append(
            f"- **{_hazard_label(view)}**（{dept}）"
            f"{_short(view.description)} → {target_txt}"
        )

    if failed_plan:
        detail.append("")
        detail.append(
            f"⚠️ 未送达 {len(failed_plan)} 张："
            + "、".join(
                f"{_hazard_label(view)}（{role} {person.name}）"
                for view, role, person in failed_plan
            )
        )

    return DigestCell(
        tag_color="orange",
        tag_text="进展催办",
        title="未更新进展催办",
        stats=(
            f"未更新进展 **{len(views)}** 项 ｜ "
            f"已私发 **{len(people)}** 人（{stats.get('sent', 0)} 张卡送达）"
        ),
        zone="已私发各隐患责任人与分管安全员，收卡人可在卡片内直接提交进展",
        detail="\n".join(detail),
    )


async def _upsert_dunning_digest(
    views: list[bitable_repo.HazardView],
    plan: list[tuple[bitable_repo.HazardView, str, Any]],
    sent_plan: list[tuple[bitable_repo.HazardView, str, Any]],
    failed_plan: list[tuple[bitable_repo.HazardView, str, Any]],
    stats: dict[str, Any],
) -> bool:
    """把催办简报投进当日「安全速递」总卡（安全AI创新交流群）。"""
    from app.modules.safety.feishu.daily_digest import upsert_daily_digest

    bj_today = (datetime.now(UTC) + timedelta(hours=8)).date()
    cell = _build_dunning_cell(views, plan, sent_plan, failed_plan, stats)
    ok = await upsert_daily_digest(bj_today, "progress_dunning", cell)
    if ok:
        logger.info("⑤ 催办简报已投递安全速递总卡: date=%s", bj_today)
    else:
        logger.warning("⑤ 催办简报总卡投递失败: date=%s", bj_today)
    return ok


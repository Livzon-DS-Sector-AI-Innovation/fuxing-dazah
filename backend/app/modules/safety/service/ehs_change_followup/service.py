"""编排：周五一轮 / 周一总结 —— 唯一测试接缝（结构照 service/interlock_warning/）。

周五（10:00，补发到 17:00）：读两表 → 定稿口径筛分 → 按安全员聚合同人一卡 →
落库快照（round/dispatch/item）→ 逐人私发 → 投安全速递格子。dispatch.send_status
即幂等锚：重跑只补发未 sent 的人；仍有失败则上抛交调度器补发窗口重试。

周一（09:00，补发到 12:00）：找 4 天内最近一轮周五督办（找不到跳过并告警，
不凭空总结）→ 重读两表逐项判定（closed/③更新/②进展不变/①未更新）→ 落库 →
投速递格子（投过以 round.status=summarized 幂等）。总卡关闭或投格失败 →
兜底发独立群卡（仓库惯例），仍失败才上抛。

降级红线（DESIGN §9）：验收表读取失败本轮不发（不退化看「变更状态」）；
两表读取失败一律上抛。数据源未登记抛 BitableConfigError 交调度器 no_source。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.modules.safety.models.ehs_change_followup import (
    DISPATCH_NO_RECIPIENT,
    DISPATCH_PENDING,
    DISPATCH_SENT,
    DISPATCH_UNRESOLVED,
    RESPONSE_UNCHANGED,
    ROUND_SENDING,
    ROUND_SENT,
    ROUND_SUMMARIZED,
    EhsChangeFollowupDispatch,
    EhsChangeFollowupItem,
    EhsChangeFollowupRound,
)
from . import cards
from .records import (
    FollowupFacts,
    accepted_change_numbers,
    classify_item,
    is_closed_now,
    parse_acceptance_row,
    parse_approval_row,
    split_followup,
)

logger = logging.getLogger(__name__)

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

FRIDAY_DIGEST_KEY = "ehs_change_followup"
MONDAY_DIGEST_KEY = "ehs_change_summary"

# 周一向前找周五轮次的窗口（周一→上周五 3 天，留 1 天余量）
MONDAY_LOOKBACK_DAYS = 4

FetchFn = Callable[[], Awaitable[list[dict[str, Any]]]]
SendFn = Callable[..., Awaitable[str | bool]]
DigestFn = Callable[[date, str, Any], Awaitable[bool]]


def bj_today() -> date:
    return datetime.now(_TZ_SHANGHAI).date()


async def _fetch_approval_rows() -> list[dict[str, Any]]:
    """默认拉取审批表全量（测试 monkeypatch 点）。"""
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("ehs_change", "approval")
    return await bd_reader.fetch_all_records(client)


async def _fetch_acceptance_rows() -> list[dict[str, Any]]:
    """默认拉取验收表全量（读取失败不降级，直接上抛）。"""
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("ehs_change", "acceptance")
    return await bd_reader.fetch_all_records(client)


async def _send_dm(receive_id: str, card: dict, *, id_type: str = "open_id") -> Any:
    """默认发送（测试钉 notification.send_user_card_dict 即可拦截）。"""
    from app.modules.safety.feishu import notification

    return await notification.send_user_card_dict(receive_id, card, id_type=id_type)


async def _upsert_digest(report_date: date, key: str, cell: Any) -> bool:
    """默认投格：总卡开启并入当日卡；关闭或投格失败 → 兜底独立群卡。"""
    from app.modules.safety.feishu.daily_digest import (
        digest_enabled,
        send_digest_cell_card,
        upsert_daily_digest,
    )

    if digest_enabled():
        if await upsert_daily_digest(report_date, key, cell):
            return True
        logger.warning("ehs_change_followup: 速递格投格失败，回落独立群卡: key=%s", key)
    return bool(await send_digest_cell_card(
        cell, title=f"📌 {cell.title} | {report_date.isoformat()}",
    ))


def _change_table_url() -> str:
    """审批表直链（按 bitable_config 实际连接；未登记返回空，卡面省链接）。"""
    try:
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("ehs_change", "approval")
        if conn is not None and conn.app_token and conn.table_id:
            return (
                f"https://j0eukrlohu.feishu.cn/base/{conn.app_token}"
                f"?table={conn.table_id}&view=vewaxNrpo8"
            )
    except Exception:
        logger.exception("ehs_change_followup: 变更表连接解析失败（卡面省「打开变更表」）")
    return ""


def _officer_of(department: str) -> str | None:
    """部门 → 分管安全员姓名（DEPARTMENT_CONFIG；未配置返回 None）。"""
    from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG

    dept = department.strip()
    return (DEPARTMENT_CONFIG.get(dept) or {}).get("safety_officer")


async def _resolve_officer_ids(name: str) -> tuple[str | None, str | None]:
    """安全员姓名 → (安全作用域 open_id, 租户级 user_id)。

    三层链里「人员字段直取」不适用（审批表无安全员字段）：静态映射 → identity。
    identity 来源 open_id 是平台作用域，发送侧优先 user_id（progress_dunning 同口径）。
    """
    from app.modules.safety.feishu import bitable_id_mapper

    oid = bitable_id_mapper.get_bitable_open_id(name=name)
    if oid:
        return oid, ""
    try:
        from app.core.database import async_session_factory
        from app.modules.safety.feishu.identity_resolver import IdentityResolver

        async with async_session_factory() as session:
            person = await IdentityResolver(session).resolve_by_name(name)
        if person is not None:
            return person.open_id, (person.user_id or "")
    except Exception:
        logger.exception("ehs_change_followup: identity 解析安全员失败: %s", name)
    return None, None


def _group_by_officer(
    facts: FollowupFacts,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """待督办 → 按安全员聚合（同人一卡）；→ (有主列表, 无主列表)。

    多部门变更归首个配置了安全员的部门（快照口径下无多部门变更，防御性处理）；
    部门未配置安全员 → 无主（速递格「未发送」单列，DESIGN §9：不是 bug）。
    """
    groups: dict[str, dict[str, Any]] = {}
    unsent: dict[str, dict[str, Any]] = {}
    for change in facts.todo:
        officer: str | None = None
        for dept in change.departments or [""]:
            officer = _officer_of(dept)
            if officer:
                break
        if officer is None:
            dept_label = change.department or "未填部门"
            slot = unsent.setdefault(
                dept_label, {"department": dept_label, "changes": []},
            )
            slot["changes"].append(change)
            continue
        slot = groups.setdefault(
            officer, {"officer": officer, "departments": [], "changes": []},
        )
        for dept in change.departments or [change.department or "未填部门"]:
            if dept and dept not in slot["departments"]:
                slot["departments"].append(dept)
        slot["changes"].append(change)
    ordered = sorted(groups.values(), key=lambda g: (-len(g["changes"]), g["officer"]))
    return ordered, list(unsent.values())


def _item_from_change(change, nag_weeks: int) -> EhsChangeFollowupItem:
    """ApprovalChange → item 行（周五快照字段）。"""
    return EhsChangeFollowupItem(
        round_id=None,  # 由调用方补
        dispatch_id=None,
        record_id=change.record_id,
        change_no=change.change_no,
        title=change.title,
        department=change.department or "未填部门",
        status_shown=change.change_status,
        progress_friday=change.progress,
        expected_start=change.expected_start,
        approval_url=change.approval_url,
        nag_weeks=nag_weeks,
    )


async def _nag_weeks(session: Any, record_ids: list[str]) -> dict[str, int]:
    """record_id → 第 N 周督办（历史轮次出现次数 + 1）。"""
    out = {rid: 1 for rid in record_ids}
    if not record_ids:
        return out
    rows = await session.execute(
        select(
            EhsChangeFollowupItem.record_id,
            func.count(func.distinct(EhsChangeFollowupItem.round_id)),
        )
        .where(EhsChangeFollowupItem.record_id.in_(record_ids))
        .group_by(EhsChangeFollowupItem.record_id)
    )
    for rid, count in rows.all():
        out[rid] = int(count) + 1
    return out


def _card_item_views(items: list[EhsChangeFollowupItem]) -> tuple[cards.CardItemView, ...]:
    return tuple(
        cards.CardItemView(
            record_id=i.record_id,
            change_no=i.change_no,
            title=i.title or "",
            status_shown=i.status_shown or "",
            progress=i.progress_friday or "",
            expected_start=i.expected_start,
            approval_url=i.approval_url,
            nag_weeks=i.nag_weeks,
            replied_progress=i.replied_progress or "",
            replied_at_short=(
                i.replied_at.strftime("%H:%M") if i.replied_at else ""
            ),
        )
        for i in sorted(items, key=lambda x: x.change_no)
    )


async def run_friday_round(
    *,
    dry_run: bool = False,
    fetch_approval: FetchFn | None = None,
    fetch_acceptance: FetchFn | None = None,
    send: SendFn | None = None,
    digest: DigestFn | None = None,
    now: date | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """周五一轮（接缝入口）。

    - dry_run：真拉取真筛分，打印聚合结果（对探针口径验收），不发送不写库不投格
    - fetch_*/send/digest/session：测试替身注入；缺省走模块级默认绑定
    """
    from . import config

    today = now or bj_today()
    iso_year, iso_week, _ = today.isocalendar()

    approval_rows = await (fetch_approval or _fetch_approval_rows)()
    acceptance_rows = await (fetch_acceptance or _fetch_acceptance_rows)()
    approvals = [a for a in (parse_approval_row(r) for r in approval_rows) if a]
    acceptances = [a for a in (parse_acceptance_row(r) for r in acceptance_rows) if a]

    excluded_numbers = {x.strip() for x in config.excluded_raw().split(",") if x.strip()}
    facts = split_followup(approvals, acceptances, excluded_numbers)
    groups, unsent = _group_by_officer(facts)

    departments = {
        dept
        for change in facts.todo
        for dept in (change.departments or [change.department or "未填部门"])
    }
    stats: dict[str, Any] = {
        "date": today.isoformat(),
        "week": f"{iso_year}-W{iso_week:02d}",
        "todo": len(facts.todo),
        "closed_accepted": len(facts.closed_accepted),
        "closed_terminated": len(facts.closed_terminated),
        "excluded": len(facts.excluded),
        "departments": len(departments),
        "recipients": len(groups),
        "unsent_departments": {u["department"]: len(u["changes"]) for u in unsent},
        "sent": 0,
        "failed": 0,
        "dry_run": dry_run,
    }
    logger.info("ehs_change_followup 周五筛分: %s", stats)

    if dry_run:
        for g in groups:
            print(
                f"[dry_run] → {g['officer']}（{'、'.join(g['departments'])}）"
                f" {len(g['changes'])} 项："
                + "、".join(c.change_no for c in g["changes"])
            )
        for u in unsent:
            print(
                f"[dry_run] × {u['department']} 未配置安全员 "
                f"{len(u['changes'])} 项："
                + "、".join(c.change_no for c in u["changes"])
            )
        return stats

    # ── 落库：get-or-create 轮次 + 补齐 dispatch/item（重跑幂等）──
    from app.core.database import async_session_factory

    own_session = session is None
    db = session if session is not None else async_session_factory()
    try:
        round_row = await db.scalar(
            select(EhsChangeFollowupRound).where(
                EhsChangeFollowupRound.year == iso_year,
                EhsChangeFollowupRound.week_no == iso_week,
                EhsChangeFollowupRound.is_deleted.is_(False),
            )
        )
        if round_row is None:
            round_row = EhsChangeFollowupRound(
                year=iso_year, week_no=iso_week, fired_on=today, status=ROUND_SENDING,
            )
            db.add(round_row)
            await db.flush()

        existing_items = {
            item.record_id: item
            for item in (await db.scalars(
                select(EhsChangeFollowupItem).where(
                    EhsChangeFollowupItem.round_id == round_row.id
                )
            )).all()
        }
        nag_map = await _nag_weeks(
            db,
            [c.record_id for c in facts.todo if c.record_id not in existing_items],
        )

        dispatches: list[EhsChangeFollowupDispatch] = list(
            (await db.scalars(
                select(EhsChangeFollowupDispatch).where(
                    EhsChangeFollowupDispatch.round_id == round_row.id
                )
            )).all()
        )
        by_officer = {d.officer_name: d for d in dispatches}

        def _ensure_item(change) -> None:
            if change.record_id in existing_items:
                return
            item = _item_from_change(change, nag_map.get(change.record_id, 1))
            item.round_id = round_row.id
            db.add(item)
            existing_items[change.record_id] = item

        for g in groups:
            officer = g["officer"]
            dispatch = by_officer.get(officer)
            if dispatch is None:
                dispatch = EhsChangeFollowupDispatch(
                    round_id=round_row.id,
                    officer_name=officer,
                    departments=",".join(g["departments"]),
                    change_count=len(g["changes"]),
                    send_status=DISPATCH_PENDING,
                )
                db.add(dispatch)
                await db.flush()
                dispatches.append(dispatch)
                by_officer[officer] = dispatch
            for change in g["changes"]:
                _ensure_item(change)
                existing_items[change.record_id].dispatch_id = dispatch.id
        # 无主项也落 item（dispatch_id 空，事后可查；周一按库内 item 逐项判定）
        for u in unsent:
            for change in u["changes"]:
                _ensure_item(change)
        await db.flush()

        # ── 发送：只补发未 sent 的（幂等锚）──
        gray = config.gray_recipient().strip()
        send_fn = send or _send_dm
        table_url = _change_table_url()
        date_label = round_row.fired_on.strftime("%m-%d 周五")
        for dispatch in dispatches:
            if dispatch.send_status in (DISPATCH_SENT, DISPATCH_NO_RECIPIENT):
                continue
            open_id, user_id = dispatch.officer_open_id, dispatch.officer_user_id
            if not open_id and not user_id:
                open_id, user_id = await _resolve_officer_ids(dispatch.officer_name)
                dispatch.officer_open_id, dispatch.officer_user_id = open_id, user_id
            items = [
                i for i in existing_items.values() if i.dispatch_id == dispatch.id
            ]
            view = cards.FridayCardView(
                officer_name=dispatch.officer_name,
                departments=dispatch.departments.replace(",", "/"),
                week_no=round_row.week_no,
                date_label=date_label,
                items=_card_item_views(items),
                has_replies=any(i.replied_at for i in items),
                responded_unchanged_at=(
                    dispatch.responded_at.strftime("%H:%M")
                    if dispatch.responded_at else ""
                ),
                change_table_url=table_url,
            )
            receive_id, id_type = (
                (gray, "open_id") if gray
                else ((user_id or open_id or ""), "user_id" if user_id else "open_id")
            )
            if not receive_id:
                dispatch.send_status = DISPATCH_UNRESOLVED
                dispatch.send_error = "安全员 open_id 解析失败"
                stats["failed"] += 1
                logger.warning(
                    "ehs_change_followup: 安全员解析失败 %s", dispatch.officer_name,
                )
                continue
            try:
                message_id = await send_fn(
                    receive_id, cards.build_friday_card(view, str(dispatch.id)),
                    id_type=id_type,
                )
            except Exception as exc:
                dispatch.send_status = "failed"
                dispatch.send_error = f"{type(exc).__name__}: {exc}"
                stats["failed"] += 1
                logger.exception(
                    "ehs_change_followup: 周五卡发送异常 %s", dispatch.officer_name,
                )
                continue
            if message_id:
                dispatch.send_status = DISPATCH_SENT
                dispatch.message_id = str(message_id)
                dispatch.sent_at = datetime.now(_TZ_SHANGHAI)
                stats["sent"] += 1
            else:
                dispatch.send_status = "failed"
                dispatch.send_error = "send_user_card_dict 返回 False"
                stats["failed"] += 1

        # ── 速递格子（重试成功后会以终态覆盖；失败不拦 DM 结果）──
        digest_view = cards.FridayDigestView(
            total_todo=len(facts.todo),
            terminated_count=len(facts.closed_terminated),
            excluded=tuple((c.change_no, note) for c, note in facts.excluded),
            stale_accepted=tuple(facts.status_stale_accepted),
            dispatched=[
                cards.DigestDispatchView(
                    officer_name=d.officer_name,
                    departments=d.departments.replace(",", "/"),
                    change_nos=tuple(
                        i.change_no
                        for i in sorted(
                            (x for x in existing_items.values()
                             if x.dispatch_id == d.id),
                            key=lambda x: x.change_no,
                        )
                    ),
                    sent=d.send_status == DISPATCH_SENT,
                )
                for d in dispatches
            ],
            unsent_departments=tuple(
                f"{u['department']} {len(u['changes'])} 项" for u in unsent
            ),
        )
        try:
            stats["digest_upserted"] = await (digest or _upsert_digest)(
                today, FRIDAY_DIGEST_KEY, cards.build_friday_cell(digest_view),
            )
        except Exception:
            stats["digest_upserted"] = False
            logger.exception("ehs_change_followup: 周五速递格投递异常（不影响私发）")

        all_sent = all(
            d.send_status in (DISPATCH_SENT, DISPATCH_NO_RECIPIENT) for d in dispatches
        )
        round_row.status = ROUND_SENT if all_sent else ROUND_SENDING
        round_row.stats = stats
        await db.commit()
    finally:
        if own_session:
            await db.close()

    if stats["failed"]:
        # 上抛交调度器补发窗口重试（重跑只补发未 sent 的人）
        raise RuntimeError(
            f"EHS变更周度督办有 {stats['failed']} 张卡未送达，交补发窗口重试"
        )
    return stats


def _dispatch_category(outcomes: set[str]) -> str | None:
    """安全员主分类：有更新→updated；否则有进展不变→unchanged；有项才落 not_updated。"""
    if not outcomes:
        return None
    if "updated" in outcomes:
        return "updated"
    if "unchanged" in outcomes:
        return "unchanged"
    return "not_updated"


async def run_monday_summary(
    *,
    dry_run: bool = False,
    fetch_approval: FetchFn | None = None,
    fetch_acceptance: FetchFn | None = None,
    digest: DigestFn | None = None,
    now: date | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """周一总结（接缝入口）：4 天窗口找轮 → 重读两表 → 三类判定 → 投格。"""
    today = now or bj_today()
    from app.core.database import async_session_factory

    own_session = session is None
    db = session if session is not None else async_session_factory()
    try:
        round_row = await db.scalar(
            select(EhsChangeFollowupRound)
            .where(
                EhsChangeFollowupRound.fired_on
                >= today - timedelta(days=MONDAY_LOOKBACK_DAYS),
                EhsChangeFollowupRound.fired_on <= today,
                EhsChangeFollowupRound.is_deleted.is_(False),
            )
            .order_by(EhsChangeFollowupRound.fired_on.desc())
            .limit(1)
        )
        if round_row is None:
            logger.warning(
                "ehs_change_followup: 周一总结找不到 %d 天内的周五督办轮次，跳过",
                MONDAY_LOOKBACK_DAYS,
            )
            return {"skipped": "no_round"}
        if round_row.status == ROUND_SUMMARIZED:
            logger.info("ehs_change_followup: 轮次 %s 已总结，跳过（幂等）", round_row.id)
            return {"skipped": "already_summarized"}

        approval_rows = await (fetch_approval or _fetch_approval_rows)()
        acceptance_rows = await (fetch_acceptance or _fetch_acceptance_rows)()
        approvals = [a for a in (parse_approval_row(r) for r in approval_rows) if a]
        acceptances = [a for a in (parse_acceptance_row(r) for r in acceptance_rows) if a]
        accepted = accepted_change_numbers(acceptances, approvals)
        by_record = {a.record_id: a for a in approvals}

        items = list((await db.scalars(
            select(EhsChangeFollowupItem).where(
                EhsChangeFollowupItem.round_id == round_row.id
            )
        )).all())
        dispatch_by_id = {
            d.id: d for d in (await db.scalars(
                select(EhsChangeFollowupDispatch).where(
                    EhsChangeFollowupDispatch.round_id == round_row.id
                )
            )).all()
        }

        counts = {"closed": 0, "updated": 0, "unchanged": 0, "not_updated": 0}
        groups: dict[str, list[cards.MondayCategoryGroup]] = {
            "not_updated": [], "unchanged": [], "updated": [],
        }
        group_index: dict[tuple[str, str], cards.MondayCategoryGroup] = {}

        for item in items:
            current = by_record.get(item.record_id)
            dispatch = dispatch_by_id.get(item.dispatch_id) if item.dispatch_id else None
            # 「进展不变」按钮管的是没提交进展的其余变更（提交过的按③判）
            unchanged_clicked = (
                dispatch is not None
                and dispatch.response_type == RESPONSE_UNCHANGED
                and item.replied_at is None
            )
            outcome = classify_item(
                closed_now=is_closed_now(current, accepted),
                progress_friday=item.progress_friday,
                progress_monday=current.progress if current else None,
                status_friday=item.status_shown,
                status_monday=current.change_status if current else None,
                unchanged_clicked=unchanged_clicked,
            )
            item.progress_monday = current.progress if current else None
            item.outcome = outcome
            counts[outcome] += 1
            if outcome == "closed":
                continue
            key = (outcome, item.department)
            group = group_index.get(key)
            if group is None:
                group = cards.MondayCategoryGroup(
                    department=item.department,
                    officer_name=dispatch.officer_name if dispatch else "未配置安全员",
                )
                group_index[key] = group
                groups[outcome].append(group)
            group.change_nos = group.change_nos + (item.change_no,)
            if outcome == "updated":
                excerpt = item.replied_progress or item.progress_monday or ""
                stamp = (
                    item.replied_at.strftime("%m-%d") if item.replied_at else ""
                )
                label = f"（卡片提交 {stamp}）" if stamp else ""
                group.updated_lines = group.updated_lines + (
                    f"{item.change_no}：{' '.join(excerpt.split())[:40]}{label}",
                )

        for dispatch in dispatch_by_id.values():
            outcomes = {
                i.outcome for i in items if i.dispatch_id == dispatch.id and i.outcome
            } - {"closed"}
            dispatch.category = _dispatch_category(outcomes)

        stats = {
            "date": today.isoformat(),
            "round_id": str(round_row.id),
            "fired_on": round_row.fired_on.isoformat(),
            "friday_total": len(items),
            **counts,
        }
        if dry_run:
            print(f"[dry_run] 周一总结: {stats}")
            return stats

        view = cards.MondayDigestView(
            not_updated=groups["not_updated"],
            unchanged=groups["unchanged"],
            updated=groups["updated"],
            friday_total=len(items),
            closed_count=counts["closed"],
        )
        ok = await (digest or _upsert_digest)(
            today, MONDAY_DIGEST_KEY, cards.build_monday_cell(view),
        )
        if not ok:
            raise RuntimeError("EHS变更督办总结投递失败（总卡与独立群卡均未确认）")
        stats["digest_upserted"] = True

        round_row.status = ROUND_SUMMARIZED
        round_row.stats = stats
        await db.commit()
        logger.info("ehs_change_followup 周一总结完成: %s", stats)
        return stats
    finally:
        if own_session:
            await db.close()

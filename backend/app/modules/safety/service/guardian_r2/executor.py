"""R2 程序执行器 —— 提醒 DM / 取消资格 / 恢复 / 成绩映射（本文件 T04 起逐票落位）。

事务边界（照 R1 executor 约定）：由 run_task_once 在 task 行锁事务外调用，
自开 session（async_session_factory）；先落业务事实（links/outbox）再
commit，Report 落库极窗失败由幂等跳过兜底。外发一律 enqueue outbox，
禁止裸 asyncio.create_task / 直接调飞书 API。

私信 open_id 三层链（拍板④/调研结论）：
  ① Bitable 人员字段直取（payload.guardian_open_id，安全应用作用域）
  ② bitable_id_mapper 静态映射（name → 安全应用 open_id）
  ③ IdentityResolver（identity 表，可能为平台作用域 open_id——尽力兜底）
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from app.platform.superagent.executors import Report

logger = logging.getLogger(__name__)

#: 提醒私信总开关（app_config：env > DB；默认开，出问题可熔断发送）
DM_TOGGLE_KEY = "SAFETY_GUARDIAN_R2_DM_ENABLED"

#: DM 卡片 outbox channel 类型（bridge 注册 feishu_dm_card sender）
DM_CHANNEL_TYPE = "feishu_dm_card"


def _dm_enabled() -> bool:
    from app.modules.safety.app_config.store import store

    return store.get_bool(DM_TOGGLE_KEY, default=True)


async def resolve_dm_open_id(
    session: Any,
    *,
    direct_open_id: str | None,
    person_name: str | None,
    department_hint: str | None = None,
) -> str | None:
    """私信 open_id 三层链（① Bitable 人员字段 ② 静态映射 ③ identity）。"""
    if direct_open_id:
        return direct_open_id
    if not person_name:
        return None
    # ② 静态映射（安全应用 open_id 快照）
    from app.modules.safety.feishu.bitable_id_mapper import get_bitable_open_id

    mapped = get_bitable_open_id(name=person_name)
    if mapped:
        return mapped
    # ③ identity 表（open_id 可能为平台作用域——尽力兜底，发送失败走重试）
    try:
        from app.modules.safety.feishu.identity_resolver import IdentityResolver

        resolver = IdentityResolver(session)
        person = await resolver.resolve_by_name(
            person_name, department_hint=department_hint
        )
        return person.open_id if person else None
    except Exception:
        logger.exception("IdentityResolver 解析失败: %s", person_name)
        return None


async def _origin_payload(session: Any, task_dict: dict[str, Any]) -> dict[str, Any]:
    """origin Trigger payload（_derived 权威来源；mandate 只带身份键）。"""
    from app.platform.superagent.models import AgentTask, AgentTrigger

    task_id = uuid.UUID(str(task_dict["id"]))
    task = await session.get(AgentTask, task_id)
    trigger = (
        await session.get(AgentTrigger, task.origin_trigger_id)
        if task is not None and task.origin_trigger_id is not None else None
    )
    return dict(trigger.payload or {}) if trigger is not None else {}


async def guardian_remind_dm(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """复审/换证提醒私信（幂等：本月已发跳过；失败 blocked 可重试）。

    幂等三层：Trigger 月度键唯一 → decision 防重复开工 → links
    last_reminded_month == 本月 → ready 跳过。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.guardian_r2.links import (
        bump_reminder,
        get_or_create_link,
    )
    from app.modules.safety.service.guardian_r2.notify import build_remind_content
    from app.platform.superagent.effects import enqueue_outbox_message

    mandate = task_dict.get("mandate") or {}
    record_id = (mandate.get("origin_actor") or {}).get("id") or ""
    if not record_id:
        return Report(
            kind="failed", end_task=True,
            note="mandate.origin_actor.id 缺失，无法定位持证记录",
        )
    task_id = uuid.UUID(str(task_dict["id"]))

    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        derived = dict(payload.get("_derived") or {})
        deadline = str(derived.get("deadline") or "")
        month_key = str(derived.get("remind_month") or "") or deadline[:7]
        if not month_key:
            await session.commit()
            return Report(
                kind="failed", end_task=True,
                note="_derived.remind_month/deadline 缺失，无月份键",
            )

        link, _ = await get_or_create_link(
            session,
            record_id=record_id,
            person_name=str(derived.get("person_name") or ""),
            department=derived.get("department"),
            cert_category=str(derived.get("cert_category") or ""),
            snapshot={"derived": derived},
        )
        # 幂等跳过：本月已发（执行器重跑/重复转正安全）
        if link.last_reminded_month == month_key:
            await session.commit()
            return Report(
                kind="ready", end_task=True,
                note=f"本月（{month_key}）已提醒，幂等跳过",
                output={"remind_count": link.remind_count},
            )

        if not _dm_enabled():
            await session.commit()
            return Report(
                kind="ready", end_task=True,
                note=f"DM 开关关闭（{DM_TOGGLE_KEY}），跳过发送与计数",
            )

        open_id = await resolve_dm_open_id(
            session,
            direct_open_id=derived.get("guardian_open_id"),
            person_name=derived.get("person_name"),
            department_hint=derived.get("department"),
        )
        if not open_id:
            link.error_message = (
                f"提醒私信 open_id 解析失败: {derived.get('person_name')}"
            )[:2000]
            await session.commit()
            # 解析失败大概率持久（人名脏数据）→ failed 终态，不无限重试
            return Report(kind="failed", end_task=True, note=link.error_message)

        await enqueue_outbox_message(
            session,
            conversation=f"guardian_remind:{record_id}:{month_key}",
            channel={"type": DM_CHANNEL_TYPE, "open_id": open_id},
            purpose="guardian_review_remind",
            task_id=task_id,
            body={
                "title": "监护人证件到期提醒",
                "content": build_remind_content(derived),
            },
        )
        await bump_reminder(session, record_id, month_key)
        link.error_message = None
        await session.commit()

    logger.info(
        "R2 提醒已发: record=%s month=%s count=%s",
        record_id, month_key, link.remind_count,
    )
    return Report(
        kind="ready", end_task=True,
        output={"month_key": month_key, "remind_count": link.remind_count},
    )


# ═══════════════════════════════════════════════════════════
# 成绩映射（规则4，T05）
# ═══════════════════════════════════════════════════════════


def _cert_client(cert_category: str):
    """按 A/B 类别构造持证表客户端（配置中心坐标）。"""
    from app.modules.safety.feishu.cert_bitable import cert_tables

    pair = cert_tables().get(cert_category)
    if not pair:
        raise RuntimeError(f"持证表未配置: {cert_category}")
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    app_token, table_id = pair
    return SafetyBitableClient(app_token=app_token, table_id=table_id)


async def ensure_exam_columns(client: Any) -> None:
    """幂等确保持证表存在考核三列（单选×2 + 日期；黄色操作在真实表执行）。"""
    existing = await client.list_fields()
    names = {f.get("field_name") for f in existing or []}
    # field_type: 3=单选 4=日期（Bitable v1 字段类型）
    for field_name, ftype, prop in (
        ("考核成绩", 3, {"options": [{"name": "合格"}, {"name": "不合格"}]}),
        ("考核类型", 3, {"options": [{"name": "取证"}, {"name": "复审"}, {"name": "换证"}]}),
        ("考核日期", 4, None),
    ):
        if field_name in names:
            continue
        kwargs: dict[str, Any] = {}
        if prop:
            kwargs["property_"] = prop
        created = await client.create_field(field_name, ftype, **kwargs)
        if not created:
            raise RuntimeError(f"ensure 列失败: {field_name}")


async def guardian_score_map(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """成绩映射（辨别取证/复审/换证 → 写回持证表 + links 事件 + DM）。

    分支：
    - 合格 + 不在名单 → 取证：create_record 进 A/B 证名单（+1/+2/+3 年推导）
    - 合格/不合格 + 在名单 → 复审/换证：写回考核三列（换证合格加已换证日期）
    - 异常（无姓名/同名无法消歧/无日期）→ failed 终态留 detail（不映射不猜测）

    幂等：持证表考核日期==本次考核日期且成绩相同 → ready 跳过（重试安全）。
    """
    from datetime import date

    from app.core.database import async_session_factory
    from app.modules.safety.service.guardian_r2.links import (
        append_score_event,
        get_or_create_link,
    )
    from app.modules.safety.service.guardian_r2.node_engine import discriminate
    from app.modules.safety.service.guardian_r2.notify import (
        build_score_event_content,
    )
    from app.modules.safety.service.guardian_r2.scan_source import (
        cert_view_from_fields,
        fetch_guardian_cert_records,
        load_links_map,
    )
    from app.modules.safety.service.guardian_r2.score_parse import ScoreFacts
    from app.modules.safety.service.guardian_r2.writeback import (
        build_enroll_fields,
        build_writeback_fields,
    )
    from app.platform.superagent.effects import enqueue_outbox_message

    mandate = task_dict.get("mandate") or {}
    score_record_id = (mandate.get("origin_actor") or {}).get("id") or ""
    if not score_record_id:
        return Report(
            kind="failed", end_task=True,
            note="mandate.origin_actor.id 缺失，无法定位成绩记录",
        )
    task_id = uuid.UUID(str(task_dict["id"]))

    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        derived = dict(payload.get("_derived") or {})
        facts = ScoreFacts(
            person_name=derived.get("person_name"),
            open_id=derived.get("open_id"),
            department=derived.get("department"),
            cert_category=derived.get("cert_category"),
            passed=derived.get("passed"),
            exam_date=date.fromisoformat(derived["exam_date"])
            if derived.get("exam_date") else None,
            score_value=derived.get("score_value"),
        )

        try:
            cert_records = await fetch_guardian_cert_records()
        except Exception as exc:
            return Report(
                kind="blocked",
                note=f"持证表拉取失败（可重试）: {type(exc).__name__}: {exc}",
            )
        links_map = await load_links_map(session)
        views = []
        for rec in cert_records:
            view = cert_view_from_fields(
                rec.get("kind") or "", rec.get("record_id") or "",
                rec.get("fields") or {},
                links_map.get(rec.get("record_id") or ""),
            )
            if view is not None:
                views.append(view)

        discriminated, detail, matched_view = discriminate(facts, views)

        if discriminated == "异常":
            return Report(
                kind="failed", end_task=True,
                note=f"成绩无法映射（不猜测）: {detail} "
                f"person={facts.person_name} score_record={score_record_id}",
            )
        if discriminated == "无需处理":
            return Report(
                kind="ready", end_task=True,
                note=f"非合格且不在名单，无需映射: {facts.person_name}",
            )

        # 匹配到的持证记录（取证分支后由 create_record 回填）
        matched_rid: str | None = (
            matched_view.record_id if matched_view is not None else None
        )

        event = {
            "exam_type": discriminated,
            "passed": facts.passed,
            "exam_date": facts.exam_date.isoformat() if facts.exam_date else None,
            "discriminated": discriminated,
            "score_record_id": score_record_id,
        }

        try:
            if discriminated == "取证":
                client = _cert_client(facts.cert_category or "guardian_a")
                await ensure_exam_columns(client)
                created = await client.create_record(build_enroll_fields(facts))
                if not created or not created.get("record_id"):
                    raise RuntimeError("取证 create_record 返回空")
                matched_rid = str(created["record_id"])
            else:
                # 幂等：已写回同日期同成绩同类型 → ready 跳过（重试安全；
                # 极窗丢事件的退化由 node_engine 考核三列回退路径兜底消费）
                if (
                    matched_view.exam_date == facts.exam_date
                    and matched_view.exam_score == facts.passed
                    and matched_view.exam_type == discriminated
                ):
                    await session.commit()
                    return Report(
                        kind="ready", end_task=True,
                        note="持证表已写回同次考核，幂等跳过",
                        output={"record_id": matched_rid},
                    )
                client = _cert_client(matched_view.cert_category)
                await ensure_exam_columns(client)
                await client.update_record(
                    matched_rid,
                    build_writeback_fields(facts, discriminated=discriminated),
                )
        except Exception as exc:  # noqa: BLE001 — 失败留痕统一走 Report
            logger.exception(
                "guardian_score_map 写回失败: person=%s", facts.person_name
            )
            return Report(
                kind="blocked",
                note=f"Bitable 写回失败（可重试）: {type(exc).__name__}: {exc}",
            )

        # links 事件流（取证用新 record_id；复审/换证用既有）
        if matched_rid:
            await get_or_create_link(
                session,
                record_id=matched_rid,
                person_name=facts.person_name or "",
                department=facts.department,
                cert_category=facts.cert_category or "",
                snapshot={"derived": derived},
            )
            await append_score_event(session, matched_rid, event)

        # DM 通知（取证欢迎/复审通过/换证延期/不合格警示）
        if _dm_enabled():
            open_id = await resolve_dm_open_id(
                session,
                direct_open_id=facts.open_id,
                person_name=facts.person_name,
                department_hint=facts.department,
            )
            if open_id:
                await enqueue_outbox_message(
                    session,
                    conversation=f"guardian_score:{matched_rid}:{score_record_id}",
                    channel={"type": DM_CHANNEL_TYPE, "open_id": open_id},
                    purpose="guardian_score_map",
                    task_id=task_id,
                    body={
                        "title": "监护人考核结果",
                        "content": build_score_event_content(
                            facts.person_name, facts.cert_category,
                            discriminated, facts.passed,
                            facts.exam_date.isoformat() if facts.exam_date else None,
                        ),
                    },
                )
        await session.commit()

    logger.info(
        "R2 成绩映射完成: person=%s type=%s passed=%s record=%s",
        facts.person_name, discriminated, facts.passed, matched_rid,
    )
    return Report(
        kind="ready", end_task=True,
        output={"discriminated": discriminated, "record_id": matched_rid},
    )


# ═══════════════════════════════════════════════════════════
# 取消资格 / 恢复（规则2/3，恒 observe 人工确认，T06）
# ═══════════════════════════════════════════════════════════

#: 安管人员兜底收件人（取消资格通知；与既有告警口径一致）
ALERT_NOTIFY_OPEN_ID = "ou_495039d6335d347b07ff92ad982b3b4e"


def _revoke_reason(trigger_type: str) -> str:
    """取消原因（拍板④后唯一触发源=考核不合格；逾期静默不催办）。"""
    return "考核不合格"


async def _decided_by(session: Any, mandate: dict[str, Any]) -> str | None:
    """确认人：promoted → decision.resolved_by（照 R1 _resolve_decided_by）。"""
    from app.platform.superagent.models import AgentDecision

    decision_id = mandate.get("promoted_from_decision")
    if decision_id:
        try:
            decision = await session.get(AgentDecision, uuid.UUID(str(decision_id)))
        except ValueError:
            decision = None
        if decision is not None and decision.resolved_by:
            return str(decision.resolved_by)
    return None


async def guardian_qualify_revoke(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """取消资格（observe→promote 后执行）：links→revoked + DM 本人/安管。

    幂等：links 已 revoked → ready 跳过（首见 reason/at 不覆盖）。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.guardian_r2.links import (
        get_or_create_link,
        mark_revoked,
    )
    from app.modules.safety.service.guardian_r2.notify import (
        build_revoke_admin_content,
        build_revoke_content,
    )
    from app.platform.superagent.effects import enqueue_outbox_message

    mandate = task_dict.get("mandate") or {}
    record_id = (mandate.get("origin_actor") or {}).get("id") or ""
    if not record_id:
        return Report(
            kind="failed", end_task=True,
            note="mandate.origin_actor.id 缺失，无法定位持证记录",
        )
    # 恒 observe 护栏（Spec 审查②）：取消资格必须人工确认——auto 模式开的
    # 任务一律拒绝执行（promote 转 */auto 强度为 promoted/inferred 之外的
    # 系统判定均拒）
    if str(mandate.get("strength") or "") != "promoted":
        return Report(
            kind="failed", end_task=True,
            note="取消资格为恒 observe 规则：须人工 promote 确认后执行，"
                 f"auto 模式被拒绝（strength={mandate.get('strength')!r}）",
        )
    task_id = uuid.UUID(str(task_dict["id"]))

    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        derived = dict(payload.get("_derived") or {})
        reason = _revoke_reason(str(derived.get("trigger_type") or ""))

        link, _ = await get_or_create_link(
            session,
            record_id=record_id,
            person_name=str(derived.get("person_name") or ""),
            department=derived.get("department"),
            cert_category=str(derived.get("cert_category") or ""),
            snapshot={"derived": derived},
        )
        confirmed_by = await _decided_by(session, mandate)

        if link.qualification_status != "revoked":
            await mark_revoked(
                session, record_id, reason=reason, revoked_by=confirmed_by
            )
            link.current_node = derived.get("node_key")
            link.node_deadline = (
                date.fromisoformat(derived["deadline"])
                if derived.get("deadline") else None
            )
            if _dm_enabled():
                person_open_id = await resolve_dm_open_id(
                    session,
                    direct_open_id=derived.get("guardian_open_id"),
                    person_name=derived.get("person_name"),
                    department_hint=derived.get("department"),
                )
                if person_open_id:
                    await enqueue_outbox_message(
                        session,
                        conversation=f"guardian_revoke:{record_id}",
                        channel={"type": DM_CHANNEL_TYPE, "open_id": person_open_id},
                        purpose="guardian_qualification_revoke",
                        task_id=task_id,
                        body={
                            "title": "监护人资格取消通知",
                            "content": build_revoke_content(
                                derived.get("person_name"),
                                derived.get("cert_category"), reason,
                                derived.get("node_label"), derived.get("deadline"),
                            ),
                        },
                    )
                await enqueue_outbox_message(
                    session,
                    conversation=f"guardian_revoke_admin:{record_id}",
                    channel={"type": DM_CHANNEL_TYPE, "open_id": ALERT_NOTIFY_OPEN_ID},
                    purpose="guardian_qualification_revoke_admin",
                    task_id=task_id,
                    body={
                        "title": "监护人资格取消（审核确认）",
                        "content": build_revoke_admin_content(
                            derived.get("person_name"), derived.get("department"),
                            derived.get("cert_category"), reason,
                            derived.get("node_label"), derived.get("deadline"),
                            confirmed_by,
                        ),
                    },
                )
            link.error_message = None
        await session.commit()

    logger.info("R2 资格取消: record=%s reason=%s by=%s", record_id, reason, confirmed_by)
    return Report(
        kind="ready", end_task=True,
        output={"record_id": record_id, "reason": reason,
                "qualification_status": "revoked"},
    )


async def guardian_qualify_restore(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """恢复资格（observe→promote 后执行）：links→restored + DM 本人。

    幂等：已 restored → ready 跳过（首见 at/确认人不覆盖）。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.guardian_r2.links import mark_restored
    from app.modules.safety.service.guardian_r2.notify import build_restore_content
    from app.platform.superagent.effects import enqueue_outbox_message

    mandate = task_dict.get("mandate") or {}
    record_id = (mandate.get("origin_actor") or {}).get("id") or ""
    if not record_id:
        return Report(
            kind="failed", end_task=True,
            note="mandate.origin_actor.id 缺失，无法定位持证记录",
        )
    # 恒 observe 护栏：恢复资格必须人工确认（「经审核确认」需求原文）
    if str(mandate.get("strength") or "") != "promoted":
        return Report(
            kind="failed", end_task=True,
            note="恢复资格为恒 observe 规则：须人工 promote 确认后执行，"
                 f"auto 模式被拒绝（strength={mandate.get('strength')!r}）",
        )
    task_id = uuid.UUID(str(task_dict["id"]))

    async with async_session_factory() as session:
        from app.modules.safety.service.guardian_r2.links import get_active_link

        link = await get_active_link(session, record_id)
        if link is None:
            await session.commit()
            return Report(
                kind="failed", end_task=True,
                note=f"links 行不存在（无资格可恢复）: {record_id}",
            )
        payload = await _origin_payload(session, task_dict)
        derived = dict(payload.get("_derived") or {})
        confirmed_by = await _decided_by(session, mandate)

        if link.qualification_status != "restored":
            await mark_restored(session, record_id, confirmed_by=confirmed_by)
            if _dm_enabled():
                open_id = await resolve_dm_open_id(
                    session,
                    direct_open_id=derived.get("guardian_open_id"),
                    person_name=derived.get("person_name"),
                    department_hint=derived.get("department"),
                )
                if open_id:
                    exam_date = (
                        (link.last_score_event or {}).get("exam_date")
                    )
                    await enqueue_outbox_message(
                        session,
                        conversation=f"guardian_restore:{record_id}",
                        channel={"type": DM_CHANNEL_TYPE, "open_id": open_id},
                        purpose="guardian_qualification_restore",
                        task_id=task_id,
                        body={
                            "title": "监护人资格恢复通知",
                            "content": build_restore_content(
                                derived.get("person_name"),
                                derived.get("cert_category"),
                                exam_date, confirmed_by,
                            ),
                        },
                    )
        await session.commit()

    logger.info("R2 资格恢复: record=%s by=%s", record_id, confirmed_by)
    return Report(
        kind="ready", end_task=True,
        output={"record_id": record_id, "qualification_status": "restored"},
    )

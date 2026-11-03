"""alarm_hazard_create 程序执行器 —— R1 转正/自动模式下的建隐患动作。

§9.2 组件映射定案：字段映射 → create_record → links 回填 → outbox 发
P4 结果卡；失败 = Task blocked 可重试。幂等三层之第三道：links 行已有
hazard_record_id → ready 跳过（执行器重跑/重复转正绝不重复建隐患）。

事务边界（spec D10）：本执行器由 run_task_once 在 task 行锁事务外调用
（自开 session）；links 先 commit——Report 落库若在极窗失败，下轮重跑
看到 links 已回填即幂等跳过。执行器内禁止裸 asyncio.create_task（红线③），
外发一律 enqueue outbox。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.platform.superagent.executors import Report

logger = logging.getLogger(__name__)

#: 隐患表「关联报警」列名（P3 a 案；执行器写前幂等 ensure 文本列）
RELATED_ALARM_FIELD = "关联报警"


async def ensure_related_alarm_column(client: Any) -> None:
    """幂等确保隐患主表存在「关联报警」文本列（无则建；已建零请求成本跳过）。"""
    existing = await client.list_fields()
    if any(f.get("field_name") == RELATED_ALARM_FIELD for f in existing or []):
        return
    field = await client.create_field(RELATED_ALARM_FIELD, 1)
    if not field:  # 既有封装失败返回空 dict
        raise RuntimeError(f"ensure 列失败: {RELATED_ALARM_FIELD}")


def _card_chat_id() -> str:
    from app.modules.safety.app_config.store import store

    return (store.get_raw("SAFETY_R1_FIRE_CARD_CHAT_ID") or "").strip()


async def alarm_hazard_create(task_dict: dict[str, Any], inputs: list[dict[str, Any]]) -> Report:
    """建隐患主表记录并回填 links（幂等；外发走 outbox）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.alarm_hazard_r1.field_map import build_hazard_fields
    from app.modules.safety.service.alarm_hazard_r1.links import get_or_create_link
    from app.platform.superagent.effects import enqueue_outbox_message
    from app.platform.superagent.models import AgentTask, AgentTrigger

    mandate = task_dict.get("mandate") or {}
    record_id = (mandate.get("origin_actor") or {}).get("id") or ""
    if not record_id:
        # 编程错误（mandate 缺身份键）不可重试：终态 failed 收尾，防任务永久 open
        return Report(
            kind="failed", end_task=True,
            note="mandate.origin_actor.id 缺失，无法定位报警记录",
        )

    task_id = uuid.UUID(str(task_dict["id"]))
    async with async_session_factory() as session:
        # origin Trigger payload = 报警原文快照（权威来源；mandate 只带身份键）
        task = await session.get(AgentTask, task_id)
        trigger = (
            await session.get(AgentTrigger, task.origin_trigger_id)
            if task is not None and task.origin_trigger_id is not None else None
        )
        payload = dict(trigger.payload or {}) if trigger is not None else {}
        fields = dict(payload.get("fields") or {})
        fingerprint = payload.get("fingerprint")

        link, _ = await get_or_create_link(
            session,
            alarm_domain="fire_alarm", alarm_record_id=record_id,
            alarm_fingerprint=str(fingerprint) if fingerprint else None,
            alarm_snapshot=fields, task_id=task_id,
        )

        # 幂等跳过：已生成过 → ready（重试/重复转正安全）
        if link.hazard_record_id:
            await session.commit()
            return Report(
                kind="ready", end_task=True, note="links 已有 hazard_record_id，幂等跳过",
                output={"hazard_record_id": link.hazard_record_id},
            )

        decided_by = await _resolve_decided_by(session, mandate)

        try:
            client = SafetyBitableClient()
            await ensure_related_alarm_column(client)
            hazard_fields = build_hazard_fields(fields, record_id)
            created = await client.create_record(hazard_fields)
        except Exception as exc:  # noqa: BLE001 — 失败原因统一留痕进 links
            link.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            await session.commit()
            logger.exception("alarm_hazard_create 失败: record=%s", record_id)
            return Report(kind="blocked", note=link.error_message)

        if created is None or not created.get("record_id"):
            link.error_message = "create_record 返回空（见 bitable_client 日志）"
            await session.commit()
            return Report(kind="blocked", note=link.error_message)

        hazard_record_id = str(created["record_id"])
        link.hazard_record_id = hazard_record_id
        link.error_message = None
        link.decided_by = decided_by

        # P4 目标群汇总卡：行内 chat_id 权威；空配置静默跳过（默认关）
        chat_id = _card_chat_id()
        if chat_id:
            await enqueue_outbox_message(
                session,
                conversation=f"r1_fire:{record_id}",
                channel={"type": "feishu_card", "chat_id": chat_id},
                purpose="alarm_hazard_created",
                task_id=task_id,
                body={
                    "title": "报警联动已生成隐患",
                    "content": (
                        f"{hazard_fields.get('隐患描述', '')}\n\n"
                        f"- 关联报警：`fire_alarm:{record_id}`\n"
                        f"- 整改期限：报警日+7d（预填，可改）\n"
                        f"- 处置来源：{decided_by or '—'}"
                    ),
                },
            )
        await session.commit()

    logger.info("R1 联动隐患已创建: alarm=%s hazard=%s", record_id, hazard_record_id)
    return Report(
        kind="ready", end_task=True,
        output={"hazard_record_id": hazard_record_id, "alarm_record_id": record_id},
    )


async def _resolve_decided_by(session: Any, mandate: dict[str, Any]) -> str:
    """处置来源：promoted → decision.resolved_by；否则 mandate.strength（auto/inferred）。"""
    from app.platform.superagent.models import AgentDecision

    decision_id = mandate.get("promoted_from_decision")
    if decision_id:
        try:
            decision = await session.get(AgentDecision, uuid.UUID(str(decision_id)))
        except ValueError:
            decision = None
        if decision is not None and decision.resolved_by:
            return str(decision.resolved_by)
    return str(mandate.get("strength") or "")

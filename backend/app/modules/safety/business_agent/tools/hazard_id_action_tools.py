"""危险源辨识流转执行面（agent-action-p3）：提交 AI 流程 + 节点补触发。

- submit_hazard_identification：draft → in_progress（进入脚本1，AI 七节点
  流转的起点；仅 draft 可提交）
- retry_hazard_identification_node：事件丢失兜底——按当前节点重新推进
  （manual-trigger 同款：跳过 60s 状态级去重，保留 120s 记录级互斥）

工具体不重写业务逻辑：提交复用 SafetyService.submit_hazard_identification，
补触发复用 feishu/hazard_identification_bitable_handler.advance_bitable_record。
定位双态（照二期 report_no/report_id 先例）：平台 UUID / hazard_id_no
（HI-YYYYMMDD-NNN）/ feishu_record_id 三选一。仅 creator。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic_ai import RunContext
from sqlalchemy import or_, select

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

__all__ = ["submit_hazard_identification", "retry_hazard_identification_node"]


async def _resolve_by_ref(db: Any, ref: str) -> Any | None:
    """按 平台 UUID / hazard_id_no / feishu_record_id 定位未删除记录。"""
    from app.modules.safety.models import HazardIdentification

    raw = str(ref).strip()
    id_match = None
    try:
        id_match = HazardIdentification.id == uuid.UUID(raw)
    except ValueError:
        id_match = None
    stmt = select(HazardIdentification).where(
        HazardIdentification.is_deleted == False,  # noqa: E712
        or_(
            id_match,
            HazardIdentification.hazard_id_no == raw,
            HazardIdentification.feishu_record_id == raw,
        ),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def submit_hazard_identification(
    ctx: RunContext[SafetyDeps],
    ref: str,
) -> dict[str, Any]:
    """把危险源辨识草案提交进 AI 流程（draft → in_progress；写操作）。

    仅草稿（draft）状态可提交；提交后进入脚本1（待 AI 解析附件），
    由既有七节点流转（事件驱动）接管。

    Args:
        ref: 辨识记录标识——平台 UUID / 编号（HI-YYYYMMDD-NNN）/ feishu_record_id

    示例：把这条危险源辨识提交 AI 流程。

    注意：此操作会变更记录状态并触发 AI 流转，需要用户确认后才执行；
    确认卡应复述编号、部门与当前状态。
    """
    from app.modules.safety.service.safety import SafetyService

    action = "hazard_identification_submit"
    if not (ref or "").strip():
        return {"success": False, "action": action,
                "message": "请提供辨识记录标识（编号 HI-… 或平台 ID）"}
    item = await _resolve_by_ref(ctx.deps.db, ref)
    if item is None:
        return {"success": False, "action": action,
                "message": f"未找到辨识记录：{ref!r}（可用 query_hazard_identifications 先查编号）"}
    if item.overall_status != "draft":
        return {
            "success": False,
            "action": action,
            "message": f"仅草稿（draft）可提交，当前状态为 {item.overall_status}；已在流程中的记录无需重复提交",
        }
    service = SafetyService(ctx.deps.db)
    updated = await service.submit_hazard_identification(item.id)
    if updated is None:
        return {"success": False, "action": action,
                "message": "提交未生效：记录状态已变化（可能刚被提交），请重新查询确认"}
    await ctx.deps.db.commit()
    return {
        "success": True,
        "action": action,
        "hazard_id_no": updated.hazard_id_no or item.hazard_id_no,
        "department": getattr(updated, "department", None) or getattr(item, "department", None),
        "overall_status": updated.overall_status,
        "ai_node_progress": updated.ai_node_progress,
        "message": "已提交 AI 流程，进入脚本1（待解析附件），后续节点由事件驱动自动流转",
    }


async def retry_hazard_identification_node(
    ctx: RunContext[SafetyDeps],
    ref: str,
) -> dict[str, Any]:
    """危险源辨识节点补触发（事件丢失兜底，重推进当前节点；写操作）。

    与 Web 面板「手动触发」同款：跳过 60s 状态级去重，保留 120s 记录级互斥。
    前提：记录是 Bitable 镜像（有 feishu_record_id）。

    Args:
        ref: 辨识记录标识——平台 UUID / 编号（HI-YYYYMMDD-NNN）/ feishu_record_id

    示例：这条辨识重新触发一下；补触发一下节点。

    注意：此操作会调 AI 并写回 Bitable 与镜像，需要用户确认后才执行；
    确认卡应复述编号、部门与当前节点。
    """
    from app.modules.safety.feishu.hazard_identification_bitable_handler import (
        advance_bitable_record,
    )

    action = "hazard_identification_retry_node"
    if not (ref or "").strip():
        return {"success": False, "action": action,
                "message": "请提供辨识记录标识（编号 HI-… 或平台 ID）"}
    item = await _resolve_by_ref(ctx.deps.db, ref)
    if item is None:
        return {"success": False, "action": action,
                "message": f"未找到辨识记录：{ref!r}"}
    record_id = (item.feishu_record_id or "").strip()
    if not record_id:
        return {
            "success": False,
            "action": action,
            "message": "该记录不是 Bitable 镜像（无 feishu_record_id），无法手动触发；仅平台内创建的镜像记录支持补触发",
        }
    result = await advance_bitable_record(record_id, channel="agent", skip_dedup=True)
    if result.get("status") == "advanced":
        return {
            "success": True,
            "action": action,
            "hazard_id_no": item.hazard_id_no,
            "department": getattr(item, "department", None),
            "status": "advanced",
            "next_node": result.get("next_node"),
            "script": result.get("script"),
            "message": f"已推进到 {result.get('next_node')}（脚本{result.get('script')}）",
        }
    return {
        "success": False,
        "action": action,
        "hazard_id_no": item.hazard_id_no,
        "status": "noop",
        "reason": result.get("reason"),
        "message": result.get("message") or f"未推进（原因：{result.get('reason', 'unknown')}）",
    }

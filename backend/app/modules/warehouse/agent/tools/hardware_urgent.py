"""五金库紧急领用对话工具（制度 5.3.4 先发后补）。

``create_urgent_requisition``：用户对机器人说「紧急领用/抢修领料」（如
「紧急领用 DN25 球阀 2 个，泵体抢修」），LLM 收集物资明细+用途后调用：

- 申请人身份从会话 open_id 反查 identity（姓名/部门自动带出，查不到时
  返回 missing 让 LLM 追问姓名+部门）；
- 物资按 名称+规格（平台唯一键）精确匹配五金库目录；可领量
  （on_hand−reserved）逐项校验，缺货返回 error 如实转告（紧急也领不出
  没有的货）；
- 齐全 → draft_flow.create_dialog_draft（scene=hardware_urgent）→ 确认
  卡片；申请人确认后 submit 回调建 urgent 单（pending 预扣）并发双卡
  （申请人临时单据卡 + 仓管带「发料出库/作废」按钮卡）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.hardware import service as hw_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


def _parse_items(raw: Any) -> tuple[list[dict[str, Any]], str]:
    """LLM 传参 → [{name, spec, qty}]；返回 (items, error)。"""
    if not isinstance(raw, list) or not raw:
        return [], "物资明细（items）不能为空：传 [{name, spec, qty}] 列表"
    items: list[dict[str, Any]] = []
    for i, r in enumerate(raw, 1):
        if not isinstance(r, dict):
            return [], f"第{i}行明细格式错误（须为对象）"
        name = str(r.get("name") or "").strip()
        spec = str(r.get("spec") or "").strip()
        try:
            qty = float(str(r.get("qty")).strip().replace(",", ""))
        except (TypeError, ValueError):
            return [], f"第{i}行数量 {r.get('qty')!r} 不是有效数字，请向用户核对"
        if not name or qty <= 0:
            return [], f"第{i}行缺物资名称或数量非正，请向用户核对"
        items.append({"name": name, "spec": spec, "qty": qty})
    return items, ""


async def _resolve_identity(open_id: str) -> dict[str, str] | None:
    """open_id → identity {name, dept}（identity.feishu_open_id 与仓储应用
    事件同作用域；查不到返回 None，由 LLM 追问姓名/部门）。"""
    from app.platform.identity.models import User

    async with _db_session() as db:
        row = (
            await db.execute(
                select(User.name, User.department).where(
                    User.feishu_open_id == open_id, User.is_deleted.is_(False)
                )
            )
        ).first()
    if row is None:
        return None
    return {"name": row[0], "dept": row[1] or ""}


async def create_urgent_requisition(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """发起五金库紧急领用（先发后补；确认卡片后建单+预扣+通知仓管）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法发起紧急领用"}

    purpose = str((fields or {}).get("purpose") or "").strip()
    missing: list[str] = []
    items, item_err = _parse_items((fields or {}).get("items"))
    if item_err:
        return {"error": item_err}
    if not purpose:
        missing.append("用途（如泵体抢修）")

    person = await _resolve_identity(open_id)
    applicant = person["name"] if person else ""
    dept = person["dept"] if person else ""
    if not applicant:
        missing.insert(0, "申请人姓名（系统未能识别你的身份）")
    if not dept:
        missing.append("领用部门")
    if missing:
        return {
            "status": "incomplete",
            "missing": missing,
            "collected": {"items": items, "purpose": purpose},
            "hint": f"请补充：{'、'.join(missing)}（向用户追问后再调用本工具，不要猜测）",
        }

    # 物资匹配 + 可领量校验（缺货如实转告，不建草稿）
    try:
        async with _db_session() as db:
            checked: list[dict[str, Any]] = []
            for it in items:
                material = await hw_service.find_material_by_name_spec(
                    db, it["name"], it["spec"]
                )
                if material is None:
                    return {
                        "error": (
                            f"物资不匹配：{it['name']} | {it['spec'] or '（无规格）'}"
                            "（须与五金库目录的名称+规格完全一致，请让用户核对后重报）"
                        )
                    }
                available = await hw_service.available_of_material(db, material.id)
                if float(available) < it["qty"]:
                    return {
                        "error": (
                            f"{material.name} {material.spec or ''} 可领量 "
                            f"{float(available):g} {material.unit}，不足 {it['qty']:g}，"
                            "无法发起紧急领用（请如实转告并停止）"
                        ),
                        "error_code": "insufficient_stock",
                    }
                checked.append({**it, "unit": material.unit})

            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.HARDWARE_URGENT_SCENE,
                fields={
                    "items": checked,
                    "purpose": purpose,
                    "dept": dept,
                    "applicant": applicant,
                    "applicant_open_id": open_id,
                },
                open_id=open_id,
                chat_id=chat_id,
            )
            await draft_flow.send_confirm_card(db, draft, chat_id=chat_id, open_id=open_id)
            draft_no = draft.draft_no
    except Exception as exc:  # noqa: BLE001 — 创建失败不中断 Runner
        logger.exception("紧急领用草稿创建失败: open_id=%r", open_id[:20])
        return {"error": f"紧急领用草稿创建失败: {type(exc).__name__}: {exc}"}

    logger.info("紧急领用草稿已创建: draft_no=%s items=%d", draft_no, len(checked))
    return {
        "status": "pending_confirm",
        "draft_no": draft_no,
        "items": checked,
        "message": (
            f"已创建紧急领用草稿 {draft_no} 并发送确认卡片（10 分钟内有效）。"
            "请提醒申请人核对物资明细后点「确认发起」；确认后系统建立紧急领料单"
            "（预扣库存）并通知仓管员发料，领料后须 24 小时内提交正式领料审批补办。"
        ),
    }


HARDWARE_URGENT_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_urgent_requisition": create_urgent_requisition,
}

HARDWARE_URGENT_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_urgent_requisition",
            "description": (
                "发起五金库紧急领用（先领用后补单，生产抢修等紧急情况；用户说"
                "「紧急领用/紧急领料/抢修领料」时用，普通领料走 create_picking_draft）。"
                "收集物资明细（名称+规格须与五金库目录完全一致）与用途；可领量不足时"
                "返回 error 如实转告并停止。创建成功后系统发送确认卡片，申请人确认后"
                "建紧急领料单并通知仓管员发料，领料后 24 小时内须提交正式领料审批补办。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。items=[{name(物资名称), spec(规格型号),"
                            " qty(数量,纯数字)}]（至少一行）、purpose(用途，如"
                            "「泵体抢修」) 必收；申请人姓名/部门自动识别，识别不到时"
                            "系统会返回 missing 请向用户追问"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]

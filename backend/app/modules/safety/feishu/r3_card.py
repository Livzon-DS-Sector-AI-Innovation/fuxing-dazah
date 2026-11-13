"""R3 诊断卡回调 —— card.action.trigger「一键执行」路由（T6 2026-11-13）。

挂在 business_agent_bot_handler.handle_card_action 路由链尾部（scope
路由模式，对齐例外复核卡/遥测报警卡）。回调不重试红线：本模块只做
「value 解析 → 操作者权限校验 → 共用服务核心 → 同步返回卡片更新」，
2.9s 内返回（event_client ACK 契约）。

服务逻辑复用点：判定核心=window_guard.execute_window_extend（REST
extend-window 同源，防两处漂移）。payload 的 ticket_id/value 是不可信
数据——授权判定只看操作者身份（open_id → 用户 → permission:role:manage），
与 REST RequireAdmin 对等。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _parse_value(raw: Any) -> dict[str, Any] | None:
    """按钮 value 兼容 dict / 双重编码 JSON str（对齐 handle_card_action）。"""
    payload = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
            if isinstance(payload, str):
                payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


async def _operator_is_admin(open_id: str) -> bool:
    """回调操作者 admin 校验（与 REST RequireAdmin 同一权限链）。"""
    if not open_id:
        return False
    try:
        from app.core.database import async_session_factory
        from app.platform.identity.repository import UserRepository
        from app.platform.permission.deps import get_user_permissions
        from app.platform.permission.repository import PermissionRepository

        async with async_session_factory() as session:
            user = await UserRepository().get_by_feishu_open_id(session, open_id)
            if user is None:
                return False
            perms = await get_user_permissions(str(user.id), session)
            return "permission:role:manage" in perms
    except Exception:  # noqa: BLE001 — 权限校验失败即拒绝（fail-closed）
        logger.exception("R3 卡片回调权限校验异常（拒绝）: open_id=%s", open_id)
        return False


async def _apply_window_extend(ticket_id: str, operator_open_id: str) -> dict[str, Any]:
    """共用服务核心的会话包装（权限已在上层校验过）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.api.ops_selfheal import _get_ticket_or_404
    from app.modules.safety.service.ops_selfheal_r3.window_guard import (
        execute_window_extend,
    )

    async with async_session_factory() as session:
        task = await _get_ticket_or_404(session, ticket_id)
        result = await execute_window_extend(
            session, task, None, operator=f"admin(card):{operator_open_id[:16]}",
        )
        await session.commit()
        return result


def handle_r3_card_action(payload: Any) -> None:
    """同步壳（value 预检；真实路由走 async 版本）。"""
    _parse_value(payload)  # 解析失败静默（回调不重试红线）


async def handle_r3_card_action_async(payload: Any) -> dict[str, Any] | None:
    """真正的回调入口（business_agent_bot_handler 路由链挂载点）。"""
    value = _parse_value(payload)
    if not value or value.get("scope") != "r3_selfheal":
        return None
    action = str(value.get("action") or "")
    ticket_id = str(value.get("ticket_id") or "")
    if action != "window_extend" or not ticket_id:
        logger.warning("R3 卡片回调未知动作/缺 ticket_id，忽略: %r", value)
        return None

    # 操作者权限校验（payload 不参与授权——open_id 只作身份识别）
    operator_open_id = str(
        (payload if isinstance(payload, dict) else {}).get("operator_open_id")
        or _extract_operator(value)
    )
    if not await _operator_is_admin(operator_open_id):
        logger.warning("R3 卡片回调拒绝（非管理员）: open_id=%s", operator_open_id)
        return _build_update_card("", False, "原因：仅管理员可一键执行")

    try:
        result = await _apply_window_extend(ticket_id, operator_open_id)
    except Exception as exc:  # noqa: BLE001 — 回调不重试红线：失败也返回卡片
        logger.exception("R3 一键执行回调异常: ticket=%s", ticket_id)
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "job_name": ""}

    if result.get("ok"):
        detail = (f"当日补发窗口：{result['old_window']} → {result['new_window']}\n"
                  "说明：仅当日生效（进程内覆写，服务重启即失效）")
    else:
        cur = result.get("current_window") or ""
        detail = f"原因：{result.get('reason')}"
        if cur:
            detail += f"（现截止 {cur}）"
    job_name = str(result.get("job_name") or "")
    return _build_update_card(job_name, bool(result.get("ok")), detail)


def _extract_operator(value: dict[str, Any]) -> str:
    """从 value 提取操作者 open_id（飞书回调会在按钮 value 外附 operator）。

    value 本身是构建时静态内容，不含 operator——真实回调操作者在
    event_data.operator；本函数只兜底 value 里可能附带的 operator 字段
    （测试/手工构造场景）。
    """
    op = value.get("operator")
    if isinstance(op, dict):
        return str(op.get("open_id") or op.get("user_id") or "")
    return str(op or "") if op else ""


def _build_update_card(job_name: str, ok: bool, detail: str) -> dict[str, Any] | None:
    """构建回调同步返回的卡片更新体（单测桩路径与真实路径共用）。"""
    from app.modules.safety.feishu.notification import build_card_dict

    head = "【R3 L2 窗口延长 ✅】一键执行成功" if ok else "【R3 L2 窗口延长 ❌】一键执行未生效"
    text = f"{head}\n任务：{job_name}\n{detail}" if job_name else f"{head}\n{detail}"
    return build_card_dict(
        "R3 一键执行成功" if ok else "R3 一键执行未生效",
        text,
        header_template="green" if ok else "red",
    )

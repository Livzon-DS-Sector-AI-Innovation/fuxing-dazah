"""URS 智能审核 — 飞书卡片构建与回调处理（卡片 JSON 2.0）。

通知对象仅申请人（D8）；卡片回调挂载在 business_agent_bot_handler.card.action.trigger，
通过 payload["scope"] == "urs" 路由到 handle_urs_card_action。

卡片更新约定（2026-09-14 仓库机器人点击实测，本模块同机制）：WS 回调响应里
携带卡片更新不生效，统一改「纯 ACK + PATCH 原卡」（message_id 取回调事件
context.open_message_id）；toast 仅作锦上添花（生效则展示，不生效无碍）。
"""

import asyncio
import logging
import uuid
from typing import Any

from app.modules.safety.feishu.notification import (
    build_card_dict,
    button_row,
    send_user_card,
)

logger = logging.getLogger(__name__)

# 风险等级 → emoji
_RISK_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
_DIM_LABELS = {
    "mechanical": "机械", "electrical": "电气", "data": "数据",
    "environmental": "环境", "chemical": "化学",
}
_APPLICABILITY_EMOJI = {"mandatory": "🔴", "recommended": "🟡", "not_applicable": "❌"}


def _btn(value: dict, text: str, btn_type: str = "default") -> dict:
    """构建卡片按钮。value 与 behaviors[type=callback].value 双写同值
    （2.0 字段表首选 behaviors，旧式 value 仍被事件回传——回调解析两侧兼容）。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _action_row(*buttons: dict) -> dict:
    return button_row(*buttons)


def _patch_message_id(event_data: dict) -> str:
    """回调事件中的原卡 message_id（2.0 事件在 context）。"""
    context = event_data.get("context") or {}
    return str(context.get("open_message_id") or "")


async def _patch_card(event_data: dict, card: dict) -> None:
    """PATCH 替换回调来源卡片为 card（失败仅告警，不阻断回调）。"""
    from app.modules.safety.feishu.notification import update_card

    msg_id = _patch_message_id(event_data)
    if not msg_id:
        logger.warning("URS 卡片回调缺少 context.open_message_id，跳过卡片更新")
        return
    ok = await update_card(msg_id, card)
    if not ok:
        logger.warning("URS 卡片 PATCH 失败: message_id=%s", msg_id)


# ════════════════════════════════════════════════════════════════
# 内容构建
# ════════════════════════════════════════════════════════════════


def build_assessment_card(report: Any) -> dict:
    """评估结果卡（五维画像 + 综合等级 + 置信度）。"""
    risk = report.overall_risk_level or "low"
    emoji = _RISK_EMOJI.get(risk, "🟢")
    profile = report.risk_profile or {}

    lines = [
        f"设备类别：{report.equipment_category or '—'}｜申请部门：{report.department or '—'}",
        "———",
        "**五维风险画像**",
    ]
    for key, label in _DIM_LABELS.items():
        dim = profile.get(key) or {}
        level = dim.get("level", "low")
        indicators = "、".join(dim.get("indicators") or []) or "无"
        lines.append(f"{_RISK_EMOJI.get(level, '⚪')} {label}风险={level}（{indicators}）")
    lines.append("———")
    lines.append(f"**综合风险：{emoji} {risk}** ｜ 置信度 {int((report.ai_confidence or 0) * 100)}%")

    if report.review_status == "human_review":
        lines.append("⚠️ 置信度不足，需人工复核风险画像。")

    elements = [_action_row(
        _btn({"scope": "urs", "action": "urs_view", "urs_id": str(report.id)}, "查看详情", "primary"),
    )]
    if report.review_status == "human_review":
        elements.append(_action_row(
            _btn({"scope": "urs", "action": "urs_confirm", "urs_id": str(report.id)}, "✅ 确认画像", "primary"),
            _btn({"scope": "urs", "action": "urs_appeal", "urs_id": str(report.id)}, "✏️ 修正画像"),
        ))
    return build_card_dict(
        f"{emoji} URS 审核结果：{report.equipment_name}",
        "\n".join(lines),
        header_template="blue",
        elements=elements,
    )


def build_conclusion_card(report: Any) -> dict:
    """结论卡（评分/等级/结论/整改要求）。"""
    grade = report.grade or "—"
    conclusion = report.conclusion or "—"
    cn = "✅ 通过" if conclusion == "approved" else "❌ 不通过"
    lines = [
        f"设备：{report.equipment_name}｜类别：{report.equipment_category or '—'}",
        "———",
        f"**评分：{report.score if report.score is not None else '—'} 分（{grade} 级）**",
        f"**结论：{cn}**",
    ]
    reqs = report.rectification_requirements or []
    if reqs:
        lines.append("———")
        lines.append(f"**整改要求（{len(reqs)} 项）**")
        for i, req in enumerate(reqs[:5], 1):
            lines.append(f"{i}. {req.get('requirement') or req.get('item_no')}")
        if len(reqs) > 5:
            lines.append(f"… 等共 {len(reqs)} 项，详见报告")
    summary = report.review_result.get("summary") if report.review_result else None
    if summary:
        lines.append("———")
        lines.append(summary)

    elements = [_action_row(
        _btn({"scope": "urs", "action": "urs_view", "urs_id": str(report.id)}, "查看详情", "primary"),
    )]
    if conclusion == "rejected":
        elements.append(_action_row(
            _btn({"scope": "urs", "action": "urs_appeal", "urs_id": str(report.id)}, "提交申诉"),
        ))
    return build_card_dict(
        f"URS 审核结论：{report.equipment_name}",
        "\n".join(lines),
        header_template="orange" if conclusion == "rejected" else "green",
        elements=elements,
    )


def build_appeal_result_card(report: Any) -> dict:
    """申诉重评结果卡（新旧画像对比 + 调整依据）。"""
    appeal = report.appeal_result or {}
    old_overall = appeal.get("old_overall") or "?"
    new_overall = report.overall_risk_level or "?"
    lines = [
        f"设备：{report.equipment_name}",
        "———",
        f"**申诉理由**：{report.appeal_reason or '—'}",
        "———",
        f"**风险画像调整**：{_RISK_EMOJI.get(old_overall, '⚪')} {old_overall} → {_RISK_EMOJI.get(new_overall, '⚪')} {new_overall}",
        f"**调整依据**：{appeal.get('basis') or '重新评估完成'}",
        f"**当前状态**：{report.review_status}",
    ]
    return build_card_dict(
        f"URS 申诉结果：{report.equipment_name}",
        "\n".join(lines),
        header_template="purple",
        elements=[
            _action_row(_btn({"scope": "urs", "action": "urs_view", "urs_id": str(report.id)}, "查看详情", "primary")),
        ],
    )


# ════════════════════════════════════════════════════════════════
# 主动通知（URSService 调用，仅申请人）
# ════════════════════════════════════════════════════════════════


async def notify_assessment_result(report: Any) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_assessment_card(report)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


async def notify_conclusion(report: Any) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_conclusion_card(report)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


async def notify_appeal_result(report: Any) -> bool:
    if not report.applicant_open_id:
        return False
    card = build_appeal_result_card(report)
    body = card["body"]["elements"]
    return await send_user_card(
        open_id=report.applicant_open_id,
        title=card["header"]["title"]["content"],
        content=str(body[0].get("content") or ""),
        elements=body[1:],
    )


# ════════════════════════════════════════════════════════════════
# 卡片回调（card.action.trigger，payload["scope"] == "urs"）
# ════════════════════════════════════════════════════════════════


async def handle_urs_card_action(payload: dict, event_data: dict) -> dict | None:
    """处理 URS 卡片按钮回调：执行动作后 PATCH 原卡，返回纯 ACK（None）。"""
    action = payload.get("action")
    urs_id_raw = payload.get("urs_id")
    if not action or not urs_id_raw:
        return None
    try:
        report_id = uuid.UUID(urs_id_raw)
    except (ValueError, TypeError):
        return None

    if action == "urs_view":
        return await _show_detail(report_id, event_data)
    if action == "urs_confirm":
        return await _confirm_assessment(report_id, event_data)
    if action == "urs_appeal":
        return _show_appeal_input(report_id, event_data)
    if action == "urs_appeal_confirm":
        reason = payload.get("reason") or ""
        asyncio.create_task(_run_appeal_background(report_id, reason))
        await _patch_card(
            event_data,
            build_card_dict(
                "URS 申诉处理中",
                "正在重新评估风险画像与标准适配，完成后将推送结果。",
                header_template="purple",
            ),
        )
        return {"toast": {"type": "success", "content": "申诉已受理，正在重新评估..."}}
    return None


async def _fetch_report(report_id: uuid.UUID):
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        from app.modules.safety.service.ehs_change.urs import URSService

        return await URSService(db).get_report(report_id)


async def _show_detail(report_id: uuid.UUID, event_data: dict) -> dict | None:
    report = await _fetch_report(report_id)
    if report is None:
        return {"toast": {"type": "error", "content": "记录不存在"}}
    card = build_conclusion_card(report) if report.conclusion else build_assessment_card(report)
    await _patch_card(event_data, card)
    return None


async def _confirm_assessment(report_id: uuid.UUID, event_data: dict) -> dict | None:
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            from app.modules.safety.service.ehs_change.urs import URSService

            report = await URSService(db).confirm_assessment(report_id)
            await db.commit()
        if report is None:
            return {"toast": {"type": "error", "content": "记录不存在"}}
        await _patch_card(event_data, build_assessment_card(report))
        return None
    except ValueError as e:
        return {"toast": {"type": "error", "content": str(e)}}


def _show_appeal_input(report_id: uuid.UUID, event_data: dict) -> dict | None:
    """展示带输入框的申诉卡（输入理由 → 确认申诉），PATCH 替换原卡。"""
    card = build_card_dict(
        "提交申诉",
        "请填写申诉理由（如设备实际不涉及某项风险）：",
        header_template="purple",
        elements=[
            {
                "tag": "input",
                "name": "reason",
                "label": {"tag": "plain_text", "content": "申诉理由"},
                "placeholder": {"tag": "plain_text", "content": "请输入申诉理由"},
            },
            _action_row(
                _btn({"scope": "urs", "action": "urs_appeal_confirm", "urs_id": str(report_id)}, "✅ 确认申诉", "primary"),
            ),
        ],
    )
    # input 值经 form 提交才随回调返回；此处仅展示，申诉理由由
    # urs_appeal_confirm 的 value.reason（前端回填）或后续表单提交携带
    asyncio.create_task(_patch_card(event_data, card))
    return {"toast": {"type": "success", "content": "请填写理由"}}


async def _run_appeal_background(report_id: uuid.UUID, reason: str) -> None:
    """后台执行申诉重评（Step1+2），完成后自动推送申诉结果卡。"""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            from app.modules.safety.service.ehs_change.urs import URSService

            await URSService(db).submit_appeal(report_id, reason)
            await db.commit()
        logger.info("URS 申诉重评完成: report_id=%s", report_id)
    except Exception:
        logger.exception("URS 申诉重评失败: report_id=%s", report_id)

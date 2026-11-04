"""五金库 agent 对话入库链（M2：发照片→草稿回显→两段式确认卡）。

复用 warehouse_agent_drafts + confirm_requests 确认门体系（scene=
hardware_receipt 注册在 draft_flow.SCENE_CONFIG）：图片消息带五金意图
（用户文本含「五金」）时由 gateway 路由到本链——下载图→OCR 识别→四级
匹配→hardware_receipts 草稿（不动账）→AgentDraft（aligned 存草稿引用）
→确认卡。确认后 draft_flow 后台执行 agent_submit.submit_hardware_receipt
真入账。
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from app.modules.warehouse.agent.cards import build_card
from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.feishu import media

logger = logging.getLogger(__name__)

HARDWARE_INTENT_KEYWORDS = ("五金",)
SUPPORTED = ("jpeg", "png")


def has_hardware_intent(user_text: str) -> bool:
    """图片消息附带文本是否表达五金入库意图（「五金入库」/「五金库」+图）。"""
    return any(kw in (user_text or "") for kw in HARDWARE_INTENT_KEYWORDS)


async def process_hardware_image(
    *,
    chat_id: str,
    chat_type: str,
    open_id: str,
    message_id: str,
    image_key: str,
    user_text: str = "",
    msg_type: str = "post",
    started: float | None = None,
) -> None:
    """五金送货单图片处理（gateway 派发，独立 DB 会话自管提交）。"""
    started = started or time.monotonic()
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as db:
            # ① 下载+格式探测（bytes 契约与原辅料链一致；仅 jpeg/png 可识别）
            image_bytes = await media.download_im_image(message_id, image_key)
            fmt = media.sniff_image_format(image_bytes)
            if fmt not in SUPPORTED:
                raise ValueError(
                    f"图片格式 {fmt} 不支持（仅 JPEG/PNG），请重拍或改用 Web 端手动登记"
                )
            content_type = f"image/{'jpeg' if fmt == 'jpeg' else 'png'}"
            image_b64 = base64.b64encode(image_bytes).decode()

            # ② 识别→四级匹配→入库草稿（receipt_pipeline；红线：只产 draft）
            from app.modules.warehouse.hardware.receipt_pipeline import (
                ScenarioDisabled,
                build_ocr_draft,
            )

            receipt, summary = await build_ocr_draft(
                db,
                image_b64=image_b64,
                content_type=content_type,
                operator=open_id,
            )

            # ③ AgentDraft（scene=hardware_receipt，aligned=入库草稿引用）
            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.HARDWARE_RECEIPT_SCENE,
                fields={
                    "receipt_id": str(receipt.id),
                    "receipt_no": receipt.receipt_no,
                    "supplier": receipt.supplier_name,
                    "mode": receipt.mode,
                    "target_dept": receipt.target_dept,
                    "rows": summary["rows"],
                },
                open_id=open_id,
                chat_id=chat_id,
            )
            await db.commit()

            # ④ 确认卡（两段式确认门；TTL/防重复点击/PATCH 机制全继承）
            await draft_flow.send_confirm_card(db, draft, chat_id=chat_id, open_id=open_id)
            await db.commit()
            logger.info(
                "五金图片入库草稿已回显: draft=%s receipt=%s rows=%d unmatched=%d cost=%.1fs",
                draft.draft_no, receipt.receipt_no, len(summary["rows"]),
                summary["unmatched"], time.monotonic() - started,
            )
    except ScenarioDisabled as exc:
        await _reply_failure(chat_id, open_id, f"五金送货单识别已停用：{exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("五金图片入库处理失败")
        await _reply_failure(
            chat_id, open_id,
            f"识别失败（{exc}）。请重拍清晰照片重试，或到 Web 端「五金出入库」手动登记。",
        )


async def _reply_failure(chat_id: str, open_id: str, reason: str) -> None:
    from app.modules.warehouse.feishu import notification

    card = build_card(
        title="⚠️ 五金入库未完成",
        template="red",
        elements=[{"tag": "markdown", "content": reason}],
    )
    try:
        if chat_id:
            await notification.send_card(chat_id, card)
        else:
            await notification.send_card_to_user(open_id, card)
    except Exception:  # noqa: BLE001
        logger.exception("五金入库失败回执发送异常")

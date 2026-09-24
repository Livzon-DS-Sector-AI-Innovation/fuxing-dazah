"""飞书机器人自定义菜单点击事件处理器。

开发者后台「机器人自定义菜单」中配置了「推送事件」动作的菜单项，
用户点击时开放平台推送 event_type=application.bot.menu_v6（v2 格式），
本处理器按 event_key（后台菜单配置的自定义标识）给点击人私发引导卡片，
把用户导向对应功能的真实入口（URS 对话上传 / MSDS 采集表上传）。

约束：菜单仅支持单聊，operator.open_id 必带；事件在 WS 通道异步分发，
不阻塞 3 秒 ACK，可放心 await 发送。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.feishu.notification import send_user_card

logger = logging.getLogger(__name__)

# MSDS 采集入口（registry: msds/collection 默认连接）
_MSDS_COLLECTION_URL = (
    "https://open.feishu.cn/base/MAzwb6JWzaA4MPswdqacyo0XnSf"
    "?table=tbliik0SMjj81wTv"
)

_URS_GUIDE_TEXT = (
    "**使用方式**：直接把 URS 文档（.docx/.pdf）发送到本对话，"
    "AI 自动完成评估并回传结论卡片与 PDF 审核报告。\n\n"
    "> 💡 Word 文档（.docx）直接发送即可；**PDF 请在点击本菜单后 30 分钟内发送**"
    "（PDF 也用于职业健康归档，靠菜单点击区分用途）。\n\n"
    "**评估内容（全自动）**\n"
    "1. 解析文档 → 生成 URS 编号与条款\n"
    "2. AI 五维风险画像（机械/电气/数据/环境/化学）+ 置信度\n"
    "3. 可靠性评估：适配清单（强制/建议/不适用）+ 否决项\n"
    "4. 出结论：评分 + 等级 + 整改要求 → PDF 审核报告\n\n"
    "- 审核结论为 AI 辅助判断，仅供参考\n"
    "- 结果只通知申请人本人，可在对话中查看详情"
)

_MSDS_GUIDE_TEXT = (
    "**使用方式**：点下方按钮打开「供应商资料」采集表，新增一行并上传"
    "原始 MSDS 附件后，平台会自动：\n\n"
    "1. 下载附件 → AI 提取 28 个字段（按化学品拆分）\n"
    "2. 生成 MSDS 台账记录（收录台账表）\n"
    "3. 自动纳入知识库检索（供法规问答引用）\n\n"
    "> 一份资料含多个化学品时，AI 会按物质拆分生成多条记录。"
)


def _link_button(text: str, url: str, btn_type: str = "primary") -> dict[str, Any]:
    """schema 2.0 卡片跳转按钮。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": btn_type,
        "url": url,
    }


@on_event("application.bot.menu_v6")
async def _on_menu_click(event: dict[str, Any]) -> None:
    """处理机器人自定义菜单点击事件（仅单聊）。"""
    event_key = str(event.get("event_key", ""))
    operator = event.get("operator") or {}
    open_id = (operator.get("operator_id") or {}).get("open_id", "")

    if not open_id:
        logger.warning("菜单点击事件缺少 operator.open_id: event_key=%s", event_key)
        return

    if event_key == "urs_review":
        # 记录 URS 上传意图（30 分钟窗口内该用户私聊发来的 PDF 按优先 URS 路由）
        from app.modules.safety.feishu.urs_upload_context import set_urs_upload_context

        set_urs_upload_context(open_id)
        ok = await send_user_card(
            open_id,
            "📑 URS 智能审核",
            _URS_GUIDE_TEXT,
            header_template="blue",
        )
    elif event_key == "msds_create":
        ok = await send_user_card(
            open_id,
            "🧪 MSDS 创建",
            _MSDS_GUIDE_TEXT,
            elements=[_link_button("📥 前往供应商资料表", _MSDS_COLLECTION_URL)],
            header_template="green",
        )
    else:
        logger.warning("未知菜单 event_key=%s（open_id=%s）", event_key, open_id)
        return

    logger.info("菜单引导卡片发送: event_key=%s open_id=%s ok=%s", event_key, open_id, ok)

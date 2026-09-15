"""质量模块飞书消息发送（发群文本/卡片，机器人身份）。"""

import json
import logging

from app.modules.quality.feishu.client import build_client

logger = logging.getLogger(__name__)


async def send_chat_text(chat_id: str, text: str) -> None:
    """向群发送纯文本消息（机器人身份）。"""
    client = build_client()
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("质量飞书发消息失败: %s", resp.msg)


async def send_interactive_card(chat_id: str, card: dict) -> None:
    """向群发送交互式卡片（机器人身份）。card 为飞书卡片 JSON。"""
    client = build_client()
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("质量飞书发卡片失败: %s", resp.msg)


async def send_alert_post(
    chat_id: str, at_open_ids: list[str], title: str, lines: list[str]
) -> None:
    """发 post 消息提醒（可 @ 指定用户 open_id；列表为空则纯文本）。"""
    client = build_client()
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    content_blocks: list[list[dict]] = []
    if at_open_ids:
        content_blocks.append([{"tag": "at", "user_id": uid} for uid in at_open_ids])
    content_blocks.append([{"tag": "text", "text": "\n".join(lines)}])
    body = {"zh_cn": {"title": title, "content": content_blocks}}
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("post")
            .content(json.dumps(body, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("质量飞书发提醒失败: %s", resp.msg)


async def send_user_interactive_card(open_id: str, card: dict) -> None:
    """向指定用户单聊发送交互式卡片（机器人身份）。"""
    client = build_client()
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    req = (
        CreateMessageRequest.builder()
        .receive_id_type("open_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type("interactive")
            .content(json.dumps(card, ensure_ascii=False))
            .build()
        )
        .build()
    )
    resp = await client.im.v1.message.acreate(req)
    if not resp.success():
        logger.error("质量飞书发单聊卡片失败: %s", resp.msg)


async def get_chat_id_of_message(message_id: str) -> str | None:
    """按消息 ID 反查所属群 chat_id（schema 2.0 卡片事件的 context 可能不含 chat_id）。"""
    client = build_client()
    from lark_oapi.api.im.v1 import GetMessageRequest

    req = GetMessageRequest.builder().message_id(message_id).build()
    resp = await client.im.v1.message.aget(req)
    if resp.success() and resp.data and resp.data.items:
        return resp.data.items[0].chat_id
    return None


_LAST_FILL_CARD: dict[str, dict] = {}


def build_fill_card(
    batch: str,
    groups: list[tuple[str, list[dict], bool, str | None]],
) -> dict:
    """构建分组填报表单卡片。

    groups: [(组名, [{label, map_value}], 是否已提交, 已提交摘要文本)]。
    label 含 SOP 号与限度；map_value 为结果行 ID 的 JSON 列表（相同 SOP 合并组）。
    已提交的组用确认文本行替代表单区（提交后卡片原地更新，落库状态一眼可辨）。
    """
    body_elements: list[dict] = [
        {"tag": "markdown", "content": "填写各项目数值后点提交，系统按标准限度自动判定；相同 SOP 号合并为一项，填一次自动匹配全部。"},
    ]
    name_map: dict[str, str] = {}
    for gi, (title, rows, submitted, submitted_text) in enumerate(groups):
        body_elements.append({"tag": "markdown", "content": f"**{title}**"})
        if submitted:
            body_elements.append({
                "tag": "markdown",
                "content": submitted_text or f"✅ {title}已提交",
            })
            continue
        if not rows:
            body_elements.append({"tag": "markdown", "content": "✅ 无待填项目"})
            continue
        inputs = []
        for i, r in enumerate(rows):
            key = f"g{gi}_item_{i}"
            name_map[key] = r["map_value"]
            inputs.append({
                "tag": "input",
                "name": key,
                "label": {"tag": "plain_text", "content": r["label"]},
                "required": True,
            })
        body_elements.append({
            "tag": "form",
            "name": f"fill_form_{gi}",
            "elements": inputs + [
                {"tag": "button", "action_type": "form_submit", "name": f"submit_{gi}",
                 "text": {"tag": "lark_md", "content": f"**提交{title}**"},
                 "type": "primary",
                 "value": {"action": "fill_form", "batch": batch, "group": gi, "map": name_map}},
            ],
        })
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"检验填报 {batch}"}, "template": "blue"},
        "body": {"elements": body_elements},
    }


def get_last_fill_card(batch: str) -> dict | None:
    """取最近一次发送的填报卡片（用于提交后原地更新）。"""
    return _LAST_FILL_CARD.get(batch)


async def send_fill_card(chat_id: str, batch: str, groups: list[tuple[str, list[dict]]]) -> None:
    """发送填报表单卡片（每组一个 form 容器）。groups: [(组名, [{item_name, limit_text}])]。"""
    built = build_fill_card(batch, [(t, r, False, None) for t, r in groups])
    if not any(g[1] for g in groups):
        await send_chat_text(chat_id, f"✅ 批号 {batch} 的数值型项目已全部填写，无待填项")
        return
    _LAST_FILL_CARD[batch] = built
    await send_interactive_card(chat_id, built)


async def send_create_task_card(chat_id: str, batch: str, docs: list[dict]) -> None:
    """建任务表单卡片：批号已自动识别产品代号并选定标准文件（可多份，一个批号可开多份报告单），
    只需补生产日期/规格/出报日期，提交后创建任务并自动推填报卡片。"""
    doc_lines = "\n".join(f"- {d.get('file_no') or ''}" for d in docs)
    doc_ids = [d.get("id") for d in docs if d.get("id")]
    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"新建检验任务 {batch}"}, "template": "green"},
        "body": {
            "elements": [
                {"tag": "markdown", "content": f"批号已识别产品代号 **{docs[0].get('product_code') or '-'}**，标准文件（{len(docs)} 份）：\n{doc_lines}\n填写以下信息后提交。出报日期为今天时立即推送填报卡片；为未来日期时当天自动推送；不填则不推送。"},
                {
                    "tag": "form",
                    "name": "create_task_form",
                    "elements": [
                        {"tag": "input", "name": "prod_date",
                         "label": {"tag": "plain_text", "content": "生产日期（如 2026.01.01，支持 - / . 分隔）"},
                         "required": True},
                        {"tag": "input", "name": "spec",
                         "label": {"tag": "plain_text", "content": "规格（留空自动取默认）"},
                         "required": False},
                        {"tag": "input", "name": "report_date",
                         "label": {"tag": "plain_text", "content": "出报日期（可选，支持 2026.01.01 格式，出报当天机器人推送提醒）"},
                         "required": False},
                        {"tag": "button", "action_type": "form_submit", "name": "submit_create",
                         "text": {"tag": "lark_md", "content": "**创建任务**"},
                         "type": "primary",
                         "value": {"action": "create_task", "batch": batch, "doc_ids": doc_ids}},
                    ],
                },
            ]
        },
    }
    await send_interactive_card(chat_id, card)


def build_pick_doc_card(
    batch: str, docs: list[dict], selected_ids: set[str], notice: str = ""
) -> dict:
    """多选标准文件卡片：输入编号查询累加选择（支持模糊，可反复搜索），文件少时也可点按钮勾选。

    selected_ids 为已选 doc_id 集合；notice 为查询未匹配等提示文本。
    """
    intro = (
        f"批号 {batch} 识别到产品代号 **{docs[0].get('product_code') or '-'}**，"
        f"该代号下共 {len(docs)} 份标准文件。"
    )
    elements: list[dict] = []
    if notice:
        elements.append({"tag": "markdown", "content": notice})
    elements.append({"tag": "markdown", "content": intro + "输入编号查询并累加选择（可模糊，如 3205；多个用顿号/逗号/空格分隔，可多次搜索）："})
    elements.append({
        "tag": "form",
        "name": "doc_query_form",
        "elements": [
            {"tag": "input", "name": "doc_query",
             "label": {"tag": "plain_text", "content": "标准文件编号（多个分隔）"},
             "required": True},
            {"tag": "button", "action_type": "form_submit", "name": "submit_doc_query",
             "text": {"tag": "lark_md", "content": "**查询并加入选择**"},
             "type": "primary",
             "value": {"action": "doc_query_submit", "batch": batch}},
        ],
    })
    if selected_ids:
        selected_file_nos = [d.get("file_no") for d in docs if (d.get("id") or "") in selected_ids]
        elements.append({"tag": "markdown", "content": f"已选 **{len(selected_ids)}** 份：{'、'.join(selected_file_nos)}"})
        elements.append({
            "tag": "button",
            "text": {"tag": "lark_md", "content": f"**下一步（已选 {len(selected_ids)} 份）**"},
            "type": "primary",
            "value": {"action": "doc_confirm", "batch": batch},
        })
        elements.append({
            "tag": "button",
            "text": {"tag": "lark_md", "content": "清空选择"},
            "type": "default",
            "value": {"action": "doc_clear", "batch": batch},
        })
    if len(docs) <= 20:
        for d in docs:
            doc_id = d.get("id") or ""
            checked = doc_id in selected_ids
            elements.append({
                "tag": "button",
                "text": {"tag": "lark_md", "content": f"{'☑' if checked else '☐'} **{d.get('file_no') or ''}**"},
                "type": "primary" if checked else "default",
                "value": {"action": "doc_toggle", "batch": batch, "doc_id": doc_id},
            })
    else:
        elements.append({"tag": "markdown", "content": "文件较多（>20 份），请使用上方编号输入方式查询选择。"})
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"选择标准文件 {batch}"}, "template": "green"},
        "body": {"elements": elements},
    }


def build_task_created_card(batch: str, file_nos: list[str], note: str) -> dict:
    """建任务成功后替换原表单卡片的确认卡片（表单已移除，不可再次提交）。"""
    lines = "\n".join(f"- {f}" for f in file_nos)
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"✅ 任务已创建 {batch}"}, "template": "green"},
        "body": {"elements": [
            {"tag": "markdown", "content": f"标准文件（{len(file_nos)} 份）：\n{lines}\n\n{note}"},
        ]},
    }


async def send_pick_doc_card(
    chat_id: str, batch: str, docs: list[dict], selected_ids: set[str], notice: str = ""
) -> None:
    """批号代号对应多份标准文件时，发多选点选卡片。"""
    await send_interactive_card(chat_id, build_pick_doc_card(batch, docs, selected_ids, notice))


async def send_menu_card(chat_id: str) -> None:
    """机器人单聊导航菜单卡片。"""
    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": "质量检验助手"}, "template": "blue"},
        "body": {
            "elements": [
                {"tag": "markdown", "content": "选择要进行的操作："},
                {"tag": "button", "text": {"tag": "lark_md", "content": "📝 建任务"}, "type": "primary",
                 "value": {"action": "menu", "next": "create_task"}},
                {"tag": "button", "text": {"tag": "lark_md", "content": "🧪 填报"}, "type": "primary",
                 "value": {"action": "menu", "next": "fill"}},
                {"tag": "button", "text": {"tag": "lark_md", "content": "📊 查进度"}, "type": "default",
                 "value": {"action": "menu", "next": "progress"}},
                {"tag": "hr"},
                {"tag": "markdown", "content": "也可直接发指令：建任务 批号 XXX / 填报 批号 XXX / 进度 批号 XXX"},
            ]
        },
    }
    await send_interactive_card(chat_id, card)


def build_batch_form_card(next_action: str) -> dict:
    """批号输入卡片（进入建任务/填报流程前的统一入口）。"""
    titles = {"create_task": "新建检验任务", "fill": "检验填报", "progress": "查询进度"}
    return {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": titles.get(next_action, next_action)}, "template": "green"},
        "body": {
            "elements": [
                {
                    "tag": "form",
                    "name": "batch_form",
                    "elements": [
                        {"tag": "input", "name": "batch",
                         "label": {"tag": "plain_text", "content": "批号"},
                         "required": True},
                        {"tag": "button", "action_type": "form_submit", "name": "submit_batch",
                         "text": {"tag": "lark_md", "content": "**下一步**"},
                         "type": "primary",
                         "value": {"action": "batch_input", "next": next_action}},
                    ],
                },
            ]
        },
    }


async def send_batch_form_card(chat_id: str, next_action: str) -> None:
    """批号输入卡片发到群。"""
    await send_interactive_card(chat_id, build_batch_form_card(next_action))

"""飞书指令端到端测试：真实指令路由 + 回滚式 db_session，消息发送全部 mock。

覆盖此前零测试的核心路由：填报写库/不合格不落库/自动转待复核/
建任务卡片/白名单拦截/图片归档。
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.modules.quality.feishu.fill_service import _commands as cmds
from app.modules.quality.feishu.fill_service._common import (
    _LAST_IMAGE,
)
from app.modules.quality.models import QualityStandardDocument
from app.modules.quality.repository import (
    create_standard_item,
    create_test_results,
    create_test_task,
    get_test_task,
    list_task_attachments,
    list_test_results,
)


def _rand_file_no() -> str:
    return f"SOP.02.{uuid.uuid4().hex[:4].upper()}.{uuid.uuid4().hex[:3].upper()}"


def _rand_batch(code: str = "HAF") -> str:
    return f"{code}{uuid.uuid4().hex[:8].upper()}"


def _text_event(text: str, chat_id: str = "oc_test", sender: str = "ou_test", chat_type: str = "group") -> dict:
    import json

    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": sender}},
        }
    }


def _image_event(chat_id: str = "oc_test", sender: str = "ou_test", chat_type: str = "group") -> dict:
    import json

    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "message_type": "image",
                "message_id": "om_test",
                "content": json.dumps({"image_key": "img_test_key"}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": sender}},
        }
    }


@pytest.fixture
def feishu_env(db_session, monkeypatch):
    """mock 消息发送/后台任务/图片下载 + 会话工厂指向回滚式 session。"""
    sent_texts: list[tuple[str, str]] = []
    sent_cards: list[dict] = []
    spawned: list[object] = []

    async def fake_send_text(chat_id: str, text: str) -> None:
        sent_texts.append((chat_id, text))

    async def fake_send_card(chat_id: str, card: dict) -> None:
        sent_cards.append({"chat_id": chat_id, "card": card})

    async def fake_send_any(*args: object, **kwargs: object) -> None:
        sent_cards.append({"args": args, "kwargs": kwargs})

    def fake_spawn(coro: object) -> None:
        spawned.append(coro)

    # _commands 模块级绑定与函数内导入两处都 patch
    # 清空白名单（env 里配了测试群，测试用独立 chat_id/sender）
    for name in ["QUALITY_FEISHU_CHAT_IDS", "QUALITY_FEISHU_USER_IDS", "QUALITY_FEISHU_CREATE_USER_IDS"]:
        monkeypatch.setattr(f"app.modules.quality.feishu.fill_service._common.{name}", [])
    monkeypatch.setattr(cmds, "send_chat_text", fake_send_text)
    monkeypatch.setattr(cmds, "spawn_background", fake_spawn)
    # service 自动流转也会 spawn 通知（真后台任务会撞回滚式 session）
    monkeypatch.setattr("app.modules.quality.service.task_lifecycle.spawn_background", fake_spawn)
    monkeypatch.setattr(cmds, "_download_image", AsyncMock(return_value=b"fake-image-bytes"))
    for name in ["send_batch_form_card", "send_fill_card", "send_create_task_card",
                 "send_pick_doc_card", "send_help_card", "send_menu_card", "send_alert_post"]:
        monkeypatch.setattr(f"app.modules.quality.feishu.message.{name}", fake_send_any)

    @asynccontextmanager
    async def _fake_factory():
        yield db_session

    monkeypatch.setattr("app.core.database.async_session_factory", _fake_factory)
    # 回滚式 fixture：会话 commit 改为 no-op，防止测试数据落库
    monkeypatch.setattr(db_session, "commit", AsyncMock())

    return {"sent_texts": sent_texts, "sent_cards": sent_cards, "spawned": spawned, "db": db_session}


async def _make_doc(db) -> QualityStandardDocument:
    doc = QualityStandardDocument(
        file_no=_rand_file_no(),
        product_name=f"测试产品{uuid.uuid4().hex[:6]}",
        product_code="HAF",
        valid_years="3年",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _make_task_with_rows(db, doc: QualityStandardDocument, batch: str | None = None):
    task = await create_test_task(
        db,
        product_name=doc.product_name,
        batch_number=batch or _rand_batch(),
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=doc.id,
    )
    task.status = "in_progress"
    await db.flush()
    rows = await create_test_results(db, task.id, [
        {"item_name": "水分", "sop_no": "SOP.03.1111", "standard_text": "≤3.0%",
         "operator": "≤", "limit_max": 3.0, "judge_mode": "auto", "source": "manual"},
    ])
    return task, rows


# ── 填报指令 ──


async def test_fill_command_writes_judged_result(feishu_env):
    doc = await _make_doc(feishu_env["db"])
    await create_standard_item(feishu_env["db"], doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    task, rows = await _make_task_with_rows(feishu_env["db"], doc)
    batch = task.batch_number

    await cmds.handle_fill_command(_text_event(f"批号 {batch} 水分 1.5"))

    saved = await list_test_results(feishu_env["db"], task.id)
    assert saved[0].is_pass is True  # 1.5 ≤ 3.0 合格落库
    assert saved[0].result_value == 1.5
    assert any("批号" in t and batch in t for _, t in feishu_env["sent_texts"])


async def test_fill_unqualified_not_saved_and_notifies(feishu_env):
    doc = await _make_doc(feishu_env["db"])
    task, _rows = await _make_task_with_rows(feishu_env["db"], doc)
    batch = task.batch_number

    await cmds.handle_fill_command(_text_event(f"批号 {batch} 水分 9.9"))

    saved = await list_test_results(feishu_env["db"], task.id)
    # 不合格不落库：行保持未填
    assert saved[0].is_pass is None
    assert saved[0].result_value is None
    # 回执声明未落库 + 触发了不合格提醒后台任务
    assert any("不合格未落库" in t for _, t in feishu_env["sent_texts"])
    assert len(feishu_env["spawned"]) >= 1


async def test_fill_all_judged_auto_advances(feishu_env):
    doc = await _make_doc(feishu_env["db"])
    task, rows = await _make_task_with_rows(feishu_env["db"], doc)
    # 追加一条「细菌内毒素」manual 行（默认规则已自动填「符合规定」）
    await create_test_results(feishu_env["db"], task.id, [{
        "item_name": "细菌内毒素", "sop_no": "SOP.03.9001", "standard_text": "应符合规定",
        "operator": None, "limit_max": None, "judge_mode": "manual", "source": "manual",
        "result_text": "符合规定", "is_pass": True,
    }])
    batch = task.batch_number

    await cmds.handle_fill_command(_text_event(f"批号 {batch} 水分 1.5"))

    fresh = await get_test_task(feishu_env["db"], task.id)
    assert fresh.status == "pending_review"


# ── 建任务指令 ──


async def test_create_task_command_sends_card(feishu_env):
    doc = await _make_doc(feishu_env["db"])
    await create_standard_item(feishu_env["db"], doc.id, {
        "seq": 1, "item_name": "水分", "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%", "operator": "≤", "limit_max": 3.0,
    })
    batch = _rand_batch()

    await cmds.handle_fill_command(_text_event(f"建任务 批号 {batch}"))

    # 发送了建任务相关卡片（create_task 卡片或点选卡片）
    assert len(feishu_env["sent_cards"]) >= 1


# ── 白名单拦截 ──


async def test_p2p_user_whitelist_blocks_unknown_user(feishu_env, monkeypatch):
    monkeypatch.setattr(
        "app.modules.quality.feishu.fill_service._common.QUALITY_FEISHU_USER_IDS",
        ["ou_allowed"],
    )
    doc = await _make_doc(feishu_env["db"])
    task, _rows = await _make_task_with_rows(feishu_env["db"], doc)
    batch = task.batch_number
    before = len(feishu_env["sent_texts"])

    await cmds.handle_fill_command(
        _text_event(f"批号 {batch} 水分 1.5", chat_type="p2p", sender="ou_stranger")
    )

    saved = await list_test_results(feishu_env["db"], task.id)
    assert saved[0].is_pass is None  # 未写库
    assert len(feishu_env["sent_texts"]) == before  # 未回复


# ── 图片归档 ──


async def test_image_archive_flow(feishu_env):
    doc = await _make_doc(feishu_env["db"])
    task, _rows = await _make_task_with_rows(feishu_env["db"], doc)
    batch = task.batch_number

    # 先发图片（暂存），再发「附件 批号 X」
    await cmds.handle_fill_command(_image_event())
    assert _LAST_IMAGE.get("oc_test") is not None

    await cmds.handle_fill_command(_text_event(f"附件 批号 {batch}"))

    atts = await list_task_attachments(feishu_env["db"], task.id)
    assert len(atts) == 1
    assert atts[0].remark == "机器人图片消息自动归档"
    assert "图片已归档" in feishu_env["sent_texts"][-1][1]
    assert _LAST_IMAGE.get("oc_test") is None  # 归档成功后清理暂存

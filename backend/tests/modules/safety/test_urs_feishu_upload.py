"""URS 对话上传链路测试（路由 / 处理器 / 上下文 / 菜单 / 确认续跑）。

修复背景：menu_handler 指南承诺「直接把 URS 文档（.docx/.pdf）发送到本对话，
即可自动建单并评估」，但 _handle_file_message 原先只支持 OH 归档文件——
.docx 被拒、.pdf 误入 OH 归档，URS 对话上传链路完全缺失。
本套测试锁定新路由语义与建单全链路编排，全部 mock 外部依赖（飞书 API/DB/AI）。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

import app.modules.safety.feishu.business_agent_bot_handler as bot_handler
import app.modules.safety.feishu.menu_handler as menu_handler
import app.modules.safety.feishu.urs_upload_context as urs_ctx
from app.modules.safety.feishu.urs_upload_context import (
    consume_urs_upload_context,
    has_urs_upload_context,
    set_urs_upload_context,
)

SENDER_OPEN_ID = "ou_test_sender_001"
CHAT_ID = "oc_test_chat_001"


def _file_message(file_name: str, chat_type: str = "p2p") -> dict[str, Any]:
    return {
        "message_id": "om_test_001",
        "chat_type": chat_type,
        "chat_id": CHAT_ID,
        "message_type": "file",
        "content": json.dumps({"file_key": "fk_test", "file_name": file_name}),
    }


@pytest.fixture()
def reply_recorder(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """记录 _send_text_to_chat 发出的所有文本。"""
    sent: list[str] = []

    async def _fake_send(chat_id: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(bot_handler, "_send_text_to_chat", _fake_send)
    return sent


@pytest.fixture(autouse=True)
def _clear_ctx():
    urs_ctx._clear_all()
    yield
    urs_ctx._clear_all()


# ════════════════════════════════════════════════════════════════
# 路由：_handle_file_message
# ════════════════════════════════════════════════════════════════


async def test_p2p_docx_routes_to_urs(
    monkeypatch: pytest.MonkeyPatch, reply_recorder: list[str],
) -> None:
    """私聊 .docx → URS 对话上传（OH 归档不接收 docx，无歧义）。"""
    routed: list[tuple[str, str]] = []

    async def _fake_urs(message: dict, chat_id: str, sender_open_id: str, sender_user_id: str = "") -> None:
        routed.append((chat_id, sender_open_id))

    async def _fake_oh(message: dict, chat_id: str) -> None:
        routed.append(("OH", chat_id))

    monkeypatch.setattr(bot_handler, "_handle_urs_file", _fake_urs)
    monkeypatch.setattr(bot_handler, "_handle_oh_archive_file", _fake_oh)

    await bot_handler._handle_file_message(
        _file_message("设备采购URS.docx"), CHAT_ID, SENDER_OPEN_ID,
    )

    assert routed == [(CHAT_ID, SENDER_OPEN_ID)]
    assert not reply_recorder


async def test_p2p_pdf_with_menu_context_routes_to_urs(
    monkeypatch: pytest.MonkeyPatch, reply_recorder: list[str],
) -> None:
    """私聊 .pdf + 菜单上下文命中 → URS，且上下文一次消费后失效。"""
    routed: list[str] = []

    async def _fake_urs(message: dict, chat_id: str, sender_open_id: str, sender_user_id: str = "") -> None:
        routed.append("urs")

    async def _fake_oh(message: dict, chat_id: str) -> None:
        routed.append("oh")

    monkeypatch.setattr(bot_handler, "_handle_urs_file", _fake_urs)
    monkeypatch.setattr(bot_handler, "_handle_oh_archive_file", _fake_oh)
    set_urs_upload_context(SENDER_OPEN_ID)

    await bot_handler._handle_file_message(
        _file_message("乙醇回收系统URS.pdf"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert routed == ["urs"]

    # 第二个 PDF：上下文已消费 → 维持 OH 归档路由
    await bot_handler._handle_file_message(
        _file_message("体检报告单.pdf"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert routed == ["urs", "oh"]


async def test_p2p_pdf_without_context_routes_to_oh(
    monkeypatch: pytest.MonkeyPatch, reply_recorder: list[str],
) -> None:
    """私聊 .pdf 无菜单上下文 → 维持原 OH 归档路由（体检报告单不受影响）。"""
    routed: list[str] = []

    async def _fake_urs(message: dict, chat_id: str, sender_open_id: str, sender_user_id: str = "") -> None:
        routed.append("urs")

    async def _fake_oh(message: dict, chat_id: str) -> None:
        routed.append("oh")

    monkeypatch.setattr(bot_handler, "_handle_urs_file", _fake_urs)
    monkeypatch.setattr(bot_handler, "_handle_oh_archive_file", _fake_oh)

    await bot_handler._handle_file_message(
        _file_message("体检报告单.pdf"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert routed == ["oh"]


async def test_p2p_pdf_with_expired_context_routes_to_oh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """私聊 .pdf + 菜单上下文已超时 → OH 归档（TTL 语义）。"""
    routed: list[str] = []

    async def _fake_urs(message: dict, chat_id: str, sender_open_id: str, sender_user_id: str = "") -> None:
        routed.append("urs")

    async def _fake_oh(message: dict, chat_id: str) -> None:
        routed.append("oh")

    monkeypatch.setattr(bot_handler, "_handle_urs_file", _fake_urs)
    monkeypatch.setattr(bot_handler, "_handle_oh_archive_file", _fake_oh)
    set_urs_upload_context(SENDER_OPEN_ID)
    # 直接把过期时间改到过去，模拟 30 分钟窗口已过
    urs_ctx._context[SENDER_OPEN_ID] -= urs_ctx.TTL_SECONDS + 1

    await bot_handler._handle_file_message(
        _file_message("文档.pdf"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert routed == ["oh"]


async def test_unsupported_ext_replies_with_supported_list(
    reply_recorder: list[str],
) -> None:
    """私聊不支持的类型 → 回复支持清单（不再只有 OH 提示）。"""
    await bot_handler._handle_file_message(
        _file_message("安装包.exe"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert len(reply_recorder) == 1
    assert "URS 审核文档" in reply_recorder[0]
    assert "docx" in reply_recorder[0]


async def test_group_docx_gets_supported_list_reply(
    reply_recorder: list[str],
) -> None:
    """群聊 .docx → 回复支持清单（有响应，不静默）。"""
    await bot_handler._handle_file_message(
        _file_message("设备URS.docx", chat_type="group"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert len(reply_recorder) == 1
    assert "URS 审核文档" in reply_recorder[0]


async def test_group_pdf_keeps_p2p_hint(reply_recorder: list[str]) -> None:
    """群聊 .pdf → 维持「私聊发送」提示（OH 归档原行为不变）。"""
    await bot_handler._handle_file_message(
        _file_message("体检报告单.pdf", chat_type="group"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert len(reply_recorder) == 1
    assert "私聊" in reply_recorder[0]


# ════════════════════════════════════════════════════════════════
# 建单链路：_handle_urs_file
# ════════════════════════════════════════════════════════════════


@dataclass
class _FakeReport:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    urs_no: str = "URS-20260918-001"
    equipment_name: str = "乙醇回收系统"


class _FakeURSService:
    """URSService 仿件：记录调用，不触 DB/AI。"""

    instances: list[_FakeURSService] = []
    parse_error: Exception | None = None

    def __init__(self, db: Any) -> None:
        self.db = db
        self.calls: list[str] = []
        self.created_with: dict[str, Any] = {}
        _FakeURSService.instances.append(self)

    async def parse_urs_attachment(self, file: Any) -> dict[str, Any]:
        self.calls.append("parse")
        if _FakeURSService.parse_error:
            raise _FakeURSService.parse_error
        return {
            "equipment_name": "乙醇回收系统",
            "equipment_category": "设备",
            "department": "精制工程一部",
            "procurement_purpose": "扩产",
            "urs_content": "URS 原文" * 10,
            "attachment_path": "safety/urs/test.docx",
        }

    async def create_report(
        self, data: dict[str, Any], *,
        applicant_open_id: str | None = None,
        source_chat_id: str | None = None,
    ) -> _FakeReport:
        self.calls.append("create")
        self.created_with = {
            "data": data,
            "applicant_open_id": applicant_open_id,
            "source_chat_id": source_chat_id,
        }
        return _FakeReport()

    async def submit_report(self, report_id: uuid.UUID) -> _FakeReport:
        self.calls.append("submit")
        return _FakeReport()

    def trigger_full_review_background(self, report_id: uuid.UUID) -> None:
        self.calls.append("trigger_full")


class _FakeDB:
    async def commit(self) -> None:
        pass


class _FakeSessionCM:
    """async_session_factory 仿件返回的 async context manager。"""

    def __init__(self) -> None:
        self.db = _FakeDB()

    async def __aenter__(self) -> Any:
        return self.db

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture()
def fake_urs(monkeypatch: pytest.MonkeyPatch) -> type[_FakeURSService]:
    _FakeURSService.instances = []
    _FakeURSService.parse_error = None
    monkeypatch.setattr(
        "app.modules.safety.service.ehs_change.urs.URSService", _FakeURSService,
    )
    monkeypatch.setattr(bot_handler, "async_session_factory", lambda: _FakeSessionCM())

    async def _fake_download(message_id: str, file_key: str) -> bytes:
        return b"PK\x03\x04fake-docx-bytes"

    monkeypatch.setattr(bot_handler, "_download_message_file", _fake_download)

    async def _fake_name(db: Any, sender_user_id: str, open_id: str) -> str | None:
        return "张三"

    monkeypatch.setattr(bot_handler, "_resolve_applicant_name", _fake_name)
    return _FakeURSService


async def test_handle_urs_file_happy_path(
    fake_urs: type[_FakeURSService], reply_recorder: list[str],
) -> None:
    """下载 → 解析建单 → 提交 → 后台全链路 → 回执含编号与设备名。"""
    await bot_handler._handle_urs_file(
        _file_message("乙醇回收系统URS.docx"), CHAT_ID, SENDER_OPEN_ID,
    )

    svc = fake_urs.instances[-1]
    assert svc.calls == ["parse", "create", "submit", "trigger_full"]
    assert svc.created_with["applicant_open_id"] == SENDER_OPEN_ID
    assert svc.created_with["source_chat_id"] == CHAT_ID
    assert svc.created_with["data"]["equipment_name"] == "乙醇回收系统"
    assert svc.created_with["data"]["applicant_name"] == "张三"

    assert len(reply_recorder) == 1
    reply = reply_recorder[0]
    assert "URS-20260918-001" in reply
    assert "乙醇回收系统" in reply
    assert "已受理" in reply


async def test_handle_urs_file_parse_failure(
    fake_urs: type[_FakeURSService], reply_recorder: list[str],
) -> None:
    """解析失败（如非 URS 文档提取不到文本）→ 友好错误，不建单。"""
    fake_urs.parse_error = ValueError("无法从文件中提取有效文本内容")

    await bot_handler._handle_urs_file(
        _file_message("随便什么.pdf"), CHAT_ID, SENDER_OPEN_ID,
    )

    svc = fake_urs.instances[-1]
    assert svc.calls == ["parse"]
    assert any("解析失败" in r for r in reply_recorder)


async def test_handle_urs_file_download_failure(
    monkeypatch: pytest.MonkeyPatch, fake_urs: type[_FakeURSService],
    reply_recorder: list[str],
) -> None:
    """文件下载失败 → 错误提示，不建单。"""

    async def _bad_download(message_id: str, file_key: str) -> bytes:
        raise RuntimeError("code=230001")

    monkeypatch.setattr(bot_handler, "_download_message_file", _bad_download)

    await bot_handler._handle_urs_file(
        _file_message("a.docx"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert not fake_urs.instances  # 下载失败在实例化 service 之前返回
    assert any("下载失败" in r for r in reply_recorder)


async def test_handle_urs_file_oversize(
    monkeypatch: pytest.MonkeyPatch, fake_urs: type[_FakeURSService],
    reply_recorder: list[str],
) -> None:
    """超过 50MB → 拒绝并提示。"""

    async def _big_download(message_id: str, file_key: str) -> bytes:
        return b"x" * (bot_handler._URS_FILE_MAX_SIZE + 1)

    monkeypatch.setattr(bot_handler, "_download_message_file", _big_download)

    await bot_handler._handle_urs_file(
        _file_message("huge.docx"), CHAT_ID, SENDER_OPEN_ID,
    )
    assert not fake_urs.instances  # 超限在实例化 service 之前返回
    assert any("文件过大" in r for r in reply_recorder)


async def test_sender_open_id_extraction() -> None:
    """事件中提取 sender open_id / user_id（URS 申请人与上下文键）。"""
    event = {
        "sender": {"sender_id": {"open_id": SENDER_OPEN_ID, "user_id": "xukangfu"}},
        "message": {},
    }
    assert bot_handler._sender_open_id(event) == SENDER_OPEN_ID
    assert bot_handler._sender_user_id(event) == "xukangfu"
    assert bot_handler._sender_open_id({"message": {}}) == ""
    assert bot_handler._sender_user_id({"message": {}}) == ""


async def test_resolve_applicant_name_prefers_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """申请人解析优先 user_id（open_id 按应用隔离，与身份表不互通）。"""
    looked_up: list[str] = []

    class _Person:
        name = "许康福"

    class _Resolver:
        def __init__(self, db: Any) -> None:
            pass

        async def resolve_by_user_id(self, key: str) -> Any:
            looked_up.append(key)
            return _Person() if key == "xukangfu" else None

    monkeypatch.setattr(bot_handler, "IdentityResolver", _Resolver)

    # user_id 优先
    name = await bot_handler._resolve_applicant_name(None, "xukangfu", SENDER_OPEN_ID)
    assert name == "许康福"
    assert looked_up == ["xukangfu"]

    # 无 user_id 时回退 open_id
    looked_up.clear()
    name = await bot_handler._resolve_applicant_name(None, "", SENDER_OPEN_ID)
    assert name is None
    assert looked_up == [SENDER_OPEN_ID]

    # 两者皆空直接跳过
    assert await bot_handler._resolve_applicant_name(None, "", "") is None


# ════════════════════════════════════════════════════════════════
# 上传上下文：urs_upload_context
# ════════════════════════════════════════════════════════════════


def test_upload_context_set_consume_once() -> None:
    set_urs_upload_context(SENDER_OPEN_ID)
    assert has_urs_upload_context(SENDER_OPEN_ID)
    assert consume_urs_upload_context(SENDER_OPEN_ID) is True
    # 消费型：一次命中即失效
    assert consume_urs_upload_context(SENDER_OPEN_ID) is False
    assert not has_urs_upload_context(SENDER_OPEN_ID)


def test_upload_context_user_isolation() -> None:
    """上下文按 open_id 隔离，其他用户不受影响。"""
    set_urs_upload_context(SENDER_OPEN_ID)
    assert consume_urs_upload_context("ou_other") is False
    assert has_urs_upload_context(SENDER_OPEN_ID)


def test_upload_context_empty_open_id() -> None:
    set_urs_upload_context("")
    assert consume_urs_upload_context("") is False


# ════════════════════════════════════════════════════════════════
# 菜单点击：写入上下文
# ════════════════════════════════════════════════════════════════


async def test_menu_click_sets_upload_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str]] = []

    async def _fake_card(open_id: str, title: str, content: str, **kw: Any) -> bool:
        sent.append((open_id, title))
        return True

    monkeypatch.setattr(menu_handler, "send_user_card", _fake_card)

    await menu_handler._on_menu_click({
        "event_key": "urs_review",
        "operator": {"operator_id": {"open_id": SENDER_OPEN_ID}},
    })

    assert sent == [(SENDER_OPEN_ID, "📑 URS 智能审核")]
    assert has_urs_upload_context(SENDER_OPEN_ID)


# ════════════════════════════════════════════════════════════════
# 确认画像后续跑：_confirm_assessment
# ════════════════════════════════════════════════════════════════


async def test_confirm_assessment_spawns_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """人工确认画像（assessment_confirmed）→ 自动 spawn 适配+结论链路。"""
    import app.modules.safety.feishu.urs_card as urs_card

    spawned: list[uuid.UUID] = []

    async def _fake_chain(report_id: uuid.UUID) -> None:
        spawned.append(report_id)

    async def _fake_patch(event_data: dict, card: dict) -> None:
        pass

    class _ConfirmedReport:
        id = uuid.uuid4()
        review_status = "assessment_confirmed"
        overall_risk_level = "low"
        risk_profile: dict[str, Any] = {}
        equipment_name = "乙醇回收系统"
        equipment_category = "设备"
        department = "精制一部"
        ai_confidence = 0.9

    class _Svc:
        def __init__(self, db: Any) -> None:
            self.db = db

        async def confirm_assessment(self, report_id: uuid.UUID) -> Any:
            return _ConfirmedReport()

    monkeypatch.setattr(
        "app.modules.safety.service.ehs_change.urs.URSService", _Svc,
    )
    monkeypatch.setattr(urs_card, "_run_confirmed_chain_background", _fake_chain)
    monkeypatch.setattr(urs_card, "_patch_card", _fake_patch)
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _FakeSessionCM(),
    )

    result = await urs_card._confirm_assessment(uuid.uuid4(), {})
    assert result is None
    # create_task 需要事件循环调度一拍
    await asyncio.sleep(0)
    assert len(spawned) == 1


# ════════════════════════════════════════════════════════════════
# Service 链路：run_adaptation_and_conclusion
# ════════════════════════════════════════════════════════════════


async def test_run_adaptation_and_conclusion_chains() -> None:
    """item_review 状态 → 结论继续执行；适配失败 → 不出结论。"""
    from app.modules.safety.service.ehs_change.urs import URSService

    svc = URSService.__new__(URSService)  # 跳过 __init__（不需要 session）
    calls: list[str] = []

    @dataclass
    class _R:
        review_status: str

    async def _adapt(report_id: uuid.UUID) -> _R:
        calls.append("adapt")
        return _R("item_review")

    async def _conclude(report_id: uuid.UUID) -> _R:
        calls.append("conclude")
        return _R("approved")

    svc.run_adaptation = _adapt  # type: ignore[method-assign]
    svc.generate_conclusion = _conclude  # type: ignore[method-assign]

    report = await svc.run_adaptation_and_conclusion(uuid.uuid4())
    assert calls == ["adapt", "conclude"]
    assert report is not None and report.review_status == "approved"

    # 适配失败（failed）→ 链路停在适配，不生成结论
    calls.clear()

    async def _adapt_fail(report_id: uuid.UUID) -> _R:
        calls.append("adapt")
        return _R("failed")

    svc.run_adaptation = _adapt_fail  # type: ignore[method-assign]
    report = await svc.run_adaptation_and_conclusion(uuid.uuid4())
    assert calls == ["adapt"]
    assert report is not None and report.review_status == "failed"


# ================================================================
# 详情卡 / 返回 / 申诉表单（2026-09-18 第二轮修复）
# ================================================================


@dataclass
class _DetailItem:
    item_no: str = "D1"
    category: str = "design"
    standard_title: str = "压力容器制造许可"
    applicability: str | None = "mandatory"
    review_status: str | None = "failed"
    review_comment: str | None = "未提供制造许可证"
    is_veto: bool = False


@dataclass
class _DetailReport:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    urs_no: str = "URS-20260918-001"
    equipment_name: str = "乙醇回收系统"
    equipment_category: str = "设备"
    department: str = "精制工程一部"
    applicant_name: str = "许康福"
    review_status: str = "rejected"
    overall_risk_level: str = "high"
    ai_confidence: float = 0.86
    source_chat_id: str | None = None
    risk_profile: dict = field(default_factory=lambda: {
        "mechanical": {"level": "high", "indicators": ["压力容器"], "evidence": "设计压力0.6MPa"},
        "electrical": {"level": "medium", "indicators": [], "evidence": ""},
        "data": {"level": "low", "indicators": [], "evidence": ""},
        "environmental": {"level": "medium", "indicators": [], "evidence": ""},
        "chemical": {"level": "high", "indicators": ["乙醇"], "evidence": "易燃液体"},
    })
    risk_profile_reasoning: str = "涉及压力容器与易燃介质"
    conclusion: str = "rejected"
    score: float = 40.0
    grade: str = "D"
    review_result: dict = field(default_factory=lambda: {"summary": "存在否决项缺失"})
    rectification_requirements: list = field(default_factory=lambda: [
        {"item_no": "D1", "requirement": "补充特种设备制造许可证"},
    ])


def test_build_detail_card_concluded_report() -> None:
    """详情卡：画像依据 + 逐条审核统计 + 整改要求 + 返回按钮（辅助判断模式无申诉）。"""
    import app.modules.safety.feishu.urs_card as urs_card

    report = _DetailReport()
    items = [
        _DetailItem(item_no="D1", review_status="failed", review_comment="未提供证书"),
        _DetailItem(item_no="D2", standard_title="防爆电气", review_status="passed"),
        _DetailItem(item_no="D3", applicability="not_applicable"),
    ]
    card = urs_card.build_detail_card(report, items)
    content = json.dumps(card, ensure_ascii=False)
    assert "URS-20260918-001" in content
    assert "依据" in content  # 每维风险依据
    assert "AI 评估摘要" in content
    assert "逐条审核" in content and "适用 2 项" in content
    assert "否决" in content or "未提供证书" in content
    assert "整改要求（1 项）" in content
    assert "urs_back" in content  # 返回按钮
    assert "urs_appeal" not in content  # 辅助判断模式：无申诉入口


def test_build_detail_card_no_conclusion_no_appeal() -> None:
    """评估阶段详情卡：无结论 → 不显示申诉按钮。"""
    import app.modules.safety.feishu.urs_card as urs_card

    report = _DetailReport(review_status="human_review", conclusion=None, rectification_requirements=[])
    card = urs_card.build_detail_card(report, [])
    content = json.dumps(card, ensure_ascii=False)
    assert "urs_back" in content
    assert "urs_appeal" not in content


async def test_show_detail_patches_detail_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """查看详情：PATCH 详情卡（不再是重发同一张结论卡）。"""
    import app.modules.safety.feishu.urs_card as urs_card

    patched: list[dict] = []

    async def _fake_fetch(report_id: uuid.UUID):
        return _DetailReport()

    async def _fake_fetch2(report_id: uuid.UUID):
        return _DetailReport(), [_DetailItem()]

    async def _fake_patch(event_data: dict, card: dict) -> None:
        patched.append(card)

    monkeypatch.setattr(urs_card, "_fetch_report_and_items", _fake_fetch2)
    monkeypatch.setattr(urs_card, "_patch_card", _fake_patch)

    result = await urs_card._show_detail(uuid.uuid4(), {})
    assert result is None
    assert len(patched) == 1
    assert "审核详情" in patched[0]["header"]["title"]["content"]


async def test_urs_back_patches_summary_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """详情卡「返回」（旧卡兼容）：PATCH 回结论卡全文视图。"""
    import app.modules.safety.feishu.urs_card as urs_card

    patched: list[dict] = []

    async def _fake_fetch2(report_id: uuid.UUID):
        return _DetailReport(), [_DetailItem()]

    async def _fake_patch(event_data: dict, card: dict) -> None:
        patched.append(card)

    monkeypatch.setattr(urs_card, "_fetch_report_and_items", _fake_fetch2)
    monkeypatch.setattr(urs_card, "_patch_card", _fake_patch)

    result = await urs_card._show_summary_card(uuid.uuid4(), {})
    assert result is None
    assert len(patched) == 1
    assert "审核结论" in patched[0]["header"]["title"]["content"]


async def test_conclusion_card_full_text_no_buttons() -> None:
    """结论卡（全文直出）：画像/逐条审核/整改要求直接进卡，无任何按钮。"""
    import app.modules.safety.feishu.urs_card as urs_card

    items = [
        _DetailItem(item_no="D1", review_status="failed", review_comment="未提供证书"),
        _DetailItem(item_no="D2", standard_title="防爆电气", review_status="passed"),
        _DetailItem(item_no="D3", applicability="not_applicable"),
    ]
    card = urs_card.build_conclusion_card(_DetailReport(), items)
    content = json.dumps(card, ensure_ascii=False)
    # 全文段落齐备
    assert "五维风险画像" in content
    assert "依据" in content
    assert "AI 评估摘要" in content
    assert "逐条审核" in content and "适用 2 项" in content
    assert "整改要求（1 项）" in content
    assert "辅助判断" in content
    # 无按钮（查看详情/申诉全部下线）
    assert "urs_view" not in content
    assert "urs_appeal" not in content
    assert '"tag": "button"' not in content

    # items 未传时跳过逐条审核段，其余内容完整
    card2 = urs_card.build_conclusion_card(_DetailReport())
    content2 = json.dumps(card2, ensure_ascii=False)
    assert "逐条审核" not in content2
    assert "五维风险画像" in content2


async def test_appeal_action_no_longer_handled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧卡片上的申诉按钮点击：不再有任何处理（静默 ACK）。"""
    import app.modules.safety.feishu.urs_card as urs_card

    called: list = []

    async def _fake_patch(event_data: dict, card: dict) -> None:
        called.append(card)

    monkeypatch.setattr(urs_card, "_patch_card", _fake_patch)
    result = await urs_card.handle_urs_card_action(
        {"action": "urs_appeal", "urs_id": str(uuid.uuid4())}, {},
    )
    assert result is None
    assert not called


# ════════════════════════════════════════════════════════════════
# 全链路管道（辅助判断模式）：_run_full_review_background
# ════════════════════════════════════════════════════════════════


@dataclass
class _PipelineReport:
    review_status: str = "assessment_confirmed"
    conclusion: str | None = "rejected"
    ai_error_message: str | None = None
    applicant_open_id: str | None = SENDER_OPEN_ID


class _PipelineSvc:
    """URSService 管道仿件：按脚本返回状态，记录调用与 notify 参数。"""

    script: list[_PipelineReport] = []
    calls: list[tuple[str, dict]] = []

    def __init__(self, db: Any) -> None:
        self.db = db

    async def run_assessment(self, report_id: uuid.UUID, *, notify: bool = True) -> Any:
        _PipelineSvc.calls.append(("assess", {"notify": notify}))
        return _PipelineSvc.script[0] if _PipelineSvc.script else None

    async def confirm_assessment(self, report_id: uuid.UUID) -> Any:
        _PipelineSvc.calls.append(("confirm", {}))
        return _PipelineReport(review_status="assessment_confirmed")

    async def run_adaptation_and_conclusion(self, report_id: uuid.UUID) -> Any:
        _PipelineSvc.calls.append(("adapt_conclude", {}))
        return _PipelineSvc.script[-1] if _PipelineSvc.script else None


def _install_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    script: list[_PipelineReport],
) -> dict[str, list]:
    """装配管道测试：fake service/session + 记录 urs_card 推送。"""
    _PipelineSvc.script = script
    _PipelineSvc.calls = []
    sent: dict[str, list] = {"pdf": [], "failed": []}

    monkeypatch.setattr(
        "app.modules.safety.service.ehs_change.urs.URSService", _PipelineSvc,
    )
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _FakeSessionCM(),
    )

    import app.modules.safety.feishu.urs_card as urs_card

    async def _fake_pdf(report_id: uuid.UUID) -> bool:
        sent["pdf"].append(report_id)
        return True

    async def _fake_failed(
        report_id: uuid.UUID, msg: str | None, open_id: str | None,
    ) -> bool:
        sent["failed"].append((report_id, msg, open_id))
        return True

    monkeypatch.setattr(urs_card, "send_urs_review_pdf", _fake_pdf)
    monkeypatch.setattr(urs_card, "notify_review_failed", _fake_failed)
    return sent


async def test_pipeline_auto_confirms_low_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """低置信度（human_review）不再暂停：自动确认 → 适配+结论 → 发送 PDF。"""
    from app.modules.safety.service.ehs_change.urs import URSService

    sent = _install_pipeline(
        monkeypatch,
        [
            _PipelineReport(review_status="human_review", conclusion=None),
            _PipelineReport(review_status="rejected", conclusion="rejected"),
        ],
    )
    svc = URSService.__new__(URSService)
    await svc._run_full_review_background(uuid.uuid4())

    names = [c[0] for c in _PipelineSvc.calls]
    assert names == ["assess", "confirm", "adapt_conclude"]
    # 飞书管道跳过中间评估卡
    assert _PipelineSvc.calls[0][1] == {"notify": False}
    assert len(sent["pdf"]) == 1
    assert not sent["failed"]


async def test_pipeline_confirmed_direct_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """置信度达标（assessment_confirmed）：无需确认，直接适配+结论+PDF。"""
    from app.modules.safety.service.ehs_change.urs import URSService

    sent = _install_pipeline(
        monkeypatch,
        [_PipelineReport(review_status="assessment_confirmed", conclusion="approved")],
    )
    svc = URSService.__new__(URSService)
    await svc._run_full_review_background(uuid.uuid4())

    names = [c[0] for c in _PipelineSvc.calls]
    assert names == ["assess", "adapt_conclude"]
    assert len(sent["pdf"]) == 1


async def test_pipeline_failure_notifies_applicant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评估失败：推送失败卡，不发 PDF。"""
    from app.modules.safety.service.ehs_change.urs import URSService

    sent = _install_pipeline(
        monkeypatch,
        [_PipelineReport(review_status="failed", conclusion=None, ai_error_message="AI 超时")],
    )
    svc = URSService.__new__(URSService)
    await svc._run_full_review_background(uuid.uuid4())

    names = [c[0] for c in _PipelineSvc.calls]
    assert names == ["assess"]
    assert not sent["pdf"]
    assert len(sent["failed"]) == 1
    assert sent["failed"][0][1] == "AI 超时"


async def test_send_urs_review_pdf_without_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """无来源会话（如 Web 建单）：跳过 PDF 发送。"""
    import app.modules.safety.feishu.urs_card as urs_card

    class _PdfSvc:
        def __init__(self, db: Any) -> None:
            pass

        async def get_report(self, report_id: uuid.UUID) -> Any:
            return _DetailReport()  # source_chat_id=None

        async def export_pdf(self, report_id: uuid.UUID) -> bytes:
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(
        "app.modules.safety.service.ehs_change.urs.URSService", _PdfSvc,
    )
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _FakeSessionCM(),
    )

    ok = await urs_card.send_urs_review_pdf(uuid.uuid4())
    assert ok is False


async def test_send_urs_review_pdf_with_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """有来源会话：PDF 按编号命名发送成功。"""
    import app.modules.safety.feishu.urs_card as urs_card

    sent_files: list[tuple[str, bytes, str]] = []

    class _PdfSvc:
        def __init__(self, db: Any) -> None:
            pass

        async def get_report(self, report_id: uuid.UUID) -> Any:
            return _DetailReport(source_chat_id=CHAT_ID)

        async def export_pdf(self, report_id: uuid.UUID) -> bytes:
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(
        "app.modules.safety.service.ehs_change.urs.URSService", _PdfSvc,
    )
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _FakeSessionCM(),
    )

    async def _fake_send(chat_id: str, file_bytes: bytes, file_name: str) -> bool:
        sent_files.append((chat_id, file_bytes, file_name))
        return True

    monkeypatch.setattr(
        "app.modules.safety.feishu.chat_sender.send_file_to_chat", _fake_send,
    )

    ok = await urs_card.send_urs_review_pdf(uuid.uuid4())
    assert ok is True
    assert len(sent_files) == 1
    chat_id, pdf, name = sent_files[0]
    assert chat_id == CHAT_ID
    assert pdf == b"%PDF-1.4 fake"
    assert name.startswith("URS-20260918-001_URS审核报告") and name.endswith(".pdf")


async def test_notify_review_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败通知：有申请人发送失败卡；无申请人跳过。"""
    import app.modules.safety.feishu.urs_card as urs_card

    sent: list[tuple[str, str]] = []

    async def _fake_card(open_id: str, title: str, content: str, **kw: Any) -> bool:
        sent.append((open_id, title))
        return True

    monkeypatch.setattr(urs_card, "send_user_card", _fake_card)

    ok = await urs_card.notify_review_failed(uuid.uuid4(), "AI 超时", SENDER_OPEN_ID)
    assert ok is True
    assert len(sent) == 1 and "失败" in sent[0][1]

    ok2 = await urs_card.notify_review_failed(uuid.uuid4(), "AI 超时", None)
    assert ok2 is False
    assert len(sent) == 1

"""报告单审核环节推送测试：生成待初审提醒、审核结果通知（门控+文案）。"""

import pytest

from app.modules.quality.feishu import client as feishu_client
from app.modules.quality.feishu import message as feishu_message
from app.modules.quality.feishu import report_push


def _configure_feishu(
    monkeypatch: pytest.MonkeyPatch, sent: list[tuple[str, str]]
) -> None:
    monkeypatch.setattr(feishu_client, "QUALITY_FEISHU_CHAT_IDS", ["oc_test"])
    monkeypatch.setattr(feishu_client, "feishu_configured", lambda: True)

    async def _fake_send(chat_id: str, text: str) -> None:
        sent.append((chat_id, text))

    monkeypatch.setattr(feishu_message, "send_chat_text", _fake_send)


@pytest.mark.asyncio
async def test_push_generated_skips_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feishu_client, "QUALITY_FEISHU_CHAT_IDS", [])
    monkeypatch.setattr(feishu_client, "feishu_configured", lambda: False)
    # 未配置即静默返回，不抛错不发送
    await report_push.push_reports_generated("产品A", "B001", ["26111901"])
    await report_push.push_audit_result("产品A", "B001", "26111901", approved=False, auditor_name="张三")


@pytest.mark.asyncio
async def test_push_generated_text(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    _configure_feishu(monkeypatch, sent)
    await report_push.push_reports_generated(
        "产品A", "B001", ["26111901", "26111902"], file_nos=["SOP-01", "SOP-02"]
    )
    assert len(sent) == 1
    text = sent[0][1]
    assert "产品A 批号 B001" in text
    assert "26111901、26111902" in text
    assert "标准文件 SOP-01、SOP-02" in text
    assert "待初审" in text
    assert "/quality/report?audit_status=pending" in text


@pytest.mark.asyncio
async def test_push_audit_rejected_text(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    _configure_feishu(monkeypatch, sent)
    await report_push.push_audit_result(
        "产品A", "B001", "26111901",
        approved=False, auditor_name="张三", comment="水分结果与图谱不一致",
    )
    text = sent[0][1]
    assert "已退回" in text
    assert "水分结果与图谱不一致" in text
    assert "审核人：张三" in text
    assert "请统计员核对原始记录后重新出报" in text


@pytest.mark.asyncio
async def test_push_audit_approved_text(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    _configure_feishu(monkeypatch, sent)
    await report_push.push_audit_result(
        "产品A", "B001", None, approved=True, auditor_name="李四"
    )
    text = sent[0][1]
    assert "审核通过" in text
    assert "流水号 —" in text  # 无流水号兜底不裸奔 None
    assert "退回" not in text


@pytest.mark.asyncio
async def test_push_send_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, str]] = []
    _configure_feishu(monkeypatch, sent)

    async def _boom(chat_id: str, text: str) -> None:
        raise RuntimeError("飞书不可用")

    monkeypatch.setattr(feishu_message, "send_chat_text", _boom)
    # 发送失败仅记日志，绝不向调用方（审核/出报端点）冒泡
    await report_push.push_audit_result("产品A", "B001", "26111901", approved=True, auditor_name="张三")

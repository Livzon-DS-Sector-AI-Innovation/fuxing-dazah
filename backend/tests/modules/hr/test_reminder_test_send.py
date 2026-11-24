"""人事提醒：接收人测试发送（/reminder-settings/test）。

飞书发送与姓名解析全部打桩——绝不在测试里发真实卡片。
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_reminder_test_send_reports_resolved_and_unresolved(client):
    """测试发送把接收人分三类如实返回：可送达 / 无法解析（同名多人等）/ 发送失败。"""
    async def fake_lookup(name: str):
        # 「同名者」解析不到 open_id（与线上「同名多人宁可不发」口径一致）
        return {"张三": "ou_zhangsan", "李四": "ou_lisi"}.get(name)

    sent_to: list[str] = []

    async def fake_send(open_id: str, card: dict):
        if open_id == "ou_lisi":
            raise RuntimeError("飞书限流")
        sent_to.append(open_id)

    with (
        patch("app.modules.hr.reminder.routes._lookup_open_id", side_effect=fake_lookup),
        patch("app.platform.integrations.feishu.notification.send_user_card", side_effect=fake_send),
    ):
        res = await client.post("/api/v1/hr/reminder-settings/test", json={
            "kind": "contract",
            "receivers": ["张三", "李四", "同名者", "ou_direct", "张三"],
        })

    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["sent"] == 2            # 张三 + 直接填的 open_id
    assert data["unresolved"] == ["同名者"]
    assert [f["receiver"] for f in data["failed"]] == ["ou_lisi"]
    assert sorted(sent_to) == ["ou_direct", "ou_zhangsan"]  # 重复填写的「张三」只发一次


@pytest.mark.asyncio
async def test_reminder_test_send_rejects_when_nothing_resolvable(client):
    with (
        patch("app.modules.hr.reminder.routes._lookup_open_id", new=AsyncMock(return_value=None)),
        patch("app.platform.integrations.feishu.notification.send_user_card", new=AsyncMock()) as send,
    ):
        res = await client.post("/api/v1/hr/reminder-settings/test", json={
            "kind": "probation", "receivers": ["查无此人"],
        })
    assert res.status_code == 400, res.text
    assert "查无此人" in res.json()["message"]
    send.assert_not_called()

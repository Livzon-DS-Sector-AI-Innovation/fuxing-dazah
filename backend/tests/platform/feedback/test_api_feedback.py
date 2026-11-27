"""系统反馈业务规则：提交快照、入参校验、列表排序过滤、我的反馈隔离、待处理计数、标记开关与审计。

列表/计数类断言一律用「包含/不包含」或「相对基线的增量」，不假设表里只有本测试的数据，
以兼容开发库里已存在的真实反馈行。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models import AuditLog
from app.platform.feedback.models import Feedback

BASE = "/api/v1/feedback"


def _payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": "bug",
        "content": "登录后首页白屏",
        "page_path": "/production/batches",
    }
    data.update(overrides)
    return data


async def _submit(fb: Any, user: Any, **overrides: Any) -> str:
    """以指定用户提交一条反馈，返回反馈 id。"""
    async with fb.client(user) as ac:
        resp = await ac.post(BASE, json=_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["id"])


async def _pending(fb: Any, admin: Any) -> int:
    async with fb.admin(admin) as ac:
        resp = await ac.get(f"{BASE}/pending-count")
    assert resp.status_code == 200, resp.text
    return int(resp.json()["data"]["pending"])


async def _row(fb: Any, feedback_id: str) -> Feedback:
    session: AsyncSession = fb.session
    stmt = select(Feedback).where(Feedback.id == uuid.UUID(feedback_id))
    return (await session.execute(stmt)).scalar_one()


class TestSubmit:
    async def test_submit_snapshots_submitter_and_defaults_pending(
        self, fb: Any
    ) -> None:
        """提交即快照提交人姓名/部门，created_by 指向本人，初始未处理。"""
        user = await fb.user("张三", department="生产部")
        async with fb.client(user) as ac:
            resp = await ac.post(BASE, json=_payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()["data"]
        assert body["type"] == "bug"
        assert body["content"] == "登录后首页白屏"
        assert body["page_path"] == "/production/batches"
        assert body["submitter_id"] == str(user.id)
        assert body["submitter_name"] == "张三"
        assert body["submitter_department"] == "生产部"
        assert body["is_handled"] is False
        assert body["handled_by_name"] is None
        assert body["handled_at"] is None
        assert body["created_at"]

        row = await _row(fb, body["id"])
        assert row.created_by == user.id

    async def test_submit_strips_content_whitespace(self, fb: Any) -> None:
        """内容首尾空白被剥离后存储。"""
        user = await fb.user("李四")
        async with fb.client(user) as ac:
            resp = await ac.post(BASE, json=_payload(content="  白屏  "))
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["content"] == "白屏"

    async def test_max_length_checked_after_strip(self, fb: Any) -> None:
        """长度按剥离空白后的正文计：2000 字加首尾换行不应 422。"""
        user = await fb.user("李四")
        async with fb.client(user) as ac:
            resp = await ac.post(BASE, json=_payload(content="\n" + "x" * 2000 + "\n"))
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["content"] == "x" * 2000

    async def test_submit_without_page_path(self, fb: Any) -> None:
        """page_path 可选：缺省为 None。"""
        user = await fb.user("李四")
        async with fb.client(user) as ac:
            resp = await ac.post(
                BASE, json={"type": "feature", "content": "希望支持导出 Excel"}
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["page_path"] is None

    @pytest.mark.parametrize(
        "payload",
        [
            _payload(type="other"),
            _payload(content="    "),
            _payload(content="x" * 2001),
            _payload(page_path="/" + "p" * 512),
            {"type": "bug", "page_path": "/production"},
        ],
        ids=[
            "bad-type",
            "blank-content",
            "long-content",
            "long-page-path",
            "missing-content",
        ],
    )
    async def test_invalid_payload_rejected(
        self, fb: Any, payload: dict[str, Any]
    ) -> None:
        """非法入参统一 422，且不为该用户落任何反馈行。"""
        user = await fb.user("李四")
        async with fb.client(user) as ac:
            resp = await ac.post(BASE, json=payload)
        assert resp.status_code == 422, resp.text
        stmt = select(Feedback).where(Feedback.created_by == user.id)
        assert (await fb.session.execute(stmt)).scalars().first() is None


class TestListing:
    async def test_list_newest_first_with_total(self, fb: Any) -> None:
        """列表按提交时间倒序，meta.total 覆盖本次提交。"""
        user = await fb.user("张三", department="生产部")
        admin = await fb.user("超管")
        # 同一事务内 server now() 相同，另造一条「昨天」的旧记录验证排序方向
        old = Feedback(
            type="bug",
            content="昨天的旧反馈",
            submitter_name="旧用户",
            created_by=user.id,
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
        fb.session.add(old)
        await fb.session.flush()

        first = await _submit(fb, user, type="bug", content="第一条")
        second = await _submit(fb, user, type="ux", content="第二条")
        async with fb.admin(admin) as ac:
            resp = await ac.get(BASE, params={"page": 1, "page_size": 50})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [item["id"] for item in body["data"]]
        assert set(ids[:2]) == {first, second}
        assert str(old.id) in ids
        assert ids.index(str(old.id)) > 1
        assert body["meta"]["total"] >= 3
        assert body["meta"]["page"] == 1
        assert body["meta"]["page_size"] == 50

    async def test_filter_by_handled_and_type(self, fb: Any) -> None:
        """is_handled 与 type 过滤可独立或组合生效。"""
        user = await fb.user("张三")
        admin = await fb.user("超管")
        bug_id = await _submit(fb, user, type="bug", content="bug 一条")
        ux_id = await _submit(fb, user, type="ux", content="ux 一条")
        async with fb.admin(admin) as ac:
            marked = await ac.patch(
                f"{BASE}/{bug_id}/handled", json={"is_handled": True}
            )
            assert marked.status_code == 200, marked.text
            unhandled = (
                await ac.get(BASE, params={"is_handled": "false", "page_size": 200})
            ).json()["data"]
            handled = (
                await ac.get(BASE, params={"is_handled": "true", "page_size": 200})
            ).json()["data"]
            only_ux = (
                await ac.get(
                    BASE,
                    params={"type": "ux", "is_handled": "false", "page_size": 200},
                )
            ).json()["data"]

        unhandled_ids = {i["id"] for i in unhandled}
        handled_ids = {i["id"] for i in handled}
        ux_ids = {i["id"] for i in only_ux}
        assert bug_id in handled_ids and bug_id not in unhandled_ids
        assert ux_id in unhandled_ids and ux_id not in handled_ids
        assert ux_id in ux_ids and bug_id not in ux_ids
        assert all(i["type"] == "ux" for i in only_ux)


class TestMine:
    async def test_mine_returns_only_own_feedback(self, fb: Any) -> None:
        """我的反馈只含本人提交的记录。"""
        alice = await fb.user("alice", department="QA部")
        bob = await fb.user("bob", department="生产部")
        alice_id = await _submit(fb, alice, content="alice 的反馈")
        bob_id = await _submit(fb, bob, content="bob 的反馈")
        async with fb.client(alice) as ac:
            resp = await ac.get(f"{BASE}/mine")
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        ids = {i["id"] for i in items}
        assert alice_id in ids
        assert bob_id not in ids
        assert all(i["submitter_id"] == str(alice.id) for i in items)


class TestPendingCount:
    async def test_counts_unhandled_and_undeleted_only(self, fb: Any) -> None:
        """计数只算未处理且未软删的反馈；标记/软删后同步回落。"""
        user = await fb.user("张三")
        admin = await fb.user("超管")
        base = await _pending(fb, admin)

        one = await _submit(fb, user, content="计数1")
        two = await _submit(fb, user, content="计数2")
        after_submit = await _pending(fb, admin)

        async with fb.admin(admin) as ac:
            marked = await ac.patch(f"{BASE}/{one}/handled", json={"is_handled": True})
            assert marked.status_code == 200, marked.text
        after_mark = await _pending(fb, admin)

        row = await _row(fb, two)
        row.is_deleted = True
        await fb.session.flush()
        after_delete = await _pending(fb, admin)

        assert after_submit == base + 2
        assert after_mark == base + 1
        assert after_delete == base


class TestHandledToggle:
    async def test_mark_and_unmark_roundtrip(self, fb: Any) -> None:
        """标记写处理人快照与时间；取消标记清空；响应含 updated_at（UPDATE 后 re-fetch）。"""
        user = await fb.user("张三")
        admin = await fb.user("管理员", department="信息部")
        feedback_id = await _submit(fb, user)
        async with fb.admin(admin) as ac:
            marked = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": True}
            )
        assert marked.status_code == 200, marked.text
        marked_body = marked.json()["data"]
        assert marked_body["is_handled"] is True
        assert marked_body["handled_by_name"] == "管理员"
        assert marked_body["handled_at"] is not None
        assert marked_body["updated_at"] is not None

        row = await _row(fb, feedback_id)
        assert row.handled_by == admin.id
        assert row.updated_by == admin.id

        async with fb.admin(admin) as ac:
            unmarked = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": False}
            )
        assert unmarked.status_code == 200, unmarked.text
        unmarked_body = unmarked.json()["data"]
        assert unmarked_body["is_handled"] is False
        assert unmarked_body["handled_by_name"] is None
        assert unmarked_body["handled_at"] is None

    async def test_mark_unknown_id_404(self, fb: Any) -> None:
        """标记不存在的反馈 404。"""
        admin = await fb.user("管理员")
        async with fb.admin(admin) as ac:
            resp = await ac.patch(
                f"{BASE}/{uuid.uuid4()}/handled", json={"is_handled": True}
            )
        assert resp.status_code == 404

    async def test_mark_missing_body_422(self, fb: Any) -> None:
        """标记缺少 is_handled 字段 422。"""
        user = await fb.user("张三")
        admin = await fb.user("管理员")
        feedback_id = await _submit(fb, user)
        async with fb.admin(admin) as ac:
            resp = await ac.patch(f"{BASE}/{feedback_id}/handled", json={})
        assert resp.status_code == 422


class TestAudit:
    async def test_submit_and_mark_write_audit_logs(self, fb: Any) -> None:
        """提交与标记各落一条审计日志，resource_type=feedback，操作人正确。"""
        user = await fb.user("张三")
        admin = await fb.user("管理员")
        feedback_id = await _submit(fb, user)
        async with fb.admin(admin) as ac:
            marked = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": True}
            )
            assert marked.status_code == 200, marked.text

        stmt = select(AuditLog).where(AuditLog.resource_id == uuid.UUID(feedback_id))
        logs = (await fb.session.execute(stmt)).scalars().all()
        by_action = {log.action: log for log in logs}
        assert "feedback.submit" in by_action
        assert "feedback.mark_handled" in by_action
        assert by_action["feedback.submit"].user_id == user.id
        assert by_action["feedback.mark_handled"].user_id == admin.id
        assert all(log.resource_type == "feedback" for log in logs)

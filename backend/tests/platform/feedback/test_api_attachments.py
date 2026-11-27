"""反馈截图附件：鉴权、图片校验、张数/冻结守卫、读取、删除、列表携带与审计。

规则：只有提交人本人能上传；本人在反馈未处理前可删，管理员随时可删；
本人与管理员可读；只收 PNG/JPG/WEBP/GIF，单张 ≤5MB，每条最多 3 张。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models import AuditLog
from app.platform.feedback.models import FeedbackAttachment
from tests.platform.feedback.conftest import (
    FEEDBACK_BASE as BASE,
)
from tests.platform.feedback.conftest import (
    GIF_BYTES,
    JPEG_BYTES,
    PNG_BYTES,
    WEBP_BYTES,
)

FIVE_MB = 5 * 1024 * 1024


def _content_url(feedback_id: str, attachment_id: str) -> str:
    return f"{BASE}/{feedback_id}/attachments/{attachment_id}/content"


def _item_url(feedback_id: str, attachment_id: str) -> str:
    return f"{BASE}/{feedback_id}/attachments/{attachment_id}"


async def _mark_handled(fb: Any, admin: Any, feedback_id: str) -> None:
    async with fb.admin(admin) as ac:
        resp = await ac.patch(f"{BASE}/{feedback_id}/handled", json={"is_handled": True})
    assert resp.status_code == 200, resp.text


async def _attachment_row(fb: Any, attachment_id: str) -> FeedbackAttachment:
    session: AsyncSession = fb.session
    stmt = select(FeedbackAttachment).where(
        FeedbackAttachment.id == uuid.UUID(attachment_id)
    )
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.usefixtures("memory_storage")
class TestAttachmentAuthz:
    async def test_anonymous_rejected(self, fb: Any) -> None:
        """未登录访问上传 / 读取 / 删除均 401。"""
        async with fb.client(None) as ac:
            upload = await fb.upload(ac, str(uuid.uuid4()))
            content = await ac.get(_content_url(str(uuid.uuid4()), str(uuid.uuid4())))
            delete = await ac.delete(_item_url(str(uuid.uuid4()), str(uuid.uuid4())))
        assert upload.status_code == 401
        assert content.status_code == 401
        assert delete.status_code == 401

    async def test_non_owner_forbidden(self, fb: Any) -> None:
        """他人不能为别人的反馈上传、读取或删除截图。"""
        owner = await fb.user("提交人")
        other = await fb.user("路人")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
        async with fb.client(other) as ac:
            upload = await fb.upload(ac, feedback_id)
            content = await ac.get(_content_url(feedback_id, attachment_id))
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
        assert upload.status_code == 403
        assert content.status_code == 403
        assert delete.status_code == 403

    async def test_admin_can_read_and_delete_but_not_upload(self, fb: Any) -> None:
        """管理员可查看与删除（处置误传），但不代替用户上传。"""
        owner = await fb.user("提交人")
        admin = await fb.user("管理员")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
        async with fb.admin(admin) as ac:
            upload = await fb.upload(ac, feedback_id)
            content = await ac.get(_content_url(feedback_id, attachment_id))
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
        assert upload.status_code == 403
        assert content.status_code == 200
        assert delete.status_code == 200


class TestUpload:
    async def test_upload_png_persists_metadata_and_object(
        self, fb: Any, memory_storage: dict[str, bytes]
    ) -> None:
        """上传成功：返回元数据，对象落在 feedback/<id>/ 前缀下，行记录提交人。"""
        owner = await fb.user("张三", department="生产部")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            resp = await fb.upload(ac, feedback_id, name="登录白屏.png")
        assert resp.status_code == 201, resp.text
        body = resp.json()["data"]
        assert body["feedback_id"] == feedback_id
        assert body["file_name"] == "登录白屏.png"
        assert body["mime_type"] == "image/png"
        assert body["file_size"] == len(PNG_BYTES)
        assert body["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
        assert body["uploaded_by_name"] == "张三"
        assert body["created_at"]

        assert len(memory_storage) == 1
        (key,) = memory_storage
        assert key.startswith(f"feedback/{feedback_id}/")
        assert key.endswith(".png")

        row = await _attachment_row(fb, body["id"])
        assert row.created_by == owner.id
        assert row.storage_key == key

    @pytest.mark.usefixtures("memory_storage")
    @pytest.mark.parametrize(
        ("name", "data", "mime", "expected_mime"),
        [
            ("a.png", PNG_BYTES, "image/png", "image/png"),
            ("b.jpg", JPEG_BYTES, "image/jpeg", "image/jpeg"),
            ("c.jpeg", JPEG_BYTES, "image/jpeg", "image/jpeg"),
            ("d.webp", WEBP_BYTES, "image/webp", "image/webp"),
            ("e.gif", GIF_BYTES, "image/gif", "image/gif"),
        ],
    )
    async def test_all_image_types_accepted(
        self, fb: Any, name: str, data: bytes, mime: str, expected_mime: str
    ) -> None:
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            resp = await fb.upload(ac, feedback_id, name=name, data=data, mime=mime)
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["mime_type"] == expected_mime

    @pytest.mark.parametrize(
        ("name", "data", "mime", "fragment"),
        [
            ("说明.txt", b"hello", "text/plain", "仅支持 PNG、JPG、WEBP、GIF"),
            ("文档.pdf", b"%PDF-1.4 ...", "application/pdf", "仅支持 PNG、JPG、WEBP、GIF"),
            ("假的.png", JPEG_BYTES, "image/png", "不匹配"),
            ("空.png", b"", "image/png", "不能为空"),
            ("大.png", PNG_BYTES + b"\x00" * FIVE_MB, "image/png", "不能超过 5MB"),
        ],
        ids=["txt", "pdf", "magic-mismatch", "empty", "oversize"],
    )
    async def test_invalid_image_rejected(
        self,
        fb: Any,
        memory_storage: dict[str, bytes],
        name: str,
        data: bytes,
        mime: str,
        fragment: str,
    ) -> None:
        """非图片、伪装扩展名、空文件、超过 5MB 一律 422 且不落对象。"""
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            resp = await fb.upload(ac, feedback_id, name=name, data=data, mime=mime)
        assert resp.status_code == 422, resp.text
        assert fragment in resp.json()["message"]
        assert memory_storage == {}

    async def test_fourth_attachment_rejected(
        self, fb: Any, memory_storage: dict[str, bytes]
    ) -> None:
        """每条反馈最多 3 张。"""
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            for index in range(3):
                ok = await fb.upload(ac, feedback_id, name=f"s{index}.png")
                assert ok.status_code == 201, ok.text
            fourth = await fb.upload(ac, feedback_id, name="s3.png")
        assert fourth.status_code == 422, fourth.text
        assert "最多 3 张" in fourth.json()["message"]
        assert len(memory_storage) == 3

    @pytest.mark.usefixtures("memory_storage")
    async def test_upload_to_unknown_feedback_404(self, fb: Any) -> None:
        owner = await fb.user("张三")
        async with fb.client(owner) as ac:
            resp = await fb.upload(ac, str(uuid.uuid4()))
        assert resp.status_code == 404


@pytest.mark.usefixtures("memory_storage")
class TestFreezeAfterHandled:
    async def test_owner_cannot_change_after_handled_but_admin_can_delete(
        self, fb: Any
    ) -> None:
        """标记已处理后本人不能再补传或删除；管理员仍可删除。"""
        owner = await fb.user("张三")
        admin = await fb.user("管理员")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
        await _mark_handled(fb, admin, feedback_id)

        async with fb.client(owner) as ac:
            upload = await fb.upload(ac, feedback_id, name="补传.png")
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
        assert upload.status_code == 409, upload.text
        assert "已处理" in upload.json()["message"]
        assert delete.status_code == 409, delete.text

        async with fb.admin(admin) as ac:
            admin_delete = await ac.delete(_item_url(feedback_id, attachment_id))
        assert admin_delete.status_code == 200, admin_delete.text


class TestContentAndDelete:
    async def test_content_streams_inline_image_with_checksum(
        self, fb: Any, memory_storage: dict[str, bytes]
    ) -> None:
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            uploaded = (await fb.upload(ac, feedback_id)).json()["data"]
            content = await ac.get(_content_url(feedback_id, uploaded["id"]))
        assert content.status_code == 200
        assert content.content == PNG_BYTES
        assert content.headers["content-type"].startswith("image/png")
        assert "inline" in content.headers["content-disposition"]
        assert content.headers["x-content-sha256"] == uploaded["sha256"]
        assert len(memory_storage) == 1

    async def test_delete_soft_deletes_row_removes_object_and_hides(
        self, fb: Any, memory_storage: dict[str, bytes]
    ) -> None:
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
            content_after = await ac.get(_content_url(feedback_id, attachment_id))
            delete_again = await ac.delete(_item_url(feedback_id, attachment_id))
        assert delete.status_code == 200, delete.text
        assert memory_storage == {}
        assert content_after.status_code == 404
        assert delete_again.status_code == 404
        row = await _attachment_row(fb, attachment_id)
        assert row.is_deleted is True
        assert row.updated_by == owner.id

    @pytest.mark.usefixtures("memory_storage")
    async def test_content_of_unknown_attachment_404(self, fb: Any) -> None:
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            resp = await ac.get(_content_url(feedback_id, str(uuid.uuid4())))
        assert resp.status_code == 404


@pytest.mark.usefixtures("memory_storage")
class TestListsCarryAttachments:
    async def test_attachments_embedded_in_all_feedback_outputs(self, fb: Any) -> None:
        """提交响应为空数组；上传后 /mine、管理列表、标记响应都带该附件；删除后移除。"""
        owner = await fb.user("张三")
        admin = await fb.user("管理员")
        async with fb.client(owner) as ac:
            created = await ac.post(
                BASE, json={"type": "bug", "content": "带图反馈"}
            )
            assert created.status_code == 201, created.text
            assert created.json()["data"]["attachments"] == []
            feedback_id = created.json()["data"]["id"]
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
            mine = await ac.get(f"{BASE}/mine")

        mine_item = next(i for i in mine.json()["data"] if i["id"] == feedback_id)
        assert [a["id"] for a in mine_item["attachments"]] == [attachment_id]
        assert mine_item["attachments"][0]["file_name"] == "截图.png"

        async with fb.admin(admin) as ac:
            listing = await ac.get(BASE, params={"page_size": 200})
            marked = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": True}
            )
        list_item = next(i for i in listing.json()["data"] if i["id"] == feedback_id)
        assert [a["id"] for a in list_item["attachments"]] == [attachment_id]
        assert [a["id"] for a in marked.json()["data"]["attachments"]] == [attachment_id]

        async with fb.admin(admin) as ac:
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
            assert delete.status_code == 200, delete.text
            listing_after = await ac.get(BASE, params={"page_size": 200})
        item_after = next(
            i for i in listing_after.json()["data"] if i["id"] == feedback_id
        )
        assert item_after["attachments"] == []


@pytest.mark.usefixtures("memory_storage")
class TestAudit:
    async def test_add_and_delete_write_audit_logs(self, fb: Any) -> None:
        """上传与删除各记一条审计，挂在反馈资源上；读取不记审计。"""
        owner = await fb.user("张三")
        feedback_id = await fb.submit(owner)
        async with fb.client(owner) as ac:
            attachment_id = (await fb.upload(ac, feedback_id)).json()["data"]["id"]
            await ac.get(_content_url(feedback_id, attachment_id))
            delete = await ac.delete(_item_url(feedback_id, attachment_id))
            assert delete.status_code == 200, delete.text

        session: AsyncSession = fb.session
        stmt = select(AuditLog).where(AuditLog.resource_id == uuid.UUID(feedback_id))
        logs = (await session.execute(stmt)).scalars().all()
        actions = [log.action for log in logs]
        assert actions.count("feedback.attachment_add") == 1
        assert actions.count("feedback.attachment_delete") == 1
        assert not any(a.startswith("feedback.attachment_read") for a in actions)
        added = next(log for log in logs if log.action == "feedback.attachment_add")
        assert added.user_id == owner.id
        assert added.resource_type == "feedback"
        assert added.new_value is not None
        assert added.new_value["attachment_id"] == attachment_id

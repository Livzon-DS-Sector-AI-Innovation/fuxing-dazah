"""系统反馈 API 测试夹具。

复用顶层 tests/conftest.py 的真实 Postgres session（每测试回滚），沿用
qa/meter 的模式覆盖 get_db / get_current_user 并 patch 权限集合：

- 匿名：不覆盖 get_current_user，走真实解析（无 token → 401）
- 普通用户：perms 为空集（仅登录，即可提交/查看自己的反馈）
- 超管：perms 含 ``system:feedback:manage``（全部列表/待处理计数/标记）

截图附件测试用 ``memory_storage`` 把 ``app.core.file_storage`` 换成内存字典，
与 QA 偏差附件测试隔离存储的方式一致，不往 UPLOAD_DIR 写文件。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app as fastapi_app
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

FEEDBACK_BASE = "/api/v1/feedback"

# 平台级管理权限码（声明于 app/platform/permission/registry.py）
ADMIN_PERMS: frozenset[str] = frozenset({"system:feedback:manage"})

# 仅带正确魔数的最小图片桩，足够通过内容校验
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


class FeedbackHarness:
    """session + 用户工厂 + 按 (用户, 权限) 换取 API client 的测试载具。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user(self, name: str, department: str | None = None) -> User:
        """现场造一个未删除用户，工号随机避免唯一约束冲突；flush 后端点可见。"""
        user = User(
            name=name,
            employee_no=f"FB-{uuid.uuid4().hex[:8].upper()}",
            department=department,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    def client(
        self,
        user: User | None,
        perms: frozenset[str] | set[str] = frozenset(),
    ) -> AbstractAsyncContextManager[AsyncClient]:
        """以指定用户+权限集合发起 API 请求；user=None 为匿名。"""
        return self._client_for(user, perms)

    def admin(self, user: User) -> AbstractAsyncContextManager[AsyncClient]:
        """以管理权限（system:feedback:manage）发起 API 请求。"""
        return self._client_for(user, ADMIN_PERMS)

    async def submit(self, user: User, **overrides: Any) -> str:
        """以指定用户提交一条反馈，返回反馈 id。"""
        payload: dict[str, Any] = {
            "type": "bug",
            "content": "测试反馈",
            "page_path": "/production",
        }
        payload.update(overrides)
        async with self.client(user) as ac:
            resp = await ac.post(FEEDBACK_BASE, json=payload)
        assert resp.status_code == 201, resp.text
        return str(resp.json()["data"]["id"])

    @staticmethod
    async def upload(
        ac: AsyncClient,
        feedback_id: str,
        *,
        name: str = "截图.png",
        data: bytes = PNG_BYTES,
        mime: str = "image/png",
    ) -> Response:
        """用已有 client 上传一张截图（multipart 字段名 file）。"""
        return await ac.post(
            f"{FEEDBACK_BASE}/{feedback_id}/attachments",
            files={"file": (name, data, mime)},
        )

    def _client_for(
        self,
        user: User | None,
        perms: frozenset[str] | set[str],
    ) -> AbstractAsyncContextManager[AsyncClient]:
        session = self.session

        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            yield session

        async def _override_user() -> User:
            return user  # type: ignore[return-value]  # 匿名分支不会注册该覆盖

        async def _perms(user_id: str, db: object) -> set[str]:
            return set(perms)

        @asynccontextmanager
        async def _ctx() -> AsyncGenerator[AsyncClient, None]:
            fastapi_app.dependency_overrides[get_db] = _override_get_db
            if user is None:
                fastapi_app.dependency_overrides.pop(get_current_user, None)
            else:
                fastapi_app.dependency_overrides[get_current_user] = _override_user
            transport = ASGITransport(app=fastapi_app)
            try:
                with patch(
                    "app.platform.permission.deps.get_user_permissions", new=_perms
                ):
                    async with AsyncClient(
                        transport=transport, base_url="http://test"
                    ) as ac:
                        yield ac
            finally:
                fastapi_app.dependency_overrides.clear()

        return _ctx()


@pytest.fixture
async def fb() -> AsyncIterator[FeedbackHarness]:
    """反馈测试载具：同一 session 预置数据端点可见；测试结束回滚。"""
    async with _test_session_factory() as session:
        harness = FeedbackHarness(session)
        try:
            yield harness
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


@pytest.fixture
def memory_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """把 core 文件存储换成内存字典；service 以模块属性方式调用，patch 才生效。"""
    import app.core.file_storage as file_storage

    store: dict[str, bytes] = {}

    def _store(
        module: str, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        assert module == "feedback"
        store[key] = data
        return key

    def _read(module: str, key: str) -> tuple[bytes, str] | None:
        return (store[key], "application/octet-stream") if key in store else None

    def _delete(module: str, key: str) -> None:
        store.pop(key, None)

    monkeypatch.setattr(file_storage, "store_object", _store)
    monkeypatch.setattr(file_storage, "read_object", _read)
    monkeypatch.setattr(file_storage, "delete_object", _delete)
    monkeypatch.setattr(file_storage, "cleanup_object", _delete)
    return store

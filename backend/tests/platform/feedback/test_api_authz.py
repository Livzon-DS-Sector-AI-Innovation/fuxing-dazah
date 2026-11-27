"""系统反馈鉴权边界：匿名 401；普通用户仅可提交/看自己的；管理端点需 system:feedback:manage。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

BASE = "/api/v1/feedback"
PAYLOAD = {"type": "bug", "content": "鉴权测试反馈", "page_path": "/production"}


class TestAnonymous:
    async def test_all_endpoints_reject_anonymous(self, fb: Any) -> None:
        """未登录访问任一反馈端点均 401。"""
        async with fb.client(None) as ac:
            post = await ac.post(BASE, json=PAYLOAD)
            mine = await ac.get(f"{BASE}/mine")
            listing = await ac.get(BASE)
            count = await ac.get(f"{BASE}/pending-count")
            mark = await ac.patch(
                f"{BASE}/{uuid4()}/handled", json={"is_handled": True}
            )
        assert post.status_code == 401
        assert mine.status_code == 401
        assert listing.status_code == 401
        assert count.status_code == 401
        assert mark.status_code == 401


class TestRegularUser:
    async def test_can_submit_and_view_own(self, fb: Any) -> None:
        """无任何权限码的登录用户可提交反馈并查看自己的反馈。"""
        user = await fb.user("反馈普通用户")
        async with fb.client(user) as ac:
            created = await ac.post(BASE, json=PAYLOAD)
            mine = await ac.get(f"{BASE}/mine")
        assert created.status_code == 201
        assert mine.status_code == 200

    async def test_management_endpoints_forbidden(self, fb: Any) -> None:
        """普通用户访问全部列表/待处理计数/标记均 403。"""
        user = await fb.user("反馈普通用户")
        async with fb.client(user) as ac:
            created = await ac.post(BASE, json=PAYLOAD)
            feedback_id = created.json()["data"]["id"]
            listing = await ac.get(BASE)
            count = await ac.get(f"{BASE}/pending-count")
            mark = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": True}
            )
        assert listing.status_code == 403
        assert count.status_code == 403
        assert mark.status_code == 403


class TestAdmin:
    async def test_manage_permission_grants_management(self, fb: Any) -> None:
        """持 system:feedback:manage：全部列表/待处理计数/标记均放行。"""
        user = await fb.user("反馈普通用户")
        admin = await fb.user("反馈超管")
        async with fb.client(user) as ac:
            feedback_id = (await ac.post(BASE, json=PAYLOAD)).json()["data"]["id"]
        async with fb.admin(admin) as ac:
            listing = await ac.get(BASE)
            count = await ac.get(f"{BASE}/pending-count")
            mark = await ac.patch(
                f"{BASE}/{feedback_id}/handled", json={"is_handled": True}
            )
        assert listing.status_code == 200
        assert count.status_code == 200
        assert mark.status_code == 200

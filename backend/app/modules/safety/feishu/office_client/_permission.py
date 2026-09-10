"""office_client Drive 协作者权限方法。"""

from __future__ import annotations

from urllib.parse import quote

from app.modules.safety.feishu.office_client._base import (
    OfficeResult,
    _normalize_perm,
)


class _PermissionOfficeMixin:
    """文件/文档协作者权限设置、快照与回滚。"""

    async def set_permission(
        self,
        token: str,
        open_ids: list[str],
        perm: str,
        *,
        member_type: str = "openid",
    ) -> OfficeResult:
        """设置文件/文档的协作者权限（drive permissions members API）。

        给指定成员授予 manage/edit/view 权限；manage 归一化为 full_access。
        创建类工具成功后调用本方法把发起人授予管理权限。
        """
        try:
            if not open_ids:
                return OfficeResult.failure("open_ids 为空，无法设置协作者权限")

            drive_type = self._drive_type_for_token(token)
            perm_value = _normalize_perm(perm)
            granted: list[str] = []
            failed: list[str] = []

            for open_id in open_ids:
                body = {
                    "member_type": member_type,
                    "member_id": open_id,
                    "perm": perm_value,
                }
                resp = await self._post(
                    f"{self._base_url}/drive/v1/permissions/{token}/members",
                    params={"type": drive_type},
                    json=body,
                    timeout=30,
                )
                data = resp.json()
                if data.get("code") == 0:
                    granted.append(open_id)
                else:
                    failed.append(
                        f"{open_id}: code={data.get('code')} "
                        f"msg={data.get('msg')}"
                    )

            if failed:
                return OfficeResult.failure(
                    "设置协作者权限部分失败：" + "；".join(failed)
                )
            return OfficeResult.data(
                {"granted": granted, "perm": perm_value},
                meta={"token": token, "type": drive_type},
            )
        except Exception as exc:
            return self._failure("设置协作者权限", exc)

    async def list_permission_members(self, token: str) -> OfficeResult:
        """读取文件/文档当前的协作者权限列表（回滚快照用）。"""
        try:
            drive_type = self._drive_type_for_token(token)
            resp = await self._get(
                f"{self._base_url}/drive/v1/permissions/{token}/members",
                params={"type": drive_type},
                timeout=30,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"读取协作者权限列表失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            items = ((data.get("data") or {}).get("items")) or []
            members = [
                {
                    "member_type": item.get("member_type"),
                    "member_id": item.get("member_id"),
                    "perm": item.get("perm"),
                }
                for item in items
                if item.get("member_id")
            ]
            return OfficeResult.data(
                members, meta={"token": token, "type": drive_type},
            )
        except Exception as exc:
            return self._failure("读取协作者权限列表", exc)

    async def remove_permission_member(
        self,
        token: str,
        member_id: str,
        *,
        member_type: str = "openid",
    ) -> OfficeResult:
        """移除某成员的协作者权限（回滚快照中「原本无权限」时使用）。"""
        try:
            drive_type = self._drive_type_for_token(token)
            resp = await self._delete(
                f"{self._base_url}/drive/v1/permissions/{token}/members/"
                f"{quote(member_id, safe='')}",
                params={"type": drive_type, "member_type": member_type},
                timeout=30,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"移除协作者权限失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )
            return OfficeResult.data(
                {"removed": member_id},
                meta={"token": token, "member_type": member_type},
            )
        except Exception as exc:
            return self._failure("移除协作者权限", exc)

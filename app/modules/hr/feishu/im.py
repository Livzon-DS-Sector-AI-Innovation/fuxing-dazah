"""Feishu IM message sending."""

import json
import logging

import httpx

from app.modules.hr.feishu.auth import FeishuAuth

logger = logging.getLogger(__name__)


class FeishuIM:
    """Send messages via Feishu IM API."""

    base_url = "https://open.feishu.cn/open-apis"

    async def _batch_get_ids(self, payload: dict) -> dict[str, str]:
        """Internal helper to call batch_get_id and extract open_id mapping."""
        token = await FeishuAuth.get_tenant_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/contact/v3/users/batch_get_id",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"Feishu batch_get_id failed: code={data.get('code')}, msg={data.get('msg')}"
            )

        result: dict[str, str] = {}
        for item in data.get("data", {}).get("user_list", []):
            open_id = item.get("open_id") or item.get("user_id")
            if not open_id:
                continue
            # Match back by whichever key was in the request
            if "mobiles" in payload:
                key = item.get("mobile")
            elif "emails" in payload:
                key = item.get("email")
            elif "employee_ids" in payload:
                key = item.get("employee_id")
            else:
                key = None
            if key:
                result[key] = open_id
        return result

    async def batch_get_open_ids_by_mobile(self, mobiles: list[str]) -> dict[str, str]:
        """Return mapping mobile -> open_id."""
        return await self._batch_get_ids({"mobiles": mobiles, "include_resigned": True})

    async def batch_get_open_ids_by_email(self, emails: list[str]) -> dict[str, str]:
        """Return mapping email -> open_id."""
        return await self._batch_get_ids({"emails": emails, "include_resigned": True})

    async def batch_get_open_ids_by_employee_id(self, employee_ids: list[str]) -> dict[str, str]:
        """Return mapping employee_id -> open_id."""
        return await self._batch_get_ids({"employee_ids": employee_ids, "include_resigned": True})

    async def send_text_message(
        self, receive_id: str, content: str, *, receive_id_type: str = "open_id"
    ) -> None:
        """Send text message to a single user."""
        token = await FeishuAuth.get_tenant_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/im/v1/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                params={"receive_id_type": receive_id_type},
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": content}, ensure_ascii=False),
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"Feishu send message failed: code={data.get('code')}, msg={data.get('msg')}"
            )

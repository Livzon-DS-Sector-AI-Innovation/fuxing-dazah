"""Feishu HTTP client with auth and retry."""

import logging

import httpx

from app.modules.hr.feishu.auth import FeishuAuth

logger = logging.getLogger(__name__)


class FeishuClient:
    system_name = "feishu"
    base_url = "https://open.feishu.cn/open-apis"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                timeout=httpx.Timeout(15.0, connect=5.0),
            )
        return self._client

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        *,
        parent_type: str = "bitable_file",
        parent_node: str | None = None,
        timeout: float = 60.0,
    ) -> dict:
        """Upload a file to Feishu Drive and return file metadata.

        Args:
            file_bytes: Raw file bytes.
            filename: Original file name.
            parent_type: Feishu parent type, e.g. "bitable_file".
            parent_node: Parent node ID, e.g. Bitable app_token.
            timeout: Upload timeout in seconds.

        Returns:
            Dict with keys like file_token, name, size, type.
        """
        import io

        token = await FeishuAuth.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        files = {"file": (filename, io.BytesIO(file_bytes))}
        data: dict[str, str] = {
            "file_name": filename,
            "size": str(len(file_bytes)),
        }
        if parent_type:
            data["parent_type"] = parent_type
        if parent_node:
            data["parent_node"] = parent_node

        client = await self._get_client()
        resp = await client.post(
            "/drive/v1/medias/upload_all",
            headers=headers,
            files=files,
            data=data,
            timeout=timeout,
        )
        try:
            resp.raise_for_status()
        except Exception:
            error_body = ""
            try:
                error_body = resp.text
            except Exception:
                pass
            logger.error(
                "Feishu upload_file failed: status=%s, body=%s, parent_type=%s, parent_node=%s",
                resp.status_code,
                error_body,
                parent_type,
                parent_node,
            )
            raise
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(
                f"Feishu upload error: code={result.get('code')}, msg={result.get('msg')}"
            )
        return result.get("data", {})

    async def health_check(self) -> dict:
        try:
            token = await FeishuAuth.get_tenant_access_token()
            return {"status": "ok", "token_prefix": token[:10] + "..."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: float = 15.0,
    ) -> dict:
        token = await FeishuAuth.get_tenant_access_token()
        default_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if headers:
            default_headers.update(headers)

        client = await self._get_client()
        resp = await client.request(
            method,
            path,
            headers=default_headers,
            json=json,
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"Feishu API error: code={data.get('code')}, msg={data.get('msg')}, "
                f"path={path}"
            )
        return data.get("data", {})

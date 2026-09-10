"""office_client 云空间（Drive）资源方法：搜索/元数据/上传/下载/删除。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.safety.feishu.office_client._base import (
    SEARCH_QUERY_MAX_CHARS,
    OfficeResult,
    _filename_from_disposition,
    _strip_highlight,
)


class _DriveOfficeMixin:
    """云空间普通文件与搜索。"""

    async def search_files(
        self,
        query: str,
        *,
        space_id: str | None = None,
        page_size: int = 20,
    ) -> OfficeResult:
        """搜索云空间/知识库文件（Search v2 doc_wiki）。"""
        try:
            body: dict[str, Any] = {
                "query": (query or "").strip()[:SEARCH_QUERY_MAX_CHARS],
                "page_size": max(1, min(int(page_size), 100)),
            }
            if space_id:
                body["wiki_filter"] = {"space_ids": [space_id]}

            resp = await self._post(
                f"{self._base_url}/search/v2/doc_wiki/search",
                json=body,
                timeout=30,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"搜索云空间/知识库文件失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            payload = data.get("data") or {}
            items: list[dict[str, Any]] = []
            for unit in payload.get("res_units") or []:
                meta = unit.get("result_meta") or {}
                items.append({
                    "name": _strip_highlight(
                        unit.get("title_highlighted")
                        or meta.get("title")
                        or meta.get("token")
                    ),
                    "type": (
                        meta.get("file_type")
                        or meta.get("doc_types")
                        or unit.get("entity_type")
                        or "unknown"
                    ),
                    "token": meta.get("token") or "",
                    "url": meta.get("url") or "",
                })
            return OfficeResult.data(
                items,
                meta={
                    "total": payload.get("total"),
                    "has_more": payload.get("has_more"),
                    "page_token": payload.get("page_token"),
                },
            )
        except Exception as exc:
            return self._failure("搜索云空间/知识库文件", exc)

    async def download_drive_file(self, file_token: str) -> OfficeResult:
        """下载云空间普通文件。"""
        try:
            url = f"{self._base_url}/drive/v1/files/{file_token}/download"
            resp = await self._get(url, timeout=120, follow_redirects=True)

            if resp.status_code != 200:
                return OfficeResult.failure(
                    f"下载云空间文件失败：HTTP {resp.status_code} "
                    f"{resp.text[:200]}"
                )

            content = resp.content
            file_name = _filename_from_disposition(
                resp.headers.get("Content-Disposition"), file_token
            )
            return OfficeResult.file(
                file_token=file_token,
                bytes=content,
                file_name=file_name,
                size=len(content),
            )
        except Exception as exc:
            return self._failure("下载云空间文件", exc)

    async def file_metadata(self, file_token: str) -> OfficeResult:
        """读取云空间文件元数据。"""
        try:
            body = {
                "request_docs": [{"doc_token": file_token}],
                "with_url": True,
            }
            resp = await self._post(
                f"{self._base_url}/drive/v1/metas/batch_query",
                json=body,
                timeout=30,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"读取文件元数据失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            metas = (data.get("data") or {}).get("metas") or []
            if not metas:
                return OfficeResult.failure(
                    "未找到该文件的元数据；请确认文件 token 正确且文件已共享给应用机器人"
                )

            meta = metas[0]
            return OfficeResult.data({
                "file_token": meta.get("doc_token", file_token),
                "name": meta.get("title", ""),
                "type": meta.get("doc_type", ""),
                "url": meta.get("url", ""),
                "owner_id": meta.get("owner_id"),
                "create_time": meta.get("create_time"),
                "latest_modify_time": meta.get("latest_modify_time"),
                "latest_modify_user": meta.get("latest_modify_user"),
            })
        except Exception as exc:
            return self._failure("读取文件元数据", exc)

    async def upload_drive_file(
        self,
        file_path: str,
        *,
        parent_token: str | None = None,
        file_name: str | None = None,
    ) -> OfficeResult:
        """上传本地文件到云空间（drive/v1/files/upload_all）。"""
        try:
            path = Path(file_path)
            if not path.is_file():
                return OfficeResult.failure(f"待上传文件不存在或不是普通文件：{file_path}")

            name = file_name or path.name
            size = path.stat().st_size
            form: dict[str, Any] = {
                "file_name": name,
                "parent_type": "explorer",
                "size": str(size),
            }
            if parent_token:
                form["parent_node"] = parent_token

            with open(path, "rb") as fh:
                resp = await self._post(
                    f"{self._base_url}/drive/v1/files/upload_all",
                    data=form,
                    files={"file": (name, fh)},
                    timeout=120,
                )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"上传云空间文件失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            file_token = ((data.get("data") or {}).get("file_token")) or ""
            if not file_token:
                return OfficeResult.failure("上传成功但未返回 file_token")

            return OfficeResult.link(
                self._file_url(file_token, "file"),
                file_token=file_token,
                message=f"已上传文件 {name}（{size} 字节）",
            )
        except Exception as exc:
            return self._failure("上传云空间文件", exc)

    async def delete_file(self, file_token: str) -> OfficeResult:
        """删除文件/文档（软删 / 移回收站；回滚钩子复用）。"""
        try:
            drive_type = self._drive_type_for_token(file_token)
            resp = await self._delete(
                f"{self._base_url}/drive/v1/files/{file_token}",
                params={"type": drive_type},
                timeout=30,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"删除文件失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )
            return OfficeResult(
                kind="link",
                file_token=file_token,
                message="已删除/移入回收站",
            )
        except Exception as exc:
            return self._failure("删除文件", exc)

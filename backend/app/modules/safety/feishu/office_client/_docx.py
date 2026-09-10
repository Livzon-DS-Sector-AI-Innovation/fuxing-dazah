"""office_client 云文档（docx）资源方法。"""

from __future__ import annotations

from typing import Any

from app.modules.safety.feishu.office_client._base import OfficeResult


class _DocxOfficeMixin:
    """docx 读写：创建文档 / 写内容块 / 读纯文本。"""

    async def read_docx_raw(
        self,
        document_id: str,
        *,
        max_chars: int = 20000,
    ) -> OfficeResult:
        """读取飞书云文档纯文本（docx raw_content）。"""
        try:
            url = (
                f"{self._base_url}/docx/v1/documents/{document_id}/raw_content"
            )
            resp = await self._get(
                url, timeout=120, follow_redirects=True,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"读取云文档正文失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            content = (data.get("data") or {}).get("content") or ""
            total_chars = len(content)
            truncated = total_chars > max_chars
            if truncated:
                content = content[:max_chars]

            return OfficeResult.data(
                content,
                truncated=truncated,
                meta={
                    "document_id": document_id,
                    "total_chars": total_chars,
                    "returned_chars": len(content),
                },
            )
        except Exception as exc:
            return self._failure("读取云文档正文", exc)

    async def create_docx(
        self,
        title: str,
        *,
        folder_token: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> OfficeResult:
        """创建飞书云文档（docx/v1/documents），可选写入 blocks。"""
        try:
            body: dict[str, Any] = {"title": title}
            if folder_token:
                body["folder_token"] = folder_token

            resp = await self._post(
                f"{self._base_url}/docx/v1/documents", json=body, timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"创建云文档失败：code={data.get('code')} msg={data.get('msg')}"
                )

            document = (data.get("data") or {}).get("document") or {}
            document_id = document.get("document_id") or ""
            if not document_id:
                return OfficeResult.failure("创建云文档成功但未返回 document_id")

            url = document.get("url") or self._file_url(document_id, "docx")
            result = OfficeResult.link(
                url, file_token=document_id, message=f"已创建云文档《{title}》",
            )

            if blocks:
                written = await self.write_blocks(document_id, blocks, index=0)
                if written.kind == "error":
                    return OfficeResult(
                        kind="error",
                        error=(
                            f"云文档已创建（{document_id}）但写入内容失败："
                            f"{written.error}"
                        ),
                        url=url,
                        file_token=document_id,
                    )
                result.message = (
                    f"已创建云文档《{title}》并写入 {len(blocks)} 个内容块"
                )
            return result
        except Exception as exc:
            return self._failure("创建云文档", exc)

    async def write_blocks(
        self,
        document_id: str,
        blocks: list[dict[str, Any]],
        *,
        index: int = 0,
    ) -> OfficeResult:
        """向既有云文档写入内容块（docx children API）。"""
        try:
            if not blocks:
                return OfficeResult.link(
                    self._file_url(document_id, "docx"),
                    file_token=document_id,
                    message="没有需要写入的内容块",
                )

            body: dict[str, Any] = {
                "children": blocks,
                "index": max(0, int(index)),
            }
            resp = await self._post(
                f"{self._base_url}/docx/v1/documents/{document_id}"
                f"/blocks/{document_id}/children",
                json=body,
                timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"写入云文档内容失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            return OfficeResult.link(
                self._file_url(document_id, "docx"),
                file_token=document_id,
                message=f"已写入 {len(blocks)} 个内容块",
            )
        except Exception as exc:
            return self._failure("写入云文档内容", exc)

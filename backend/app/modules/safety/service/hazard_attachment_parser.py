"""脚本1 附件解析适配器：飞书岗位资料附件 → 本地文本。

Ticket 05：让脚本 1 能读取 Bitable「岗位资料附件（人工）」的云文档 URL / 文件 token，
下载（复用 `SafetyBitableClient` 的下载逻辑）→ 解析（复用 `knowledge/document_parser.SafetyDocumentParser`）→ 文本。

失败路径一律返回 None（附件为空 / 下载失败 / 解析失败），节点保持等待、不产生部分写入。
客户端与文档解析器均可注入，测试用 fake 客户端 + fake 解析器，无网络/无真实文档依赖。
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class HazardAttachmentParser:
    """将 Bitable 岗位资料附件（URL / 文件 token）下载并解析为文本。

    注入 `client`（暴露 `download_attachment_from_url(url)` / `download_attachment(token)` /
    `download_bitable_attachment(token, record_id, field_id)` 的飞书客户端接口，生产为
    `SafetyBitableClient`，测试为 fake）与 `document_parser`（默认 `SafetyDocumentParser`，
    静态 `extract_text(path, max_chars)`）。

    用法:
        parser = HazardAttachmentParser(client)
        text = await parser("https://xxx.feishu.cn/wiki/FileToken123")   # URL / 裸 token
        text = await parser({                                            # Bitable 附件（URL 字段）
            "url": "https://.../medias/Token123/download?token=Token123",
            "record_id": "recXXX",
            "field_name": "岗位资料附件（人工）",
        })
        # → str | None（None = 下载/解析失败）
    """

    def __init__(
        self,
        client: object,
        *,
        document_parser: object | None = None,
        max_chars: int = 30000,
    ):
        self.client = client
        self.document_parser = document_parser
        self.max_chars = max_chars
        # 附件字段 field_id 惰性解析缓存（extra 位权限定用；每次只解析一次）
        self._field_id: str | None = None

    @property
    def _doc_parser(self) -> object:
        """惰性默认文档解析器（避免模块级导入 PyMuPDF 等重型依赖）。"""
        if self.document_parser is None:
            from app.modules.safety.knowledge.document_parser import (
                SafetyDocumentParser,
            )

            self.document_parser = SafetyDocumentParser
        return self.document_parser

    async def __call__(self, source: str | dict) -> str | None:
        """附件 URL / 文件 token / 下载上下文 dict → 文本；失败返回 None。

        传入 dict 时（Bitable 附件上下文）走 `_download_context`：构建 bitablePerm
        extra 后经 Drive API 下载；字符串走原有 URL/裸 token 路径。
        """
        if not source:
            return None
        src = (
            str(source.get("url") or source.get("file_token") or "")
            if isinstance(source, dict)
            else str(source or "")
        )
        # 飞书云文档（`/docx/` 链接）优先走 raw_content API（返回纯文本，跳过字节解析）
        docx_text = await self._try_docx_raw(src)
        if docx_text:
            return docx_text
        content = (
            await self._download_context(source)
            if isinstance(source, dict)
            else await self._download(source)
        )
        if not content:
            logger.warning("脚本1 附件下载失败: %s...", src[:80])
            return None
        return self._parse(content, src)

    async def _try_docx_raw(self, src: str) -> str | None:
        """飞书云文档（`/docx/` 链接）→ raw_content API 纯文本；非 docx 或失败返回 None。

        「岗位资料附件（人工）」可能粘贴飞书云文档链接（`https://xxx.feishu.cn/docx/{token}`）。
        docx 不是 Drive 普通文件/媒体附件，URL 预签名下载与 token 下载均不可达；但
        `docx/v1/documents/{id}/raw_content` 可直接返回文档纯文本。文本超长时截断到 max_chars。
        """
        if not _looks_like_url(src) or "/docx/" not in src:
            return None
        if not hasattr(self.client, "download_docx_raw"):
            return None
        token = _extract_file_token(src)
        if not token:
            return None
        try:
            text = await self.client.download_docx_raw(token)
        except Exception as e:
            logger.warning("脚本1 docx raw_content 获取异常: %s", e)
            return None
        if not text:
            return None
        logger.info("脚本1 附件经 docx raw_content 取文本成功: len=%d", len(text))
        return text[: self.max_chars]

    async def _download(self, source: str) -> bytes | None:
        """下载附件字节。

        策略（与 CLAUDE.md 照片同步一致，优先预签名 URL）：
        1. 完整 URL → 预签名 URL 下载（`download_attachment_from_url`）；
        2. URL 下载失败且 URL 含文件 token →
           a. 飞书 Drive 普通文件（`download_drive_file`，岗位资料附件 `file/` 链接、存量数据）；
           b. 回退 Bitable 媒体附件（`download_attachment`，需附件注册 + extra）。
        3. 裸文件 token → 先 Drive 文件、再 Bitable 媒体。
        """
        if _looks_like_url(source):
            content = await self.client.download_attachment_from_url(source)
            if content:
                return content
            token = _extract_file_token(source)
            if token:
                return await self._download_token(token)
            return None
        return await self._download_token(source)

    async def _download_token(self, token: str) -> bytes | None:
        """按文件 token 下载：优先 Drive 普通文件，其次 Bitable 媒体附件。"""
        if hasattr(self.client, "download_drive_file"):
            content = await self.client.download_drive_file(token)
            if content:
                return content
        if hasattr(self.client, "download_attachment"):
            return await self.client.download_attachment(token)
        return None

    async def _download_context(self, ctx: dict) -> bytes | None:
        """Bitable 附件下载（构建 extra 位权限定）。

        Bitable URL 字段中的附件 link 指向 `drive/v1/medias/{token}/download`，
        直接下载需带 `extra`（bitablePerm，含 tableId + 附件所属 record/field）。
        需要 record_id + 附件字段 field_id（按字段名惰性解析）。任一缺失或下载失败
        则回退到 URL 直下/裸 token 路径。
        """
        url = str(ctx.get("url") or "")
        token = str(ctx.get("file_token") or "") or (_extract_file_token(url) or "")
        record_id = str(ctx.get("record_id") or "")
        if not token or not record_id:
            return await self._download(url or token)
        field_id = str(ctx.get("field_id") or "") or await self._resolve_field_id(
            str(ctx.get("field_name") or "")
        )
        if not field_id:
            logger.warning(
                "脚本1 附件字段 field_id 未解析，回退 URL 下载: field=%s",
                ctx.get("field_name"),
            )
            return await self._download(url or token)
        if not hasattr(self.client, "download_bitable_attachment"):
            logger.warning(
                "脚本1 客户端不支持 bitablePerm extra 下载，回退 URL 下载"
            )
            return await self._download(url or token)
        content = await self.client.download_bitable_attachment(
            token, record_id, field_id,
        )
        if content:
            return content
        # extra 下载失败 → 回退 URL 直下（预签名 URL / token）
        return await self._download(url or token)

    async def _resolve_field_id(self, field_name: str) -> str | None:
        """按字段名解析附件字段的 field_id（惰性缓存，仅解析一次）。"""
        if not field_name or not hasattr(self.client, "get_field_id_by_name"):
            return None
        if self._field_id is None:
            self._field_id = await self.client.get_field_id_by_name(field_name)
        return self._field_id

    def _parse(self, content: bytes, source: str) -> str | None:
        """临时文件落盘 → 文档解析 → 文本；解析失败返回 None。"""
        ext = _guess_extension(source)
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
                f.write(content)
                path = f.name
            try:
                text = self._doc_parser.extract_text(path, max_chars=self.max_chars)
            finally:
                Path(path).unlink(missing_ok=True)
        except Exception as e:  # 文档解析失败不致命，保持等待
            logger.warning("脚本1 附件解析失败: %s", e)
            return None
        return text if text else None


def _looks_like_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


_URL_TOKEN_RE = re.compile(r"(?:token|file_token|media_id)=([A-Za-z0-9_\-]+)")


def _extract_file_token(source: str) -> str | None:
    """从 URL 提取文件 token（优先 query 参数，其次去掉 query/fragment 后的路径最后一段）。"""
    m = _URL_TOKEN_RE.search(source)
    if m:
        return m.group(1)
    # 飞书 URL 形态：https://xxx.feishu.cn/wiki/<token> 或 /docx/<token>
    # 先剥离 query/fragment（docx 链接形如 /docx/<token>?from=from_copylink）
    path = source.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if _looks_like_token(path):
        return path
    return None


def _looks_like_token(segment: str) -> bool:
    return bool(segment) and all(
        c.isalnum() or c in ("_", "-") for c in segment
    ) and len(segment) >= 8


def _guess_extension(source: str) -> str:
    """从 URL 路径推断扩展名；未知默认 .docx（岗位资料附件常见云文档）。"""
    import os

    _, ext = os.path.splitext(source.rsplit("?", 1)[0])
    if ext.lower() in {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}:
        return ext.lower()
    return ".docx"

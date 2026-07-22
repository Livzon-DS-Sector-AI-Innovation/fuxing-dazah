"""法规文档加载器 — 从飞书 Drive 下载法规标准文件并解析为纯文本。

复用安全模块飞书应用的 token 管理，调用飞书 Drive API 下载文件，
通过 DocumentParser 解析 PDF/DOCX/TXT 格式的法规文档。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from app.modules.safety.feishu.client import get_safety_tenant_token
from app.modules.safety.knowledge.knowledge_card import (
    KNOWLEDGE_DOCUMENTS,
)
from app.platform.integrations.ai.document_parser import DocumentParser

logger = logging.getLogger(__name__)

# 上传文件存储目录
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "uploads" / "safety" / "knowledge"

# 飞书 Drive API
FEISHU_DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"


class DocumentLoader:
    """从飞书 Drive 下载法规文档并解析为纯文本。

    用法:
        loader = DocumentLoader()
        text = await loader.download_and_parse("GGCuboOZJoxax2x7aVXcXyrWnAM")
    """

    def __init__(self, uploads_dir: Path | None = None):
        self.uploads_dir = uploads_dir or UPLOADS_DIR
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    async def _token(self) -> str:
        return await get_safety_tenant_token()

    # ── 公共 API ──

    async def download_and_parse(
        self,
        file_token: str,
        title: str = "",
        max_chars: int = 50000,
    ) -> tuple[str, str]:
        """下载文件并解析为纯文本。

        Args:
            file_token: 飞书 Drive 文件 token（从飞书文件链接提取）
            title: 文档标题（用于日志和文件命名）
            max_chars: 最大提取字符数（超出截断），默认 50000

        Returns:
            (parsed_text, saved_file_path)  — 解析后的纯文本 + 本地文件路径

        Raises:
            RuntimeError: 下载或解析失败
        """
        # 1. 下载
        logger.info("下载法规文档: title=%s file_token=%s", title, file_token)
        content_bytes = await self._download_from_drive(file_token)

        if not content_bytes:
            raise RuntimeError(f"下载失败: {title} (file_token={file_token})")

        logger.info("下载成功: title=%s size=%d bytes", title, len(content_bytes))

        # 2. 检测文件格式并保存
        ext = self._detect_extension(content_bytes)
        safe_name = self._safe_filename(title, ext)
        file_path = self.uploads_dir / safe_name
        file_path.write_bytes(content_bytes)
        logger.info("文件已保存: %s", file_path)

        # 3. 解析文本
        try:
            text = DocumentParser.extract_text(str(file_path), max_chars=max_chars)
        except Exception as e:
            logger.error("解析文档失败: %s, error=%s", title, e)
            # 尝试作为纯文本读取
            text = self._fallback_text_read(content_bytes)

        if not text.strip():
            raise RuntimeError(f"解析结果为空: {title}")

        logger.info(
            "解析完成: title=%s chars=%d preview=%s...",
            title, len(text), text[:80].replace("\n", " "),
        )
        return text, str(file_path)

    async def load_all_documents(
        self,
        priority_filter: str | None = None,
        max_chars: int = 50000,
    ) -> list[dict[str, Any]]:
        """批量加载 KNOWLEDGE_DOCUMENTS 中的所有法规文档。

        Args:
            priority_filter: 仅加载指定优先级（"P0"/"P1"/"P2"），None 表示全部
            max_chars: 每份文档的最大提取字符数

        Returns:
            [{"meta": KnowledgeDocumentMeta, "text": ..., "file_path": ...}, ...]
            下载失败时对应条目被跳过（记录日志）
        """
        documents = KNOWLEDGE_DOCUMENTS
        if priority_filter:
            documents = [d for d in documents if d.priority == priority_filter]

        results: list[dict[str, Any]] = []
        for doc in documents:
            try:
                text, file_path = await self.download_and_parse(
                    file_token=doc.file_token,
                    title=doc.title,
                    max_chars=max_chars,
                )
                results.append({
                    "meta": doc,
                    "text": text,
                    "file_path": file_path,
                })
            except Exception as e:
                logger.error(
                    "加载文档失败 [%s/%s]: %s — %s",
                    doc.priority, doc.title, doc.file_token, e,
                )
                continue

        logger.info(
            "批量加载完成: 成功=%d/%d",
            len(results), len(documents),
        )
        return results

    async def download_metadata(self, file_token: str) -> dict[str, Any] | None:
        """获取飞书文件的元信息（文件名、类型、大小等）。

        GET /open-apis/drive/v1/files/{file_token}
        """
        token = await self._token()
        url = f"{FEISHU_DRIVE_BASE}/files/{file_token}"

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        return data.get("data", {})
                logger.warning(
                    "获取文件元信息失败: file_token=%s status=%s body=%s",
                    file_token, resp.status_code, (resp.text or "")[:200],
                )
        except Exception as e:
            logger.error("获取文件元信息异常: file_token=%s error=%s", file_token, e)

        return None

    # ── 内部方法 ──

    async def _download_from_drive(self, file_token: str) -> bytes | None:
        """从飞书 Drive API 下载文件原始内容。

        GET /open-apis/drive/v1/files/{file_token}/download
        """
        token = await self._token()
        url = f"{FEISHU_DRIVE_BASE}/files/{file_token}/download"

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
            resp = await http.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                # 拒绝 JSON/HTML 错误响应（飞书报错时 Content-Type 可能是 JSON）
                if ct.startswith("application/json") or ct.startswith("text/html"):
                    text = resp.content[:500].decode(errors="replace")
                    logger.warning(
                        "飞书 Drive 返回非文件内容 (ct=%s): %s",
                        ct, text,
                    )
                    return None
                return resp.content

            logger.warning(
                "飞书 Drive 下载失败: file_token=%s status=%s body=%s",
                file_token, resp.status_code, (resp.text or "")[:200],
            )
            return None

    @staticmethod
    def _detect_extension(content: bytes) -> str:
        """通过文件头魔数检测文件扩展名。"""
        if content[:4] == b"%PDF":
            return ".pdf"
        if content[:2] == b"PK":
            # ZIP 格式 — 可能是 DOCX 或 XLSX
            return ".docx"
        # 尝试 UTF-8 解码判断是否为纯文本
        try:
            text = content[:200].decode("utf-8")
            if "<!DOCTYPE html" in text.lower() or "<html" in text.lower():
                return ".html"
            return ".txt"
        except UnicodeDecodeError:
            return ".bin"

    @staticmethod
    def _safe_filename(title: str, ext: str) -> str:
        """从文档标题生成安全的文件名。"""
        safe = title.replace("/", "_").replace("\\", "_").replace(":", "_")
        safe = safe.replace(" ", "_").replace("《", "").replace("》", "")
        # 限制长度
        if len(safe) > 80:
            safe = safe[:80]
        return f"{safe}{ext}"

    @staticmethod
    def _fallback_text_read(content: bytes) -> str:
        """解析失败时尝试以 UTF-8 纯文本方式读取。"""
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return ""

"""Safety business workflows."""

import logging
import os
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import (
    delete_object as minio_delete,
    get_object as minio_get,
    is_enabled as minio_enabled,
    upload_object,
)
from app.modules.safety.document_parser import (
    extract_to_markdown as _extract_to_markdown,
)
from app.modules.safety.repository import SafetyRepository
from app.platform.integrations.ai.document_parser import DocumentParser

logger = logging.getLogger(__name__)


class AttachmentService:
    """AI 工作流调用文档附件管理服务

    职责：
    - 上传附件并转换为 Markdown 供 AI 读取
    - 从知识库文章创建附件引用
    - 删除附件及其关联的 Markdown 文件
    - 提供附件预览文件路径
    """

    UPLOAD_DIR = os.path.join("uploads", "safety", "ai-workflow")
    MD_SUBDIR = "md"

    def __init__(self):
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(os.path.join(self.UPLOAD_DIR, self.MD_SUBDIR), exist_ok=True)

    async def upload_attachment(self, file) -> dict:
        """上传附件并转换为 Markdown。

        流程：
        1. 保存原始文件到 uploads/safety/ai-workflow/{uuid}.{ext}
        2. 调用 DocumentParser 提取文本并转为 Markdown
        3. 保存 MD 文件到 uploads/safety/ai-workflow/md/{uuid}.md
        4. 返回附件元数据

        支持格式：PDF, DOCX, XLSX, TXT, MD
        """

        content = await file.read()
        original_name = file.filename or "unknown"
        ext = os.path.splitext(original_name)[1].lower()

        if ext not in DocumentParser.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"不支持的文件格式: {ext}，支持的格式: {', '.join(sorted(DocumentParser.SUPPORTED_EXTENSIONS))}"
            )

        attachment_id = str(uuid.uuid4())
        file_size = len(content)

        # 1. 保存原始文件
        if minio_enabled():
            upload_object("safety", f"ai-workflow/{attachment_id}{ext}", content, file_size, "application/octet-stream")
        else:
            original_path = os.path.join(self.UPLOAD_DIR, f"{attachment_id}{ext}")
            with open(original_path, "wb") as f:
                f.write(content)

        # 2. 提取文本并转为 Markdown
        if minio_enabled():
            # In MinIO mode, write content to a temp file for DocumentParser
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                md_content = _extract_to_markdown(tmp_path)
            except Exception:
                md_content = f"# 📎 {original_name}\n\n> 未能解析文档内容，请查看原始文件。"
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            # Local mode: can read directly from saved file
            try:
                md_content = _extract_to_markdown(original_path)
            except Exception:
                md_content = f"# 📎 {original_name}\n\n> 未能解析文档内容，请查看原始文件。"

        # 3. 保存 MD 文件
        md_bytes = md_content.encode("utf-8")
        if minio_enabled():
            upload_object("safety", f"ai-workflow/md/{attachment_id}.md", md_bytes, len(md_bytes), "text/markdown; charset=utf-8")
            markdown_path = f"ai-workflow/md/{attachment_id}.md"
        else:
            md_path = os.path.join(self.UPLOAD_DIR, self.MD_SUBDIR, f"{attachment_id}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            markdown_path = md_path

        # 4. 构建预览 URL
        preview_url = f"/api/v1/safety/ai-workflow-configs/attachments/{attachment_id}/preview"

        return {
            "id": attachment_id,
            "type": "file",
            "name": original_name,
            "url": preview_url,
            "original_name": original_name,
            "file_type": ext.lstrip("."),
            "file_size": file_size,
            "markdown_path": markdown_path,
            "knowledge_id": None,
            "created_at": datetime.now().isoformat(),
        }

    async def delete_attachment(self, attachment_id: str) -> bool:
        """删除附件及其关联文件。

        清理（MinIO 模式：按 object_key 删除；本地模式：glob + remove）：
        - ai-workflow/{attachment_id}.* （原始文件）
        - ai-workflow/md/{attachment_id}.md （MD 文件）
        """
        import glob as glob_m

        if minio_enabled():
            # MinIO mode: we know the pattern but not the extension
            # Delete common extensions; 404s are ignored by MinIO
            for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".png", ".jpg"):
                try:
                    minio_delete("safety", f"ai-workflow/{attachment_id}{ext}")
                except Exception:
                    pass
            try:
                minio_delete("safety", f"ai-workflow/md/{attachment_id}.md")
            except Exception:
                pass
            return True

        # Local mode
        deleted = False
        for f in glob_m.iglob(os.path.join(self.UPLOAD_DIR, f"{attachment_id}.*")):
            os.remove(f)
            deleted = True

        md_file = os.path.join(self.UPLOAD_DIR, self.MD_SUBDIR, f"{attachment_id}.md")
        if os.path.exists(md_file):
            os.remove(md_file)
            deleted = True

        return deleted

    def get_preview_path(self, attachment_id: str) -> str | None:
        """获取附件原始文件的路径，供预览使用。

        MinIO mode: returns the object_key (not a local path).
        Local mode: returns the local file path.
        """
        import glob as glob_m

        if minio_enabled():
            # Return the object_key prefix — caller must try common extensions
            return f"ai-workflow/{attachment_id}"

        matches = list(glob_m.iglob(os.path.join(self.UPLOAD_DIR, f"{attachment_id}.*")))
        if matches:
            return matches[0]
        return None

    async def create_knowledge_attachments(
        self, knowledge_ids: list[str], db: AsyncSession
    ) -> list[dict]:
        """从知识库文章创建附件引用。

        流程：
        1. 查询 knowledge_articles 表获取文章内容
        2. 将文章内容转为 Markdown 文件供 AI 读取
        3. 返回附件元数据列表
        """

        repo = SafetyRepository(db)
        results: list[dict] = []

        for kid in knowledge_ids:
            try:
                article_id = uuid.UUID(kid)
                article = await repo.get_knowledge_article_by_id(article_id)
            except (ValueError, TypeError):
                continue

            if not article:
                continue

            attachment_id = str(uuid.uuid4())

            # 构建 Markdown 内容
            md_lines = [f"# 📚 {article.title}"]
            if article.summary:
                md_lines.append(f"\n> {article.summary}")
            if article.content:
                md_lines.append(f"\n{article.content}")
            if article.tags:
                md_lines.append(f"\n\n**标签**: {article.tags}")
            if article.category:
                md_lines.append(f"**分类**: {article.category}")

            md_content = "\n".join(md_lines)

            # 保存 MD 文件
            md_bytes = md_content.encode("utf-8")
            if minio_enabled():
                upload_object("safety", f"ai-workflow/md/{attachment_id}.md", md_bytes, len(md_bytes), "text/markdown; charset=utf-8")
                markdown_path = f"ai-workflow/md/{attachment_id}.md"
            else:
                md_path = os.path.join(self.UPLOAD_DIR, self.MD_SUBDIR, f"{attachment_id}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                markdown_path = md_path

            preview_url = f"/api/v1/safety/ai-workflow-configs/attachments/{attachment_id}/preview"

            results.append({
                "id": attachment_id,
                "type": "knowledge",
                "name": article.title,
                "url": preview_url,
                "original_name": None,
                "file_type": "md",
                "file_size": len(md_content.encode("utf-8")),
                "markdown_path": markdown_path,
                "knowledge_id": kid,
                "created_at": datetime.now().isoformat(),
            })

        return results


# ==================== 特殊作业管理 Service ====================



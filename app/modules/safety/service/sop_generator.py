"""SOP Generator Service — Web adapter for the safety-sop-generator plugin.

Calls the three-layer pipeline (extract → transform → render) from within
the FastAPI web service, wrapping synchronous calls in asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import is_enabled as minio_enabled
from app.core.storage import upload_object
from app.modules.safety.repository import SafetyRepository

# ── Plugin path resolution ─────────────────────────────────────────

_PLUGIN_DIR = Path(__file__).parents[5] / ".claude" / "skills" / "safety-sop-generator"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))


class SopGeneratorService:
    """安全操规标准化生成服务 — 调用插件 pipeline 的 Web 适配层"""

    UPLOAD_DIR = os.path.join("uploads", "safety", "regulations")

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    # ── Public API ─────────────────────────────────────────────────

    async def generate_from_draft(self, file: Any) -> dict:
        """上传旧版操规 → 运行三层 pipeline → 返回标准化内容

        Args:
            file: FastAPI UploadFile object (.docx)

        Returns:
            dict with keys: regulation_id, meta, content, status
        """

        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        # 1. Save uploaded draft
        draft_path = await self._save_upload(file)

        # 2. Create regulation record (draft status)
        name = file.filename or "unknown"
        reg = await self._create_draft_regulation(name, draft_path)

        # 3. Run the generator pipeline (synchronous, in thread)
        pdf_local_path = os.path.join(
            self.UPLOAD_DIR, f"{reg.id}_{int(datetime.now().timestamp())}.pdf"
        )
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        result = await asyncio.to_thread(
            self._run_pipeline_sync, draft_path, str(pdf_local_path)
        )

        # 4. Read generated Markdown
        md_path = result.get("md_path", "")
        content = ""
        if md_path and os.path.exists(md_path):
            with open(md_path, encoding="utf-8") as f:
                content = f.read()

        # 5. Upload PDF to MinIO (or keep local path)
        pdf_stored_path: str = pdf_local_path
        if minio_enabled() and os.path.exists(pdf_local_path):
            with open(pdf_local_path, "rb") as f:
                pdf_data = f.read()
            object_key = f"regulation/{reg.id}_export_{int(datetime.now().timestamp())}.pdf"
            upload_object("safety", object_key, pdf_data, len(pdf_data), "application/pdf")
            pdf_stored_path = object_key

        # 6. Update regulation record with generated content
        await self.repo.update_regulation(
            reg.id,
            {
                "content": content,
                "status": "generated",
                "document_path": pdf_stored_path,
                "document_original_name": os.path.basename(pdf_stored_path),
            },
        )
        await self.session.flush()

        meta = result.get("meta", {})
        # Normalize meta (it might be a DotDict or dataclass)
        if hasattr(meta, "__dict__"):
            meta = {
                "product_name": getattr(meta, "product_name", ""),
                "post_name": getattr(meta, "post_name", ""),
                "department": getattr(meta, "department", ""),
                "doc_number": getattr(meta, "doc_number", ""),
                "effective_date": getattr(meta, "effective_date", ""),
                "company_name": getattr(meta, "company_name", ""),
            }
        elif isinstance(meta, dict):
            meta = dict(meta)

        return {
            "regulation_id": str(reg.id),
            "meta": meta,
            "content": content,
            "status": "generated",
        }

    async def update_content(
        self, regulation_id: uuid.UUID, content: str, status: str | None = None
    ) -> Any | None:
        """保存用户编辑后的 Markdown 内容"""
        update_data: dict[str, Any] = {"content": content}
        if status:
            update_data["status"] = status
        return await self.repo.update_regulation(regulation_id, update_data)

    @staticmethod
    def _parse_markdown_header_meta(content: str) -> dict[str, str]:
        """从 Markdown 内容中解析页眉元信息（文件编号/生效日期/颁发部门）。

        前端编辑器将这些字段以 **字段名：** 值 格式存入 Markdown 前导区。
        解析成功时返回对应值；未找到时返回空字符串。
        """
        import re

        result: dict[str, str] = {}
        lines = content.split("\n")
        for line in lines[:15]:
            line = line.strip()
            if not line or line == "---":
                continue
            m = re.match(r"\*\*文件编号[：:]\s*\*\*\s*(.*)", line)
            if m:
                result["doc_number"] = m.group(1).strip()
                continue
            m = re.match(r"\*\*生效日期[：:]\s*\*\*\s*(.*)", line)
            if m:
                result["effective_date"] = m.group(1).strip()
                continue
            m = re.match(r"\*\*颁发部门[：:]\s*\*\*\s*(.*)", line)
            if m:
                result["department"] = m.group(1).strip()
                continue
            # Stop at first non-meta, non-blank, non-separator line
            if not line.startswith("**"):
                break
        return result

    async def export_pdf(self, regulation_id: uuid.UUID) -> str | None:
        """将存储的 Markdown 渲染为 PDF，返回文件路径

        Returns:
            Absolute path to the generated PDF file, or None on failure.
        """
        reg = await self.repo.get_regulation_by_id(regulation_id)
        if not reg or not reg.content:
            return None

        # Parse header meta from markdown content (editor-saved values take priority)
        md_meta = self._parse_markdown_header_meta(reg.content or "")

        # Build meta dict: markdown header > DB record fields
        pdf_meta = {
            "company_name": "",
            "company_name_en": "",
            "doc_number": md_meta.get("doc_number") or reg.regulation_no or "",
            "effective_date": md_meta.get("effective_date") or "",
            "department": md_meta.get("department") or reg.position or "",
            "product_name": reg.regulation_name or "",
            "post_name": "",
        }

        pdf_local_path = os.path.join(
            self.UPLOAD_DIR,
            f"{regulation_id}_export_{int(datetime.now().timestamp())}.pdf",
        )

        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        await asyncio.to_thread(
            self._render_markdown_sync, reg.content, str(pdf_local_path), pdf_meta
        )

        # Upload to MinIO (or keep local path)
        if minio_enabled() and os.path.exists(pdf_local_path):
            with open(pdf_local_path, "rb") as f:
                pdf_data = f.read()
            object_key = f"regulation/{regulation_id}_export_{int(datetime.now().timestamp())}.pdf"
            upload_object("safety", object_key, pdf_data, len(pdf_data), "application/pdf")
            stored_path = object_key
        else:
            stored_path = pdf_local_path

        # Update status
        await self.repo.update_regulation(
            regulation_id,
            {"status": "exported", "document_path": stored_path},
        )
        await self.session.flush()

        return stored_path

    async def get_content(self, regulation_id: uuid.UUID) -> dict | None:
        """获取 Markdown 内容（供编辑器加载）"""
        reg = await self.repo.get_regulation_by_id(regulation_id)
        if not reg:
            return None
        return {
            "regulation_id": str(reg.id),
            "regulation_name": reg.regulation_name,
            "content": reg.content or "",
            "status": reg.status or "draft",
        }

    # ── Private helpers ────────────────────────────────────────────

    async def _save_upload(self, file: Any) -> str:
        """Save uploaded .docx — MinIO or local, return path/object_key."""
        file_ext = os.path.splitext(file.filename or ".docx")[1]
        safe_name = f"draft_{uuid.uuid4().hex}{file_ext}"
        content = await file.read()
        await file.seek(0)  # Reset for potential re-reads

        if minio_enabled():
            object_key = f"regulation/{safe_name}"
            upload_object("safety", object_key, content, len(content), file.content_type or "application/octet-stream")
            return object_key

        file_path = os.path.join(self.UPLOAD_DIR, safe_name)
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(content)
        return file_path

    async def _create_draft_regulation(
        self, filename: str, draft_path: str
    ) -> Any:
        """Create an initial OperationRegulation record with draft status."""
        base_name = os.path.splitext(os.path.basename(filename))[0]
        create_data = {
            "regulation_no": f"GEN-{uuid.uuid4().hex[:8].upper()}",
            "regulation_name": base_name,
            "source_document_path": draft_path,
            "status": "draft",
        }
        reg = await self.repo.create_regulation(create_data)
        await self.session.flush()
        return reg

    @staticmethod
    def _run_pipeline_sync(draft_path: str, pdf_path: str) -> dict:
        """Synchronous pipeline call — runs in asyncio.to_thread."""
        from pipeline import run_pipeline

        return run_pipeline(
            draft_path=draft_path,
            output_pdf=pdf_path,
            keep_intermediate=True,  # Keep JSON & MD so we can read content
            work_dir=os.path.dirname(pdf_path),
        )

    @staticmethod
    def _render_markdown_sync(
        content: str, pdf_path: str, meta: dict
    ) -> None:
        """Synchronous Markdown → PDF render — runs in asyncio.to_thread."""
        from layer3_render_pdf import render

        render(content, pdf_path, meta)

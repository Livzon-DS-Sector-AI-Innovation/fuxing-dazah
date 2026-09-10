"""SOP Generator Service — Web adapter for the safety-sop-generator plugin.

Calls the three-layer pipeline (extract → transform → render) from within
the FastAPI web service, wrapping synchronous calls in asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import is_enabled as minio_enabled
from app.core.storage import upload_object
from app.modules.safety.repository import SafetyRepository

logger = logging.getLogger(__name__)

# ── Plugin path resolution ─────────────────────────────────────────

_PLUGIN_DIR = Path(__file__).parents[5] / ".claude" / "skills" / "safety-sop-generator"
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))


def _meta_to_dict(extracted) -> dict:
    """layer1 ExtractedMeta 对象 → dict（逐章生成函数 / 知识包 meta 参数）。"""
    meta = getattr(extracted, "meta", None)
    if meta is None:
        return {}
    if hasattr(meta, "__dict__"):
        return dict(meta.__dict__)
    return {}


def _tables_to_dict(tables) -> dict:
    """layer1 reference_tables（TableData dict）→ {"key": {"headers", "rows"}}。

    layer2_transform 与逐章生成函数均消费 dict 形态（headers 列表 + rows 行列表）。
    """
    result: dict = {}
    for k, v in (tables or {}).items():
        headers = list(getattr(v, "headers", []) or [])
        rows = [list(r) for r in (getattr(v, "rows", []) or [])]
        result[k] = {"headers": headers, "rows": rows}
    return result


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

        # 1.5. MinIO 模式下 draft_path 为 object key → 解析为本地可读文件（管线需本地路径）
        draft_local = await self._resolve_source_file(draft_path)
        if draft_local is None:
            raise RuntimeError("无法读取上传的源文档（本地与 MinIO 均不可读）")
        draft_is_tmp = draft_local != draft_path  # True = 下载的临时文件，结束需清理

        # 2. Create regulation record (draft status)
        name = file.filename or "unknown"
        reg = await self._create_draft_regulation(name, draft_path)

        # 2.5. 逐章 AI 主生成（ch3/5/6/7/8 内容 + ch9 选型）+ 知识参考包
        #      知识包/逐章 AI 任一失败 → 该章回退规则生成（占位文本），绝不阻塞管线。
        ai_data = None
        kb = None
        raw_text = None
        pre_extracted = None
        baseline_stages_list: list[str] = []
        sop_type = "process"  # 提取失败时保守按 process 处理（9 章产物均可审核）
        try:
            from layer1_extract import extract

            from app.modules.safety.knowledge.document_parser import (
                SafetyDocumentParser,
            )
            from app.modules.safety.service.sop_ai import (
                baseline_stages,
                build_knowledge_package,
                generate_ch3_risk,
                generate_ch5_params,
                generate_ch6_safety,
                generate_ch7_flow,
                generate_ch8_abnormal,
                generate_ch9_selection,
            )

            pre_extracted = await asyncio.to_thread(extract, draft_local)
            sop_type = getattr(pre_extracted, "sop_type", "process")
            if sop_type == "process":
                raw_text = await asyncio.to_thread(
                    SafetyDocumentParser.extract_text, draft_local, 100000
                )
                meta = _meta_to_dict(pre_extracted)
                ref_tables = _tables_to_dict(pre_extracted.reference_tables)
                baseline_stages_list = baseline_stages(pre_extracted)
                kb = await build_knowledge_package(
                    extracted=pre_extracted,
                    raw_text=raw_text,
                    meta=meta,
                    session=self.session,
                )
                ch3 = await generate_ch3_risk(
                    extracted=pre_extracted, ref_tables=ref_tables, kb=kb,
                    meta=meta, regulation_id=reg.id,
                )
                ch5 = await generate_ch5_params(
                    extracted=pre_extracted, ref_tables=ref_tables, kb=kb,
                    raw_text=raw_text, meta=meta, regulation_id=reg.id,
                )
                ch6 = await generate_ch6_safety(
                    extracted=pre_extracted, kb=kb, meta=meta, regulation_id=reg.id,
                )
                ch7 = await generate_ch7_flow(
                    extracted=pre_extracted, meta=meta, regulation_id=reg.id,
                )
                ch8 = await generate_ch8_abnormal(
                    extracted=pre_extracted, ref_tables=ref_tables, kb=kb,
                    meta=meta, regulation_id=reg.id,
                )
                ch9 = await generate_ch9_selection(
                    extracted=pre_extracted, ref_tables=ref_tables, kb=kb,
                    meta=meta, regulation_id=reg.id,
                )
                ai_data = {
                    "ch3": (ch3 or {}).get("rows") or [],
                    "ch5": (ch5 or {}).get("rows") or [],
                    "ch6": (ch6 or {}).get("rows") or [],
                    "ch7": (ch7 or {}).get("rows") or [],
                    "ch8": (ch8 or {}).get("rows") or [],
                    "ch9": (ch9 or {}).get("types") or [],
                }
                # 留档：逐章 AI 数据（pipeline 直接吃 dict，文件仅供排查）
                ai_data_path = os.path.join(self.UPLOAD_DIR, f"{reg.id}_ai_data.json")
                with open(ai_data_path, "w", encoding="utf-8") as f:
                    json.dump(ai_data, f, ensure_ascii=False, indent=2)
                logger.info(
                    "SOP 逐章 AI 生成完成：regulation=%s ch3=%d ch5=%d ch6=%d ch7=%d ch8=%d ch9=%d",
                    reg.id,
                    len(ai_data["ch3"]), len(ai_data["ch5"]),
                    len(ai_data["ch6"]), len(ai_data["ch7"]),
                    len(ai_data["ch8"]), len(ai_data["ch9"]),
                )
        except Exception as exc:  # noqa: BLE001 — AI 失败回退规则生成
            logger.warning("SOP 逐章 AI 生成失败，回退规则生成：%s", exc)
            ai_data = None
            pre_extracted = None

        # 3. Run the generator pipeline (synchronous, in thread)
        pdf_local_path = os.path.join(
            self.UPLOAD_DIR, f"{reg.id}_{int(datetime.now().timestamp())}.pdf"
        )
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        result = await asyncio.to_thread(
            self._run_pipeline_sync,
            draft_local,
            str(pdf_local_path),
            ai_data,
            pre_extracted,
        )

        # 4. Read generated Markdown
        md_path = result.get("md_path", "")
        content = ""
        if md_path and os.path.exists(md_path):
            with open(md_path, encoding="utf-8") as f:
                content = f.read()

        # 4.5. 生成质量硬基线评估（ch7 覆盖率 / ch5 数值溯源 / 占位符扫描）
        #      result dict 新增 generation_quality，仅供日志与测试；API 响应结构不变。
        generation_quality = None
        try:
            from app.modules.safety.service.sop_ai import (
                assess_generation_quality as _assess,
            )

            generation_quality = _assess(
                content,
                source_text=raw_text or "",
                kb=kb,
                baseline_stages=baseline_stages_list or None,
                ch7_rows=(ai_data or {}).get("ch7"),
                ch5_rows=(ai_data or {}).get("ch5"),
            )
        except Exception as exc:  # noqa: BLE001 — 质量评估失败仅告警，不阻塞
            logger.warning("SOP generation_quality 评估失败：%s", exc)
        if generation_quality:
            logger.info("SOP generation_quality: %s", generation_quality)

        # 5. Upload PDF to MinIO (or keep local path)
        pdf_stored_path: str = pdf_local_path
        if minio_enabled() and os.path.exists(pdf_local_path):
            with open(pdf_local_path, "rb") as f:
                pdf_data = f.read()
            object_key = f"regulation/{reg.id}_export_{int(datetime.now().timestamp())}.pdf"
            upload_object("safety", object_key, pdf_data, len(pdf_data), "application/pdf")
            pdf_stored_path = object_key

        # 6. Update regulation record with generated content
        #    重新生成时重置 AI 审核状态/说明（防新旧内容错位）
        await self.repo.update_regulation(
            reg.id,
            {
                "content": content,
                "status": "generated",
                "document_path": pdf_stored_path,
                "document_original_name": os.path.basename(pdf_stored_path),
                "ai_review_status": "pending",
                "ai_review_note": None,
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

        # 6.5. 自动 AI 审核：由 API handler 在 db.commit() 之后触发（详见 api/regulations.py）。
        #      原因：此处事务尚未提交，后台独立 session 按 READ COMMITTED 读不到未提交行，
        #      若在此 create_task 会导致新记录卡 pending 永不审核。
        if draft_is_tmp:
            try:
                os.remove(draft_local)
            except OSError:
                pass

        return {
            "regulation_id": str(reg.id),
            "meta": meta,
            "content": content,
            "status": "generated",
            "generation_quality": generation_quality,
            "ai_review_auto": sop_type == "process",  # 指示 handler 是否触发后台 AI 审核
        }

    async def update_content(
        self, regulation_id: uuid.UUID, content: str, status: str | None = None
    ) -> Any | None:
        """保存用户编辑后的 Markdown 内容"""
        update_data: dict[str, Any] = {"content": content}
        if status:
            update_data["status"] = status
        # 内容变更后旧 AI 审核结论失效 → 重置（防"新内容配旧结论"状态失同步）
        update_data["ai_review_status"] = "pending"
        update_data["ai_review_note"] = None
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

    # 导出格式 → (扩展名, 媒体类型)
    EXPORT_FORMATS: dict[str, tuple[str, str]] = {
        "pdf": (".pdf", "application/pdf"),
        "docx": (
            ".docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    }

    async def export(
        self, regulation_id: uuid.UUID, fmt: str = "pdf"
    ) -> tuple[str, str] | None:
        """将存储的 Markdown 渲染为 PDF 或 DOCX，返回 (存储路径, 媒体类型)。

        fmt: pdf | docx（非法值回退 pdf）。
        Returns:
            (stored_path, media_type)，失败返回 None。
        """
        fmt = fmt.lower()
        if fmt not in self.EXPORT_FORMATS:
            fmt = "pdf"
        ext, media_type = self.EXPORT_FORMATS[fmt]
        render_sync = self._render_docx_sync if fmt == "docx" else self._render_markdown_sync

        reg = await self.repo.get_regulation_by_id(regulation_id)
        if not reg or not reg.content:
            return None

        # Parse header meta from markdown content (editor-saved values take priority)
        md_meta = self._parse_markdown_header_meta(reg.content or "")

        # Build meta dict: markdown header > DB record fields
        export_meta = {
            "company_name": "",
            "company_name_en": "",
            "doc_number": md_meta.get("doc_number") or reg.regulation_no or "",
            "effective_date": md_meta.get("effective_date") or "",
            "department": md_meta.get("department") or reg.position or "",
            "product_name": reg.regulation_name or "",
            "post_name": "",
        }

        local_path = os.path.join(
            self.UPLOAD_DIR,
            f"{regulation_id}_export_{int(datetime.now().timestamp())}{ext}",
        )

        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

        await asyncio.to_thread(render_sync, reg.content, str(local_path), export_meta)

        # Upload to MinIO (or keep local path)
        if minio_enabled() and os.path.exists(local_path):
            with open(local_path, "rb") as f:
                file_data = f.read()
            object_key = f"regulation/{regulation_id}_export_{int(datetime.now().timestamp())}{ext}"
            upload_object("safety", object_key, file_data, len(file_data), media_type)
            stored_path = object_key
        else:
            stored_path = local_path

        # Update status
        await self.repo.update_regulation(
            regulation_id,
            {"status": "exported", "document_path": stored_path},
        )
        await self.session.flush()

        return stored_path, media_type

    async def read_exported_file(self, stored_path: str) -> bytes | None:
        """读取已导出文件的字节（MinIO object key 或本地路径）。

        供导出 endpoint 流式返回使用——存储读取统一收敛在 service 层，
        避免 API 层直接访问外部存储（MinIO）。
        """
        from app.core.storage import get_object as minio_get
        from app.core.storage import is_enabled as _minio_enabled

        if _minio_enabled():
            try:
                result = await asyncio.to_thread(minio_get, "safety", stored_path)
            except Exception as exc:  # noqa: BLE001 — 读文件失败按不存在处理
                logger.warning("MinIO 读取导出文件失败: %s (%s)", stored_path, exc)
                return None
            return result[0] if result else None

        if os.path.exists(stored_path):
            with open(stored_path, "rb") as f:
                return f.read()
        return None

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
            "ai_review_status": reg.ai_review_status or "pending",
            "ai_review_note": reg.ai_review_note,
        }

    async def run_ai_review(
        self, regulation_id: uuid.UUID, *, channel: str = "system"
    ) -> None:
        """执行操规 AI 审核（对照源文档），独立 session 后台运行。

        供 generate 自动触发（channel="system"）与手动重试 API（channel="web"）共用。

        成功：content 替换为重组后 Markdown、status=ai_reviewed、
              ai_review_status=completed、ai_review_note 落库。
        失败：content 不动、status 保持 generated、ai_review_status=failed、
              ai_review_note 记录失败原因。写库失败不影响生成主流程。
        """
        from app.core.database import async_session_factory

        async with async_session_factory() as bg_session:
            bg_service = SopGeneratorService(bg_session)
            try:
                reg = await bg_service.repo.get_regulation_by_id(regulation_id)
                if not reg or not reg.content:
                    logger.warning(
                        "run_ai_review: 操规不存在或内容为空 id=%s", regulation_id
                    )
                    return

                # 标记审核中
                await bg_service.repo.update_regulation(
                    regulation_id,
                    {"ai_review_status": "reviewing", "ai_review_note": None},
                )
                await bg_session.commit()

                # 源文档全文（本地优先，MinIO 兜底）
                source_text = await self._resolve_source_text(reg.source_document_path)
                if source_text is None:
                    await bg_service.repo.update_regulation(
                        regulation_id,
                        {
                            "ai_review_status": "failed",
                            "ai_review_note": {
                                "summary": "源文档读取失败，无法执行 AI 审核",
                                "failed_reason": "源文档读取失败",
                                "dimensions": [],
                                "chapter_fixes": [],
                            },
                        },
                    )
                    await bg_session.commit()
                    return

                from app.modules.safety.service.sop_ai import (
                    merge_reviews,
                    reassemble_sop,
                    sop_review_document,
                    sop_review_document_vision,
                )

                # ── 视觉通道：渲染当前内容 → 每页 PNG → 视觉审核（只报告，不自动改）──
                page_paths = await self._render_pages_for_review(reg.content)
                vision_review = None
                if page_paths:
                    try:
                        vision_review = await sop_review_document_vision(
                            page_paths=page_paths,
                            regulation_id=regulation_id,
                            channel=channel,
                        )
                    except Exception as exc:  # noqa: BLE001 — 视觉通道异常不阻断文本审核
                        logger.warning(
                            "SOP 视觉审核异常，降级为纯文本通道：%s", exc
                        )
                        vision_review = None
                    finally:
                        self._cleanup_review_pages(page_paths)

                # ── 文本通道：对照源文档的内容深度审核（自动改内容）──
                text_review = await sop_review_document(
                    source_text=source_text,
                    generated_md=reg.content,
                    regulation_id=regulation_id,
                    channel=channel,
                )
                if not text_review:
                    await bg_service.repo.update_regulation(
                        regulation_id,
                        {
                            "ai_review_status": "failed",
                            "ai_review_note": {
                                "summary": "AI 审核失败（3 次调用均失败或结果校验不过），保留原稿，可重试",
                                "failed_reason": "AI 调用失败或结果校验不过",
                                "dimensions": [],
                                "chapter_fixes": [],
                            },
                        },
                    )
                    await bg_session.commit()
                    return

                # 合并双通道；视觉不可用时追加「排版布局」warn 维度提示
                review = merge_reviews(text_review, vision_review)
                if not vision_review:
                    review["dimensions"] = list(review.get("dimensions", [])) + [
                        {
                            "dimension": "排版布局",
                            "status": "warn",
                            "detail": "视觉审核未执行（渲染或视觉模型不可用），排版布局未检查",
                        }
                    ]

                # 重组 9 章（ch1/ch9 rewrite 自动降级为 append）
                reassembled = reassemble_sop(
                    reg.content, review.get("chapter_fixes") or []
                )
                review_note = {
                    **review,
                    "reviewed_at": datetime.now().isoformat(timespec="seconds"),
                }
                await bg_service.repo.update_regulation(
                    regulation_id,
                    {
                        "content": reassembled,
                        "status": "ai_reviewed",
                        "ai_review_status": "completed",
                        "ai_review_note": review_note,
                    },
                )
                await bg_session.commit()
                logger.info(
                    "SOP AI 审核完成：regulation=%s dims=%d fixes=%d layout=%d content=%d→%d chars",
                    regulation_id,
                    len(review.get("dimensions", [])),
                    len(review.get("chapter_fixes", [])),
                    len(review.get("layout_issues", []) or []),
                    len(reg.content),
                    len(reassembled),
                )
            except Exception as exc:  # noqa: BLE001 — 审核失败不阻断生成
                logger.exception("run_ai_review 异常 regulation=%s", regulation_id)
                try:
                    await bg_service.repo.update_regulation(
                        regulation_id,
                        {
                            "ai_review_status": "failed",
                            "ai_review_note": {
                                "summary": "AI 审核异常，保留原稿，可重试",
                                "failed_reason": f"AI 审核异常: {str(exc)[:500]}",
                                "dimensions": [],
                                "chapter_fixes": [],
                            },
                        },
                    )
                    await bg_session.commit()
                except Exception:
                    logger.exception(
                        "run_ai_review 失败状态写入失败 regulation=%s", regulation_id
                    )

    # ── Private helpers ────────────────────────────────────────────

    async def _render_pages_for_review(self, content: str) -> list[str]:
        """渲染 Markdown 内容为 PDF 并导出每页 PNG（供视觉审核送审）。

        临时 PDF 用完即删；PNG 由调用方通过 _cleanup_review_pages 清理。
        渲染/导出任一失败返回 []（视觉通道跳过，不阻断文本审核）。
        """
        from app.modules.safety.vision.utils import pdf_to_page_images

        if not content:
            return []
        pdf_path: str | None = None
        try:
            work_dir = os.path.join(self.UPLOAD_DIR, "review_pages")
            os.makedirs(work_dir, exist_ok=True)
            pdf_path = os.path.join(work_dir, f"review_{uuid.uuid4().hex}.pdf")
            meta = self._parse_markdown_header_meta(content)
            await asyncio.to_thread(self._render_markdown_sync, content, pdf_path, meta)
            png_dir = os.path.join(work_dir, f"review_{uuid.uuid4().hex}")
            return await asyncio.to_thread(
                pdf_to_page_images, pdf_path, png_dir, max_pages=24
            )
        except Exception as exc:  # noqa: BLE001 — 渲染失败仅跳过视觉通道
            logger.warning("渲染操规页面供视觉审核失败: %s", exc)
            return []
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass

    @staticmethod
    def _cleanup_review_pages(page_paths: list[str]) -> None:
        """删除视觉审核临时页面 PNG 及其目录（best-effort）。"""
        png_dir = os.path.dirname(page_paths[0]) if page_paths else None
        for p in page_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        if png_dir:
            try:
                os.rmdir(png_dir)
            except OSError:
                pass

    async def _resolve_source_file(self, source_path: str | None) -> str | None:
        """存储路径 → 本地可读文件路径。

        本地路径原样返回；MinIO object key 下载到 UPLOAD_DIR 临时文件并返回其路径。
        返回的若为下载临时文件（返回值 != source_path），调用方负责清理。
        任一环节失败返回 None。

        下载的临时文件名保留原始 stem（去掉随机 uuid 后缀）——layer1 从文件名
        兜底解析产品/岗位名，若用 src_<uuid>.docx 之类随机名，会把临时文件名
        泄漏进生成的操规正文（验收复现：新线纯化 ch1 出现 src_d89b...）。
        """
        from app.core.storage import get_object as minio_get
        from app.core.storage import is_enabled as _minio_enabled

        if not source_path:
            return None
        if os.path.exists(source_path):
            return source_path

        # 非本地路径 → MinIO 下载到临时文件
        if not _minio_enabled():
            logger.warning("文件本地不存在且未启用 MinIO: %s", source_path)
            return None
        try:
            result = await asyncio.to_thread(minio_get, "safety", source_path)
            if result is None:
                logger.warning("MinIO 读取文件失败: %s", source_path)
                return None
            data = result[0]
            ext = os.path.splitext(source_path)[1] or ".docx"
            stem = os.path.splitext(os.path.basename(source_path))[0]
            # 去掉自身的随机 uuid 后缀再补新后缀，保持文件名可读且防并发冲突
            readable_stem = re.sub(r"_[0-9a-f]{8,}$", "", stem)
            os.makedirs(self.UPLOAD_DIR, exist_ok=True)
            tmp_path = os.path.join(
                self.UPLOAD_DIR, f"{readable_stem}_{uuid.uuid4().hex[:8]}{ext}"
            )
            with open(tmp_path, "wb") as f:
                f.write(data)
            return tmp_path
        except Exception as exc:
            logger.warning("MinIO 下载文件失败: %s", exc)
            return None

    async def _resolve_source_text(self, source_path: str | None) -> str | None:
        """读取源文档全文：本地优先，MinIO object key 下载兜底（复用 _resolve_source_file）。

        返回提取的纯文本；任一环节失败返回 None（由调用方按审核失败处理）。
        """
        from app.modules.safety.knowledge.document_parser import (
            SafetyDocumentParser,
        )

        local_path = await self._resolve_source_file(source_path)
        if local_path is None:
            return None
        tmp_downloaded = local_path != source_path
        try:
            return await asyncio.to_thread(
                SafetyDocumentParser.extract_text, local_path, 100000
            )
        except Exception as exc:
            logger.warning("源文档文本提取失败: %s", exc)
            return None
        finally:
            if tmp_downloaded:
                try:
                    os.remove(local_path)
                except OSError:
                    pass

    async def _save_upload(self, file: Any) -> str:
        """Save uploaded .docx — MinIO or local, return path/object_key.

        文件名保留原始 stem（+ 短随机后缀防冲突）：layer1 从文件名兜底解析
        产品/岗位名，纯随机名会把临时文件名泄漏进操规正文（验收复现）。
        """
        raw_name = os.path.basename(file.filename or "draft.docx")
        file_ext = os.path.splitext(raw_name)[1] or ".docx"
        stem = os.path.splitext(raw_name)[0]
        # 去除 Windows/Mac 非法字符，避免 MinIO/本地路径被截断或注入
        stem = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", stem).strip() or "draft"
        safe_name = f"{stem}_{uuid.uuid4().hex[:8]}{file_ext}"
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
    def _run_pipeline_sync(
        draft_path: str,
        pdf_path: str,
        ai_data: dict | None = None,
        pre_extracted: Any | None = None,
    ) -> dict:
        """Synchronous pipeline call — runs in asyncio.to_thread.

        ai_data: 逐章 AI 数据 dict（{"ch3": rows, "ch5": rows, ..., "ch9": types}），
                直接透传给 transform；None 则走纯规则渲染。
        """
        from pipeline import run_pipeline

        return run_pipeline(
            draft_path=draft_path,
            output_pdf=pdf_path,
            keep_intermediate=True,  # Keep JSON & MD so we can read content
            work_dir=os.path.dirname(pdf_path),
            ai_data=ai_data,
            pre_extracted=pre_extracted,
        )

    @staticmethod
    def _render_markdown_sync(
        content: str, pdf_path: str, meta: dict
    ) -> None:
        """Synchronous Markdown → PDF render — runs in asyncio.to_thread."""
        from layer3_render_pdf import render

        render(content, pdf_path, meta)

    @staticmethod
    def _render_docx_sync(
        content: str, docx_path: str, meta: dict
    ) -> None:
        """Synchronous Markdown → Word render — runs in asyncio.to_thread."""
        from layer3_render_docx import render_docx

        render_docx(content, docx_path, meta)

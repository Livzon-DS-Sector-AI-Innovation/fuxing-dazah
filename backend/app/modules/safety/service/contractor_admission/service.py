"""相关方准入业务服务（Bitable 镜像同步 + AI 三维度审核编排）。

覆盖：
- Bitable 事件同步：upsert / 软删除 / 查询
- AI 审核编排：附件下载 → 文本提取 + 视觉补审 → RAG 法规检索 →
  AI 三维度审核 → 回填 Bitable 3 字段 → 更新平台 ai_review_*
- 列表/详情/统计查询（供 API / Agent 工具使用）
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_contractor_review.schemas import AdmissionReviewOutput
from app.modules.safety.models import ContractorAdmission
from app.modules.safety.repository import ContractorAdmissionRepository

logger = logging.getLogger(__name__)

# 图片附件扩展名（跳过文本提取，仅送视觉）
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
# 可文本提取的扩展名
_TEXT_EXTS = {".pdf", ".docx", ".doc", ".txt"}

# 各维度视觉分析提示词与期望键（公章/签字/骑缝章等签章要素）
_VISION_PROMPTS: dict[str, str] = {
    "agreement": (
        "请逐项分析这张安全管理协议页面的签章情况：1) 甲方公章是否加盖且清晰（单位名称可辨认）；"
        "2) 乙方公章是否加盖且单位名称一致；3) 甲方代表是否签字；4) 乙方代表是否签字；"
        "5) 双方签订日期是否完整清晰；6) 页面边缘是否可见骑缝章（跨页连续）。"
        "逐项说明，不确定的写「无法判断」。"
    ),
    "license": (
        "请逐项分析这张企业营业执照图片：1) 单位名称；2) 法定代表人；3) 营业期限/有效期是否过期；"
        "4) 经营范围；5) 公章/登记机关印章是否清晰。逐项说明，不确定的写「无法判断」。"
    ),
    "insurance": (
        "请逐项分析这张现场作业保险凭证图片：1) 被保险人名称；2) 保险类型；3) 保险金额/保额；"
        "4) 保险有效期起止日期；5) 保单印章/公章是否清晰。逐项说明，不确定的写「无法判断」。"
    ),
}
_VISION_KEYS: dict[str, list[str]] = {
    "agreement": ["甲方公章", "乙方公章", "甲方签字", "乙方签字", "签订日期", "骑缝章"],
    "license": ["单位名称", "法定代表人", "营业期限", "经营范围", "公章"],
    "insurance": ["被保险人", "保险类型", "保额", "保险有效期", "公章"],
}


class ContractorAdmissionService:
    """相关方准入业务服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ContractorAdmissionRepository(session)

    # ── Bitable 同步（纯数据对齐，不触发 AI/通知）──

    async def upsert_from_bitable(
        self,
        mapped: dict[str, Any],
        record_id: str,
        table_kind: str = "admission",
    ) -> ContractorAdmission | None:
        """将 Bitable 记录 upsert 到 ContractorAdmission（source='bitable'）。

        mapped 为映射后的字段 dict；feishu_record_id 作为同步主键，更新时保持稳定。
        ai_review_result 保留平台已有值，不覆盖（Bitable 无此字段，防御性跳过）。
        """
        data = dict(mapped)
        data["source"] = "bitable"
        data["feishu_record_id"] = record_id
        data["feishu_table_id"] = table_kind

        existing = await self.repo.get_contractor_admission_by_feishu_id(record_id)
        if existing:
            for k, v in data.items():
                if k == "ai_review_result":
                    continue  # AI 审核结果保留，不覆盖
                if v is not None:
                    setattr(existing, k, v)
            existing.updated_at = datetime.now()
            await self.session.commit()
            return existing

        item = await self.repo.create_contractor_admission(data)
        await self.session.commit()
        return item

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        """按 feishu_record_id 软删除 Bitable 来源记录（仅 source='bitable'）。"""
        result = await self.session.execute(
            update(ContractorAdmission)
            .where(
                ContractorAdmission.feishu_record_id == feishu_record_id,
                ContractorAdmission.source == "bitable",
            )
            .values(is_deleted=True)
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    async def get_by_feishu_id(self, record_id: str) -> ContractorAdmission | None:
        """按 feishu_record_id 查询未删除记录。"""
        return await self.repo.get_contractor_admission_by_feishu_id(record_id)

    # ── 查询（供 API / Agent 工具使用）──

    async def get_list(
        self,
        filters: dict[str, Any] | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ContractorAdmission], int]:
        """相关方准入列表（分页 + 筛选），返回 (items, total)。

        filters 支持键：
          - related_party_type / submit_status / ai_review_status / ai_conclusion（精确匹配）
          - keyword（模糊匹配 company_name / contact_person）
          - sort_by（entry_date / actual_complete_date / created_at / company_name）
          - sort_order（asc / desc，默认 desc）
        """
        f = dict(filters or {})
        return await self.repo.get_contractor_admission_list(
            skip=(page - 1) * page_size,
            limit=page_size,
            related_party_type=f.get("related_party_type"),
            submit_status=f.get("submit_status"),
            ai_review_status=f.get("ai_review_status"),
            ai_conclusion=f.get("ai_conclusion"),
            keyword=f.get("keyword"),
            sort_by=f.get("sort_by"),
            sort_order=f.get("sort_order", "desc"),
        )

    async def get_by_id(self, admission_id: uuid.UUID) -> ContractorAdmission | None:
        """按主键查询未删除记录（详情）。"""
        return await self.repo.get_contractor_admission_by_id(admission_id)

    async def get_stats(self) -> dict[str, Any]:
        """相关方准入统计（精确计数，不估算）。

        返回 {total, by_ai_review_status, by_related_party_type, by_submit_status}。
        """
        return await self.repo.get_contractor_admission_stats()

    # ── AI 审核编排 ──

    async def run_admission_review(
        self,
        admission_id: uuid.UUID,
        channel: str = "system",
    ) -> ContractorAdmission | None:
        """对单条相关方准入执行 AI 审核并回填 Bitable（当前仅审核安全管理协议）。

        流程：附件下载（安全管理协议）→ 文本提取 + 视觉补审 →
        RAG 法规检索 → AI 协议维度审核 → 回填 Bitable 3 字段 → 更新平台 ai_review_*。

        - 仅支持 source='bitable' 且 feishu_record_id 非空的记录
        - 失败 → ai_review_status='failed' + ai_error_message（可重审），不抛异常
        - 企业营业执照/保险凭证维度预留待开发（license/insurance 置空）
        """
        admission = await self.repo.get_contractor_admission_by_id(admission_id)
        if (
            not admission
            or admission.source != "bitable"
            or not admission.feishu_record_id
        ):
            return None

        # ── 防重锁（Redis SET NX，TTL=180；附件下载+视觉耗时长）──
        from app.modules.safety.feishu import bitable_handler as bh

        try:
            if await bh._is_duplicate(
                "admission_review",
                admission.feishu_record_id,
                ttl=180,
                suffix=str(admission.id)[:8],
            ):
                logger.info(
                    "相关方准入 AI 审核重复触发跳过 admission_id=%s", admission_id
                )
                return admission
        except Exception:
            pass  # Redis 不可用 → 降级，依赖 completed 状态判断

        # ── 置 processing（防前端误判）──
        await self.repo.update_contractor_admission(
            admission_id, {"ai_review_status": "processing"}
        )
        await self.session.commit()

        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.ai_contractor_review import (
            AdmissionReviewInput,
            ContractorAdmissionReviewError,
            ContractorAdmissionReviewPlugin,
        )
        from app.modules.safety.service.config import create_ai_service
        from app.modules.safety.vision.service import VisionService

        try:
            with ai_audit_scope(
                scenario="contractor_admission_review",
                channel=channel,
                resource_type="contractor_admission",
                resource_id=admission.id,
                user_name=admission.contact_person or admission.company_name,
            ):
                ai = create_ai_service("text")
                vision = VisionService(create_ai_service("vision"))

                # ① 附件下载（当前仅协议；营业执照/保险预留）
                paths_by_dim = await self._download_attachments(admission)

                # ② 文本提取（图片附件跳过）
                agreement_text = self._parse_attachment_text(
                    paths_by_dim.get("agreement", [])
                )
                license_text = ""
                insurance_text = ""

                # ③ 视觉补审（当前仅协议；视觉不可用降级空描述）
                agreement_vision = await self._parse_attachment_vision(
                    vision, paths_by_dim.get("agreement", []), "agreement"
                )
                license_vision = ""
                insurance_vision = ""

                # ④ RAG 法规检索（失败降级空知识，不阻断）
                knowledge_md = ""
                regulations: list[dict[str, str]] = []
                try:
                    from app.modules.safety.knowledge.query_service import (
                        _build_document_context,
                        _group_chunks_by_document,
                    )
                    from app.modules.safety.knowledge.retriever import (
                        SafetyKnowledgeRetriever,
                    )

                    query = " ".join(filter(None, [
                        admission.company_name,
                        admission.related_party_type,
                        "承包商 安全管理协议 准入",
                    ])).strip() or "相关方准入"
                    retriever = SafetyKnowledgeRetriever(self.session, ai_service=ai)
                    ctx = await retriever.retrieve(
                        description=query,
                        target_chunks=6,
                    )
                    # 按文档去重分组注入（复用知识库问答的成熟格式）
                    doc_groups = _group_chunks_by_document(ctx.chunks)
                    knowledge_md = _build_document_context(doc_groups)
                    # 收集法规来源（供前端展示审核依据）
                    for doc in doc_groups.values():
                        refs: list[str] = []
                        seen: set[str] = set()
                        for c in doc["chunks"]:
                            ref = c.source_article or ""
                            if ref and ref not in seen:
                                seen.add(ref)
                                refs.append(ref)
                        regulations.append({
                            "doc_title": doc["title"],
                            "article_ref": "; ".join(refs),
                        })
                except Exception:
                    logger.warning(
                        "相关方准入 RAG 检索失败，降级为无知识增强 admission_id=%s",
                        admission_id,
                    )

                # ⑤ AI 三维度审核
                input_data = AdmissionReviewInput(
                    company_name=admission.company_name or "",
                    related_party_type=admission.related_party_type or "",
                    agreement_text=agreement_text,
                    agreement_vision_desc=agreement_vision,
                    license_text=license_text,
                    license_vision_desc=license_vision,
                    insurance_text=insurance_text,
                    insurance_vision_desc=insurance_vision,
                )
                plugin = ContractorAdmissionReviewPlugin(ai)
                output = await plugin.review(input_data, knowledge_md)
                if output is None:
                    raise ContractorAdmissionReviewError(
                        "AI 未返回可解析的审核结果"
                    )
        except Exception as e:
            logger.exception("相关方准入 AI 审核失败 admission_id=%s", admission_id)
            await self.repo.update_contractor_admission(
                admission_id,
                {"ai_review_status": "failed", "ai_error_message": str(e)[:2000]},
            )
            await self.session.commit()
            return await self.repo.get_contractor_admission_by_id(admission_id)

        # ── 回填 Bitable（写前 _set_sync_ignore 防回环）──
        writeback_ok = await self._writeback_review(admission, output)
        if not writeback_ok:
            logger.error(
                "相关方准入 AI 审核结果回填 Bitable 失败 admission_id=%s",
                admission_id,
            )

        # ── 更新平台（UPDATE 后 re-fetch，遵守 SQLAlchemy async 铁律）──
        ai_result = {
            "agreement": output.agreement.model_dump(),
            # license / insurance 预留维度：当前不审核，置 None
            "license": None,
            "insurance": None,
            "overall_conclusion": str(output.overall_conclusion),
            "overall_report": output.overall_report,
            "defect_categories": output.defect_categories,
            "regulations": regulations,
        }
        await self.repo.update_contractor_admission(
            admission_id,
            {
                "ai_review_status": "completed",
                "ai_review_result": ai_result,
                "ai_error_message": None,
                "ai_reviewed_at": datetime.now(),
            },
        )
        await self.session.commit()
        logger.info(
            "相关方准入 AI 审核完成 admission_id=%s writeback_ok=%s conclusion=%s",
            admission_id, writeback_ok, output.overall_conclusion,
        )
        return await self.repo.get_contractor_admission_by_id(admission_id)

    async def _writeback_review(
        self, admission: ContractorAdmission, output: AdmissionReviewOutput
    ) -> bool:
        """回填 Bitable 3 字段（AI审核结论/报告/不符合项），写前 _set_sync_ignore 防回环。"""
        assert admission.feishu_record_id, "仅支持 Bitable 来源记录的回填"
        from app.modules.safety.feishu import bitable_handler as bh
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.feishu.contractor_admission_bitable import (
            admission_app_token,
            admission_tables,
        )

        writeback: dict[str, Any] = {
            "AI审核结论": bh._format_bitable_select_value(
                "AI审核结论", str(output.overall_conclusion)
            ),
            "AI审核报告": output.overall_report,
            "AI不符合项": bh._format_bitable_select_value(
                "AI不符合项", output.defect_categories
            ),
        }

        bitable = SafetyBitableClient(
            app_token=admission_app_token(),
            table_id=admission_tables().get("admission"),
        )
        try:
            await bh._set_sync_ignore(admission.feishu_record_id, ttl=30)
        except Exception:
            logger.warning(
                "相关方准入 _set_sync_ignore 失败 record_id=%s",
                admission.feishu_record_id,
            )
        try:
            # 字段不存在（code 1254045）由 update_record 内部按良性处理（warning + False）
            ok = await bitable.update_record(admission.feishu_record_id, writeback)
            logger.info(
                "相关方准入 AI 审核已回写 record_id=%s fields=%s ok=%s",
                admission.feishu_record_id, list(writeback.keys()), ok,
            )
            return ok
        except Exception:
            logger.exception(
                "相关方准入 AI 审核回写 Bitable 异常 record_id=%s",
                admission.feishu_record_id,
            )
            return False

    async def _download_attachments(
        self, admission: ContractorAdmission
    ) -> dict[str, list[str]]:
        """下载审核附件到本地存储，返回 {dimension: [存储路径]}。

        当前仅下载安全管理协议（按 related_party_type 三选一）；
        营业执照/保险凭证维度预留待开发（license/insurance 恒空）。
        优先用 Bitable API 返回的预签名 URL；无 URL 时走 file_token +
        extra 鉴权（field_id 从字段名查询，查不到降级裸 token）。
        下载失败跳过该附件（warning 不阻断审核）。
        """
        assert admission.feishu_record_id, "仅支持 Bitable 来源记录的附件下载"
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.feishu.contractor_admission_bitable import (
            _AGREEMENT_FIELD_BY_TYPE,
            admission_app_token,
            admission_tables,
        )
        from app.modules.safety.vision.utils import save_upload_to_storage

        # 附件字段名：协议按 related_party_type 三选一（与 map_fields 一致）
        dim_field_map = {
            "agreement": (
                admission.safety_agreement_files or [],
                _AGREEMENT_FIELD_BY_TYPE.get(
                    admission.related_party_type or "", "承包商安全管理协议"
                ),
            ),
        }

        bitable = SafetyBitableClient(
            app_token=admission_app_token(),
            table_id=admission_tables().get("admission"),
        )
        # 字段名 → field_id（一次拉取复用；附件下载 extra 位权限定需要）
        field_name_to_id: dict[str, str] = {}
        try:
            for f in await bitable.list_fields():
                fid = f.get("field_id") or ""
                fname = f.get("field_name") or ""
                if fid and fname:
                    field_name_to_id[fname] = fid
        except Exception:
            logger.warning("Bitable 字段列表获取失败，附件下载降级为无 extra 模式")

        result: dict[str, list[str]] = {"agreement": []}
        for dim, (files, field_cn) in dim_field_map.items():
            for att in files or []:
                if not isinstance(att, dict):
                    continue
                token = att.get("file_token") or ""
                name = att.get("name") or att.get("original_name") or "file"
                if not token:
                    continue
                content: bytes | None = None
                # 优先预签名 URL（map_fields 保留的原始 Bitable 附件结构含 url/tmp_url）
                url = att.get("url") or att.get("tmp_url")
                if url:
                    try:
                        content = await bitable.download_attachment_from_url(url)
                    except Exception:
                        logger.warning(
                            "准入附件预签名 URL 下载失败，回退 file_token: dim=%s name=%s",
                            dim, name,
                        )
                if content is None:
                    field_id = field_name_to_id.get(field_cn) or ""
                    try:
                        if field_id:
                            content = await bitable.download_bitable_attachment(
                                token, admission.feishu_record_id, field_id
                            )
                        else:
                            content = await bitable.download_attachment(token)
                    except Exception:
                        logger.warning(
                            "准入附件下载异常 token=%s dim=%s", token, dim,
                            exc_info=True,
                        )
                if content is None:
                    logger.warning(
                        "准入附件下载失败跳过 dim=%s name=%s token=%s",
                        dim, name, token,
                    )
                    continue
                # 保存到 uploads/safety/contractor_admission/（文件名含 record_id/token，
                # save_upload_to_storage 取扩展名生成存储名，保证后续解析按扩展名分派）
                path = save_upload_to_storage(
                    content,
                    f"{admission.feishu_record_id}_{token}_{name}",
                    subdir="contractor_admission",
                    content_type="application/octet-stream",
                )
                result[dim].append(path)
        return result

    def _parse_attachment_text(self, paths: list[str]) -> str:
        """对附件做文本提取（pdf/docx/doc/txt），图片附件跳过；多附件文本拼接。"""
        from app.modules.safety.attachment_store import cleanup_temp, materialize
        from app.modules.safety.document_parser import extract_to_markdown
        from app.modules.safety.vision.utils import resolve_local_path

        parts: list[str] = []
        for p in paths:
            ext = os.path.splitext(str(p))[1].lower()
            if ext not in _TEXT_EXTS:
                continue
            local = resolve_local_path(str(p))
            is_temp = False
            if not local:
                # 回读适配：MinIO key → 物化临时文件（本地原样，MinIO 下载临时）
                tmp = materialize(str(p), suffix=ext)
                if tmp is None:
                    logger.warning("准入附件本地文件不存在，跳过文本提取: %s", p)
                    continue
                local = str(tmp)
                is_temp = True
            try:
                text = extract_to_markdown(local, max_chars=50000)
            except Exception:
                logger.warning("准入附件文本提取失败: %s", p, exc_info=True)
                text = ""
            finally:
                if is_temp:
                    cleanup_temp(local)
            if text:
                parts.append(text)
        return "\n\n---\n\n".join(parts)

    # 视觉分析失败/不可用时的注入标记（与 prompts.py 模板约定一致）
    _VISION_UNAVAILABLE_TEXT = "（视觉分析服务不可用,以下内容缺失,无法判断）"

    async def _parse_attachment_vision(
        self, vision: Any, paths: list[str], dimension: str
    ) -> str:
        """对附件做视觉补审（公章/签字/骑缝章等），返回描述文本。

        - PDF → pdf_to_page_images 渲染页图后送视觉；图片直接送视觉
        - 无附件/无可送视觉图片 → 返回空字符串（prompt 模板显示「无视觉信息/未发现」）
        - vision.analyze 抛异常或返回空 → 返回标记文本
          （视觉分析服务不可用,以下内容缺失,无法判断），与「未检出」状态区分
        """
        from app.modules.safety.attachment_store import cleanup_temp, materialize
        from app.modules.safety.vision.utils import (
            filter_relevant_images,
            pdf_to_page_images,
            resolve_local_path,
        )

        if not paths:
            return ""
        images: list[str] = []
        temp_files: list[str] = []
        out_dir = os.path.join("uploads", "safety", "contractor_admission", "_vision")
        os.makedirs(out_dir, exist_ok=True)
        for p in paths:
            ext = os.path.splitext(str(p))[1].lower()
            if ext == ".pdf":
                local = resolve_local_path(str(p))
                if local:
                    images.extend(pdf_to_page_images(local, out_dir, max_pages=8))
                    continue
                # 回读适配：MinIO key → 物化临时 PDF，渲染后即清理
                tmp = materialize(str(p), suffix=".pdf")
                if tmp is None:
                    continue
                try:
                    images.extend(pdf_to_page_images(str(tmp), out_dir, max_pages=8))
                finally:
                    cleanup_temp(tmp)
            elif ext in _IMAGE_EXTS:
                local = resolve_local_path(str(p))
                if local:
                    images.append(local)
                    continue
                # 回读适配：MinIO key → 物化临时图片（保留扩展名，视觉分析后清理）
                tmp = materialize(str(p), suffix=ext)
                if tmp is None:
                    continue
                images.append(str(tmp))
                temp_files.append(str(tmp))
        if not images:
            return ""
        images = filter_relevant_images(images)  # 视觉模型单次分析上限（默认 4 张）
        try:
            # 用 analyze（原始文本）而非 analyze_parsed（JSON）——视觉模型 qwen-vl-max
            # 返回 prose 而非严格 JSON，analyze_parsed 的 JSON 提取会抛错降级。
            # prose 描述直接喂给文本审核 AI，更自然且零解析风险。
            text = await vision.analyze(
                text_prompt=_VISION_PROMPTS.get(dimension, ""),
                image_urls=images,
            )
        except Exception:
            logger.warning(
                "准入附件视觉分析异常，降级标记不可用 dim=%s", dimension,
                exc_info=True,
            )
            return self._VISION_UNAVAILABLE_TEXT
        finally:
            for t in temp_files:
                cleanup_temp(t)
        # 正常返回但内容为空 → 同样视为服务不可用（避免被当作「已检出但未发现」）
        if not text or not text.strip():
            return self._VISION_UNAVAILABLE_TEXT
        return text

"""URS 智能审核 Service — 状态机编排 + AI 四步流水线 + 飞书通知。

属于 EHS变更功能域（与 EhsChangeService 同包）。无审批链（D4）：
- submit → assessing（后台任务跑 Step1）
- confidence < 0.8 → human_review（人工复核画像，复核兜底）
- 维度门控适配（适配口径 A）+ AI 预填逐条审核 → 人工确认 → 结论
- 仅否决项任一 failed → rejected（一票否决 D7）；非否决强制项 failed 只降分整改
- 申诉 → 重跑 Step1+2（D9）
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_urs_review import rules
from app.modules.safety.ai_urs_review.orchestrator import URSReviewOrchestrator
from app.modules.safety.ai_urs_review.schemas import (
    ConclusionInput,
    ItemReviewInput,
    RiskProfileInput,
    StandardAdaptationInput,
)
from app.modules.safety.ai_urs_review.seed_items import SEED_STANDARD_ITEMS
from app.modules.safety.models import (
    URSReport,
    URSReviewDocument,
    URSStandardItem,
)

logger = logging.getLogger(__name__)

# fire-and-forget 后台任务保活集合：asyncio.create_task 返回的 task 若不被强引用持有，
# 仅被事件循环 WeakSet 弱引用，await 挂起时可能被 GC 回收并注入 CancelledError
# （CancelledError 是 BaseException，绕过 except Exception，导致任务静默中断、状态卡 processing）。
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _track_background_task(task: asyncio.Task) -> None:
    """登记后台 task 防止被 GC，done 后自动移除。"""
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

# URS 文档解析的 AI 提取字段
_DOC_PARSE_SYSTEM_PROMPT = """你是一名制药企业设备采购审核助手，擅长从 URS（用户需求标准）文档中提取结构化信息。

请从以下 URS 文档内容中提取设备信息，严格按 JSON 返回：
{
  "equipment_name": "设备名称",
  "equipment_category": "设备类别（如：采样系统/反应釜/泵/离心机/干燥设备/储罐/实验室仪器）",
  "department": "申请部门（若文档未提及则为空字符串）",
  "procurement_purpose": "采购用途（新增/更换/技术改造，若文档未提及则为空字符串）",
  "structured_points": [
    {"category": "技术参数", "items": ["如：直径4.2m、高度6m、容积60m³", ...]},
    {"category": "安全要求", "items": [...]},
    {"category": "法规遵循", "items": ["如：GB 5226.1-2008", ...]},
    {"category": "清洁要求", "items": [...]},
    {"category": "EHS要求", "items": [...]},
    {"category": "文件资料", "items": [...]},
    {"category": "备品备件", "items": [...]}
  ]
}
规则：
- equipment_name 必填；找不到的字段设为空字符串 "" 或空数组 []
- structured_points 按原文实际覆盖的分类提取，每类下用简短条目列出关键要点，供后续展示与审核参考
- 不要输出任何 JSON 之外的内容"""


class URSService:
    """URS 智能审核业务服务。"""

    # ── 状态常量 ──
    STATUS_DRAFT = "draft"
    STATUS_PENDING_ASSESSMENT = "pending_assessment"
    STATUS_ASSESSING = "assessing"
    STATUS_FAILED = "failed"
    STATUS_ASSESSMENT_CONFIRMED = "assessment_confirmed"
    STATUS_HUMAN_REVIEW = "human_review"
    STATUS_ADAPTING = "adapting"
    STATUS_ITEM_REVIEW = "item_review"
    STATUS_CONCLUSION = "conclusion"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_APPEAL = "appeal"
    STATUS_CLOSED = "closed"

    def __init__(self, session: AsyncSession):
        self.session = session

    # ══════════════════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════════════════

    async def list_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        *,
        department: str | None = None,
        equipment_category: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[URSReport], int]:
        base = select(URSReport).where(~URSReport.is_deleted)
        count_base = select(func.count(URSReport.id)).where(~URSReport.is_deleted)

        if department:
            base = base.where(URSReport.department == department)
            count_base = count_base.where(URSReport.department == department)
        if equipment_category:
            base = base.where(URSReport.equipment_category == equipment_category)
            count_base = count_base.where(URSReport.equipment_category == equipment_category)
        if status:
            base = base.where(URSReport.review_status == status)
            count_base = count_base.where(URSReport.review_status == status)
        if keyword:
            kw = URSReport.equipment_name.ilike(f"%{keyword}%")
            base = base.where(kw)
            count_base = count_base.where(kw)

        total = (await self.session.scalar(count_base)) or 0
        query = base.offset(skip).limit(limit).order_by(URSReport.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all()), total

    async def get_report(self, report_id: uuid.UUID) -> URSReport | None:
        query = select(URSReport).where(
            URSReport.id == report_id, ~URSReport.is_deleted,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_items(self, report_id: uuid.UUID) -> list[URSStandardItem]:
        query = (
            select(URSStandardItem)
            .where(
                URSStandardItem.urs_id == report_id,
                ~URSStandardItem.is_deleted,
            )
            .order_by(URSStandardItem.item_no)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_item(self, report_id: uuid.UUID, item_id: uuid.UUID) -> URSStandardItem | None:
        """按 report+item 取单条审核条目（供 UPDATE 后 re-fetch，避免 MissingGreenlet）。"""
        query = select(URSStandardItem).where(
            URSStandardItem.id == item_id,
            URSStandardItem.urs_id == report_id,
            ~URSStandardItem.is_deleted,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_documents(self, report_id: uuid.UUID) -> list[URSReviewDocument]:
        query = (
            select(URSReviewDocument)
            .where(
                URSReviewDocument.resource_id == report_id,
                ~URSReviewDocument.is_deleted,
            )
            .order_by(URSReviewDocument.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def export_pdf(self, report_id: uuid.UUID) -> bytes:
        """生成单条 URS 审核的完整报告 PDF（只读，不写库）。

        Raises:
            ValueError: 记录不存在
        """
        report = await self.get_report(report_id)
        if report is None:
            raise ValueError("记录不存在")
        items = await self.get_items(report_id)
        from app.modules.safety.service.ehs_change.urs_pdf import build_urs_review_pdf

        return build_urs_review_pdf(report, items)


    async def get_stats(self) -> dict:
        no_del = ~URSReport.is_deleted
        total = (await self.session.scalar(select(func.count(URSReport.id)).where(no_del))) or 0
        by_status = {}
        rows = await self.session.execute(
            select(URSReport.review_status, func.count(URSReport.id))
            .where(no_del)
            .group_by(URSReport.review_status)
        )
        for status, cnt in rows.all():
            by_status[status] = cnt
        high_risk = (await self.session.scalar(
            select(func.count(URSReport.id)).where(no_del, URSReport.overall_risk_level == "high")
        )) or 0
        approved = (await self.session.scalar(
            select(func.count(URSReport.id)).where(no_del, URSReport.review_status == self.STATUS_APPROVED)
        )) or 0
        return {
            "total": total,
            "by_status": by_status,
            "high_risk": high_risk,
            "approved": approved,
        }

    async def delete_report(self, report_id: uuid.UUID) -> bool:
        report = await self.get_report(report_id)
        if not report:
            return False
        report.is_deleted = True
        await self.session.flush()
        return True

    # ══════════════════════════════════════════════════════════
    # 创建 / 解析
    # ══════════════════════════════════════════════════════════

    async def create_report(
        self,
        data: dict,
        *,
        applicant_open_id: str | None = None,
        source_chat_id: str | None = None,
    ) -> URSReport:
        """创建 URS 审核记录（draft）+ 写入 seed 标准条款。"""
        urs_no = await self._next_urs_no()
        report = URSReport(
            urs_no=urs_no,
            equipment_name=data.get("equipment_name") or "未命名设备",
            equipment_category=data.get("equipment_category"),
            department=data.get("department"),
            applicant_name=data.get("applicant_name"),
            applicant_open_id=applicant_open_id or data.get("applicant_open_id"),
            procurement_purpose=data.get("procurement_purpose"),
            urs_content=data.get("urs_content"),
            attachment_path=data.get("attachment_path"),
            source_chat_id=source_chat_id,
            notes=data.get("notes"),
            review_status=self.STATUS_DRAFT,
        )
        self.session.add(report)
        await self.session.flush()
        await self._seed_standard_items(report.id)
        await self.session.flush()
        return report

    async def _seed_standard_items(self, urs_id: uuid.UUID) -> None:
        """幂等写入 seed 通用条款（D12）。"""
        existing = await self.session.scalar(
            select(func.count(URSStandardItem.id)).where(URSStandardItem.urs_id == urs_id)
        )
        if existing:
            return
        for item in SEED_STANDARD_ITEMS:
            self.session.add(URSStandardItem(
                urs_id=urs_id,
                item_no=item["item_no"],
                category=item["category"],
                risk_dimension=item["risk_dimension"],
                standard_title=item["standard_title"],
                standard_ref=item.get("standard_ref"),
                is_veto=bool(item["is_veto"]),
                source="seed",
            ))

    async def _next_urs_no(self) -> str:
        """生成 URS-YYYYMMDD-{seq:03d}（含软删除计数，规避唯一索引占用）。"""
        today_str = datetime.now().strftime("%Y%m%d")
        cnt_q = select(func.count(URSReport.id)).where(
            URSReport.urs_no.like(f"URS-{today_str}-%")
        )
        existing = (await self.session.scalar(cnt_q)) or 0
        return f"URS-{today_str}-{existing + 1:03d}"

    @staticmethod
    async def parse_urs_document(document_text: str) -> dict:
        """AI 从 URS 文档文本中提取设备字段（飞书上传场景，不依赖 session）。

        返回字段：equipment_name / equipment_category / department /
                  procurement_purpose / structured_points（结构化要点数组）。
        urs_content 由调用方决定（文本场景下通常是完整原文）。
        """
        fields = await URSService._ai_parse_urs_fields(document_text)
        return fields

    @staticmethod
    async def _ai_parse_urs_fields(full_text: str) -> dict:
        """AI 从 URS 文档完整原文中提取元数据 + 结构化要点。

        统一走 ai_audit_scope(scenario="urs_review", channel="system") 审计。
        返回：
        {
          equipment_name, equipment_category, department, procurement_purpose,
          structured_points: [{category, items: []}, ...],
        }
        """
        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.service.config import create_ai_service

        ai = create_ai_service("text")
        text = (full_text or "")[:12000]
        with ai_audit_scope(scenario="urs_review", channel="system", resource_type="urs"):
            try:
                response = await ai.chat(
                    [
                        {"role": "system", "content": _DOC_PARSE_SYSTEM_PROMPT},
                        {"role": "user", "content": f"URS 文档内容：\n\n{text}"},
                    ],
                    response_format="json_object",
                )
            except Exception:  # noqa: BLE001 — 含场景停用(ScenarioDisabledError)等,按「字段缺失走默认」降级
                logger.warning("URS 文档 AI 解析失败（含 AI 场景停用），返回空字段")
                return {}
        import json

        try:
            parsed = json.loads(response)
        except Exception:  # noqa: BLE001 — 原仅捕获 JSONDecodeError,扩大兜底(熔断异常不会到这,双保险)
            logger.warning("URS 文档解析返回非法 JSON")
            return {}
        structured = parsed.get("structured_points") or []
        if not isinstance(structured, list):
            structured = []
        return {
            "equipment_name": parsed.get("equipment_name") or "",
            "equipment_category": parsed.get("equipment_category") or "",
            "department": parsed.get("department") or "",
            "procurement_purpose": parsed.get("procurement_purpose") or "",
            "structured_points": structured,
        }

    async def parse_urs_attachment(self, file) -> dict:
        """上传 URS 附件 → 提取完整原文 → AI 提取元数据 + 结构化要点。

        复用 vision.utils.save_upload_to_storage（MinIO/本地双分支）存储附件，
        document_parser.extract_to_markdown 提取完整原文（最多 50000 字符）。

        返回：
        {
          equipment_name, equipment_category, department, procurement_purpose,
          urs_content(完整原文), structured_points, attachment_path,
        }
        """
        import os

        from app.modules.safety.document_parser import extract_to_markdown
        from app.modules.safety.vision.utils import save_upload_to_storage

        allowed_exts = {".docx", ".pdf", ".doc", ".txt", ".xlsx", ".xls", ".md"}
        file_ext = os.path.splitext(file.filename or ".txt")[1].lower()
        if file_ext not in allowed_exts:
            raise ValueError(
                f"不支持的文件格式: {file_ext}，支持: {', '.join(sorted(allowed_exts))}"
            )

        content_bytes = await file.read()

        # ① 保存附件到存储，得到可被 /files/{path} 代理访问的相对路径
        attachment_path = save_upload_to_storage(
            content_bytes,
            file.filename or f"urs{file_ext}",
            subdir="urs",
            content_type=file.content_type or "application/octet-stream",
        )

        # ② 写临时文件 → extract_to_markdown 提取完整原文
        import uuid as _uuid
        from datetime import datetime as _dt

        temp_dir = os.path.join("uploads", "safety", "urs", "_temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(
            temp_dir,
            f"parse_{_uuid.uuid4().hex[:8]}_{_dt.now().timestamp()}{file_ext}",
        )
        try:
            with open(temp_path, "wb") as f:
                f.write(content_bytes)
            full_text = extract_to_markdown(temp_path, max_chars=50000)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

        if not full_text or len(full_text.strip()) < 20:
            raise ValueError("无法从文件中提取有效文本内容，请确认文件格式正确")

        # ③ AI 提取元数据 + 结构化要点（urs_content 用完整原文，不截断不摘要）
        fields = await URSService._ai_parse_urs_fields(full_text)
        fields["urs_content"] = full_text
        fields["attachment_path"] = attachment_path
        return fields

    # ══════════════════════════════════════════════════════════
    # 状态机：提交 → 评估
    # ══════════════════════════════════════════════════════════

    async def submit_report(self, report_id: uuid.UUID) -> URSReport | None:
        """draft → assessing，返回更新后的记录。"""
        report = await self.get_report(report_id)
        if not report:
            return None
        if report.review_status != self.STATUS_DRAFT:
            raise ValueError(f"当前状态不允许提交: {report.review_status}")
        report.review_status = self.STATUS_ASSESSING
        report.ai_assessment_status = "processing"
        report.ai_error_message = None
        await self.session.flush()
        return report

    def trigger_assessment_background(self, report_id: uuid.UUID) -> None:
        """spawn 后台评估任务（需在请求 session 提交后调用）。"""
        task = asyncio.create_task(self._run_assessment_background(report_id))
        _track_background_task(task)

    async def _run_assessment_background(self, report_id: uuid.UUID) -> None:
        """独立 session 后台执行 Step1（请求 session 可能已关闭）。"""
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as bg_session:
                svc = URSService(bg_session)
                await svc.run_assessment(report_id)
                # async with session 退出只 close() 不自动 commit，
                # 必须显式提交，否则 run_assessment 内 flush 的事务全部回滚，
                # 造成「内存评估完成、DB 却一直 processing」的静默失败。
                await bg_session.commit()
        except Exception:
            logger.exception("URS 后台评估失败: report_id=%s", report_id)

    async def run_assessment(self, report_id: uuid.UUID) -> URSReport | None:
        """执行 Step1（五维风险画像）。同步方法，供后台任务与测试直接调用。"""
        report = await self.get_report(report_id)
        if not report:
            return None
        if report.review_status != self.STATUS_ASSESSING:
            # 允许从 failed 重试
            if report.review_status != self.STATUS_FAILED:
                raise ValueError(f"当前状态不允许评估: {report.review_status}")

        report.ai_assessment_status = "processing"
        report.ai_error_message = None
        await self.session.flush()

        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")
            orch = URSReviewOrchestrator(ai_service)
            inp = RiskProfileInput(
                equipment_name=report.equipment_name,
                equipment_category=report.equipment_category,
                urs_content=report.urs_content or "",
                department=report.department,
                procurement_purpose=report.procurement_purpose,
            )
            with ai_audit_scope(
                scenario="urs_review",
                channel="web",
                resource_type="urs",
                resource_id=report.id,
                user_name=report.applicant_name,
            ):
                output = await orch.assess_risk(inp)

            report.risk_profile = {
                "mechanical": output.mechanical.model_dump(),
                "electrical": output.electrical.model_dump(),
                "data": output.data.model_dump(),
                "environmental": output.environmental.model_dump(),
                "chemical": output.chemical.model_dump(),
            }
            report.overall_risk_level = output.overall_risk_level.value
            report.risk_profile_reasoning = output.reasoning
            report.ai_confidence = output.confidence
            report.ai_assessment_status = "completed"
            report.ai_assessment_completed_at = datetime.now(UTC)

            if output.confidence >= rules.CONFIDENCE_REVIEW_THRESHOLD:
                report.review_status = self.STATUS_ASSESSMENT_CONFIRMED
            else:
                report.review_status = self.STATUS_HUMAN_REVIEW

            await self._save_document(
                report, "risk_assessment", f"{report.equipment_name} 风险画像评估",
                content_json=report.risk_profile,
            )
            await self.session.flush()
            logger.info(
                "URS 评估完成: id=%s risk=%s confidence=%s status=%s",
                report.id, output.overall_risk_level.value, output.confidence, report.review_status,
            )
        except Exception as e:
            report.ai_assessment_status = "failed"
            report.review_status = self.STATUS_FAILED
            report.ai_error_message = str(e)[:1000]
            await self.session.flush()
            logger.exception("URS 评估失败: id=%s", report.id)
            return report

        # 通知申请人
        await self._notify("assessment", report)
        return report

    async def confirm_assessment(
        self,
        report_id: uuid.UUID,
        *,
        comment: str | None = None,
        corrections: dict | None = None,
    ) -> URSReport | None:
        """人工复核画像（human_review → assessment_confirmed）。

        corrections: {dimension: level} 的人工修正。修正后自动重跑适配（D10）。
        """
        report = await self.get_report(report_id)
        if not report:
            return None
        if report.review_status != self.STATUS_HUMAN_REVIEW:
            raise ValueError(f"当前状态不允许人工复核: {report.review_status}")

        if corrections:
            profile = dict(report.risk_profile or {})
            for dim, level in corrections.items():
                if dim in profile and level in ("high", "medium", "low"):
                    profile[dim]["level"] = level
            report.risk_profile = profile
            # 综合等级按代码兜底重算
            dim_levels = {k: v["level"] for k, v in profile.items()}
            report.overall_risk_level = rules.compute_overall_risk(dim_levels)
        report.human_review_comment = comment
        report.review_status = self.STATUS_ASSESSMENT_CONFIRMED
        await self.session.flush()

        # 修正了画像 → 自动重跑适配（D10）
        if corrections:
            await self.run_adaptation(report_id)
            report = await self.get_report(report_id)
        return report

    # ══════════════════════════════════════════════════════════
    # 标准适配（Step2）+ 逐条预填（Step3 AI）
    # ══════════════════════════════════════════════════════════

    async def run_adaptation(self, report_id: uuid.UUID) -> URSReport | None:
        """Step2 标准适配（seed + 知识库补充）+ Step3 AI 预填。"""
        report = await self.get_report(report_id)
        if not report:
            return None
        if report.review_status not in (
            self.STATUS_ASSESSMENT_CONFIRMED, self.STATUS_ADAPTING, self.STATUS_ITEM_REVIEW,
        ):
            raise ValueError(f"当前状态不允许标准适配: {report.review_status}")

        report.review_status = self.STATUS_ADAPTING
        await self.session.flush()

        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")
            orch = URSReviewOrchestrator(ai_service)

            items = await self.get_items(report.id)
            if not items:
                await self._seed_standard_items(report.id)
                items = await self.get_items(report.id)

            # 知识库补充（best-effort，失败降级为仅 seed）
            knowledge_ctx = await self._load_knowledge_context(report)
            items = await self._supplement_knowledge_items(report, items, knowledge_ctx)

            item_dicts = [
                {
                    "item_no": it.item_no, "category": it.category,
                    "risk_dimension": it.risk_dimension,
                    "standard_title": it.standard_title, "is_veto": it.is_veto,
                }
                for it in items
            ]
            if not report.risk_profile:
                raise ValueError("缺少风险画像，请先完成适用性评估")

            from app.modules.safety.ai_urs_review.schemas import RiskProfileOutput

            profile = RiskProfileOutput.model_validate(
                {
                    **report.risk_profile,
                    "overall_risk_level": report.overall_risk_level or "low",
                    "confidence": report.ai_confidence or 0.0,
                }
            )
            inp = StandardAdaptationInput(
                equipment_name=report.equipment_name,
                risk_profile=profile,
                items=item_dicts,
            )
            with ai_audit_scope(
                scenario="urs_review", channel="web",
                resource_type="urs", resource_id=report.id,
            ):
                output = await orch.adapt_standards(inp)

            adapted_map = {a.item_no: a for a in output.items}
            for it in items:
                adapted = adapted_map.get(it.item_no)
                if adapted:
                    it.applicability = adapted.applicability.value
                    it.applicability_reason = adapted.applicability_reason

            # 维度门控（代码强制，适配口径 A）：按五维风险等级覆盖全部条目适配结果。
            # 覆盖 AI 遗漏条目（未返回的保持 NULL → 按维度兜底判定），与插件层门控幂等。
            dim_levels = {
                dim: (report.risk_profile.get(dim) or {}).get("level", "low")
                for dim in ("mechanical", "electrical", "data", "environmental", "chemical")
            }
            gate_dicts = [
                {
                    "item_no": it.item_no, "risk_dimension": it.risk_dimension,
                    "is_veto": it.is_veto, "applicability": it.applicability,
                }
                for it in items
            ]
            rules.apply_dimension_gate(gate_dicts, dim_levels, report.overall_risk_level or "low")
            for it, g in zip(items, gate_dicts):
                it.applicability = g["applicability"]
            await self.session.flush()

            # Step3 AI 预填适用项的审核结论
            await self._prefill_item_review(report, items, orch, ai_service)

            report.review_status = self.STATUS_ITEM_REVIEW
            await self.session.flush()
            logger.info("URS 适配完成: id=%s items=%d", report.id, len(items))
        except Exception as e:
            report.review_status = self.STATUS_FAILED
            report.ai_error_message = str(e)[:1000]
            await self.session.flush()
            logger.exception("URS 适配失败: id=%s", report.id)
        return report

    async def _prefill_item_review(
        self,
        report: URSReport,
        items: list[URSStandardItem],
        orch: URSReviewOrchestrator,
        ai_service: Any,
    ) -> None:
        """Step3 AI 预填逐条审核结论（人工确认后生效）。"""
        from app.modules.safety.ai_audit import ai_audit_scope

        applicable = [
            it for it in items
            if it.applicability in ("mandatory", "recommended")
        ]
        if not applicable:
            return
        inp = ItemReviewInput(
            equipment_name=report.equipment_name,
            urs_content=report.urs_content or "",
            items=[
                {
                    "item_no": it.item_no, "standard_title": it.standard_title,
                    "standard_ref": it.standard_ref, "applicability": it.applicability,
                    "category": it.category, "is_veto": it.is_veto,
                }
                for it in applicable
            ],
        )
        with ai_audit_scope(
            scenario="urs_review", channel="web",
            resource_type="urs", resource_id=report.id,
        ):
            output = await orch.review_items(inp)
        verdict_map = {v.item_no: v for v in output.items}
        for it in applicable:
            verdict = verdict_map.get(it.item_no)
            if verdict:
                it.review_status = verdict.review_status.value
                it.review_comment = verdict.review_comment
                it.ai_suggestion = verdict.ai_suggestion
                it.rectification_required = verdict.rectification_required
        await self.session.flush()

    async def _supplement_knowledge_items(
        self, report: URSReport, items: list[URSStandardItem], knowledge_ctx: str | None
    ) -> list[URSStandardItem]:
        """知识库补充标准条目（D3，best-effort）。返回补充后的完整条目列表。"""
        if not knowledge_ctx:
            return items
        # 简单实现：知识库命中条目作为 knowledge 源条目补充（后续可增强）
        return items

    async def _load_knowledge_context(self, report: URSReport) -> str | None:
        """从知识库检索与设备相关的法规上下文（供补充/引用，失败降级）。"""
        try:
            from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

            retriever = SafetyKnowledgeRetriever(self.session)
            ctx = await retriever.retrieve(
                description=f"{report.equipment_category or ''} {report.equipment_name} 设备安全 标准",
                categories=["laws_regulations", "standards"],
                target_chunks=3,
            )
            if not ctx.chunks:
                return None
            return retriever.build_injection_context(ctx)
        except Exception:
            logger.warning("URS 知识库检索失败（非致命）", exc_info=True)
            return None

    # ══════════════════════════════════════════════════════════
    # 逐条审核（人工确认）
    # ══════════════════════════════════════════════════════════

    async def review_item(
        self,
        report_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        verdict: str,
        comment: str | None = None,
        rectification_required: bool = False,
        reviewed_by: str | None = None,
    ) -> URSStandardItem | None:
        if verdict not in ("passed", "failed"):
            raise ValueError(f"非法审核结论: {verdict}")
        query = select(URSStandardItem).where(
            URSStandardItem.id == item_id,
            URSStandardItem.urs_id == report_id,
            ~URSStandardItem.is_deleted,
        )
        result = await self.session.execute(query)
        item = result.scalar_one_or_none()
        if not item:
            return None
        item.review_status = verdict
        item.review_comment = comment
        item.rectification_required = rectification_required
        item.reviewed_by = reviewed_by
        item.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        return item

    async def review_items_batch(
        self,
        report_id: uuid.UUID,
        items: list[dict],
        *,
        reviewed_by: str | None = None,
    ) -> list[URSStandardItem]:
        """批量审核确认：items = [{item_id, verdict, comment, rectification_required}]。"""
        updated: list[URSStandardItem] = []
        for data in items:
            item_id = data.get("item_id")
            if not item_id:
                continue
            item = await self.review_item(
                report_id, uuid.UUID(str(item_id)),
                verdict=data.get("verdict") or "passed",
                comment=data.get("comment"),
                rectification_required=bool(data.get("rectification_required")),
                reviewed_by=reviewed_by,
            )
            if item:
                updated.append(item)
        return updated

    # ══════════════════════════════════════════════════════════
    # 结论生成（Step4）
    # ══════════════════════════════════════════════════════════

    async def generate_conclusion(self, report_id: uuid.UUID) -> URSReport | None:
        """Step4 结论：评分/等级/结论由代码计算，AI 辅助摘要+整改要求。"""
        report = await self.get_report(report_id)
        if not report:
            return None
        items = await self.get_items(report.id)
        if not items:
            raise ValueError("没有审核条目，无法生成结论")

        item_dicts = [
            {
                "item_no": it.item_no, "category": it.category,
                "applicability": it.applicability, "review_status": it.review_status,
                "review_comment": it.review_comment or "", "is_veto": it.is_veto,
            }
            for it in items
        ]
        inp = ConclusionInput(
            equipment_name=report.equipment_name,
            items=item_dicts,
        )

        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.service.config import create_ai_service

            ai_service = create_ai_service("text")
            orch = URSReviewOrchestrator(ai_service)
            with ai_audit_scope(
                scenario="urs_review", channel="web",
                resource_type="urs", resource_id=report.id,
            ):
                output = await orch.generate_conclusion(inp)
        except Exception:
            logger.exception("结论 AI 辅助失败，使用代码计算结果")
            output = orch_based_fallback(item_dicts)

        report.score = output.score
        report.grade = output.grade
        report.conclusion = output.conclusion.value
        report.review_result = {
            "score": output.score, "grade": output.grade,
            "conclusion": output.conclusion.value,
            "summary": output.summary, "veto_break": output.veto_break,
        }
        report.rectification_requirements = [
            req.model_dump() for req in output.rectification_requirements
        ]
        report.review_status = output.conclusion.value  # approved / rejected
        await self._save_document(
            report, "review_report", f"{report.equipment_name} 审核结论",
            content_json=report.review_result,
        )
        await self.session.flush()
        logger.info(
            "URS 结论生成: id=%s score=%s grade=%s conclusion=%s",
            report.id, output.score, output.grade, output.conclusion.value,
        )

        # 通知申请人
        await self._notify("conclusion", report)
        return report

    # ══════════════════════════════════════════════════════════
    # 申诉（D9：只重跑 Step1+2）
    # ══════════════════════════════════════════════════════════

    async def submit_appeal(self, report_id: uuid.UUID, reason: str) -> URSReport | None:
        """rejected → appeal → 重跑 Step1+2 → 输出调整依据。"""
        report = await self.get_report(report_id)
        if not report:
            return None
        if report.review_status != self.STATUS_REJECTED:
            raise ValueError(f"当前状态不允许申诉: {report.review_status}")

        report.appeal_reason = reason
        report.review_status = self.STATUS_APPEAL
        await self.session.flush()

        old_profile = report.risk_profile
        old_overall = report.overall_risk_level

        # 重跑 Step1
        report.review_status = self.STATUS_ASSESSING
        await self.session.flush()
        await self.run_assessment(report_id)

        report = await self.get_report(report_id)
        if not report:
            return None

        # 重跑 Step2（适配 + 预填）
        if report.review_status in (self.STATUS_ASSESSMENT_CONFIRMED, self.STATUS_HUMAN_REVIEW):
            await self.run_adaptation(report_id)
            report = await self.get_report(report_id)

        # 记录调整依据（新旧画像对比）
        report.appeal_result = {
            "old_risk": old_profile,
            "old_overall": old_overall,
            "reassessed_risk": report.risk_profile,
            "reassessed_overall": report.overall_risk_level,
            "basis": "重新评估后的风险画像与适配结果",
            "appealed_at": datetime.now(UTC).isoformat(),
        }
        await self.session.flush()

        # 通知申请人
        await self._notify("appeal", report)
        return report

    # ══════════════════════════════════════════════════════════
    # 内部
    # ══════════════════════════════════════════════════════════

    async def _save_document(
        self,
        report: URSReport,
        doc_type: str,
        title: str,
        *,
        content_json: dict | None = None,
    ) -> URSReviewDocument:
        version = await self._next_document_version(report.id, doc_type)
        doc = URSReviewDocument(
            resource_type="urs_report",
            resource_id=report.id,
            doc_type=doc_type,
            title=title,
            content_json=content_json,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def _next_document_version(self, report_id: uuid.UUID, doc_type: str) -> int:
        q = select(func.max(URSReviewDocument.version)).where(
            URSReviewDocument.resource_id == report_id,
            URSReviewDocument.doc_type == doc_type,
            ~URSReviewDocument.is_deleted,
        )
        v = await self.session.scalar(q)
        return (v or 0) + 1

    async def _notify(self, kind: str, report: URSReport) -> None:
        """飞书通知申请人（失败不阻塞，D8 仅申请人）。"""
        if not report.applicant_open_id:
            return
        try:
            if kind == "assessment":
                from app.modules.safety.feishu.urs_card import notify_assessment_result

                await notify_assessment_result(report)
            elif kind == "conclusion":
                from app.modules.safety.feishu.urs_card import notify_conclusion

                await notify_conclusion(report)
            elif kind == "appeal":
                from app.modules.safety.feishu.urs_card import notify_appeal_result

                await notify_appeal_result(report)
            report.notify_status = "success"
            report.notified_at = datetime.now(UTC)
        except Exception:
            logger.exception("URS 通知失败（非致命）: id=%s", report.id)
            report.notify_status = "failed"


def orch_based_fallback(item_dicts: list[dict]) -> Any:
    """结论 AI 失败时的代码兜底（纯代码计算，不调用 AI）。"""
    from app.modules.safety.ai_urs_review.schemas import (
        ConclusionEnum,
        ConclusionOutput,
        RectificationRequirement,
    )

    conclusion, veto_break = rules.conclude(item_dicts)
    score = rules.compute_score(item_dicts)
    requirements: list[RectificationRequirement] = []
    for it in item_dicts:
        if it.get("review_status") == "failed":
            requirements.append(RectificationRequirement(
                item_no=it.get("item_no", ""),
                requirement=f"整改项 {it.get('item_no')}：{it.get('review_comment') or ''}",
            ))
    return ConclusionOutput(
        score=score,
        grade=rules.grade_for_score(score),
        conclusion=ConclusionEnum(conclusion),
        veto_break=veto_break,
        summary=f"设备审核结论：{conclusion}，评分 {score} 分。",
        rectification_requirements=requirements,
    )

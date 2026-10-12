"""Safety business workflows."""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)

# 人工确认占位值（字段值为空或该占位值视为「未确认」，阻断 AI 脚本执行）
_UNCONFIRMED_PLACEHOLDER = "待人工确认"

# ── AI 配置默认值（仅用于自动种子和 temperature fallback）──


class SafetyService:
    """Safety module service — delegates to per-domain sub-services.

    Sub-services are exposed as attributes for gradual migration:
        svc = SafetyService(session)
        svc.hazard.get_hazards(...)       # → HazardService
        svc.ehs.get_ehs_changes(...)      # → EhsChangeService
        svc.special_op.get_personnel(...)  # → SpecialOperationService
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SafetyRepository(session)

        # Per-domain sub-services (lazy init to avoid circular imports)
        self._hazard = None
        self._ehs = None
        self._regulation = None
        self._special_op = None
        self._special_op_report = None
        self._oh_exam = None
        self._knowledge = None
        self._sop = None

    # ── Lazy-loading accessors for per-domain sub-services ──

    @property
    def hazard(self) -> Any:
        if self._hazard is None:
            from app.modules.safety.service.hazard import HazardService
            self._hazard = HazardService(self.session)
        return self._hazard

    @property
    def ehs(self) -> Any:
        if self._ehs is None:
            from app.modules.safety.service.ehs_change import EhsChangeService
            self._ehs = EhsChangeService(self.session)
        return self._ehs

    @property
    def special_op(self) -> Any:
        if self._special_op is None:
            from app.modules.safety.service.special_operation import (
                SpecialOperationService,
            )
            self._special_op = SpecialOperationService(self.session)
        return self._special_op

    @property
    def special_op_report(self) -> Any:
        if self._special_op_report is None:
            from app.modules.safety.service.special_operation_report import (
                SpecialOperationReportService,
            )
            self._special_op_report = SpecialOperationReportService(self.session)
        return self._special_op_report

    @property
    def oh_exam(self) -> Any:
        if self._oh_exam is None:
            from app.modules.safety.service.oh_health_exam import OhHealthExamService
            self._oh_exam = OhHealthExamService(self.session)
        return self._oh_exam

    @property
    def knowledge(self) -> Any:
        if self._knowledge is None:
            from app.modules.safety.service.knowledge import KnowledgeService
            self._knowledge = KnowledgeService(self.session)
        return self._knowledge

    @property
    def sop(self) -> Any:
        if self._sop is None:
            from app.modules.safety.service.sop_generator import SopGeneratorService
            self._sop = SopGeneratorService(self.session)
        return self._sop

    # ── Audit helper ──

    async def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await audit_log(
            self.session,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        """Delete a single file from MinIO or local disk."""
        if not file_path:
            return
        try:
            if minio_enabled():
                try:
                    delete_object("safety", file_path)
                except Exception:
                    pass
            else:
                abs_path = os.path.abspath(file_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
        except OSError:
            pass

    @staticmethod
    def _cleanup_json_array_files(json_str: str | None) -> None:
        """Parse a JSON array of file paths and delete each file."""
        if not json_str:
            return
        try:
            paths = json.loads(json_str)
            if isinstance(paths, list):
                for p in paths:
                    if isinstance(p, str):
                        SafetyService._cleanup_file(p)
        except (json.JSONDecodeError, TypeError):
            pass

    # ==================== HazardIdentification Operations ====================

    # ── 批量危险源辨识 + 工段预览 ──

    async def create_hazard_identification_batch(self, data: Any) -> dict[str, Any]:
        """批量创建危险源辨识记录（一个操规 → 多工艺阶段）。

        流程:
        1. 查询 regulation，校验 content 非空
        2. 解析 Chapter 7 → 提取工艺阶段列表
        3. 校验 stage_names ⊆ 解析结果
        4. 生成 batch_id，对每个 stage 生成 hazard_id_no + chapter7_context
        5. 批量 INSERT
        6. 可选 auto_submit
        """
        from app.modules.safety.document_parser import parse_chapter7_stages

        batch_id = uuid.uuid4()

        # 1. 查询操规
        reg = await self.repo.get_regulation_by_id(data.regulation_id)
        if not reg:
            raise ValueError(f"安全操作规程不存在: {data.regulation_id}")
        if not reg.content:
            raise ValueError(
                f"安全操作规程「{reg.regulation_name}」尚无标准化内容，"
                "请先生成操规后再创建危险源辨识"
            )

        # 2. 解析工艺阶段
        all_stages = parse_chapter7_stages(reg.content)
        if not all_stages:
            raise ValueError(
                f"安全操作规程「{reg.regulation_name}」第7章未找到工艺阶段，"
                "请确认操规包含完整的生产工艺流程（第7章应为 H2 标题的工艺阶段）"
            )

        # 3. 校验 stage_names
        valid_names = {s["stage_name"] for s in all_stages}
        for sn in data.stage_names:
            if sn not in valid_names:
                raise ValueError(
                    f"工艺阶段「{sn}」不在操规第7章中。"
                    f"可用阶段: {', '.join(sorted(valid_names))}"
                )

        # 4. 生成编号 & 构建记录
        today = datetime.now().strftime("%Y%m%d")
        existing = await self.repo.count_hi_today(today)
        seq = existing + 1

        records_data: list[dict[str, Any]] = []
        for sn in data.stage_names:
            stage_info = next(s for s in all_stages if s["stage_name"] == sn)
            records_data.append({
                "hazard_id_no": f"HI-{today}-{seq:03d}",
                "department": data.department,
                "position": data.position,
                "production_step": sn,
                "regulation_id": data.regulation_id,
                "regulation_name": reg.regulation_name,
                "batch_id": batch_id,
                "stage_name": sn,
                "chapter7_context": stage_info["markdown"],
                "notes": data.notes,
                "ai_node_progress": "pending_input",
                "overall_status": "draft",
            })
            seq += 1

        # 5. 批量 INSERT
        items = await self.repo.create_hazard_identifications_batch(records_data)
        logger.info(
            "批量创建危险源辨识: batch_id=%s, regulation=%s, stages=%d",
            batch_id, reg.regulation_name, len(items),
        )
        await self._audit("create_batch", "hazard_identification", resource_id=batch_id)

        # 6. 可选自动提交
        if data.auto_submit:
            for item in items:
                await self.repo.update_hazard_identification(
                    item.id,
                    {"ai_node_progress": "pending_script1", "overall_status": "in_progress"},
                )

        from app.modules.safety.schemas.hazard_identifications import (
            HazardIdentificationResponse,
        )
        return {
            "batch_id": str(batch_id),
            "regulation_id": str(data.regulation_id),
            "regulation_name": reg.regulation_name,
            "records": [HazardIdentificationResponse.model_validate(r) for r in items],
            "total_stages": len(all_stages),
            "created_count": len(items),
        }

    async def get_regulation_stages(self, regulation_id: uuid.UUID) -> dict[str, Any] | None:
        """获取操规 Chapter 7 的工艺阶段列表（供前端批量辨识预览）。"""
        from app.modules.safety.document_parser import parse_chapter7_stages

        reg = await self.repo.get_regulation_by_id(regulation_id)
        if not reg or not reg.content:
            return None

        all_stages = parse_chapter7_stages(reg.content)
        if not all_stages:
            return None

        return {
            "regulation_id": str(regulation_id),
            "regulation_name": reg.regulation_name,
            "stages": [
                {
                    "stage_name": s["stage_name"],
                    "safety_count": len(s["safety_items"]),
                    "operation_count": len(s["operation_items"]),
                }
                for s in all_stages
            ],
        }

    # ==================== 附件上传 ====================

    async def upload_attachment(
        self, hid: uuid.UUID, file_name: str, file_path: str
    ) -> Any | None:
        """保存附件路径到记录"""
        return await self.repo.update_hazard_identification(
            hid,
            {
                "attachment_path": file_path,
                "attachment_original_name": file_name,
            },
        )

    # ── AI 导出 ──

    async def parse_hazard_export_query(self, natural_query: str) -> dict[str, Any]:
        """使用 AI 将自然语言筛选条件解析为结构化参数。

        支持的自然语言示例：
        - 「导出所有重大危险源」
        - 「原料药车间上月的记录」
        - 「合成岗位最近三个月一级和二级风险」
        """
        system_prompt = (
            "你是一个数据库查询助手，负责将用户的中文自然语言查询 "
            "转换为危险源辨识台账的结构化筛选条件。\n\n"
            "可用字段：\n"
            "- department: 部门名称（如「原料药车间」「生产部」）\n"
            "- position: 岗位名称（如「操作工」「合成岗位」）\n"
            "- risk_level: 风险等级（level_1/level_2/level_3/level_4）\n"
            "- date_from / date_to: 日期范围 YYYY-MM-DD\n"
            "- keyword: 关键词搜索（编号/部门/岗位/作业活动）\n\n"
            "只返回 JSON，不要任何其他文字。没有匹配的字段不返回。\n"
            '示例输出: {"department":"原料药车间","risk_level":"level_1"}'
        )
        try:
            ai = await self._get_ai_service()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": natural_query},
            ]
            response_text = await ai.chat(messages, response_format="json_object")
            result = json.loads(response_text)
            return {k: v for k, v in result.items() if v is not None}
        except Exception as e:
            logger.warning("AI 自然语言解析失败(hazard-identification): %s", e)
            return {
                "explanation": f"AI 解析失败，将使用原始查询: {natural_query}",
                "keyword": natural_query,
            }

    async def export_hazard_ledger_pdf(
        self,
        natural_query: str | None = None,
        department: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        ids: list[uuid.UUID] | None = None,
    ) -> bytes:
        """导出危险源辨识台账为 PDF。

        流程：
        1. AI 解析自然语言 → 筛选条件（如「导出所有重大危险源」）
        2. 按条件查询数据库
        3. Excel 标准化输出插件填表 → LibreOffice 转 PDF
        4. 回退：reportlab 固定模板

        ids 非空时按 ID 精确导出（忽略状态过滤），跳过 AI 解析。
        """
        # 查询逻辑（AI 解析自然语言 → 筛选条件 → 查询记录）抽到 _load_hazard_ledger_data，
        # 与 export_hazard_ledger_excel 共用，避免重复。
        items, filters = await self._load_hazard_ledger_data(
            natural_query, department, position, risk_level,
            date_from, date_to, keyword, ids,
        )

        # ── 策略 1：Excel 标准化输出（最高优先级）──
        try:
            pdf_bytes = self._export_via_template_plugin(items, filters)
            if pdf_bytes and len(pdf_bytes) > 5000:
                logger.info("Excel标准化输出导出成功: %d records, %d bytes",
                            len(items), len(pdf_bytes))
                return pdf_bytes
        except Exception as exc:
            logger.warning("Excel标准化输出导出失败: %s，回退到固定模板", exc)

        # ── 回退：reportlab 固定模板 ──
        logger.debug("使用 reportlab 固定模板生成 PDF")
        return await self._export_hazard_ledger_pdf_fallback(items, filters)

    async def export_hazard_ledger_excel(
        self,
        natural_query: str | None = None,
        department: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        ids: list[uuid.UUID] | None = None,
    ) -> bytes:
        """导出危险源辨识台账为 Excel（.xlsx），跳过 PDF 转化。

        与 export_hazard_ledger_pdf 共享查询逻辑，但模板填表后直接输出 xlsx bytes，
        不经过 LibreOffice 转 PDF（无外部依赖、无回退路径，openpyxl 为已装依赖）。
        """
        items, filters = await self._load_hazard_ledger_data(
            natural_query, department, position, risk_level,
            date_from, date_to, keyword, ids,
        )
        # 严格取 Bitable「建议措施内容（人工）」：人工非空用之，人工空留空
        manual_map = await self._read_manual_recommendations(items)
        return self._export_via_template_excel(items, filters, manual_map)

    async def _load_hazard_ledger_data(
        self,
        natural_query: str | None,
        department: str | None,
        position: str | None,
        risk_level: str | None,
        date_from: str | None,
        date_to: str | None,
        keyword: str | None,
        ids: list[uuid.UUID] | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        """危险源辨识台账查询：AI 解析自然语言 → 筛选条件 → 查询记录。

        返回 (items, filters)，供 PDF / Excel 导出共用（避免两处重复查询逻辑）。
        - ids 非空：按 ID 精确导出，忽略 overall_status 过滤（可导出任意状态记录）
        - ids 为空：仅查询 completed 记录，可用自然语言筛选
        """
        # 第一阶段：AI 解析自然语言 → 筛选条件（按 ids 精确导出时跳过 AI 解析）
        if not ids and natural_query:
            parsed = await self.parse_hazard_export_query(natural_query)
            department = department or parsed.get("department")
            position = position or parsed.get("position")
            risk_level = risk_level or parsed.get("risk_level")
            date_from = date_from or parsed.get("date_from")
            date_to = date_to or parsed.get("date_to")
            keyword = keyword or parsed.get("keyword")

        # 第二阶段：按条件查询数据
        # ids 非空时不强制 overall_status=completed，允许导出任意状态的选中记录
        overall_status = None if ids else "completed"
        items, _ = await self.repo.get_hazard_identifications(
            skip=0,
            limit=10000,
            department=department,
            overall_status=overall_status,
            position=position,
            risk_level=risk_level,
            date_from=date_from,
            date_to=date_to,
            keyword=keyword,
            ids=ids,
        )
        filters = {
            k: v for k, v in {
                "department": department, "position": position,
                "risk_level": risk_level, "date_from": date_from,
                "date_to": date_to, "keyword": keyword,
            }.items() if v is not None
        }
        return items, filters

    def _export_via_template_excel(
        self,
        items: Any,
        filters: dict[str, Any],
        manual_recommendations: dict[str, Any] | None = None,
    ) -> bytes:
        """模板填表 → xlsx bytes（跳过 LibreOffice PDF 转化，取消转化 PDF 步骤）。

        manual_recommendations: {item.id: str}，严格取 Bitable「建议措施内容（人工）」
        （人工空 → 空字符串留空）；不传或未覆盖的记录保留平台 recommendation_content。
        """
        import io

        from app.modules.safety.template_export import (
            HAZARD_TEMPLATE_CONFIG,
            ExcelTemplateFiller,
        )

        data = []
        for item in items:
            d = self._item_to_dict(item)
            if manual_recommendations and item.id in manual_recommendations:
                d["recommendation_content"] = manual_recommendations[item.id]
            data.append(d)
        data = self._sort_ledger_data(data)
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        template_path = template_dir / "危险源辨识管控清单模板.xlsx"
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

        filler = ExcelTemplateFiller(HAZARD_TEMPLATE_CONFIG)
        wb = filler.fill(template_path, data)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def _sort_ledger_data(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """台账导出按岗位排序：先「合成」再「精制」（如 阿福合成 → 阿福拉纳精制）。

        稳定排序：岗位包含「合成」排最前，「精制」次之，其余按岗位字典序兜底。
        """
        def _position_sort_key(d: dict[str, Any]) -> tuple[int, str]:
            pos = d.get("position") or ""
            if "合成" in pos:
                return (0, pos)
            if "精制" in pos:
                return (1, pos)
            return (2, pos)

        return sorted(data, key=_position_sort_key)

    async def _read_manual_recommendations(self, items: Any) -> dict[str, Any]:
        """从 Bitable 读「建议措施内容（人工）」，供 Excel 导出严格取人工值。

        返回 {item.id: str}——人工非空返回内容、人工空返回空字符串（导出留空）。
        读失败的记录不覆盖（保留平台 recommendation_content，人工优先回退 AI），
        避免 Bitable 临时不可用时整份导出失败。
        """
        import asyncio

        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.hazard_identification_bitable_handler import (
                _hazard_id_app_token,
                _hazard_id_table_id,
            )
        except Exception:
            return {}

        client = SafetyBitableClient(
            app_token=_hazard_id_app_token(), table_id=_hazard_id_table_id()
        )
        sem = asyncio.Semaphore(8)

        async def _fetch(item: Any) -> tuple[uuid.UUID, str | None]:
            rid = getattr(item, "feishu_record_id", None)
            if not rid:
                return item.id, None
            async with sem:
                try:
                    fields = await client.get_record(rid) or {}
                    manual = self._extract_bitable_text(
                        fields.get("建议措施内容（人工）")
                    )
                    return item.id, manual or ""
                except Exception:
                    return item.id, None  # 读失败 → 不覆盖

        results = await asyncio.gather(*(_fetch(i) for i in items))
        return {rid: value for rid, value in results if value is not None}

    @staticmethod
    def _extract_bitable_text(value: Any) -> str:
        """Bitable 文本字段取纯文本：list[{text}] / dict{text} / str 统一处理。"""
        if not value:
            return ""
        if isinstance(value, list):
            return "".join(
                str(x.get("text", "") if isinstance(x, dict) else x) for x in value
            ).strip()
        if isinstance(value, dict):
            return str(value.get("text", "") or "").strip()
        return str(value).strip()

    def _export_via_template_plugin(self, items: Any, filters: dict[str, Any]) -> bytes:
        """使用 Excel 标准化输出插件填充模板并导出 PDF。

        流程：ORM 对象 → dict 列表 → openpyxl 填表 → LibreOffice → PDF bytes
        不依赖 AI，格式 100% 复刻 Excel 模板。
        """
        import tempfile

        from app.modules.safety.template_export import (
            HAZARD_TEMPLATE_CONFIG,
            ExcelTemplateFiller,
            ExcelToPdfConverter,
        )

        # ORM → dict（按岗位排序：先合成再精制）
        data = self._sort_ledger_data([self._item_to_dict(item) for item in items])

        # 模板位置
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        template_path = template_dir / "危险源辨识管控清单模板.xlsx"
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

        # 临时文件 → PDF bytes
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            xlsx_path = tmp / "hazard_ledger.xlsx"
            pdf_path = tmp / "hazard_ledger.pdf"

            filler = ExcelTemplateFiller(HAZARD_TEMPLATE_CONFIG)
            filler.fill_and_save(template_path, data, xlsx_path)
            ExcelToPdfConverter().convert(xlsx_path, pdf_path)

            return pdf_path.read_bytes()

    def _item_to_dict(self, item: Any) -> dict[str, Any]:
        """将 HazardIdentification ORM 对象转为可 JSON 序列化的 dict"""
        from app.modules.safety.template_export import TRAINING_EDUCATION_FIXED_TEXT

        return {
            "hazard_id_no": item.hazard_id_no,
            "department": item.department,
            "position": item.position,
            "production_step": item.production_step,
            "specific_activity": item.specific_activity,
            "equipment_facilities": item.equipment_facilities,
            "hazard_type": item.hazard_type,
            "possible_accident": item.possible_accident,
            "unsafe_behavior": item.unsafe_behavior,
            "inherent_risk_level": item.inherent_risk_level,
            "inherent_risk_label": item.inherent_risk_label,
            "l_inherent": int(item.l_inherent) if item.l_inherent else None,
            "e_inherent": int(item.e_inherent) if item.e_inherent else None,
            "c_inherent": int(item.c_inherent) if item.c_inherent else None,
            "d_inherent": int(item.d_inherent) if item.d_inherent else None,
            "residual_risk_level": item.residual_risk_level,
            "residual_risk_label": item.residual_risk_label,
            "l_residual": int(item.l_residual) if item.l_residual else None,
            "e_residual": int(item.e_residual) if item.e_residual else None,
            "c_residual": int(item.c_residual) if item.c_residual else None,
            "d_residual": int(item.d_residual) if item.d_residual else None,
            # 培训教育措施（I 列）：固定文本，所有记录统一
            "training_education_measures": TRAINING_EDUCATION_FIXED_TEXT,
            "existing_engineering_controls": item.existing_engineering_controls,
            "existing_management_controls": item.existing_management_controls,
            "existing_ppe": item.existing_ppe,
            "existing_emergency_measures": item.existing_emergency_measures,
            "control_level": item.control_level,
            "responsible_person": item.responsible_person,
            "needs_recommendation": item.needs_recommendation,
            "recommendation_type": item.recommendation_type,
            "recommendation_content": item.recommendation_content,
            "overall_status": item.overall_status,
            "notes": item.notes,
        }

    # ── 固定模板 PDF 回退（reportlab）──

    async def _export_hazard_ledger_pdf_fallback(
        self, items: Any, filters: dict[str, Any]
    ) -> bytes:
        """固定模板 PDF 生成（reportlab）—— AI 格式化失败时的回退方案"""
        import io
        from datetime import datetime as dt_module

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        # A4 横向
        page_w, page_h = landscape(A4)
        margin = 15 * mm
        buf = io.BytesIO()

        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A4),
            leftMargin=margin,
            rightMargin=margin,
            topMargin=margin,
            bottomMargin=margin,
            title="危险源辨识台账",
        )

        # 字体注册
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        _font_name = "Helvetica"
        _font_name_bold = "Helvetica-Bold"
        _chinese_fonts = [
            ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
            ("C:/Windows/Fonts/msyh.ttc", "MicrosoftYaHei"),
        ]
        for font_path, font_alias in _chinese_fonts:
            try:
                pdfmetrics.registerFont(TTFont(font_alias, font_path))
                if font_alias == "SimSun":
                    _font_name = "SimSun"
                if font_alias == "SimHei":
                    _font_name_bold = "SimHei"
            except Exception:
                pass
        logger.debug("PDF fonts: body=%s, bold=%s", _font_name, _font_name_bold)

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "BodyCN", parent=styles["Normal"],
            fontName=_font_name, fontSize=8, leading=12,
        )
        title_style = ParagraphStyle(
            "TitleCN", parent=styles["Title"],
            fontName=_font_name_bold, fontSize=16, leading=22,
            alignment=TA_CENTER, spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "SubtitleCN", parent=styles["Normal"],
            fontName=_font_name, fontSize=9, leading=14,
            alignment=TA_CENTER, textColor=colors.grey,
        )

        elements: list[Any] = []

        # 标题
        elements.append(Paragraph("危险源辨识台账", title_style))

        # 副标题
        filter_parts: list[str] = []
        for k, v in filters.items():
            if k == "risk_level":
                level_map = {
                    "level_1": "一级/重大风险", "level_2": "二级/较大风险",
                    "level_3": "三级/一般风险", "level_4": "四级/低风险",
                }
                filter_parts.append(f"风险等级：{level_map.get(v, v)}")
            elif k in ("date_from", "date_to"):
                label = "起" if k == "date_from" else "止"
                filter_parts.append(f"{label}：{v}")
            elif k == "keyword":
                filter_parts.append(f"关键词：{v}")
            else:
                filter_parts.append(f"{k}：{v}")
        filter_text = "；".join(filter_parts) if filter_parts else "全部记录"
        export_time = dt_module.now().strftime("%Y-%m-%d %H:%M")
        elements.append(Paragraph(
            f"筛选条件：{filter_text}　|　导出时间：{export_time}　|　共 {len(items)} 条",
            subtitle_style,
        ))
        elements.append(Spacer(1, 6 * mm))

        # ── 数据表 ──
        level_label_map = {
            "level_1": "重大", "level_2": "较大",
            "level_3": "一般", "level_4": "低",
        }
        headers = [
            "序号", "编号", "部门", "岗位", "作业活动",
            "危险类型", "固有风险", "残余风险",
            "管控层级", "责任人", "控制措施摘要",
        ]
        col_widths = [25, 70, 50, 50, 80, 55, 55, 55, 45, 50, 160]

        table_data = [headers]
        for idx, item in enumerate(items, 1):
            inherent_label = item.inherent_risk_label or level_label_map.get(
                item.inherent_risk_level or "", ""
            )
            inherent_d = (
                f"{inherent_label}(D={int(item.d_inherent)})"
                if item.d_inherent and inherent_label
                else inherent_label or "-"
            )
            residual_label = item.residual_risk_label or level_label_map.get(
                item.residual_risk_level or "", ""
            )
            residual_d = (
                f"{residual_label}(D={int(item.d_residual)})"
                if item.d_residual and residual_label
                else residual_label or "-"
            )

            controls_parts = []
            if item.existing_engineering_controls:
                controls_parts.append(f"工程：{item.existing_engineering_controls[:60]}")
            if item.existing_management_controls:
                controls_parts.append(f"管理：{item.existing_management_controls[:60]}")
            if item.existing_ppe:
                controls_parts.append(f"PPE：{item.existing_ppe[:40]}")
            controls_summary = "；".join(controls_parts) if controls_parts else "-"

            table_data.append([
                str(idx),
                item.hazard_id_no or "",
                item.department or "",
                item.position or "",
                item.specific_activity or item.production_step or "",
                item.hazard_type or "",
                inherent_d,
                residual_d,
                item.control_level or "",
                item.responsible_person or "",
                controls_summary,
            ])

        table = Table(table_data, colWidths=[w * mm / 4 for w in col_widths], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5645D4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _font_name_bold),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (-1, -1), _font_name),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#3D2DA6")),
            *[
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7F6FB"))
                for i in range(2, len(table_data) + 1, 2)
            ],
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10 * mm))

        # ── 签发栏 ──
        sign_style = ParagraphStyle(
            "SignCN", parent=body_style, fontSize=10, leading=16,
        )
        sign_table = Table(
            [[
                Paragraph("编制人：______________", sign_style),
                Paragraph("审核人：______________", sign_style),
                Paragraph("批准人：______________", sign_style),
            ]],
            colWidths=[page_w / 3 - 20, page_w / 3 - 20, page_w / 3 - 20],
        )
        sign_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), _font_name),
            ("LEFTPADDING", (0, 0), (-1, -1), 30),
            ("RIGHTPADDING", (0, 0), (-1, -1), 30),
        ]))
        sign_table2 = Table(
            [[
                Paragraph("日期：______________", sign_style),
                Paragraph("日期：______________", sign_style),
                Paragraph("日期：______________", sign_style),
            ]],
            colWidths=[page_w / 3 - 20, page_w / 3 - 20, page_w / 3 - 20],
        )
        sign_table2.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), _font_name),
            ("LEFTPADDING", (0, 0), (-1, -1), 30),
            ("RIGHTPADDING", (0, 0), (-1, -1), 30),
        ]))
        elements.append(sign_table)
        elements.append(Spacer(1, 4 * mm))
        elements.append(sign_table2)

        def add_page_number(canvas: Any, doc_obj: Any) -> None:
            canvas.saveState()
            canvas.setFont(_font_name, 8)
            canvas.drawCentredString(
                page_w / 2, 10 * mm, f"第 {canvas.getPageNumber()} 页",
            )
            canvas.restoreState()

        doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buf.seek(0)
        return buf.getvalue()

# ==================== 操规修订 Service ====================



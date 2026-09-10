"""URS 智能审核 Agent 工具（铁律：所有新功能必须暴露 Agent 工具）。

只读 → query_urs_records / query_urs_review_detail
写入（requires_approval=True）→ create_urs_review / parse_urs_document / run_urs_assessment
                                 / update_urs_item / confirm_urs_assessment / submit_urs_appeal

每个工具 docstring 即发给模型的功能描述，需保持准确、含参数说明与枚举合法值。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

# URS 审核状态 → 中文标签（供模型展示）
_STATUS_LABEL = {
    "draft": "草稿",
    "pending_assessment": "待评估",
    "assessing": "评估中",
    "failed": "评估失败",
    "assessment_confirmed": "评估已确认",
    "human_review": "待人工复核",
    "adapting": "标准适配中",
    "item_review": "逐条审核中",
    "conclusion": "结论生成中",
    "approved": "已通过",
    "rejected": "已驳回",
    "appeal": "申诉中",
    "closed": "已闭环",
}


def _serialize_report(report) -> dict:
    return {
        "urs_id": str(report.id),
        "urs_no": report.urs_no,
        "equipment_name": report.equipment_name,
        "equipment_category": report.equipment_category or "",
        "department": report.department or "",
        "applicant_name": report.applicant_name or "",
        "procurement_purpose": report.procurement_purpose or "",
        "overall_risk_level": report.overall_risk_level or "",
        "ai_confidence": report.ai_confidence,
        "score": report.score,
        "grade": report.grade or "",
        "conclusion": report.conclusion or "",
        "review_status": report.review_status,
        "review_status_label": _STATUS_LABEL.get(report.review_status, report.review_status),
        "created_at": report.created_at.isoformat() if report.created_at else "",
    }


def _serialize_item(item) -> dict:
    return {
        "item_id": str(item.id),
        "item_no": item.item_no,
        "standard_title": item.standard_title,
        "standard_ref": item.standard_ref or "",
        "category": item.category,
        "risk_dimension": item.risk_dimension or "",
        "is_veto": item.is_veto,
        "applicability": item.applicability,
        "review_status": item.review_status,
        "review_comment": item.review_comment or "",
        "ai_suggestion": item.ai_suggestion or "",
        "rectification_required": item.rectification_required,
    }


# ════════════════════════════════════════════════════════════════
# 只读工具
# ════════════════════════════════════════════════════════════════


async def query_urs_records(
    ctx: RunContext[SafetyDeps],
    department: str | None = None,
    equipment_category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> dict:
    """查询 URS 智能审核记录列表。

    Args:
        department: 申请部门（如"生产部"）
        equipment_category: 设备类别（如"采样系统"、"反应釜"）
        status: 审核状态（draft/assessing/human_review/item_review/approved/rejected/appeal/closed）
        keyword: 关键词（匹配设备名称）
        limit: 返回条数上限，默认 20

    Returns:
        {"items": [URS 记录摘要], "total": 总数}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    items, total = await service.list_reports(
        0, min(limit, 50),
        department=department,
        equipment_category=equipment_category,
        status=status,
        keyword=keyword,
    )
    return {
        "items": [_serialize_report(r) for r in items],
        "total": total,
    }


async def query_urs_review_detail(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
) -> dict:
    """查询单条 URS 审核的完整详情（风险画像、标准适配清单、逐条审核结论、最终结论）。

    Args:
        urs_id: URS 记录 ID（UUID 字符串，从 query_urs_records 的 items[].urs_id 获取）

    Returns:
        {"report": {...}, "items": [标准条目审核结果]}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    report = await service.get_report(uuid_parse(urs_id))
    if report is None:
        return {"error": "未找到该 URS 审核记录，请确认 urs_id 是否正确"}
    items = await service.get_items(report.id)
    return {
        "report": _serialize_report(report),
        "risk_profile": report.risk_profile,
        "reasoning": report.risk_profile_reasoning or "",
        "rectification_requirements": report.rectification_requirements or [],
        "items": [_serialize_item(i) for i in items],
    }


async def generate_urs_report_pdf(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
) -> dict:
    """导出单条 URS 审核的完整报告为 PDF 文件，并返回可下载的文件路径。

    生成包含基本信息、五维风险画像、审核结论、标准条款审核过程（逐条适配与 AI 判定）
    的排版整齐 PDF，保存到平台统一存储（MinIO 桶或本地 uploads/safety/urs/）。
    属于写操作，需用户确认后执行。

    Args:
        urs_id: URS 记录 ID（UUID 字符串，从 query_urs_records 的 items[].urs_id 获取）

    Returns:
        {"action": "urs_pdf_generated", "urs_no": ..., "file_path": ..., "message": ...}
        - file_path: 存储标识（MinIO object key 或平台相对路径），
          可通过文件代理访问（前端 fileProxyUrl 可转为下载链接）
    """
    from datetime import datetime

    from app.modules.safety.attachment_store import store_bytes
    from app.modules.safety.service.ehs_change.urs import URSService

    try:
        service = URSService(ctx.deps.db)
        report = await service.get_report(uuid_parse(urs_id))
        if report is None:
            return {"error": "未找到该 URS 审核记录，请确认 urs_id 是否正确"}

        pdf_bytes = await service.export_pdf(report.id)
        filename = f"{report.urs_no}_URS审核报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        rel_path = store_bytes("urs", filename, pdf_bytes, content_type="application/pdf")
    except Exception as e:
        logger.exception("URS PDF 导出失败: urs_id=%s", urs_id)
        return {"error": f"PDF 导出失败: {e}"}

    return {
        "action": "urs_pdf_generated",
        "urs_no": report.urs_no,
        "file_path": rel_path,
        "message": (
            f"已生成《{report.urs_no} URS 智能审核报告》PDF"
            f"（{report.equipment_name}，评分 {report.score} 分 / {report.grade} 级），"
            f"文件保存在平台文件目录，可通过 file_path: {rel_path} 访问下载。"
        ),
    }


# ════════════════════════════════════════════════════════════════
# 写入工具（requires_approval=True）
# ════════════════════════════════════════════════════════════════


async def create_urs_review(
    ctx: RunContext[SafetyDeps],
    equipment_name: str,
    equipment_category: str | None = None,
    department: str | None = None,
    procurement_purpose: str | None = None,
    urs_content: str | None = None,
) -> dict:
    """创建一条 URS 智能审核记录（草稿状态），并自动内置审核标准条款。

    Args:
        equipment_name: 设备名称（必填）
        equipment_category: 设备类别（采样系统/反应釜/泵/离心机/干燥设备/储罐/实验室仪器/其他）
        department: 申请部门
        procurement_purpose: 采购用途（新增/更换/技术改造）
        urs_content: URS 正文内容（可后续通过上传文档解析）

    Returns:
        {"action": "urs_created", "urs_id": ..., "urs_no": ..., "equipment_name": ...}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    person = ctx.deps.person
    service = URSService(ctx.deps.db)
    report = await service.create_report(
        {
            "equipment_name": equipment_name,
            "equipment_category": equipment_category,
            "department": department,
            "applicant_name": person.name if person else None,
            "procurement_purpose": procurement_purpose,
            "urs_content": urs_content,
        },
        applicant_open_id=person.open_id if person else None,
    )
    await ctx.deps.db.flush()
    return {
        "action": "urs_created",
        "urs_id": str(report.id),
        "urs_no": report.urs_no,
        "equipment_name": report.equipment_name,
        "message": f"已创建 URS 审核 {report.urs_no}，请确认后再提交评估",
    }


async def parse_urs_document(
    ctx: RunContext[SafetyDeps],
    document_text: str,
) -> dict:
    """解析 URS 文档文本，提取设备名称/类别/部门/采购用途等字段。

    Args:
        document_text: URS 文档全文（从飞书上传的文件解析出的文本）

    Returns:
        {"action": "urs_document_parsed", "fields": {设备字段}, "message": ...}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    fields = await URSService.parse_urs_document(document_text)
    return {
        "action": "urs_document_parsed",
        "fields": fields,
        "message": "已解析 URS 文档，请确认提取的字段是否正确，确认后可创建审核",
    }


async def run_urs_assessment(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
) -> dict:
    """提交 URS 审核并触发 AI 适用性评估（五维风险画像）。

    Args:
        urs_id: URS 记录 ID

    Returns:
        {"action": "urs_assessment_started", "urs_id": ..., "message": "评估进行中，完成后将推送结果"}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    report = await service.submit_report(uuid_parse(urs_id))
    if report is None:
        return {"error": "未找到该 URS 审核记录"}
    await ctx.deps.db.flush()
    service.trigger_assessment_background(report.id)
    return {
        "action": "urs_assessment_started",
        "urs_id": str(report.id),
        "message": "已提交，AI 适用性评估进行中，完成后将推送风险画像结果",
    }


async def update_urs_item(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
    item_id: str,
    verdict: str,
    comment: str | None = None,
) -> dict:
    """更新单条标准审核结论（AI 预填后的人工确认/修正）。

    Args:
        urs_id: URS 记录 ID
        item_id: 标准条目 ID（从 query_urs_review_detail 的 items[].item_id 获取）
        verdict: 审核结论（passed/failed）
        comment: 审核意见

    Returns:
        {"action": "urs_item_updated", "item_no": ..., "verdict": ...}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    item = await service.review_item(
        uuid_parse(urs_id), uuid_parse(item_id),
        verdict=verdict, comment=comment,
        reviewed_by=ctx.deps.person.name if ctx.deps.person else None,
    )
    if item is None:
        return {"error": "审核条目不存在，请确认 item_id"}
    return {
        "action": "urs_item_updated",
        "item_no": item.item_no,
        "verdict": item.review_status,
        "message": f"条目 {item.item_no} 已更新为 {item.review_status}",
    }


async def confirm_urs_assessment(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
    comment: str | None = None,
    corrections: dict | None = None,
) -> dict:
    """人工确认/修正 URS 风险画像（适用于置信度<80% 需人工复核的场景）。

    Args:
        urs_id: URS 记录 ID
        comment: 复核意见
        corrections: 风险画像修正，如 {"data": "low"}（维度 mechanical/electrical/data/environmental/chemical，值 high/medium/low）

    Returns:
        {"action": "urs_assessment_confirmed", "urs_id": ..., "message": ...}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    report = await service.confirm_assessment(uuid_parse(urs_id), comment=comment, corrections=corrections)
    if report is None:
        return {"error": "未找到该 URS 审核记录"}
    return {
        "action": "urs_assessment_confirmed",
        "urs_id": str(report.id),
        "overall_risk_level": report.overall_risk_level,
        "message": "风险画像已确认，标准适配进行中",
    }


async def submit_urs_appeal(
    ctx: RunContext[SafetyDeps],
    urs_id: str,
    reason: str,
) -> dict:
    """对已驳回的 URS 审核结论提交申诉，系统将重新评估风险画像与标准适配。

    Args:
        urs_id: URS 记录 ID
        reason: 申诉理由（如"该设备位于洁净区，不涉及防爆要求"）

    Returns:
        {"action": "urs_appeal_submitted", "urs_id": ..., "message": "申诉已受理，正在重新评估"}
    """
    from app.modules.safety.service.ehs_change.urs import URSService

    service = URSService(ctx.deps.db)
    report = await service.submit_appeal(uuid_parse(urs_id), reason)
    if report is None:
        return {"error": "未找到该 URS 审核记录"}
    return {
        "action": "urs_appeal_submitted",
        "urs_id": str(report.id),
        "message": "申诉已受理，正在重新评估风险画像，完成后将推送调整依据",
    }


def uuid_parse(value: str):
    """安全解析 UUID，非法时抛 ValueError（模型可据此提示用户修正）。"""
    import uuid

    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as e:
        raise ValueError(f"无效的 ID 格式: {value}") from e

"""写工具：演练 / 报警日报 / URS / 操规 / 职业健康等写操作。标记 ``requires_approval=True`` 以触发确认流。

每个工具的 docstring 即发给模型的功能描述。工具体内 **不重写任何业务逻辑**，
直接调用已有 service。

安全底线：``requires_approval=True`` 表示这些工具在 agent.run() 时不会被直接执行，
而是生成 ``DeferredToolRequests`` 等待用户确认后再由 executor.resume() 真正执行。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


# ── AI 生成应急演练方案 ──────────────────────────────────────────


async def generate_drill_plan(
    ctx: RunContext[SafetyDeps],
    plan_id: str,
) -> dict[str, Any]:
    """AI 生成标准化的应急演练方案文档。

    输入演练计划 ID，AI 将根据计划中的场景、需求等信息，结合安全法规知识库，
    生成符合 AQ/T 9007-2019 标准的应急演练方案。

    参数：
    - plan_id: 演练计划的 UUID（必填）

    返回生成的方案文档信息，包含文档 ID 和标题。
    注意：此操作需要用户确认后才执行。
    """
    from app.modules.safety.service.emergency_drill import EmergencyDrillService

    doc = await EmergencyDrillService(ctx.deps.db).generate_drill_plan(
        __import__("uuid").UUID(plan_id),
    )
    if doc is None:
        return {"error": "演练方案生成失败，请确认计划存在且 AI 服务可用"}
    return {
        "document_id": str(doc.id),
        "title": doc.title,
        "doc_type": doc.doc_type,
        "version": doc.version,
        "feishu_doc_url": doc.feishu_doc_url,
        "feishu_doc_status": doc.feishu_doc_status,
        "action": "drill_plan_generated",
    }


async def sync_drill_plan_to_feishu(
    ctx: RunContext[SafetyDeps],
    document_id: str,
) -> dict[str, Any]:
    """将已生成的演练方案文档同步到飞书云文档（含可编辑分享链接）。

    当演练方案首次生成时飞书文档创建失败，或用户想将已有方案重新发布到飞书时使用。
    使用前提：该文档必须已有 AI 生成的 content_json。

    参数：
    - document_id: 演练方案文档的 UUID（必填）

    返回同步结果，包含飞书文档链接。
    注意：此操作需要用户确认后才执行。
    """
    from sqlalchemy import select

    from app.modules.safety.feishu.docx_service import FeishuDocxService
    from app.modules.safety.models import EmergencyDrillDocument

    doc_id = __import__("uuid").UUID(document_id)
    doc = await ctx.deps.db.scalar(
        select(EmergencyDrillDocument).where(
            EmergencyDrillDocument.id == doc_id,
            ~EmergencyDrillDocument.is_deleted,
        )
    )
    if doc is None:
        return {"error": "文档不存在"}
    if not doc.content_json:
        return {"error": "文档没有 AI 生成的内容，请先生成方案"}

    try:
        docx = FeishuDocxService()
        result = await docx.create_drill_document(doc.content_json, doc.title)
        if result:
            feishu_doc_id, feishu_doc_url = result
            doc.feishu_doc_id = feishu_doc_id
            doc.feishu_doc_url = feishu_doc_url
            doc.feishu_doc_status = "created"
            await ctx.deps.db.flush()
            return {
                "success": True,
                "feishu_doc_url": feishu_doc_url,
                "action": "drill_plan_synced_to_feishu",
            }
        return {"error": "飞书文档创建失败，请检查飞书服务状态"}
    except Exception as e:
        logger.exception("sync_drill_plan_to_feishu failed: doc_id=%s", document_id)
        return {"error": f"飞书同步异常: {e}"}


# generate_drill_report 已移除 — 当前版本仅支持 AI 演练方案生成


async def sync_audit_hazards(
    ctx: RunContext[SafetyDeps],
) -> dict[str, Any]:
    """从外部审计/检查表读取最新数据并同步到平台隐患台账。

    每日调用一次，从 7 张外部审计表（集团EHS审计、政府检查、事业部审计等）读取
    最新缺陷记录，按 feishu_record_id 去重后创建或更新到平台的隐患台账中。

    同步的数据仅用于记录和督办，不会触发 AI 隐患识别、AI 整改初审或飞书通知。
    督办等级（红色预警/一般预警/closed）由平台在同步时自动计算。

    返回每张表的同步统计：读取数、新建数、更新数、跳过数。
    注意：此操作需要用户确认后才执行。
    """
    from app.modules.safety.audit.service import import_all_audit_tables

    try:
        results = await import_all_audit_tables()
        return {"success": True, "tables": results}
    except Exception as e:
        logger.exception("sync_audit_hazards failed")
        return {"error": f"外部审计同步失败: {e}"}


# ── 生成特殊作业日报 ────────────────────────────────────────────


async def generate_daily_report(
    ctx: RunContext[SafetyDeps],
    mode: str = "today",
) -> dict[str, Any]:
    """生成特殊作业日报或次日预警，直接在对话中返回完整报告。

    先从飞书多维表格同步最新特殊作业数据，执行 V3.5 风险判定引擎，
    再对每条高风险作业进行 AI 独立分析（风险描述+管控措施），
    最后生成 Markdown 格式日报并推送给安全管理人员。
    报告内容直接在对话窗口展示，无需二次确认，即时执行。

    Args:
        mode: "today" 当日日报，"afternoon" 17点日报(含今日新增计划外作业对比总结)，
              "tomorrow" 次日预警，默认 today

    Returns:
        完整日报内容（markdown_report 字段）及统计概要。
    """
    from app.modules.safety.service.special_operation_daily_report import (
        SpecialOperationDailyReportService,
    )

    try:
        service = SpecialOperationDailyReportService(ctx.deps.db)
        # 数据新鲜度检查（增量，非全量）：以本地最新修改时间为锚，
        # 只补拉 Bitable 中锚点后新增/变更而本地缺失的记录；
        # 实时 WS 同步正常时通常 0 条，毫秒级完成，不会拖慢对话。
        sync_check = await service.check_and_sync_incremental()
        await ctx.deps.db.commit()
        result = await service.generate_and_push(mode=mode, push=False)
        await ctx.deps.db.commit()
        return {
            "success": True,
            "report_date": result.report_date.isoformat(),
            "mode": result.mode,
            "total": result.total,
            "high_risk": result.high_risk,
            "medium_risk": result.medium_risk,
            "low_risk": result.low_risk,
            "excluded": result.excluded,
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "sync_check": sync_check,
            # 原样输出指令：告诉模型不要改写
            "_output_instruction": "以下 markdown_report 是已格式化的完整日报，你必须原样输出全部内容，不要改写、精简或重新排版。只需加一句简短引导语后直接贴出。",
            "markdown_report": result.markdown_report,
        }
    except Exception as e:
        logger.exception("generate_daily_report failed: mode=%s", mode)
        return {"success": False, "error": f"日报生成失败: {e}"}


# ── 生成督办通报 ────────────────────────────────────────────


async def generate_supervision_bulletin(
    ctx: RunContext[SafetyDeps],
) -> dict[str, Any]:
    """生成当前督办通报，列出所有红色预警/一般预警隐患的完整清单。

    当用户询问"督办情况""未关闭隐患总结""隐患督办通报""还有多少隐患没整改"
    等涉及隐患督办、未关闭隐患汇总的问题时，调用此工具获取最新通报。

    数据源：**直读飞书多维表格**（隐患登记表），不读平台数据库。
    通报按部门分组，包含每条隐患的描述、责任人、等级和存在天数，
    以及底部各部门的红色/一般预警数量汇总。即时执行，无需用户确认。

    Returns:
        完整通报内容（bulletin 字段）及统计概要。
    """
    from app.modules.safety.service.hazard_direct.bulletin import build_bulletin

    try:
        content, stats = await build_bulletin()
        return {
            "success": True,
            "bulletin": content,
            "stats": stats,
            "_output_instruction": (
                '以下是已格式化的完整督办通报，你必须原样输出全部内容，'
                '不要改写、精简、重新排版、添加表格或添加额外分析。'
                '只需在前面加一句简短引导语（如「📋 当前隐患督办通报：」），'
                '然后直接贴出 bulletin 的原始文本。'
            ),
        }
    except Exception as e:
        logger.exception("generate_supervision_bulletin failed")
        return {"success": False, "error": f"通报生成失败: {e}"}


# ── 重跑操规 AI 审核 ────────────────────────────────────────────


async def run_regulation_ai_review(
    ctx: RunContext[SafetyDeps],
    regulation_id: str,
) -> dict[str, Any]:
    """对已生成的标准化操规重新执行 AI 审核（对照源文档校正细节错误与缺失内容）。

    当用户反馈生成的操规存在细节错误或操作内容缺失、需要让 AI 重新审核并自动修正时使用。
    审核在后台异步执行（channel=web），本工具立即返回"已触发"；
    若该操规审核正在进行中，则幂等跳过并提示稍后再查。

    Args:
        regulation_id: 操规记录 ID（UUID 字符串）

    Returns:
        触发结果：{regulation_id, regulation_no, ai_review_status, message}
    """
    import asyncio
    import uuid

    from sqlalchemy import select

    from app.modules.safety.models import OperationRegulation
    from app.modules.safety.service.sop_generator import SopGeneratorService

    reg_id = uuid.UUID(regulation_id)
    reg = await ctx.deps.db.scalar(
        select(OperationRegulation).where(
            OperationRegulation.id == reg_id,
            ~OperationRegulation.is_deleted,
        )
    )
    if reg is None:
        return {"error": f"操规不存在: {regulation_id}"}
    if reg.ai_review_status == "reviewing":
        return {
            "regulation_id": regulation_id,
            "ai_review_status": "reviewing",
            "message": "该操规 AI 审核正在进行中，已幂等跳过，请稍后再查询结果",
        }
    if not reg.content:
        return {"error": "该操规内容为空，无法执行 AI 审核"}

    # 重置为待审并提交，随后后台任务接管状态流转（run_ai_review 用独立 session）
    await SopGeneratorService(ctx.deps.db).repo.update_regulation(
        reg_id,
        {"ai_review_status": "pending", "ai_review_note": None},
    )
    await ctx.deps.db.commit()
    asyncio.create_task(
        SopGeneratorService(ctx.deps.db).run_ai_review(reg_id, channel="web")
    )
    return {
        "regulation_id": regulation_id,
        "regulation_no": reg.regulation_no,
        "ai_review_status": "pending",
        "message": "已触发操规 AI 审核，结果将自动回写操规内容并附审核说明（后台执行，稍后可再查询）",
    }


# ═══════════════════════════════════════════════════════════════════
# 职业健康管理 — 写工具（requires_approval=True）
# ═══════════════════════════════════════════════════════════════════


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    """宽松 UUID 解析：非法输入返回 None（由 Service 层做存在性校验）。"""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def trigger_oh_exam_parse(
    ctx: RunContext[SafetyDeps],
    exam_id: str,
) -> dict[str, Any]:
    """触发/重试体检报告 AI 智能解析。

    对指定体检记录执行 AI 解析（提取异常指标、结论分类、职业禁忌证、适配判定），
    解析完成后自动生成异常随访并回填人员汇总表。解析需调用 AI，耗时较长。

    Args:
        exam_id: 体检记录 ID（UUID 字符串）

    Returns:
        dict: {exam_id, exam_no, ai_parse_status, ai_conclusion, ai_parse_error, message}
        - ai_parse_status: parsed=解析完成 / failed=解析失败（见 ai_parse_error）

    示例：把体检记录 xxx 重新解析一下。
    """
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    exam_uuid = _uuid_or_none(exam_id)
    if exam_uuid is None:
        return {"error": f"exam_id 不是合法的 UUID: {exam_id}"}

    svc = OhHealthExamService(ctx.deps.db)
    exam = await svc.get_exam(exam_uuid)
    if exam is None:
        return {"error": f"体检记录不存在: {exam_id}"}
    if exam.ai_parse_status == "parsing":
        return {
            "exam_id": exam_id,
            "ai_parse_status": "parsing",
            "message": "该体检正在解析中，请稍后再查询结果",
        }

    updated = await svc.run_ai_parse(exam_uuid, channel="web")
    if updated is None:
        return {"error": f"体检记录不存在: {exam_id}"}
    return {
        "exam_id": exam_id,
        "exam_no": updated.exam_no,
        "ai_parse_status": updated.ai_parse_status,
        "ai_conclusion": updated.ai_conclusion,
        "ai_parse_error": updated.ai_parse_error,
        "message": (
            "体检报告 AI 解析完成"
            if updated.ai_parse_status == "parsed"
            else "体检报告 AI 解析失败，请查看 ai_parse_error"
        ),
    }


async def create_oh_followup(
    ctx: RunContext[SafetyDeps],
    exam_id: str,
    indicator_name: str,
    followup_type: str | None = None,
    followup_date: str | None = None,
    responsible: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """手动补录职业健康异常随访记录。

    用于 AI 解析未覆盖或人工发现的异常指标跟踪（如复查、专科转诊、调离岗位、健康监护）。
    同一体检的同一异常指标只能有一条活随访，重复补录会报错。

    Args:
        exam_id: 体检记录 ID（UUID 字符串，必填）
        indicator_name: 异常指标名（如"谷丙转氨酶"、"纯音听阈"，必填）
        followup_type: 随访类型（re_examination=复查 / specialist_referral=专科转诊 /
            transfer_post=调离岗位 / health_monitor=健康监护）
        followup_date: 建议复查/处置日期（ISO 格式，如 "2026-08-20"，可选）
        responsible: 责任人姓名（可选）
        notes: 备注（可选）

    Returns:
        dict: {id, person_name, indicator_name, followup_type, followup_date, status}

    示例：给体检 xxx 补录一条"谷丙转氨酶"复查随访，建议 2026-08-20 复查。
    """
    from datetime import date

    from app.modules.safety.schemas.oh_followups import OhFollowupCreate
    from app.modules.safety.service.oh_followup import OhFollowupService

    exam_uuid = _uuid_or_none(exam_id)
    if exam_uuid is None:
        return {"error": f"exam_id 不是合法的 UUID: {exam_id}"}
    try:
        followup_date_value = (
            date.fromisoformat(followup_date) if followup_date else None
        )
    except ValueError:
        return {"error": f"followup_date 不是合法的日期（ISO 格式，如 2026-08-20）: {followup_date}"}

    data = OhFollowupCreate(
        exam_id=exam_uuid,
        indicator_name=indicator_name,
        followup_type=followup_type if followup_type else None,
        followup_date=followup_date_value,
        responsible=responsible,
        notes=notes,
    )
    try:
        item = await OhFollowupService(ctx.deps.db).create_followup(
            data, user_id=_current_user_id(ctx),
        )
    except ValueError as e:
        return {"error": str(e)}
    return {
        "id": str(item.id),
        "person_name": item.person_name,
        "exam_id": str(item.exam_id) if item.exam_id else None,
        "indicator_name": item.indicator_name,
        "followup_type": item.followup_type,
        "followup_date": item.followup_date.isoformat() if item.followup_date else None,
        "status": item.status,
    }


async def close_oh_followup(
    ctx: RunContext[SafetyDeps],
    followup_id: str,
    action_taken: str,
) -> dict[str, Any]:
    """关闭职业健康异常随访（闭环）。

    关闭前该随访须先完成处置（status=followed）；关闭后写入处置记录与关闭时间。
    已关闭的随访不可重复关闭。

    Args:
        followup_id: 随访记录 ID（UUID 字符串，必填）
        action_taken: 处置记录（如"已复查，指标恢复正常"，必填）

    Returns:
        dict: {id, indicator_name, person_name, status, action_taken, closed_at}

    示例：把随访 xxx 关闭，处置记录为"已复查，指标恢复正常"。
    """
    from app.modules.safety.service.oh_followup import OhFollowupService

    followup_uuid = _uuid_or_none(followup_id)
    if followup_uuid is None:
        return {"error": f"followup_id 不是合法的 UUID: {followup_id}"}
    try:
        item = await OhFollowupService(ctx.deps.db).close_followup(
            followup_uuid,
            action_taken=action_taken,
            user_id=_current_user_id(ctx),
        )
    except ValueError as e:
        return {"error": str(e)}
    if item is None:
        return {"error": f"随访记录不存在: {followup_id}"}
    return {
        "id": str(item.id),
        "person_name": item.person_name,
        "indicator_name": item.indicator_name,
        "status": item.status,
        "action_taken": item.action_taken,
        "closed_at": item.closed_at.isoformat() if item.closed_at else None,
    }


async def analyze_oh_transfer(
    ctx: RunContext[SafetyDeps],
    application_id: str,
) -> dict[str, Any]:
    """触发转岗/离岗危害差异分析。

    对转岗/离岗申请执行 AI 差异分析：对比原岗位与新岗位的危害因素变化（标准名），
    给出新增/移除危害、防护用品建议、重点复查项，并判断是否需体检、建议体检类型；
    若需体检则自动创建体检登记。分析需调用 AI，耗时较长。

    Args:
        application_id: 转岗/离岗申请 ID（UUID 字符串，必填）

    Returns:
        dict: {application_id, diff_analyze_status, needs_exam, exam_suggestion,
            diff_summary, created_exam_id, message}
        - diff_analyze_status: analyzed=完成 / failed=失败

    示例：把转岗申请 xxx 做一次危害差异分析。
    """
    from app.modules.safety.service.oh_transfer import OhTransferService

    application_uuid = _uuid_or_none(application_id)
    if application_uuid is None:
        return {"error": f"application_id 不是合法的 UUID: {application_id}"}

    svc = OhTransferService(ctx.deps.db)
    application = await svc.get_application(application_uuid)
    if application is None:
        return {"error": f"申请记录不存在: {application_id}"}
    if application.diff_analyze_status == "parsing":
        return {
            "application_id": application_id,
            "diff_analyze_status": "parsing",
            "message": "该申请正在分析中，请稍后再查询结果",
        }

    updated = await svc.analyze_transfer_diff(
        application_uuid,
        channel="web",
        user_id=_current_user_id(ctx),
        user_name=_current_user_name(ctx),
    )
    if updated is None:
        return {"error": f"申请记录不存在: {application_id}"}
    return {
        "application_id": application_id,
        "diff_analyze_status": updated.diff_analyze_status,
        "needs_exam": updated.needs_exam,
        "exam_suggestion": updated.exam_suggestion,
        "diff_summary": updated.diff_summary,
        "created_exam_id": str(updated.created_exam_id) if updated.created_exam_id else None,
        "message": (
            "转岗危害差异分析完成"
            if updated.diff_analyze_status == "analyzed"
            else "转岗危害差异分析失败，请查看 diff_analyze_error"
        ),
    }


async def override_oh_conclusion(
    ctx: RunContext[SafetyDeps],
    exam_id: str,
    override_conclusion: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """人工覆盖体检记录的 AI 结论（留痕，仅安全管理员可用）。

    当 AI 结论判定有误或需人工修正时使用。覆盖值写入生效结论（ai_conclusion）与
    覆盖标记（override_conclusion），原 AI 结论与说明自动留痕（ai_override_notes），
    并同步更新人员汇总表的最后体检结论。此操作不可撤销，请确认后执行。

    Args:
        exam_id: 体检记录 ID（UUID 字符串，必填）
        override_conclusion: 覆盖后的结论（normal=未见异常 / abnormal_other=其他异常 /
            contraindicated=职业禁忌证 / suspected_od=疑似职业病 /
            od_diagnosed=职业病确诊 / re_examination=复查）
        notes: 覆盖说明（如"医生复核确认正常，原 AI 误判"，建议填写）

    Returns:
        dict: {exam_id, exam_no, ai_conclusion, override_conclusion,
            override_by, override_at, ai_override_notes}

    示例：把体检 xxx 的结论覆盖为 normal，说明"医生复核确认无异常"。
    """
    from app.modules.safety.schemas.oh_health_exams import OhAiConclusion
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    exam_uuid = _uuid_or_none(exam_id)
    if exam_uuid is None:
        return {"error": f"exam_id 不是合法的 UUID: {exam_id}"}
    value = str(override_conclusion)
    if value not in {c.value for c in OhAiConclusion}:
        return {
            "error": (
                f"override_conclusion 必须是标准结论之一: "
                f"{[c.value for c in OhAiConclusion]}，当前: {value}"
            )
        }

    svc = OhHealthExamService(ctx.deps.db)
    item = await svc.override_conclusion(
        exam_uuid,
        override_conclusion=value,
        notes=notes,
        user_id=_current_user_id(ctx),
        user_name=_current_user_name(ctx),
    )
    if item is None:
        return {"error": f"体检记录不存在: {exam_id}"}
    return {
        "exam_id": exam_id,
        "exam_no": item.exam_no,
        "ai_conclusion": item.ai_conclusion,
        "override_conclusion": item.override_conclusion,
        "override_by": str(item.override_by) if item.override_by else None,
        "override_at": item.override_at.isoformat() if item.override_at else None,
        "ai_override_notes": item.ai_override_notes,
    }


def _current_user_id(ctx: RunContext[SafetyDeps]) -> uuid.UUID | None:
    """当前用户的 identity.users UUID（未识别返回 None，Service 层留痕为 unknown）。"""
    import uuid as _uuid

    raw = ctx.deps.person.id if ctx.deps.person else ""
    if raw:
        try:
            return _uuid.UUID(str(raw))
        except (ValueError, TypeError):
            return None
    return None


def _current_user_name(ctx: RunContext[SafetyDeps]) -> str | None:
    """当前用户姓名（未识别返回 None）。"""
    return ctx.deps.person.name if ctx.deps.person else None


# ═══════════════════════════════════════════════════════════════════
# 消防报警分析 — 写工具（requires_approval=True）
# ═══════════════════════════════════════════════════════════════════


async def generate_fire_alarm_daily_report(
    ctx: RunContext[SafetyDeps],
    target_date: str | None = None,
) -> dict[str, Any]:
    """生成消防报警日报并直接在对话中返回完整报告。

    先同步最新 Bitable 数据 → 聚合当日报警 → 逐条 AI 分析（工艺/人员操作/设备设施/其他）
    → 汇总 AI → Markdown 渲染 → 推送（env 配置时）。报告直接在对话窗口展示。

    Args:
        target_date: 目标日期（ISO，如 "2026-08-18"，默认今天）

    Returns:
        {success, report_date, total, analyzed, push_ok, markdown_report}
        - markdown_report: 已格式化的完整日报，必须原样输出
    """
    from datetime import date as _date

    from app.modules.safety.service.fire_alarm.service import FireAlarmService

    try:
        service = FireAlarmService(ctx.deps.db)
        result = await service.generate_daily_report(
            target_date=_date.fromisoformat(target_date) if target_date else None,
            push=False, channel="feishu",   # Agent 触发不推送，直接返回报告
        )
        await ctx.deps.db.commit()
        return {
            "success": True,
            "report_date": result.target_date.isoformat(),
            "total": result.total,
            "analyzed": result.analyzed,
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "_output_instruction": (
                "以下 markdown_report 是已格式化的完整日报，你必须原样输出全部内容，"
                "不要改写、精简或重新排版。只需加一句简短引导语后直接贴出。"
            ),
            "markdown_report": result.markdown_report,
        }
    except Exception as e:
        logger.exception("generate_fire_alarm_daily_report failed")
        return {"success": False, "error": f"日报生成失败: {e}"}


async def generate_central_alarm_daily_report(
    ctx: RunContext[SafetyDeps],
    target_date: str | None = None,
) -> dict[str, Any]:
    """生成中控报警日报并直接在对话中返回完整报告。

    先同步最新 Bitable 数据 → 聚合当日报警 → 逐条 AI 分析（报警类型/异常模式/四维）
    → 汇总 AI → Markdown 渲染 → 推送（env 配置时）。报告直接在对话窗口展示。

    Args:
        target_date: 目标日期（ISO，如 "2026-08-18"，默认今天）

    Returns:
        {success, report_date, total, analyzed, push_ok, markdown_report}
        - markdown_report: 已格式化的完整日报，必须原样输出
    """
    from datetime import date as _date

    from app.modules.safety.service.central_alarm.service import CentralAlarmService

    try:
        service = CentralAlarmService(ctx.deps.db)
        result = await service.generate_daily_report(
            target_date=_date.fromisoformat(target_date) if target_date else None,
            push=False, channel="feishu",  # Agent 触发不推送，直接返回报告
        )
        await ctx.deps.db.commit()
        return {
            "success": True,
            "report_date": result.target_date.isoformat(),
            "total": result.total,
            "analyzed": result.analyzed,
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "_output_instruction": (
                "以下 markdown_report 是已格式化的完整日报，你必须原样输出全部内容，"
                "不要改写、精简或重新排版。只需加一句简短引导语后直接贴出。"
            ),
            "markdown_report": result.markdown_report,
        }
    except Exception as e:
        logger.exception("generate_central_alarm_daily_report failed")
        return {"success": False, "error": f"日报生成失败: {e}"}


async def generate_fire_alarm_weekly_report(
    ctx: RunContext[SafetyDeps],
    week_end: str | None = None,
) -> dict[str, Any]:
    """生成消防报警周报（自然周周一~周日）并直接在对话中返回完整报告。

    聚合本周报警 → 周级 AI 分类与重复问题识别 → Markdown 渲染 → 推送（env 配置时）。
    复用记录上已有的日 AI 分析结果，不重复逐条调用。

    Args:
        week_end: 周末日期（ISO，如 "2026-08-24"，默认本周日或今天所在自然周）

    Returns:
        {success, week_start, week_end, total, push_ok, markdown_report}
        - markdown_report: 已格式化的完整周报，必须原样输出
    """
    from datetime import date as _date

    from app.modules.safety.service.fire_alarm.service import FireAlarmService

    try:
        service = FireAlarmService(ctx.deps.db)
        result = await service.generate_weekly_report(
            week_end=_date.fromisoformat(week_end) if week_end else None,
            push=False, channel="feishu",
        )
        await ctx.deps.db.commit()
        return {
            "success": True,
            "week_start": result.week_start.isoformat() if result.week_start else None,
            "week_end": result.target_date.isoformat(),
            "total": result.total,
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "_output_instruction": (
                "以下 markdown_report 是已格式化的完整周报，你必须原样输出全部内容，"
                "不要改写、精简或重新排版。只需加一句简短引导语后直接贴出。"
            ),
            "markdown_report": result.markdown_report,
        }
    except Exception as e:
        logger.exception("generate_fire_alarm_weekly_report failed")
        return {"success": False, "error": f"周报生成失败: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 持证到期预警 — 写工具（requires_approval=True）
# ═══════════════════════════════════════════════════════════════════


async def renew_person_certificate(
    ctx: RunContext[SafetyDeps],
    certificate_id: str,
    renewed_date: str | None = None,
    next_review_date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """回填人员持证复审/换证结果（闭环，进入下一证件周期）。

    特种作业证回填 next_review_date（再复审时间）→ 系统重算剩余天数；
    监护人 A/B 证回填 renewed_date（已换证日期）→ 系统以 renewed_date 为新 issue_date
    重算复审及换证时间，进入下一周期。回填后预警状态自动刷新。

    Args:
        certificate_id: 持证记录 ID（UUID 字符串，必填）
        renewed_date: 已换证日期（ISO 格式如 "2026-08-20"，监护人 A/B 证用）
        next_review_date: 再复审时间（ISO 格式，特种作业证用）
        notes: 备注（可选）

    Returns:
        dict: {id, person_name, cert_category, current_node, deadline,
            remaining_days, status_level, suggestion, message}

    示例：把特种作业证 xxx 的复审时间更新为 2027-08-20；监护人 A 证 xxx 已换证，日期 2026-08-20。
    """
    from datetime import date as _date

    from app.modules.safety.schemas.cert_warnings import RenewRequest
    from app.modules.safety.service.cert_warning import CertWarningService

    cert_uuid = _uuid_or_none(certificate_id)
    if cert_uuid is None:
        return {"error": f"certificate_id 不是合法的 UUID: {certificate_id}"}
    try:
        renewed = _date.fromisoformat(renewed_date) if renewed_date else None
        next_review = _date.fromisoformat(next_review_date) if next_review_date else None
    except ValueError as e:
        return {"error": f"日期格式非法（ISO 如 2026-08-20）: {e}"}

    data = RenewRequest(
        renewed_date=renewed, next_review_date=next_review, notes=notes)
    try:
        item = await CertWarningService(ctx.deps.db).renew(
            cert_uuid, data, user_id=_current_user_id(ctx),
        )
    except ValueError as e:
        return {"error": str(e)}
    if item is None:
        return {"error": f"持证记录不存在: {certificate_id}"}
    return {
        "id": str(item.id),
        "person_name": item.person_name,
        "cert_category": item.cert_category,
        "current_node": item.current_node,
        "deadline": item.deadline.isoformat() if item.deadline else None,
        "remaining_days": item.remaining_days,
        "status_level": item.status_level,
        "suggestion": item.suggestion,
        "message": "已回填，预警状态已刷新",
    }


# ── 隐患系统「直读多维表格」三个手动触发工具 ──────────────────────


async def poll_hazard_ai_analysis(
    ctx: RunContext[SafetyDeps],
    limit: int | None = None,
) -> dict[str, Any]:
    """立即执行一轮「隐患AI分析」（直读多维表格，不落库）。

    扫描多维表格中「隐患分类（AI）」为空的隐患记录，逐条执行 AI 识别
    （缺陷图片视觉分析 + 法规知识库检索），并把识别结果写回多维表格的
    AI 字段（隐患分类/类别/级别/隐患描述（AI）/判定依据/整改建议 + 督办等级）。

    典型用法：用户说「轮询隐患AI分析」「跑一下隐患AI」「把没做 AI 的隐患补上」时调用。
    平时该动作由定时任务每 5 分钟自动执行，本工具用于立即触发一次。

    参数：
    - limit: 本次最多处理条数（可选，默认取系统配置 200）

    返回本轮统计：total / succeeded / failed / skipped / failures 明细。
    注意：此操作会实际调用 AI 并写回多维表格，需要用户确认后才执行。
    """
    from app.modules.safety.service.hazard_direct.ai_analysis import (
        run_ai_analysis_round,
    )

    result = await run_ai_analysis_round(limit=limit)
    return {
        **result.as_dict(),
        "action": "hazard_ai_analysis_polled",
        "message": (
            f"本轮处理 {result.total} 条，成功 {result.succeeded} 条，"
            f"失败 {result.failed} 条，跳过 {result.skipped} 条"
        ),
    }


async def poll_hazard_rectification_review(
    ctx: RunContext[SafetyDeps],
    limit: int | None = None,
) -> dict[str, Any]:
    """立即执行一轮「AI整改审核」（直读多维表格，不落库）。

    扫描多维表格中「已填整改回复、但尚未 AI 初审、且未关闭」的隐患记录，
    逐条执行 AI 整改初审（缺陷图 vs 整改后图对比 + 措施有效性 + 标准合规 +
    法规知识库检索），并把结论写回「AI初审结果」「AI初审说明」两个字段。

    结论取值以多维表格字段为准：已通过 / 未通过 / 无需整改；
    未知或解析失败时**不写字段**，下一轮自动重试。

    典型用法：用户说「轮询AI整改审核」「跑一下整改初审」时调用。
    平时该动作由定时任务每 5 分钟自动执行，本工具用于立即触发一次。

    参数：
    - limit: 本次最多处理条数（可选，默认取系统配置 200）

    返回本轮统计：total / succeeded / failed / skipped / no_conclusion / failures。
    注意：此操作会实际调用 AI 并写回多维表格，需要用户确认后才执行。
    """
    from app.modules.safety.service.hazard_direct.review import run_review_round

    result = await run_review_round(limit=limit)
    return {
        **result.as_dict(),
        "action": "hazard_rectification_review_polled",
        "message": (
            f"本轮处理 {result.total} 条，成功 {result.succeeded} 条，"
            f"失败 {result.failed} 条，跳过 {result.skipped} 条，"
            f"无结论 {result.no_conclusion} 条"
        ),
    }


async def send_hazard_supervision_bulletin(
    ctx: RunContext[SafetyDeps],
    chat_id: str | None = None,
) -> dict[str, Any]:
    """发送「隐患督办通报」到飞书群（直读多维表格）。

    生成当前督办通报（按部门分组的红色/一般预警清单 + 未更新进展标记 + 底部汇总），
    并推送到指定群聊。

    典型用法：用户说「发送隐患督办报告」「把督办通报发到群里」「推送督办通报」时调用。

    参数：
    - chat_id: 目标群 chat_id（可选，默认使用系统配置的隐患督办通报群）

    返回统计：total / urgent / warning / marked / sent。
    注意：此操作会向飞书群发送消息，需要用户确认后才执行。
    """
    from app.modules.safety.service.hazard_direct.bulletin import send_bulletin

    stats = await send_bulletin(chat_id)
    stats["action"] = "hazard_supervision_bulletin_sent"
    stats["message"] = (
        f"红色预警 {stats.get('urgent', 0)} 条、一般预警 {stats.get('warning', 0)} 条、"
        f"未更新进展 {stats.get('marked', 0)} 条；"
        f"推送{'成功' if stats.get('sent') else '未成功'}"
    )
    return stats


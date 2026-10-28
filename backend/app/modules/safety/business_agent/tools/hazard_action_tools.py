"""隐患/报表执行面工具（agent-action-p2）。

点对点催办 / 隐患报表导出 / 通用推群三个写操作。标记
``requires_approval=True`` 走既有确认流（挂起 → 确认卡 → executor.resume）。
工具体不重写业务逻辑：催办核心链在 ``hazard_direct.progress_dunning``，
拉取复用 ``bitable_repo.query_hazards``，文件发送复用 ``chat_sender``。
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

# 批量催办上限：防止误触全表催办（spec 拍板①）
URGE_BATCH_LIMIT = 50
# 导出条数保护上限：超出截断并在返回中提示（spec 拍板⑨）
EXPORT_ROW_LIMIT = 5000
# 单条催办定位拉取窗口：与导出同上限，避免未关闭超窗时误报「不存在」
_URGE_LOOKUP_LIMIT = 5000

# 整改状态 → 展示标签（平台口径严格两值，对齐 read_tools._to_display_status）
_RECTIFY_LABELS = {"closed": "已关闭", "no_rectification_need": "已关闭",
                   "level3_approved": "已关闭"}

# Excel 列头（spec：对齐台账页面关键列）
_EXPORT_HEADERS = [
    "隐患编号", "来源", "部门", "隐患描述", "等级", "责任人",
    "发现日期", "整改状态", "督办等级",
]


async def send_hazard_urge(
    ctx: RunContext[SafetyDeps],
    record_id: str = "",
    department: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    """点对点催办未整改隐患：DM 催办卡给责任人与分管安全员。

    对指定的未关闭隐患，把「督办催办卡」私发给整改责任人 + 责任部门的
    分管安全员；收卡人可在卡片内直接提交整改进展（回写隐患台账）。

    两种入口（二选一）：
    - record_id：催单条隐患（Bitable recXXX，query_hazards 返回的 id）
    - 筛选条件批量：department / keyword / date_from / date_to 组合，
      只催筛选命中的未关闭隐患，上限 50 条（超出请收窄条件）

    典型用法：用户说「这条隐患没整改，催一下责任人」「把生产部未关闭的
    隐患都催一遍」「督办到人」时调用。先查后催：建议先 query_hazards
    让用户确认范围。

    Args:
        record_id: 隐患记录 ID（recXXX，单条催办用）
        department: 部门名称（批量催办筛选）
        keyword: 关键词（匹配隐患描述或编号）
        date_from: 起始日期 ISO（按检查日期，批量筛选）
        date_to: 截止日期 ISO（按检查日期，批量筛选）

    返回发送统计：total / recipients / sent / skipped / errors。
    注意：此操作会向责任人私发飞书卡片，需要用户确认后才执行。
    """
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct import bitable_repo, progress_dunning

    client = SafetyBitableClient()

    if record_id:
        # 单条入口：拉未关闭隐患后按 record_id 匹配（已关闭的不在候选）
        views, _total = await bitable_repo.query_hazards(
            client, status="open", limit=_URGE_LOOKUP_LIMIT,
        )
        matched = [v for v in views if v.record_id == record_id]
        if not matched:
            return {
                "success": False,
                "error": (
                    f"未找到未关闭的隐患 {record_id}（可能已关闭、编号有误或不存在），"
                    "请先用 query_hazards 确认隐患 ID"
                ),
            }
        target_views = matched
    else:
        filters = {
            "department": department, "keyword": keyword,
            "date_from": date_from, "date_to": date_to,
        }
        if not any(filters.values()):
            return {
                "success": False,
                "error": (
                    "请提供 record_id（催单条）或至少一个筛选条件"
                    "（department/keyword/date_from/date_to），避免全表催办"
                ),
            }
        views, total = await bitable_repo.query_hazards(
            client,
            status="open",
            department=department or None,
            keyword=keyword or None,
            date_from=date_from or None,
            date_to=date_to or None,
            limit=URGE_BATCH_LIMIT + 1,
        )
        if total > URGE_BATCH_LIMIT:
            return {
                "success": False,
                "error": (
                    f"命中 {total} 条未关闭隐患，超过批量催办上限 "
                    f"{URGE_BATCH_LIMIT} 条，请收窄条件（如加部门或日期范围）"
                ),
            }
        if not views:
            return {
                "success": True,
                "total": 0, "recipients": 0, "sent": 0, "skipped": 0,
                "errors": 0,
                "message": "筛选条件下无未关闭隐患，无需催办",
            }
        target_views = views

    # 催办核心链：三层链收件人解析 + @提及换算 + DM 卡片（卡片内可提交进展）
    stats, _plan, _sent, _failed = await progress_dunning.send_urge_cards(
        target_views,
    )
    stats["success"] = True
    stats["action"] = "hazard_urge_sent"
    stats["message"] = (
        f"已对 {stats.get('total', 0)} 条隐患发出催办：送达 "
        f"{stats.get('sent', 0)} 张卡（跳过 {stats.get('skipped', 0)}、"
        f"异常 {stats.get('errors', 0)}），去重收件人 {stats.get('recipients', 0)} 人；"
        "收卡人可在卡片内直接提交整改进展"
    )
    return stats


def _internal_export_rows(views: list[Any]) -> list[list[str]]:
    """内部隐患 HazardView → Excel 行。"""
    out: list[list[str]] = []
    for v in views:
        out.append([
            v.hazard_no or v.record_id,
            "内部",
            v.department or "",
            v.description or "",
            v.hazard_level or v.hazard_level_manual or "",
            v.rectification_responsible_person_name or "",
            v.discovered_at.isoformat() if v.discovered_at else "",
            _RECTIFY_LABELS.get(v.rectification_status, "未关闭"),
            v.supervision_level or "",
        ])
    return out


def _external_export_rows(views: list[Any]) -> list[list[str]]:
    """外审缺陷项 ExternalAuditView → Excel 行。"""
    out: list[list[str]] = []
    for v in views:
        out.append([
            v.record_id,
            "外审",
            "、".join(v.departments),
            v.description or "",
            "",
            "、".join(name for name, _ in v.responsible),
            v.checked_at.isoformat() if v.checked_at else "",
            "已关闭" if v.closed else "未关闭",
            "",
        ])
    return out


def _rows_to_excel(rows: list[list[str]]) -> bytes:
    """行集 → Excel 文件字节（openpyxl，表头加粗、列宽自适应简化）。"""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "隐患报表"
    ws.append(_EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def export_hazard_report(
    ctx: RunContext[SafetyDeps],
    department: str = "",
    rectification_status: str = "",
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    source: str = "",
) -> dict[str, Any]:
    """按筛选条件导出隐患报表 Excel，并发送到当前对话。

    数据源与 query_hazards 同口径：internal=公司内部隐患登记表（默认）/
    external=管委会检查外审缺陷项 / all=两源合并。筛选参数与 query_hazards
    参数面对齐（部门/整改状态/关键词/日期范围）。

    典型用法：用户说「导一份 7 月的隐患报表」「导出生产部的隐患清单」时调用。
    先在确认卡中展示筛选条件与预计条数，用户确认后执行。

    Args:
        department: 部门名称
        rectification_status: 整改状态（pending=未关闭/in_progress=整改中/
            closed=已关闭，空=全部）
        keyword: 关键词（匹配隐患描述或编号）
        date_from: 起始日期 ISO（按检查日期）
        date_to: 截止日期 ISO（按检查日期）
        source: 数据来源（空/internal=内部登记表/external=外审/all=合并）

    返回：total / truncated / sent / file_name（web 渠道无 chat_id 时降级
    返回 file_content_base64）。上限 5000 条，超出截断并在 message 提示。
    注意：此操作会向当前对话发送文件，需要用户确认后才执行。
    """
    import base64
    from datetime import datetime

    from app.modules.safety.feishu.chat_sender import send_file_to_chat
    from app.modules.safety.service.hazard_direct.external_audit import (
        fetch_external_audit,
        filter_views,
    )

    src = (source or "internal").strip().lower()
    if src not in ("internal", "external", "all"):
        return {
            "success": False,
            "error": f"未知 source={source!r}，可选：internal / external / all",
        }

    rows: list[list[str]] = []
    total = 0
    truncated = False

    if src in ("internal", "all"):
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.service.hazard_direct import bitable_repo

        views, int_total = await bitable_repo.query_hazards(
            SafetyBitableClient(),
            department=department or None,
            rectification_status=rectification_status or None,
            keyword=keyword or None,
            date_from=date_from or None,
            date_to=date_to or None,
            limit=EXPORT_ROW_LIMIT,
        )
        total += int_total
        truncated = truncated or int_total > EXPORT_ROW_LIMIT
        rows.extend(_internal_export_rows(views))

    if src in ("external", "all"):
        ext_views = await fetch_external_audit()
        if ext_views is not None:
            want_closed: bool | None = None
            if rectification_status:
                want_closed = rectification_status == "closed"
            filtered = filter_views(
                ext_views,
                department=department or None,
                closed=want_closed,
                keyword=keyword or None,
                date_from=date_from or None,
                date_to=date_to or None,
            )
            if len(filtered) > EXPORT_ROW_LIMIT:
                truncated = True
            ext_rows = filtered[:EXPORT_ROW_LIMIT]
            total += len(filtered)
            rows.extend(_external_export_rows(ext_rows))

    if not rows:
        return {
            "success": False,
            "error": "筛选条件下没有命中隐患，未生成报表。请确认条件（部门/状态/日期范围）后重试",
        }

    excel_bytes = _rows_to_excel(rows)
    file_name = f"隐患报表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    truncated_hint = (
        f"（命中 {total} 条超过上限 {EXPORT_ROW_LIMIT}，已截断，请收窄条件分批导出）"
        if truncated else ""
    )

    if not ctx.deps.chat_id:
        return {
            "success": True,
            "sent": False,
            "degraded": True,
            "total": total,
            "truncated": truncated,
            "file_name": file_name,
            "file_content_base64": base64.b64encode(excel_bytes).decode(),
            "message": (
                f"当前渠道无法回传文件，已生成 {file_name}（{len(rows)} 行）"
                f"{truncated_hint}，请在飞书会话中使用此功能"
            ),
        }

    ok = await send_file_to_chat(ctx.deps.chat_id, excel_bytes, file_name)
    if not ok:
        return {
            "success": True,
            "sent": False,
            "total": total,
            "truncated": truncated,
            "file_name": file_name,
            "file_content_base64": base64.b64encode(excel_bytes).decode(),
            "message": "Excel 已生成但发送失败，请稍后重试",
        }
    return {
        "success": True,
        "sent": True,
        "total": total,
        "truncated": truncated,
        "file_name": file_name,
        "message": (
            f"已导出《{file_name}》并发送到当前会话：共 {len(rows)} 行"
            f"（命中 {total} 条）{truncated_hint}"
        ),
    }


async def push_report_to_chat(
    ctx: RunContext[SafetyDeps],
    report_kind: str,
    chat_id: str = "",
    mode: str = "today",
    scope: str = "fire",
) -> dict[str, Any]:
    """把安全报表推送到飞书群（三类报表，目标群默认系统配置、可指定）。

    支持的报表类型：
    - supervision：隐患督办通报（红色/一般预警清单，按部门分组）
    - daily_op：特殊作业日报（mode=today 当日 / afternoon 17点 / tomorrow 次日预警）
    - alarm：消防/中控报警日报（scope=fire 消防默认 / central 中控）

    典型用法：用户说「把日报发到群里」「把督办通报推送到XX群」「报表推送」时调用。
    「把督办通报发到群里」不指定群时走常驻的 send_hazard_supervision_bulletin
    即可；本工具用于需要指定目标群、或推其他两类报表的场景。

    Args:
        report_kind: 报表类型（supervision / daily_op / alarm，必填）
        chat_id: 目标群 chat_id（可选，默认各报表的系统配置群）
        mode: daily_op 专用（today / afternoon / tomorrow）
        scope: alarm 专用（fire / central）

    返回各报表的生成与送达统计。
    注意：此操作会向飞书群发送消息，需要用户确认后才执行。
    """
    kind = (report_kind or "").strip().lower()
    target = (chat_id or "").strip() or None

    if kind == "supervision":
        from app.modules.safety.service.hazard_direct.bulletin import send_bulletin

        stats = await send_bulletin(target)
        stats["success"] = True
        stats["action"] = "report_pushed"
        stats["message"] = (
            f"督办通报已推送：未关闭 {stats.get('total', 0)} 项"
            f"（红色预警 {stats.get('urgent', 0)}、一般预警 {stats.get('warning', 0)}），"
            f"推送{'成功' if stats.get('sent') else '未成功'}"
        )
        return stats

    if kind == "daily_op":
        from app.modules.safety.service.special_operation_daily_report import (
            SpecialOperationDailyReportService,
        )

        service = SpecialOperationDailyReportService(ctx.deps.db)
        result = await service.generate_and_push(
            mode=mode if mode in ("today", "afternoon", "tomorrow") else "today",
            target_chats=[target] if target else None,
            push=True,
        )
        await ctx.deps.db.commit()
        return {
            "success": True,
            "action": "report_pushed",
            "report_kind": "daily_op",
            "report_date": result.report_date.isoformat()
            if hasattr(result.report_date, "isoformat") else str(result.report_date),
            "mode": result.mode,
            "total": result.total,
            "high_risk": result.high_risk,
            "medium_risk": result.medium_risk,
            "low_risk": result.low_risk,
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "message": (
                f"特殊作业日报已推送：共 {result.total} 条作业"
                f"（高风险 {result.high_risk}、中风险 {result.medium_risk}、"
                f"低风险 {result.low_risk}）"
            ),
        }

    if kind == "alarm":
        svc_scope = (scope or "fire").strip().lower()
        if svc_scope == "fire":
            from app.modules.safety.service.fire_alarm.service import FireAlarmService

            service = FireAlarmService(ctx.deps.db)
        elif svc_scope == "central":
            from app.modules.safety.service.central_alarm.service import (
                CentralAlarmService,
            )

            service = CentralAlarmService(ctx.deps.db)
        else:
            return {
                "success": False,
                "error": (
                    f"未知 scope={scope!r}，报警日报可选：fire（消防）/ central（中控）"
                ),
            }
        result = await service.generate_daily_report(
            push=True, channel="feishu", chat_id=target,
        )
        await ctx.deps.db.commit()
        return {
            "success": True,
            "action": "report_pushed",
            "report_kind": "alarm",
            "scope": svc_scope,
            "report_date": result.target_date.isoformat()
            if hasattr(result.target_date, "isoformat") else str(result.target_date),
            "total": result.total,
            "analyzed": getattr(result, "analyzed", None),
            "push_ok": sum(1 for p in result.push_results if p.get("success")),
            "message": (
                f"{'消防' if svc_scope == 'fire' else '中控'}报警日报已推送："
                f"当日报警 {result.total} 条"
            ),
        }

    return {
        "success": False,
        "error": (
            f"未知 report_kind={report_kind!r}，可选：supervision（督办通报）/ "
            "daily_op（特殊作业日报）/ alarm（报警日报）"
        ),
    }


__all__ = ["send_hazard_urge", "export_hazard_report", "push_report_to_chat"]

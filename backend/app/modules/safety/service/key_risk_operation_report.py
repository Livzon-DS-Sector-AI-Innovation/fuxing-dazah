"""关键风险作业报备 Service — Bitable 同步 + 只读查询 + Excel 导出。

数据源: 飞书多维表格「每日关键风险操作预报备（审批）」，
连接配置从配置中心 store 读取（key_risk_op/daily，原代码硬编码值）。
平台侧只读展示，审批在飞书完成。以 feishu_record_id 为主键 upsert。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.client import get_safety_tenant_token
from app.modules.safety.models import KeyRiskOperationReport
from app.modules.safety.repository import SafetyRepository

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Bitable 配置（配置中心 store；未启用/缺失时降级为空串）
# ═══════════════════════════════════════════════════════════


def _key_risk_op_conn() -> ConnectionView | None:
    """关键风险作业连接配置（配置中心 store 读取）。"""
    return store.get_connection("key_risk_op", "daily")


def bitable_app_token() -> str:
    """关键风险作业 Bitable app_token；未启用/缺失返回空串。"""
    conn = _key_risk_op_conn()
    return conn.app_token if conn and conn.enabled else ""


def bitable_table_id() -> str:
    """关键风险作业 Bitable table_id；未启用/缺失返回空串。"""
    conn = _key_risk_op_conn()
    return conn.table_id if conn and conn.enabled else ""


# 申请状态（Bitable 审批表单选值）
APPLY_STATUS_APPROVED = "已通过"
APPLY_STATUS_DELETED = "已删除"


# ═══════════════════════════════════════════════════════════
# 时间工具（Bitable 存 UTC epoch ms；平台存 UTC，前端按北京时区渲染）
# ═══════════════════════════════════════════════════════════


def _bj_to_utc(d: datetime) -> datetime:
    """北京墙钟时间 → UTC 时刻（中国无夏令时，固定 UTC+8）。"""
    return (d - timedelta(hours=8)).replace(tzinfo=UTC)


def _day_bounds_utc(target: date) -> tuple[datetime, datetime]:
    """目标日（北京时间）的 UTC 边界 [start, end)。"""
    bj_start = datetime.combine(target, time.min)
    bj_end = datetime.combine(target + timedelta(days=1), time.min)
    return _bj_to_utc(bj_start), _bj_to_utc(bj_end)


def _month_bounds_utc(target: date) -> tuple[datetime, datetime]:
    """目标月（北京时间）的 UTC 边界 [start, end)。"""
    month_start = target.replace(day=1)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    return _bj_to_utc(datetime.combine(month_start, time.min)), _bj_to_utc(datetime.combine(month_end, time.min))


class KeyRiskOperationReportService:
    """关键风险作业报备业务服务（只读，Bitable 为主）"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    # ── Bitable 字段映射 ──

    @staticmethod
    def map_bitable_fields(fields: dict) -> dict[str, Any]:
        """将 Bitable 原始字段映射为 KeyRiskOperationReport 字段。"""

        def _name(v):
            """SingleSelect/User 字段 → 字符串（User 取 name）。"""
            if isinstance(v, str):
                return v
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    return first.get("name", "")
                return str(first)
            if isinstance(v, dict):
                return v.get("name", "")
            return None

        def _text(v):
            """Text/Url 字段 → 文本。"""
            if isinstance(v, str):
                return v
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    return first.get("text", "")
                return str(first)
            if isinstance(v, dict):
                return v.get("text", "")
            return None

        def _url_link(v):
            """Url 字段 → link。"""
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get("link", "")
            return None

        def _ts(v):
            """Bitable epoch ms → UTC datetime。"""
            if v is None:
                return None
            try:
                return datetime.fromtimestamp(int(v) / 1000.0, tz=UTC)
            except (TypeError, ValueError, OSError):
                return None

        def _float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # 申请编号（Url: {text, link}）
        approval_no = fields.get("申请编号")
        report_no = _text(approval_no) or ""

        # 多作业块（xxx1 / xxx2）
        operations: list[dict] = []
        for suffix in ("1", "2"):
            block = {
                "department": _name(fields.get(f"部门{suffix}")),
                "area": _name(fields.get(f"区域{suffix}")),
                "operation_content": _name(fields.get(f"作业内容{suffix}")),
                "time_slot": _name(fields.get(f"作业时间段{suffix}")),
                "personal_protection": _name(fields.get(f"个人防护{suffix}")),
                "preparation_measures": _name(fields.get(f"准备措施{suffix}")),
                "operation_precautions": _name(fields.get(f"操作注意事项{suffix}")),
                "emergency_measures": _name(fields.get(f"应急措施{suffix}")),
                "guardian": _name(fields.get(f"现场作业监护人{suffix}")),
            }
            cleaned = {k: v for k, v in block.items() if v}
            if cleaned:
                operations.append(cleaned)

        # 三阶段现场确认
        def _phase(key: str) -> dict | None:
            result: dict[str, Any] = {}
            date_v = _ts(fields.get(f"日期（{key}）"))
            photo_url = _url_link(fields.get(f"现场确认（{key}）"))
            issue_desc = _text(fields.get(f"问题描述（{key}）"))
            if date_v:
                result["date"] = date_v.isoformat()
            if photo_url:
                result["photo_url"] = photo_url
            if issue_desc:
                result["issue_desc"] = issue_desc
            return result or None

        return {
            "report_no": report_no,
            "approval_no_url": _url_link(approval_no),
            "source": "bitable",
            "feishu_record_id": None,  # 由调用方设置
            # 审批字段
            "apply_status": _name(fields.get("申请状态")),
            "approval_node": _text(fields.get("审批节点")),
            "approval_flow": _name(fields.get("审批流程")),
            "current_handler": _name(fields.get("当前处理人")),
            "initiator_name": _name(fields.get("发起人")),
            "initiator_department": _text(fields.get("发起人部门")),
            "submitted_at": _ts(fields.get("发起时间")),
            "completed_at": _ts(fields.get("完成时间")),
            # 作业主信息
            "department": _name(fields.get("部门")),
            "area": _name(fields.get("区域")),
            "operation_content": _name(fields.get("作业内容")),
            "start_time": _ts(fields.get("作业开始时间")),
            "end_time": _ts(fields.get("作业结束时间")),
            "duration_hours": _float(fields.get("时长")),
            "notes": _text(fields.get("备注")),
            # 安全措施（主作业）
            "personal_protection": _name(fields.get("个人防护")),
            "preparation_measures": _name(fields.get("准备措施")),
            "operation_precautions": _name(fields.get("操作注意事项")),
            "emergency_measures": _name(fields.get("应急措施")),
            "guardian": _name(fields.get("现场作业监护人")),
            "site_guardian": _name(fields.get("现场监护人")),
            "dept_safety_officer": _name(fields.get("部门安全员")),
            # 多作业块 / 三阶段现场确认
            "operations": operations or None,
            "phase_before": _phase("作业前"),
            "phase_ongoing": _phase("作业中"),
            "phase_after": _phase("作业后"),
            "source_id": _text(fields.get("SourceID")),
        }

    # ── Bitable 同步 ──

    async def sync_from_bitable(self) -> dict:
        """从飞书 Bitable 全量同步（GET /records 分页，upsert + 软删除）。

        以 feishu_record_id 为唯一键；申请状态为「已删除」的记录按删除处理。
        """
        records: list[dict] = []
        page_token = None
        max_pages = 10

        async with httpx.AsyncClient(timeout=30) as http:
            token = await get_safety_tenant_token()
            headers = {"Authorization": f"Bearer {token}"}
            for _ in range(max_pages):
                params: dict[str, Any] = {"page_size": 200}
                if page_token:
                    params["page_token"] = page_token
                resp = await http.get(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{bitable_app_token()}/tables/{bitable_table_id()}/records",
                    headers=headers, params=params,
                )
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                records.extend(items)
                has_more = data.get("data", {}).get("has_more", False)
                page_token = data.get("data", {}).get("page_token")
                if not has_more or not page_token:
                    break

        # 收集同步键
        bitable_ids: set[str] = set()
        stats = {"created": 0, "updated": 0, "deleted": 0, "skipped_deleted": 0}

        for rec in records:
            record_id = rec.get("record_id", "")
            if not record_id:
                continue
            fields = rec.get("fields", {})
            if _name_of(fields.get("申请状态")) == APPLY_STATUS_DELETED:
                stats["skipped_deleted"] += 1
                continue
            bitable_ids.add(record_id)
            try:
                mapped = self.map_bitable_fields(fields)
                mapped["feishu_record_id"] = record_id
                if not mapped.get("report_no"):
                    mapped["report_no"] = f"BT-{record_id[-12:]}"

                existing = await self.repo.get_key_risk_operation_report_by_record_id(record_id)
                if existing:
                    for k, v in mapped.items():
                        if v is not None and k not in ("report_no", "source"):
                            setattr(existing, k, v)
                    stats["updated"] += 1
                else:
                    self.session.add(KeyRiskOperationReport(**mapped))
                    stats["created"] += 1
            except Exception:
                logger.exception("同步关键风险作业 Bitable 记录失败: record_id=%s", record_id)

        # 软删除：平台有、Bitable 已无（含「已删除」状态）的记录
        from sqlalchemy import update

        stmt = select(KeyRiskOperationReport.id, KeyRiskOperationReport.feishu_record_id).where(
            KeyRiskOperationReport.source == "bitable",
            KeyRiskOperationReport.is_deleted == False,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        stale_ids = [
            row[0] for row in result.all()
            if not row[1] or row[1] not in bitable_ids
        ]
        if stale_ids:
            await self.session.execute(
                update(KeyRiskOperationReport)
                .where(KeyRiskOperationReport.id.in_(stale_ids))
                .values(is_deleted=True)
            )
            stats["deleted"] = len(stale_ids)
        await self.session.commit()
        return stats

    # ── 查询 ──

    async def get_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        area: str | None = None,
        operation_content: str | None = None,
        apply_status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        keyword: str | None = None,
    ) -> tuple[list[KeyRiskOperationReport], int]:
        """获取关键风险作业报备列表（只读）。date_from/date_to 为北京时间日期。"""
        from_dt = _day_bounds_utc(date_from)[0] if date_from else None
        to_dt = _day_bounds_utc(date_to)[1] if date_to else None
        return await self.repo.get_key_risk_operation_reports(
            skip, limit, department, area, operation_content,
            apply_status, from_dt, to_dt, keyword,
        )

    async def get_report(self, report_id: uuid.UUID) -> KeyRiskOperationReport | None:
        """获取报备详情"""
        return await self.repo.get_key_risk_operation_report_by_id(report_id)

    async def get_stats(self) -> dict:
        """KPI 统计（北京时间口径）。"""
        today = date.today()
        today_start, today_end = _day_bounds_utc(today)
        month_start, month_end = _month_bounds_utc(today)
        return await self.repo.get_key_risk_operation_stats(
            today_start, today_end, month_start, month_end,
        )

    # ── Excel 导出 ──

    async def export_excel(
        self,
        department: str | None = None,
        area: str | None = None,
        operation_content: str | None = None,
        apply_status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        keyword: str | None = None,
    ) -> bytes:
        """导出台账为 Excel 文件。"""
        import io

        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        items, _ = await self.get_reports(
            skip=0, limit=10000,
            department=department, area=area, operation_content=operation_content,
            apply_status=apply_status, date_from=date_from, date_to=date_to, keyword=keyword,
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "关键风险作业台账"

        header_font = Font(name="微软雅黑", bold=True, size=11, color="FFFFFF")
        header_fill = PatternFill(start_color="5645D4", end_color="5645D4", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell_font = Font(name="微软雅黑", size=10)
        cell_alignment = Alignment(vertical="center", wrap_text=True)
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        headers = [
            "序号", "申请编号", "申请状态", "部门", "区域", "作业内容",
            "作业开始", "作业结束", "时长(h)", "现场作业监护人", "发起人",
            "发起部门", "发起时间", "审批节点", "备注",
        ]
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        def _fmt(dt):
            return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if dt else ""

        for row_idx, item in enumerate(items, 2):
            values = [
                row_idx - 1,
                item.report_no or "",
                item.apply_status or "",
                item.department or "",
                item.area or "",
                item.operation_content or "",
                _fmt(item.start_time),
                _fmt(item.end_time),
                item.duration_hours if item.duration_hours is not None else "",
                item.guardian or "",
                item.initiator_name or "",
                item.initiator_department or "",
                _fmt(item.submitted_at),
                item.approval_node or "",
                item.notes or "",
            ]
            for col_idx, val in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = cell_font
                cell.alignment = cell_alignment
                cell.border = thin_border

        col_widths = [6, 14, 10, 12, 18, 16, 16, 16, 8, 12, 10, 16, 16, 12, 20]
        for col_idx, width in enumerate(col_widths, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
        ws.freeze_panes = "A2"

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()


def _name_of(v) -> str | None:
    """轻量字段取值（SingleSelect/User），供同步循环内判断申请状态。"""
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            return first.get("name", "")
        return str(first)
    if isinstance(v, dict):
        return v.get("name", "")
    return None

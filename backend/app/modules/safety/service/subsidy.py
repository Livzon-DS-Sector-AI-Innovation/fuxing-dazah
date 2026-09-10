"""监护补贴统计服务。

平台级能力：补贴计算引擎 + Excel 报表生成。
Agent 工具和 REST API 只是本服务的薄包装，不写业务逻辑。

补贴标准来源于公司内部薪酬制度，非国家法规标准。
与知识库中 GB 30871-2022 的监护人"强制配备要求"无关。
"""

from __future__ import annotations

import io
import math
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from app.modules.safety.schemas.subsidy import (
    SubsidyCalculateResponse,
    SubsidyDetailItem,
    SubsidyRecordInput,
    SubsidyStats,
    SubsidySummaryItem,
)

if TYPE_CHECKING:
    from app.modules.safety.service.subsidy_plan import ReviewNotes

# ═══════════════════════════════════════════════════════════════════
# 补贴标准配置
# 公司内部薪酬制度，非国家法规标准。
# 该费率由企业管理层制定，与 GB 30871-2022 等安全规范的
# 监护人"强制配备要求"是完全不同的两个层面。
# ═══════════════════════════════════════════════════════════════════

SUBSIDY_RATES: dict = {
    "动火作业": {
        "特级": 50,
        "一级": 10,
        "二级": 8,
        "二级_连续": 120,
    },
    "登高作业": {
        "一级": 5,
        "二级": 6,
        "三级": 8,
        "一级_连续": 70,
        "二级_连续": 80,
        "三级_连续": 120,
        "四级_连续": 120,
    },
    "高处作业": {
        "一级": 5,
        "二级": 6,
        "三级": 8,
        "一级_连续": 70,
        "二级_连续": 80,
        "三级_连续": 120,
        "四级_连续": 120,
    },
    "受限空间": {"默认": 10},
    "临时用电": {"默认": 15},
    "抽堵盲板": {"默认": 10},
    "动土": {"默认": 5},
    "断路": {"默认": 5},
    "吊装作业": {
        "一级": 5,
        "二级": 6,
        "三级": 8,
    },
}

# ── 作业票许可时长上限（统计时长不得超过；超出按许可上限计）──
# 口径与 rule_engine.DURATION_LIMIT_BY_TYPE / DONGHUO_LEVEL_HOURS 保持一致，改动需两处同步。
_PERMIT_HOURS_BY_TYPE: dict[str, float | None] = {
    "动火作业": None,          # 动火由级别决定，见 _DONGHUO_LEVEL_HOURS
    "受限空间": 24.0,
    "临时用电": 360.0,
    "登高作业": 72.0,
    "高处作业": 72.0,
    "吊装作业": None,
    "动土": None,
    "断路": None,
    "抽堵盲板": None,
}
_DONGHUO_LEVEL_HOURS: dict[str, float] = {
    "特级": 8.0, "特": 8.0, "特殊": 8.0, "一": 8.0, "一级": 8.0, "1": 8.0,
    "二": 72.0, "二级": 72.0, "2": 72.0, "三": 72.0, "三级": 72.0, "3": 72.0,
}
_DEFAULT_DONGHUO_HOURS: float = 72.0

# 监护人汇总表中的作业类型字段映射
_SUMMARY_OP_TYPES: list[str] = [
    "动火作业", "登高作业", "高处作业", "受限空间",
    "临时用电", "抽堵盲板", "动土", "断路", "吊装作业",
]

# 按次/块计费的类型（不是按半小时计费）
# 公开常量：subsidy_plan 用其判定「缺结束时间 → 以开始时间兜底」（P-2）。
PER_OCCURRENCE_TYPES: frozenset[str] = frozenset({"临时用电", "抽堵盲板"})
_SUMMARY_FIELD_MAP: dict[str, str] = {
    "动火作业": "hot_work",
    "登高作业": "height_work",
    "高处作业": "height_work",
    "受限空间": "confined_space",
    "临时用电": "temporary_electricity",
    "抽堵盲板": "blind_plate",
    "动土": "excavation",
    "断路": "road_breaking",
    "吊装作业": "lifting",
}


class SubsidyService:
    """监护补贴统计服务 — 平台级能力，无 DB 依赖，Agent/API 共用。"""

    # ═══════════════════════════════════════════════════════════════
    # 公开 API
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def calculate(
        cls,
        records: list[SubsidyRecordInput],
        year: int | None = None,
        month: int | None = None,
    ) -> SubsidyCalculateResponse:
        """批量计算监护补贴 → 明细 + 按监护人汇总 + 统计。

        Args:
            records: 监护记录列表
            year: 年份筛选（可选，None=不过滤年份）
            month: 月份筛选（可选，None=不过滤月份）

        Returns:
            SubsidyCalculateResponse 含 details / summaries / stats
        """
        # 按年月筛选
        filtered: list[SubsidyRecordInput] = []
        for record in records:
            try:
                dt = cls._parse_datetime(record.start_time)
            except (ValueError, OSError):
                dt = None

            # 仅对有效时间应用年月筛选
            if dt is not None and year is not None and dt.year != year:
                continue
            if dt is not None and month is not None and dt.month != month:
                continue

            filtered.append(record)

        # 逐条计算
        details: list[SubsidyDetailItem] = []
        for record in filtered:
            detail = cls._calc_single(record)
            details.append(detail)

        # 按监护人汇总
        guardian_data: dict[str, dict] = defaultdict(
            lambda: {
                "guardian_level": "",
                "hot_work": 0.0,
                "height_work": 0.0,
                "confined_space": 0.0,
                "temporary_electricity": 0.0,
                "blind_plate": 0.0,
                "excavation": 0.0,
                "road_breaking": 0.0,
                "lifting": 0.0,
                "total": 0.0,
            }
        )

        for detail in details:
            name = detail.guardian_name
            op_type = detail.operation_type
            amount = detail.subsidy_amount

            if not guardian_data[name]["guardian_level"]:
                guardian_data[name]["guardian_level"] = detail.guardian_level

            field = _SUMMARY_FIELD_MAP.get(op_type, "")
            if field and field in guardian_data[name]:
                guardian_data[name][field] += amount
            guardian_data[name]["total"] += amount

        summaries: list[SubsidySummaryItem] = []
        for name, data in sorted(guardian_data.items()):
            summaries.append(SubsidySummaryItem(
                guardian_name=name,
                guardian_level=data["guardian_level"],
                hot_work=round(data["hot_work"], 2),
                height_work=round(data["height_work"], 2),
                confined_space=round(data["confined_space"], 2),
                temporary_electricity=round(data["temporary_electricity"], 2),
                blind_plate=round(data["blind_plate"], 2),
                excavation=round(data["excavation"], 2),
                road_breaking=round(data["road_breaking"], 2),
                lifting=round(data["lifting"], 2),
                total=round(data["total"], 2),
            ))

        # 统计
        a_cert = sum(1 for s in summaries if s.guardian_level == "A证")
        b_cert = sum(1 for s in summaries if s.guardian_level == "B证")
        total_amount = sum(d.subsidy_amount for d in details)

        return SubsidyCalculateResponse(
            details=details,
            summaries=summaries,
            stats=SubsidyStats(
                total_records=len(details),
                guardian_count=len(summaries),
                a_cert_count=a_cert,
                b_cert_count=b_cert,
                total_amount=round(total_amount, 2),
            ),
        )

    @classmethod
    def export_excel(
        cls,
        details: list[SubsidyDetailItem],
        summaries: list[SubsidySummaryItem],
        title: str,
        department: str,
        b_cert_rate: float = 0.5,
        review_notes: ReviewNotes | None = None,
    ) -> bytes:
        """生成格式化的监护补贴 Excel 报表。

        格式严格对齐企业模板（提炼五部特殊作业统计表）：
        - 字体：等线(DengXian) 11pt，标题16pt bold
        - 边框：thin 全边框
        - 对齐：居中，D列（作业内容）左对齐，均自动换行
        - 行高：标题/表头30，数据行44
        - 序号列用 =ROW()-2 公式自动编号
        - 监护人列(B) + 应发补贴列(K) 按监护人合并
        - 底部：部门合计（SUM公式）+ 确认栏
        - review_notes 非空时追加第二页「待核对/跳过说明」；
          为 None / 空列表时行为与旧版完全一致（仅主表单页）。
        - ``details`` 输入只读：B 证系数通过 ``model_copy`` 拷贝应用，
          不就地修改入参，重复导出结果一致（P-1 防副作用/重复打折）。
        """
        # ── 应用 B 证系数（model_copy 防副作用/重复打折） ──
        adjusted_details = [
            d.model_copy(
                update={"subsidy_amount": round(d.subsidy_amount * b_cert_rate, 2)}
            )
            if d.guardian_level == "B证"
            else d.model_copy()
            for d in details
        ]

        # 按监护人分组（保持原始顺序）
        guardian_groups: dict[str, dict] = defaultdict(
            lambda: {"level": "", "records": [], "total": 0.0}
        )
        ordered_guardians: list[str] = []
        for d in adjusted_details:
            if d.guardian_name not in guardian_groups:
                ordered_guardians.append(d.guardian_name)
            g = guardian_groups[d.guardian_name]
            if not g["level"]:
                g["level"] = d.guardian_level
            g["records"].append(d)
            g["total"] += d.subsidy_amount

        # ── 创建 Workbook ──
        wb = Workbook()
        ws = wb.active
        _sn = title.replace(".", "").replace(" ", "")[:31] if title else "Sheet"
        ws.title = _sn if _sn else "Sheet"
        ws.sheet_view.showGridLines = True

        # ── 样式定义（严格对齐企业模板）──
        title_font = Font(name="等线", size=16, bold=True)
        data_font = Font(name="等线", size=11)
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
        title_align = Alignment(horizontal="center", vertical="center")

        # ── 标题行 (Row 1) ──
        ws.merge_cells("A1:L1")
        c = ws["A1"]
        c.value = title
        c.font = title_font
        c.alignment = title_align
        c.border = thin_border
        ws.row_dimensions[1].height = 30

        # ── 表头 (Row 2) ──
        headers = [
            "序号", "监护人", "监护人级别", "作业地点+作业内容",
            "特殊作业类型", "作业级别", "作业票号", "开始时间", "结束时间",
            "作业间隔时间(h)", "补贴标准", "应发补贴",
        ]
        for ci, h in enumerate(headers, 1):
            c = ws.cell(row=2, column=ci, value=h)
            c.font = data_font
            c.alignment = center_align
            c.border = thin_border
        ws.row_dimensions[2].height = 30

        # ── 数据行 (Row 3+) ──
        row_num = 3
        for name in ordered_guardians:
            info = guardian_groups[name]
            recs = info["records"]
            g_total = round(info["total"])
            g_start_row = row_num

            for ri, record in enumerate(recs):
                # A: 序号 — 用公式 =ROW()-2
                ca = ws.cell(row=row_num, column=1)
                ca.value = f"=ROW()-{row_num - 1}"
                ca.font = data_font
                ca.alignment = center_align
                ca.border = thin_border

                # B: 监护人（首行填值，后续合并时留空）
                cb = ws.cell(row=row_num, column=2,
                             value=record.guardian_name if ri == 0 else None)
                cb.font = data_font
                cb.alignment = center_align
                cb.border = thin_border

                # C: 监护人级别（仅首行）
                cc = ws.cell(row=row_num, column=3,
                             value=record.guardian_level if ri == 0 else None)
                cc.font = data_font
                cc.alignment = center_align
                cc.border = thin_border

                # D: 作业地点+作业内容（左对齐）
                cd = ws.cell(row=row_num, column=4, value=record.location_content)
                cd.font = data_font
                cd.alignment = left_align
                cd.border = thin_border

                # E: 特殊作业类型
                ce = ws.cell(row=row_num, column=5, value=record.operation_type)
                ce.font = data_font
                ce.alignment = center_align
                ce.border = thin_border

                # F: 作业级别
                cf = ws.cell(row=row_num, column=6, value=record.operation_level or "")
                cf.font = data_font
                cf.alignment = center_align
                cf.border = thin_border

                # G: 作业票号（新增）
                cg = ws.cell(row=row_num, column=7, value=record.ticket_no or "")
                cg.font = data_font
                cg.alignment = center_align
                cg.border = thin_border

                # H: 开始时间
                sd = record.start_time[:16].replace("T", " ") if record.start_time else ""
                ch = ws.cell(row=row_num, column=8, value=sd)
                ch.font = data_font
                ch.alignment = center_align
                ch.border = thin_border

                # I: 结束时间
                eh = record.end_time[:16].replace("T", " ") if record.end_time else ""
                ci = ws.cell(row=row_num, column=9, value=eh)
                ci.font = data_font
                ci.alignment = center_align
                ci.border = thin_border

                # J: 作业间隔时间(h)
                cj = ws.cell(row=row_num, column=10, value=record.interval_hours)
                cj.font = data_font
                cj.alignment = center_align
                cj.border = thin_border

                # K: 补贴标准
                if record.billing_unit_label == "天":
                    rate_total = round(record.unit_price)
                else:
                    rate_total = round(record.unit_price * record.billing_units)
                ck = ws.cell(row=row_num, column=11, value=rate_total)
                ck.font = data_font
                ck.alignment = center_align
                ck.border = thin_border

                # L: 应发补贴（仅首行填值——监护人合计）
                cl = ws.cell(row=row_num, column=12,
                             value=g_total if ri == 0 else None)
                cl.font = data_font
                cl.alignment = center_align
                cl.border = thin_border

                ws.row_dimensions[row_num].height = 44
                row_num += 1

            g_end_row = row_num - 1

            # 合并监护人(B) + 应发补贴(L)
            if len(recs) > 1:
                ws.merge_cells(start_row=g_start_row, start_column=2,
                               end_row=g_end_row, end_column=2)
                ws.merge_cells(start_row=g_start_row, start_column=12,
                               end_row=g_end_row, end_column=12)

        # ── 部门合计行（合并 A:K，SUM 公式，全线框）──
        data_end_row = row_num - 1
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=12)
        for col in range(1, 13):
            ct = ws.cell(row=row_num, column=col)
            ct.border = thin_border
            ct.font = data_font
        c = ws.cell(row=row_num, column=1,
                    value=f'="部门合计:"&SUM(L3:L{data_end_row})&"元"')
        c.alignment = center_align
        ws.row_dimensions[row_num].height = 30

        # ── 确认栏（无线框）──
        confirm_row = row_num + 1
        c = ws.cell(row=confirm_row, column=1, value="部门安全员确认:                                                                                ")
        c.font = data_font
        c.alignment = Alignment(horizontal="left", vertical="center")
        c2 = ws.cell(row=confirm_row, column=9, value=" 部门负责人确认:        ")
        c2.font = data_font
        c2.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[confirm_row].height = 30

        # ── 列宽（精确匹配企业模板）──
        col_widths = {
            1: 5.26, 2: 8.84, 3: 7.5, 4: 19, 5: 8.64,
            6: 5.84, 7: 15, 8: 19, 9: 13, 10: 8.83, 11: 13, 12: 13,
        }
        for ci, w in col_widths.items():
            ws.column_dimensions[get_column_letter(ci)].width = w

        # ── 第二页：待核对/跳过说明（review_notes 非空时）──
        if review_notes is not None and not review_notes.is_empty:
            _write_review_sheet(
                wb,
                review_notes,
                title_font=title_font,
                data_font=data_font,
                thin_border=thin_border,
                center_align=center_align,
                left_align=left_align,
            )

        # ── 输出 ──
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    # ═══════════════════════════════════════════════════════════════
    # 内部计算引擎（移植自 Skill calculate_subsidy.py）
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_datetime(dt_str: str) -> datetime | None:
        """解析 ISO 8601 日期时间字符串。"""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calc_duration(start: datetime, end: datetime) -> float:
        """计算原始时长（小时）。"""
        if not start or not end:
            return 0.0
        delta = end - start
        return delta.total_seconds() / 3600.0

    @staticmethod
    def _deduct_lunch(hours: float, start: datetime, end: datetime) -> float:
        """扣除午休时间（12:00-13:30）。

        如果作业跨越午休时段，扣除重叠部分。
        """
        if not start or not end:
            return hours

        lunch_start = start.replace(hour=12, minute=0, second=0, microsecond=0)
        lunch_end = start.replace(hour=13, minute=30, second=0, microsecond=0)

        if start < lunch_end and end > lunch_start:
            overlap_start = max(start, lunch_start)
            overlap_end = min(end, lunch_end)
            if overlap_end > overlap_start:
                overlap_hours = (overlap_end - overlap_start).total_seconds() / 3600.0
                return hours - overlap_hours

        return hours

    @staticmethod
    def _is_continuous(start: datetime, end: datetime) -> bool:
        """判断是否为连续作业（跨天 或 时长超过 8 小时）。"""
        if not start or not end:
            return False
        return (end - start).total_seconds() / 3600.0 > 8 or start.date() != end.date()

    @classmethod
    def _permit_hours(cls, op_type: str, op_level: str | None) -> float | None:
        """返回该作业票的许可时长上限（小时）；None 表示不设限。

        动火按级别（一级/特级 8h，二/三级 72h，未知 72h），其余按类型固定值。
        统计时长不得超过许可上限，超出按许可上限计。
        """
        if op_type == "动火作业":
            lv = (op_level or "").strip()
            if lv in _DONGHUO_LEVEL_HOURS:
                return _DONGHUO_LEVEL_HOURS[lv]
            if "特" in lv or "一" in lv:
                return 8.0
            if "二" in lv or "三" in lv:
                return 72.0
            return _DEFAULT_DONGHUO_HOURS
        return _PERMIT_HOURS_BY_TYPE.get(op_type)

    @classmethod
    def _get_rate(cls, op_type: str, op_level: str | None,
                  is_continuous: bool) -> tuple[float, str]:
        """根据作业类型、级别、是否连续，查找补贴单价。

        Returns:
            (单价, 计费单位) — 单位为 "半小时" / "天" / "次/块/罐"
        """
        if op_type not in SUBSIDY_RATES:
            return 0.0, "半小时"

        rates = SUBSIDY_RATES[op_type]
        level = op_level or ""

        # 连续作业优先匹配 _连续 键
        if is_continuous:
            continuous_key = f"{level}_连续"
            if continuous_key in rates:
                return float(rates[continuous_key]), "天"

        # 精确级别匹配
        if level and level in rates:
            return float(rates[level]), "半小时"

        # 默认费率
        if "默认" in rates:
            unit = "次/块/罐" if op_type in PER_OCCURRENCE_TYPES else "半小时"
            return float(rates["默认"]), unit

        # fallback
        return 0.0, "半小时"

    @classmethod
    def _calc_single(cls, record: SubsidyRecordInput) -> SubsidyDetailItem:
        """计算单条记录的补贴金额。"""
        remark = ""

        start = cls._parse_datetime(record.start_time)
        end = cls._parse_datetime(record.end_time)

        # 发酵工程部受限空间：按张计费 30 元/张（不按时长，不参与重叠去重）
        if record.department == "发酵工程部" and record.operation_type == "受限空间":
            return SubsidyDetailItem(
                guardian_name=record.guardian_name,
                guardian_level=record.guardian_level or "",
                ticket_no=record.ticket_no or "",
                department=record.department or "",
                operation_type=record.operation_type,
                operation_level=record.operation_level or "",
                location_content=record.location_content,
                start_time=record.start_time,
                end_time=record.end_time,
                interval_hours=record.interval_hours,
                raw_hours=0.0,
                adjusted_hours=0.0,
                billing_units=1,
                billing_unit_label="张",
                unit_price=30.0,
                subsidy_amount=30.0,
                remark="发酵部门受限空间：按张计费30元/张（不按时长、不参与重叠去重）",
            )

        if not start or not end:
            return SubsidyDetailItem(
                guardian_name=record.guardian_name,
                guardian_level=record.guardian_level or "",
                ticket_no=record.ticket_no or "",
                operation_type=record.operation_type,
                operation_level=record.operation_level or "",
                location_content=record.location_content,
                start_time=record.start_time,
                end_time=record.end_time,
                interval_hours=record.interval_hours,
                raw_hours=0.0,
                adjusted_hours=0.0,
                billing_units=0,
                billing_unit_label="半小时",
                unit_price=0.0,
                subsidy_amount=0.0,
                remark="时间解析失败",
            )

        # 原始时长
        raw_hours = cls._calc_duration(start, end)

        # 统计时长不得超过作业票许可时长（如一级动火 8h）；超出按许可上限计
        permit_hours = cls._permit_hours(record.operation_type, record.operation_level)
        over_permit = False
        if permit_hours is not None and raw_hours > permit_hours:
            raw_hours = permit_hours
            over_permit = True

        # 扣除
        try:
            interval = float(record.interval_hours or 0)
        except ValueError:
            interval = 0.0

        if interval > 0:
            adjusted_hours = raw_hours - interval
            eff_interval = interval
            remark = f"扣除间隔{interval}小时"
        else:
            raw_adj = cls._deduct_lunch(raw_hours, start, end)
            deducted = raw_hours - raw_adj
            adjusted_hours = raw_adj
            if deducted > 0.001:
                remark = f"扣除午休{round(deducted, 1)}小时"
                eff_interval = round(deducted, 1)
            else:
                remark = ""
                eff_interval = 0.0

        adjusted_hours = max(adjusted_hours, 0)

        # 连续作业判定（基于扣除午休后的有效时长 > 8h，或跨天；避免把所有长票一股脑判连续）
        is_continuous = adjusted_hours > 8 or (start.date() != end.date())

        # 单价查找
        rate, unit = cls._get_rate(record.operation_type, record.operation_level, is_continuous)

        # 金额计算
        if unit == "天":
            billing_units = 1
            amount = rate
            if is_continuous and "连续" not in remark:
                remark = ("连续作业按天计费; " + remark).rstrip("; ")
        elif unit == "次/块/罐":
            billing_units = 1
            amount = rate
        else:
            # 半小时计费，向上取整
            billing_units = math.ceil(adjusted_hours * 2)
            amount = rate * billing_units

        if over_permit:
            remark = (f"超出许可上限，按许可上限计; {remark}" if remark else "超出许可上限，按许可上限计")

        return SubsidyDetailItem(
            guardian_name=record.guardian_name,
            guardian_level=record.guardian_level or "",
            ticket_no=record.ticket_no or "",
            department=record.department or "",
            operation_type=record.operation_type,
            operation_level=record.operation_level or "",
            location_content=record.location_content,
            start_time=record.start_time,
            end_time=record.end_time,
            interval_hours=str(eff_interval),
            raw_hours=round(raw_hours, 2),
            adjusted_hours=round(adjusted_hours, 2),
            billing_units=billing_units,
            billing_unit_label=unit,
            unit_price=rate,
            subsidy_amount=round(amount, 2),
            remark=remark,
        )


# ═══════════════════════════════════════════════════════════════════
# 模块级工具函数
# ═══════════════════════════════════════════════════════════════════


def b_cert_adjusted_total(
    details: list[SubsidyDetailItem],
    b_cert_rate: float = 0.5,
) -> float:
    """B 证折算后实发合计 — 与 ``export_excel`` 主表 K 列口径一致。

    K 列「应发补贴」按监护人合并：组内 B 证记录 × ``b_cert_rate``（默认 0.5）
    四舍五入 2 位，组内求和后再取整（A 证不折）；本函数复刻该口径，
    generate 等调用方直接引用，保证「Excel K 列合计 = 摘要总金额」。

    Args:
        details: ``SubsidyService.calculate`` 产出的明细（B 证系数**前**金额）
        b_cert_rate: B 证折算系数，默认 0.5

    Returns:
        折算后实发合计（与主表部门合计 SUM(K) 一致）
    """
    group_totals: dict[str, float] = defaultdict(float)
    for d in details:
        amount = d.subsidy_amount
        if d.guardian_level == "B证":
            amount = round(amount * b_cert_rate, 2)
        group_totals[d.guardian_name] += amount
    return round(sum(round(total) for total in group_totals.values()), 2)


# ── 第二页「待核对-跳过说明」 ──
# 注：Excel 工作表名不允许 "/"，设计稿的「待核对/跳过说明」落地为「待核对-跳过说明」。

_REVIEW_SHEET_NAME = "待核对-跳过说明"
_REVIEW_HEADERS = ["类别", "姓名或票号", "说明", "金额占位(元)"]
# 实际只有两个分区：① 证书未匹配监护人 ② 跳过票
_REVIEW_SECTION_NAMES = ["一", "二"]


def _cell_display_len(value) -> int:
    """估算单元格显示宽度：CJK 字符按 2 个半角宽度计。"""
    text = "" if value is None else str(value)
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _unmatched_note(name: str, ticket_count: int, operation_types: list[str]) -> str:
    """未匹配监护人行的说明文案：涉及票数 + 不计入补贴提示 + 作业类型。"""
    note = f"{name}：涉及 {ticket_count} 张票；未匹配到A/B证，不计入补贴"
    if operation_types:
        note += f"（作业类型：{'、'.join(operation_types)}）"
    return note


def _write_review_sheet(
    wb: Workbook,
    review_notes: ReviewNotes,
    title_font: Font,
    data_font: Font,
    thin_border: Border,
    center_align: Alignment,
    left_align: Alignment,
) -> None:
    """在主表之后追加「待核对-跳过说明」页，样式与主表一致（字体/边框/表头）。

    布局：标题行 → 表头（类别/姓名或票号/说明/金额占位(元)）→ 分区：
    ① 证书未匹配监护人（姓名+涉及票数+金额占位 0）；② 跳过票（票号/类型/原因）。
    """
    ws = wb.create_sheet(_REVIEW_SHEET_NAME)
    ws.sheet_view.showGridLines = True
    col_count = len(_REVIEW_HEADERS)

    # ── 标题行（合并整行，16pt bold）──
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    title_cell = ws.cell(row=1, column=1, value=_REVIEW_SHEET_NAME)
    title_cell.font = title_font
    title_cell.alignment = center_align
    title_cell.border = thin_border
    ws.row_dimensions[1].height = 30

    # ── 表头行 ──
    for ci, header in enumerate(_REVIEW_HEADERS, 1):
        cell = ws.cell(row=2, column=ci, value=header)
        cell.font = data_font
        cell.alignment = center_align
        cell.border = thin_border
    ws.row_dimensions[2].height = 30

    # ── 分区与数据行 ──
    sections = [
        (
            "证书未匹配监护人（未匹配到A/B证，不计入补贴，金额占位为0）",
            [
                ("未匹配", u.name, _unmatched_note(u.name, u.ticket_count, u.operation_types), 0)
                for u in review_notes.unmatched
            ],
        ),
        (
            "跳过票（无监护人/缺时间/未知类型/作废等，未计入补贴）",
            [
                ("跳过", s.ticket_no, f"票种：{s.ticket_type}；原因：{s.reason}", 0)
                for s in review_notes.skipped
            ],
        ),
    ]
    row = 3
    section_no = 0
    for section_title, rows in sections:
        if not rows:
            continue
        section_no += 1
        banner_value = f"{_REVIEW_SECTION_NAMES[section_no - 1]}、{section_title}"
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col_count)
        banner = ws.cell(row=row, column=1, value=banner_value)
        banner.font = data_font
        banner.alignment = center_align
        banner.border = thin_border
        ws.row_dimensions[row].height = 30
        row += 1

        for values in rows:
            for ci, value in enumerate(values, 1):
                cell = ws.cell(row=row, column=ci, value=value)
                cell.font = data_font
                cell.alignment = left_align if ci == 3 else center_align
                cell.border = thin_border
            ws.row_dimensions[row].height = 44
            row += 1

    # ── 列宽按内容自适应（CJK 双宽估算，上限 60）──
    for ci in range(1, col_count + 1):
        max_len = 8
        for r in range(1, row):
            max_len = max(max_len, _cell_display_len(ws.cell(row=r, column=ci).value))
        ws.column_dimensions[get_column_letter(ci)].width = min(60, max(12, max_len + 4))


__all__ = [
    "SubsidyService",
    "SUBSIDY_RATES",
    "PER_OCCURRENCE_TYPES",
    "b_cert_adjusted_total",
]

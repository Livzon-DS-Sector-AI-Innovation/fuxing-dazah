"""提炼五部监护补贴台账（飞书多维表格，第二数据源）。

2026-10-08 用户指定：提炼五部监护人特殊作业数据**固定来源于该 Bitable**
（链接 https://j0eukrlohu.feishu.cn/base/QHm7bOyMlaWLZysRYw6cnA5tnHh?table=tblXsOBhSvv1JW8Q），
安全员按补贴模板逐行登记：监护人（人员字段）/监护人级别（A证·B证）/特殊作业类型
（8 类 select）/作业级别/开始·结束时间/作业地点+作业内容/作业间隔时间(h)。

与作业票平台源（``subsidy_plan.SubsidyPlanBuilder``）的口径（2026-10-08 用户确认）：

- **提炼五部不使用电子作业票，数据与证书级别均以本台账为准**；
- **级别只认台账「监护人级别」列**，不回退证书台账；未登级别进待核对，
  按 A 证暂计（与平台源 ``uncertified_level`` 口径一致）；
- **同日重叠去重**：与平台源同规则（同监护人+同日+时间区间重叠的连通分量
  保留补贴最高一行），台账行重叠按重复登记处理；金额/许可封顶/午休扣除仍由
  ``SubsidyService.calculate`` 按起止时间实算，表内「作业间隔时间(h)」列不参与计算；
- **无票号列**：跳过/待核对的行以「MM-DD 姓名」标识；月份按「开始时间」归集；
- 表内类型 select 与费率键的差异（动土作业/盲板抽堵/断路作业）经 ``_OP_TYPE_ALIAS``
  归一到 ``SUBSIDY_RATES`` 键（「高处作业」为费率表既有别名键，直接可用）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.schemas.subsidy import SubsidyRecordInput
from app.modules.safety.service.bitable_direct.reader import fetch_all_records
from app.modules.safety.service.subsidy import PER_OCCURRENCE_TYPES
from app.modules.safety.service.subsidy_plan import (
    SkippedTicket,
    SubsidyPlan,
    UnmatchedGuardian,
    _dedup_overlapping_records,
    _normalize_name,
)

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")

APP_TOKEN = "QHm7bOyMlaWLZysRYw6cnA5tnHh"
TABLE_ID = "tblXsOBhSvv1JW8Q"
DEPARTMENT = "提炼工程五部"

# 台账列名（Bitable 中文字段名，与字段结构一一对应）
_F_GUARDIAN = "监护人"
_F_LEVEL = "监护人级别"
_F_OP_TYPE = "特殊作业类型"
_F_OP_LEVEL = "作业级别"
_F_START = "开始时间"
_F_END = "结束时间"
_F_LOCATION = "作业地点+作业内容"
_FIELD_NAMES = [
    _F_GUARDIAN, _F_LEVEL, _F_OP_TYPE, _F_OP_LEVEL, _F_START, _F_END, _F_LOCATION,
]

# 表内 select → SUBSIDY_RATES 键（未列出的键两边一致）
_OP_TYPE_ALIAS: dict[str, str] = {
    "动土作业": "动土",
    "盲板抽堵": "抽堵盲板",
    "断路作业": "断路",
}

_LEVEL_A = "A证"
_LEVEL_B = "B证"
_UNCERTIFIED_LEVEL = "A证"  # 与 subsidy_tools._UNCERTIFIED_LEVEL 口径一致


def _ms_to_datetime(value: Any) -> datetime | None:
    """Bitable datetime 字段（毫秒时间戳）→ 带时区 datetime；非法值返回 None。"""
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=TZ)


def _first_user_name(value: Any) -> str:
    """人员字段（list[dict]，multiple=false）→ 首个姓名。"""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"])
    return ""


def _first_select(value: Any) -> str:
    """select 字段（API 可能返回 str 或 list[str]）→ 首个选项。"""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


async def fetch_t5_rows() -> list[dict[str, Any]]:
    """分页拉取台账全部行（安全应用凭据已验证可读；只请求需要的列）。"""
    client = SafetyBitableClient(app_token=APP_TOKEN)
    rows = await fetch_all_records(
        client,
        table_id=TABLE_ID,
        field_names=_FIELD_NAMES,
    )
    logger.info("提炼五部监护台账拉取完成: %d 行", len(rows))
    return rows


def build_t5_plan(
    rows: list[dict[str, Any]],
    year: int,
    month: int,
    *,
    uncertified_level: str | None = _UNCERTIFIED_LEVEL,
) -> SubsidyPlan:
    """台账行 → SubsidyPlan（纯函数）。

    - **级别只认台账登记**（2026-10-08 用户确认：证书以台账上的级别为主，
      不回退证书台账）；未登级别的监护人进待核对名单，按 ``uncertified_level``
      暂计（None 则不计入）。同名多行级别不一致时以最后一次登记为准。
    - **同日重叠去重**（2026-10-08 用户确认）：与平台源同规则
      （``_dedup_overlapping_records``，同监护人+同日开始日+时间区间重叠的
      连通分量保留补贴最高一行，其余进 skipped 注明并入哪行）。
    - 跳过原因与平台源对齐：缺少开始时间 / 缺少结束时间（按次类型兜底除外）/
      无监护人 / 未知作业类型；行标识 = "MM-DD 姓名"（表无票号列）。
    """
    # 表内级别映射（全表登记皆参与；级别是人的属性，不限目标月）
    sheet_level_map: dict[str, str] = {}
    for row in rows:
        fields = row.get("fields") or {}
        name = _normalize_name(_first_user_name(fields.get(_F_GUARDIAN)))
        sheet_level = _first_select(fields.get(_F_LEVEL))
        if name and sheet_level in (_LEVEL_A, _LEVEL_B):
            sheet_level_map[name] = sheet_level

    records: list[SubsidyRecordInput] = []
    skipped: list[SkippedTicket] = []
    unmatched: list[UnmatchedGuardian] = []
    unmatched_by_name: dict[str, UnmatchedGuardian] = {}
    unmatched_tickets = 0
    departments = {DEPARTMENT}

    for row in rows:
        fields = row.get("fields") or {}
        guardian_name = _normalize_name(_first_user_name(fields.get(_F_GUARDIAN)))
        start = _ms_to_datetime(fields.get(_F_START))
        end = _ms_to_datetime(fields.get(_F_END))
        op_label = _OP_TYPE_ALIAS.get(_first_select(fields.get(_F_OP_TYPE)),
                                       _first_select(fields.get(_F_OP_TYPE)))
        op_level = _first_select(fields.get(_F_OP_LEVEL))
        row_id = f"{start:%m-%d} {guardian_name}" if start and guardian_name else "(不完整行)"

        if start is None:
            skipped.append(SkippedTicket(row_id, op_label or "?", "缺少开始时间"))
            continue
        if start.year != year or start.month != month:
            continue  # 非目标月：直接忽略（不进任何清单）

        if end is None:
            if op_label in PER_OCCURRENCE_TYPES:
                end = start  # 按次计费：时长不影响金额
            else:
                skipped.append(SkippedTicket(row_id, op_label or "?", "缺少结束时间"))
                continue
        if not guardian_name:
            skipped.append(SkippedTicket(row_id, op_label or "?", "无监护人"))
            continue
        if not _known_op_type(op_label):
            skipped.append(SkippedTicket(row_id, op_label or "?", "未知作业类型"))
            continue

        level = sheet_level_map.get(guardian_name)
        if level is None:
            unmatched_tickets += 1
            entry = unmatched_by_name.get(guardian_name)
            if entry is None:
                entry = UnmatchedGuardian(name=guardian_name, ticket_count=0)
                unmatched_by_name[guardian_name] = entry
                unmatched.append(entry)
            entry.ticket_count += 1
            if op_label not in entry.operation_types:
                entry.operation_types.append(op_label)
            if not uncertified_level:
                continue  # 未登级别且未开暂计：不计金额
            level = uncertified_level

        records.append(
            SubsidyRecordInput(
                guardian_name=guardian_name,
                guardian_level=level,
                ticket_no=row_id,  # 台账无票号,以「MM-DD 姓名」行标识(去重淘汰说明/Excel 票号列用)
                department=DEPARTMENT,
                operation_type=op_label,
                operation_level=op_level,
                location_content=str(fields.get(_F_LOCATION) or "").strip(),
                start_time=start.isoformat(),
                end_time=end.isoformat(),
                interval_hours="0",
            )
        )

    # 同监护人同日重叠去重（与平台源同规则；台账行重叠多为重复登记，
    # 连通分量内保留补贴最高一行，其余进 skipped 注明并入哪行）
    records, dedup_skipped = _dedup_overlapping_records(records)
    skipped.extend(dedup_skipped)

    return SubsidyPlan(
        records=records,
        unmatched=unmatched,
        skipped=skipped,
        departments=departments,
        total_tickets=len(rows),
        domain_tickets=len(records) + unmatched_tickets + len(skipped),
        matched_tickets=len(records),
        unmatched_tickets=unmatched_tickets,
        skipped_tickets=len(skipped),
    )


def _known_op_type(op_label: str) -> bool:
    """是否为费率表可计费的作业类型（用于未知类型跳过判定）。"""
    from app.modules.safety.service.subsidy import SUBSIDY_RATES

    return op_label in SUBSIDY_RATES


__all__ = [
    "APP_TOKEN",
    "TABLE_ID",
    "DEPARTMENT",
    "fetch_t5_rows",
    "build_t5_plan",
]

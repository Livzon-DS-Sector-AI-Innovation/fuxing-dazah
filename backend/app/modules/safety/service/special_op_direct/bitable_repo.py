"""特殊作业「直读多维表格」仓储层：按日期批量拉取 -> 视图对象 -> 风险判定。

与旧镜像链路的关系（spec「复用而不改动」）：
- 字段映射复用 ``SpecialOperationDailyReportService.map_bitable_fields``，业务语义不变
- 风险判定复用 ``RiskAssessmentEngine.assess``，判定规则一行不改
- 视图对象 ``SpecialOpView`` 字段名与 ORM 模型 ``SpecialOperationReport`` 同名，
  因此渲染（``ReportBuilder``）与 AI 分析（``AIAnalyst``）两处消费方零改动复用

取数语义（2026-09-11 连生产表实测）：
- Bitable 的 ExactDate 过滤按**天**粒度、以表格时区（北京时间）切天，
  与旧镜像 ``get_reports_by_date`` 的窗口一致：09-11 两路各 42 条，
  record_id 集合完全相同
- 一律走批量 search 接口（``list_all_records``），不逐条调用单记录读接口
- ``strict=True``：查询失败向上抛 ``BitableQueryError``，绝不返回空列表伪装
  「当天无作业」

Ticket 06 收敛：字段取值 / 时间换算 / 日期窗口 / 过滤构造 / 连接解析 / 回写串行
全部转发公共底座 ``bitable_direct``；本模块只保留特殊作业的字段映射、视图对象、
风险判定入口与列契约，不重复实现通用能力。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.bitable_direct.reader import (
    BitableRecordsReader as BitableRecordsReader,
)
from app.modules.safety.service.bitable_direct.reader import (
    resolve_client as _resolve_client,
)
from app.modules.safety.service.bitable_direct.writer import (
    WRITEBACK_INTERVAL_SECONDS as WRITEBACK_INTERVAL_SECONDS,
)
from app.modules.safety.service.bitable_direct.writer import (
    BitableRecordWriter as BitableRecordWriter,
)
from app.modules.safety.service.bitable_direct.writer import (
    RecordUpdate,
    write_serial,
)
from app.modules.safety.service.bitable_direct.writer import (
    WritebackResult as WritebackResult,
)
from app.modules.safety.service.special_op_direct import contract
from app.modules.safety.service.special_operation_daily_report import (
    RiskAssessmentEngine,
    SpecialOperationDailyReportService,
)

logger = logging.getLogger(__name__)

RecordWriter = BitableRecordWriter

# 多维表格列名（与生产表实际列名一致）
F_START_TIME = "作业时间_开始时间"
F_APPLICATION_STATUS = "申请状态"

# 「申请状态」= 已撤回 的旧票不计入日报统计（撤回后通常重新提交了一张新票，
# 按行数统计会把同一作业算两次；2026-09-22 真机数据 34 条 vs 有效票 31 条）
WITHDRAWN_APPLICATION_STATUS = "已撤回"
WITHDRAWN_EXCLUSION_REASON = "申请已撤回"

# 顶层系统字段（需 automatic_fields=True 才返回；单位 ms 时间戳）
SYSTEM_FIELD_CREATED_TIME = "created_time"

# 北京时间固定偏移（中国大陆无夏令时；表格时区实测为北京时间）
BJT = bd_filters.BJT

# 发起时间与系统「创建时间」都取不到时的哨兵：必然落在「今日新增」窗口之外
UNKNOWN_CREATED_AT = datetime.min.replace(tzinfo=UTC)

# map_bitable_fields 产出的时间字段（需统一归一为 UTC aware）
_DATETIME_FIELDS: tuple[str, ...] = (
    "planned_start_time",
    "planned_end_time",
    "submitted_at",
    "completed_at",
)


class SpecialOpDirectError(BitableConfigError):
    """直读路径的前置条件不满足（连接未配置/停用等），调用方不得当作「无数据」。"""


@dataclass
class SpecialOpView:
    """Bitable 记录在内存中的统一视图对象（不落库、不参与 ORM）。

    字段名与 ``SpecialOperationReport`` 同名同义，外加引擎派生结果
    （``daily_risk_level`` 等）与 ``record_id`` / ``created_at`` 兜底。
    """

    # 标识与时间兜底
    record_id: str = ""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = UNKNOWN_CREATED_AT
    created_at_known: bool = False

    # 映射结果（与 ORM 模型同名）
    report_no: str = ""
    source: str = "bitable"
    feishu_record_id: str | None = None
    operation_type: str = ""
    operation_level: str = "grade2"
    department: str | None = None
    location: str | None = None
    work_description: str | None = None
    planned_start_time: datetime | None = None
    planned_end_time: datetime | None = None
    work_duration_hours: float | None = None
    personnel_type: str | None = None
    fire_work_method: str | None = None
    height_work_method: str | None = None
    work_height: float | None = None
    lifting_weight: float | None = None
    contractor_name: str | None = None
    has_other_operations: str | None = None
    other_operation_types: list[Any] | None = None
    is_weekend_holiday: str | None = None
    is_national_holiday: str | None = None
    holiday_period: str | None = None
    report_type: str | None = None
    initiator_department: str | None = None
    initiator_name: str | None = None
    approver_type: str | None = None
    safety_approver_name: str | None = None
    approver_name: str | None = None
    approval_no: str | None = None
    work_plan_url: str | None = None
    work_scheme_url: str | None = None
    approved_permit_url: str | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    approval_node: str | None = None
    risk_level: str | None = None
    status: str = "approved"
    notes: str | None = None
    # 申请状态（单据生命周期：审批中 / 已通过 / 已撤回；已撤回票不参与日报统计）
    application_status: str | None = None

    # 引擎派生结果（内存，不落库）
    daily_risk_level: str | None = None
    daily_risk_reason: str | None = None
    inferred_operation_types: list[Any] | None = None
    is_excluded: bool = False
    exclusion_reason: str | None = None
    daily_report_date: date | None = None

    # 原始记录（排障用）
    raw: dict[str, Any] = field(default_factory=dict)


# 通用字段取值 / 时间换算转发底座，保留原模块内名称与调用签名。
to_utc = bd_fields.to_utc
_ms_to_utc = bd_fields.ms_to_utc
_to_ms = bd_fields.utc_to_ms


def to_view(record: dict[str, Any]) -> SpecialOpView:
    """单条 Bitable 记录 -> ``SpecialOpView``（映射复用镜像链路 + 创建时间兜底）。

    created_at 取值链（决策 5：created_at 兜底）：
    系统字段「创建时间」-> 「发起时间」-> ``UNKNOWN_CREATED_AT`` 哨兵；
    哨兵必然落在「今日新增」窗口之外，且 ``created_at_known=False`` 供日报标注。
    """
    fields: dict[str, Any] = record.get("fields") or {}
    record_id = str(record.get("record_id") or "")
    mapped = SpecialOperationDailyReportService.map_bitable_fields(fields)
    for name in _DATETIME_FIELDS:
        mapped[name] = to_utc(mapped.get(name))
    mapped["feishu_record_id"] = record_id or None
    mapped["application_status"] = bd_fields.text(fields, F_APPLICATION_STATUS)

    submitted_at: datetime | None = mapped.get("submitted_at")
    system_created = _ms_to_utc(record.get(SYSTEM_FIELD_CREATED_TIME))
    created_at_known = system_created is not None or submitted_at is not None
    created_at = system_created or submitted_at or UNKNOWN_CREATED_AT

    return SpecialOpView(
        record_id=record_id,
        created_at=created_at,
        created_at_known=created_at_known,
        raw=fields,
        **mapped,
    )


def assess_view(view: SpecialOpView) -> SpecialOpView:
    """在视图对象上跑风险判定，并把结果按镜像链路的同一写法写回视图。

    引擎赋值与 ``sync_from_bitable`` / ``_upsert_one_from_fields`` 的写法逐字
    一致（等级、命中规则、推断类型、是否排除）；其上叠加直读域独有的撤回票
    排除（``mark_withdrawn``）——镜像链路不感知「申请状态」列。
    """
    result = RiskAssessmentEngine.assess(view)
    view.daily_risk_level = result.risk_level
    view.daily_risk_reason = (
        "; ".join(result.matched_rules) if result.matched_rules else None
    )
    view.inferred_operation_types = (
        result.inferred_types if result.inferred_types else None
    )
    view.is_excluded = result.is_excluded
    view.exclusion_reason = result.exclusion_reason
    return mark_withdrawn(view)


def mark_withdrawn(view: SpecialOpView) -> SpecialOpView:
    """撤回票排除：「申请状态」= 已撤回 的记录不计入日报统计（幂等，可兜底重复调用）。

    独立于风险判定引擎（引擎规则一行不改），且需在「日报风险等级（AI）」存量列
    读取之后兜底——撤回票此前被回写过的列值不能让它重新算作有效票。
    """
    if (view.application_status or "") == WITHDRAWN_APPLICATION_STATUS:
        view.is_excluded = True
        view.exclusion_reason = WITHDRAWN_EXCLUSION_REASON
    return view


def day_window(target_date: date) -> tuple[datetime, datetime]:
    """目标日期的 [下界, 上界) 瞬时区间（北京时间日界，左闭右开）。"""
    return bd_filters.day_window(target_date)


def day_filter(target_date: date) -> dict[str, Any]:
    """目标日期（北京时间日）的 Bitable 结构化过滤条件。

    实测（2026-09-11）：ExactDate 过滤按天粒度、以表格时区（北京时间）切天，
    因此下界取当日 00:00、上界取次日 00:00，语义等同「日期属于该天」；
    与旧镜像 ``get_reports_by_date`` 的窗口逐条一致。
    """
    return bd_filters.day_filter(F_START_TIME, target_date)


def resolve_client() -> SafetyBitableClient:
    """按配置中心连接创建 Bitable 客户端；连接缺失/停用时抛错（不静默降级）。

    连接解析转发 ``bitable_direct.reader.resolve_client``；异常仍保留原域异常
    类型 ``SpecialOpDirectError``，保证既有 ``except`` 语义不变。
    """
    try:
        return _resolve_client("special_op", "daily")
    except BitableConfigError as exc:
        raise SpecialOpDirectError(
            "特殊作业 Bitable 连接未配置或已停用（special_op/daily）"
        ) from exc


async def fetch_day_views(
    target_date: date,
    *,
    client: BitableRecordsReader | None = None,
) -> list[SpecialOpView]:
    """直读目标日期（北京时间日）全部特殊作业：批量拉取 -> 映射 -> 判定。

    一次批量查询（``list_all_records`` 内部自动翻页），不逐条调用单记录读接口。
    查询失败时 ``strict=True`` 向上抛 ``BitableQueryError``，由调度器标记 failed
    并进入重试窗口，而不是静默发出一份空日报。
    """
    reader = client or resolve_client()
    records = await reader.list_all_records(
        filter_info=day_filter(target_date),
        automatic_fields=True,
        page_size=200,
        strict=True,
    )
    logger.info(
        "特殊作业直读完成: date=%s records=%d", target_date.isoformat(), len(records)
    )
    return [assess_view(to_view(record)) for record in records]


#
# 风险等级回写（Ticket 05）：只写「日报风险等级（AI）」一列
#


async def writeback_risk_levels(
    views: Sequence[SpecialOpView],
    *,
    writer: RecordWriter | None = None,
    interval_seconds: float = WRITEBACK_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> WritebackResult:
    """把判定出的风险等级回写到「日报风险等级（AI）」列。

    - **只回写这一列**：请求体恒为 ``{日报风险等级（AI）: 高风险|中风险|低风险}``，
      绝不触碰人工填写列与公式列
    - 等级为空/未知、缺少 record_id，或申请已撤回 -> 跳过（不回写、不报错；
      撤回票此前被回写的列值保留不动）
    - 串行执行，条目之间间隔 ``interval_seconds``（默认 0.5 秒），由底座
      ``bitable_direct.writer.write_serial`` 保证
    - 单条失败只记 warning 并计入 ``failed``，**不抛异常**：回写不阻塞日报推送，
      下一轮日报自然补写（spec「回写失败」决策）
    """
    target = writer or resolve_client()
    pending = [
        view
        for view in views
        if view.feishu_record_id
        and (view.application_status or "") != WITHDRAWN_APPLICATION_STATUS
        and contract.option_for_risk_level(view.daily_risk_level) is not None
    ]
    updates = [
        RecordUpdate(
            record_id=view.feishu_record_id or "",
            fields={
                contract.RISK_FIELD_NAME: contract.option_for_risk_level(
                    view.daily_risk_level
                )
            },
        )
        for view in pending
    ]
    result = await write_serial(
        target,
        updates,
        interval_seconds=interval_seconds,
        sleep=sleep,
    )
    result.skipped = len(views) - len(pending)

    logger.info(
        "风险等级回写完成: attempted=%d written=%d skipped=%d failed=%d",
        result.attempted,
        result.written,
        result.skipped,
        len(result.failed),
    )
    return result

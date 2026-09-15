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
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Protocol

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.special_op_direct import contract
from app.modules.safety.service.special_operation_daily_report import (
    RiskAssessmentEngine,
    SpecialOperationDailyReportService,
)

logger = logging.getLogger(__name__)

# 多维表格列名（与生产表实际列名一致）
F_START_TIME = "作业时间_开始时间"

# 顶层系统字段（需 automatic_fields=True 才返回；单位 ms 时间戳）
SYSTEM_FIELD_CREATED_TIME = "created_time"

# 北京时间固定偏移（中国大陆无夏令时；表格时区实测为北京时间）
BJT = timezone(timedelta(hours=8))

# 发起时间与系统「创建时间」都取不到时的哨兵：必然落在「今日新增」窗口之外
UNKNOWN_CREATED_AT = datetime.min.replace(tzinfo=UTC)

# map_bitable_fields 产出的时间字段（需统一归一为 UTC aware）
_DATETIME_FIELDS: tuple[str, ...] = (
    "planned_start_time",
    "planned_end_time",
    "submitted_at",
    "completed_at",
)


class SpecialOpDirectError(RuntimeError):
    """直读路径的前置条件不满足（连接未配置/停用等），调用方不得当作「无数据」。"""


class BitableRecordsReader(Protocol):
    """批量只读拉取接缝：真实实现为 ``SafetyBitableClient``，单测注入替身。"""

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        automatic_fields: bool = False,
        page_size: int = 200,
        strict: bool = False,
    ) -> list[dict[str, Any]]: ...


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

    # 引擎派生结果（内存，不落库）
    daily_risk_level: str | None = None
    daily_risk_reason: str | None = None
    inferred_operation_types: list[Any] | None = None
    is_excluded: bool = False
    exclusion_reason: str | None = None
    daily_report_date: date | None = None

    # 原始记录（排障用）
    raw: dict[str, Any] = field(default_factory=dict)

def to_utc(value: datetime | None) -> datetime | None:
    """把映射产出的 datetime 统一归一为 UTC aware（None 原样返回）。

    ``map_bitable_fields`` 用 ``datetime.fromtimestamp(ms / 1000)`` 生成**进程本地
    时钟**的 naive datetime：生产容器 TZ=UTC 时它本就是 UTC（与镜像行读回值一致），
    而本机（TZ=Asia/Shanghai）会整体平移 8 小时。这里按「naive = 本地时钟，取同一
    瞬时」归一，两种环境结果一致；同时保证下游 ``ReportBuilder._new_ops_section``
    的 aware 窗口比较不会因 naive/aware 混用而抛 TypeError。
    """
    if value is None:
        return None
    return value.astimezone(UTC)


def _ms_to_utc(value: Any) -> datetime | None:
    """Bitable 毫秒时间戳 -> UTC aware datetime（无法解析返回 None）。"""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


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

    与 ``sync_from_bitable`` / ``_upsert_one_from_fields`` 的赋值口径逐字一致，
    保证同一份数据两路判定结果相同（等级、命中规则、推断类型、是否排除）。
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
    return view


def day_window(target_date: date) -> tuple[datetime, datetime]:
    """目标日期的 [下界, 上界) 瞬时区间（北京时间日界，左闭右开）。"""
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=BJT)
    return start, start + timedelta(days=1)


def day_filter(target_date: date) -> dict[str, Any]:
    """目标日期（北京时间日）的 Bitable 结构化过滤条件。

    实测（2026-09-11）：ExactDate 过滤按天粒度、以表格时区（北京时间）切天，
    因此下界取当日 00:00、上界取次日 00:00，语义等同「日期属于该天」；
    与旧镜像 ``get_reports_by_date`` 的窗口逐条一致。
    """
    start, end = day_window(target_date)
    return {
        "conjunction": "and",
        "conditions": [
            {
                "field_name": F_START_TIME,
                "operator": "isGreater",
                "value": ["ExactDate", str(_to_ms(start))],
            },
            {
                "field_name": F_START_TIME,
                "operator": "isLess",
                "value": ["ExactDate", str(_to_ms(end))],
            },
        ],
    }


def _to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def resolve_client() -> SafetyBitableClient:
    """按配置中心连接创建 Bitable 客户端；连接缺失/停用时抛错（不静默降级）。"""
    conn = store.get_connection("special_op", "daily")
    if conn is None or not conn.enabled:
        raise SpecialOpDirectError(
            "特殊作业 Bitable 连接未配置或已停用（special_op/daily）"
        )
    return SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)


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

# Bitable 同一张表不支持并发写，条目之间留间隔（spec「回写」）
WRITEBACK_INTERVAL_SECONDS = 0.5


class RecordWriter(Protocol):
    """单条记录回写接缝（真实实现为 ``SafetyBitableClient.update_record``）。"""

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> bool: ...


@dataclass
class WritebackResult:
    """回写结果（供编排入口 log warning / 计入告警）。"""

    attempted: int = 0
    written: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


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
    - 等级为空/未知，或缺少 record_id -> 跳过（不回写、不报错）
    - 串行执行，条目之间间隔 ``interval_seconds``（默认 0.5 秒）
    - 单条失败只记 warning 并计入 ``failed``，**不抛异常**：回写不阻塞日报推送，
      下一轮日报自然补写（spec「回写失败」决策）
    """
    target = writer or resolve_client()
    result = WritebackResult()
    pending = [
        view
        for view in views
        if view.feishu_record_id
        and contract.option_for_risk_level(view.daily_risk_level) is not None
    ]
    result.skipped = len(views) - len(pending)

    for index, view in enumerate(pending):
        if index:
            await sleep(interval_seconds)
        option = contract.option_for_risk_level(view.daily_risk_level)
        record_id = view.feishu_record_id or ""
        result.attempted += 1
        try:
            written = await target.update_record(
                record_id, {contract.RISK_FIELD_NAME: option}
            )
        except Exception:
            logger.warning(
                "风险等级回写异常: record_id=%s level=%s",
                record_id, view.daily_risk_level, exc_info=True,
            )
            written = False
        if written:
            result.written += 1
        else:
            result.failed.append(record_id)
            logger.warning(
                "风险等级回写失败: record_id=%s level=%s（不阻塞日报推送，下一轮补写）",
                record_id, view.daily_risk_level,
            )

    logger.info(
        "风险等级回写完成: attempted=%d written=%d skipped=%d failed=%d",
        result.attempted, result.written, result.skipped, len(result.failed),
    )
    return result

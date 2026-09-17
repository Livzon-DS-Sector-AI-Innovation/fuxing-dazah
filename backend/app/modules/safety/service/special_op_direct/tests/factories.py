"""special_op_direct 单测共用夹具（不依赖真实 Bitable / DB / 大模型）。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from app.modules.safety.models import SpecialOperationReport
from app.modules.safety.schemas.special_op_daily import AIDailyAnalysisResult
from app.modules.safety.service.special_op_contract import SpecialOpRecord
from app.modules.safety.service.special_op_direct import bitable_repo
from app.modules.safety.service.special_operation_daily_report import (
    RiskAssessmentEngine,
    SpecialOperationDailyReportService,
)

DAY = date(2026, 9, 11)
BJT = timezone(timedelta(hours=8))
CREATED_MS = int(datetime(2026, 9, 10, 23, 0, tzinfo=UTC).timestamp() * 1000)

# 四种判定结果样本（列名与生产表一致）
HIGH_FIELDS: dict[str, Any] = {
    "作业类型": "动火作业", "作业地点": "罐区", "作业内容": "管道焊接",
}
MEDIUM_FIELDS: dict[str, Any] = {
    "作业类型": "受限空间", "申请部门": "生产部",
    "作业地点": "污水站", "作业内容": "池内清理",
}
LOW_FIELDS: dict[str, Any] = {
    "作业类型": "临时用电", "作业地点": "车间", "作业内容": "更换照明灯具",
}
FALLBACK_FIELDS: dict[str, Any] = {
    "作业类型": "常规作业", "作业地点": "车间", "作业内容": "现场巡视",
}


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def record(
    record_id: str = "rec001",
    *,
    created_time: int | None = CREATED_MS,
    **fields: Any,
) -> dict[str, Any]:
    """构造一条 Bitable 原始记录（含系统字段 created_time，可显式传 None 去掉）。"""
    payload: dict[str, Any] = {
        "作业类型": "动火作业",
        "申请部门": "生产部",
        "作业内容": "管道焊接",
        "作业地点": "罐区",
        "作业时间_开始时间": ms(datetime(2026, 9, 11, 0, 30, tzinfo=UTC)),
        "作业时间_结束时间": ms(datetime(2026, 9, 11, 3, 30, tzinfo=UTC)),
        "作业时间_时长": 3.0,
        "作业人员类型": "公司人员",
        "发起时间": ms(datetime(2026, 9, 11, 0, 0, tzinfo=UTC)),
    }
    payload.update(fields)
    item: dict[str, Any] = {"record_id": record_id, "fields": payload}
    if created_time is not None:
        item["created_time"] = created_time
    return item


def mirror_keys(item: dict[str, Any]) -> list[str]:
    """镜像映射产出的字段名（直接问生产映射函数，避免手工维护清单）。"""
    return list(SpecialOperationDailyReportService.map_bitable_fields(item["fields"]))


def orm_from_view(
    view: bitable_repo.SpecialOpView, item: dict[str, Any],
) -> SpecialOperationReport:
    """按视图对象构造 ORM 对象，并按镜像链路（sync_from_bitable）的写法写回判定。

    等价于「镜像行从库里读回 + 那 5 行判定赋值」之后的内存对象。
    """
    orm = SpecialOperationReport(**{k: getattr(view, k) for k in mirror_keys(item)})
    orm.id = view.id
    result = RiskAssessmentEngine.assess(orm)
    orm.daily_risk_level = result.risk_level
    orm.daily_risk_reason = (
        "; ".join(result.matched_rules) if result.matched_rules else None
    )
    orm.inferred_operation_types = result.inferred_types if result.inferred_types else None
    orm.is_excluded = result.is_excluded
    orm.exclusion_reason = result.exclusion_reason
    return orm


class FakeReader:
    """替身读取器：记录调用参数，可返回受控记录或直接抛错。"""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.records = records or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 200,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.calls.append({
            "table_id": table_id,
            "filter_info": filter_info,
            "field_names": field_names,
            "sort": sort,
            "automatic_fields": automatic_fields,
            "page_size": page_size,
            "strict": strict,
        })
        if self.error is not None:
            raise self.error
        return list(self.records)


class FakePusher:
    """替身推送器：记录每次推送的 chat_id / 标题 / 正文，不真发。"""

    def __init__(self, message_id: str | None = "om_test") -> None:
        self.message_id = message_id
        self.calls: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        chat_id: str,
        title: str,
        content: str,
        elements: list[dict[str, Any]] | None = None,
        header_template: str = "orange",
        subtitle: str | None = None,
        header_tags: list[dict[str, Any]] | None = None,
    ) -> str | None:
        self.calls.append({
            "chat_id": chat_id,
            "title": title,
            "content": content,
            "elements": elements,
            "header_template": header_template,
            "subtitle": subtitle,
            "header_tags": header_tags,
        })
        return self.message_id


class FakeAnalyst:
    """替身 AI 分析器：可返回受控结果或抛错（覆盖失败回退分支）。"""

    def __init__(
        self,
        result: AIDailyAnalysisResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def analyze(
        self,
        report_date: date,
        mode: str,
        reports: Sequence[SpecialOpRecord],
        stats: dict[str, int],
    ) -> AIDailyAnalysisResult | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result

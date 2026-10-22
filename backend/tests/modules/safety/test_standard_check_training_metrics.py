"""D3 取数器测试：training.completion_rate / training.record_integrity。

接缝：opener 替身（training_behavior/training 注入，与 hazard 取数器测试同款）。
口径（spec 链5 节 + DESIGN D3 组）：
- completion_rate：窗口内（计划日期锚定）状态≠已取消行中，
  已完成 /（未开始+进行中+已完成）；
- record_integrity：窗口内（实施日期锚定）状态=已完成行中，
  （签到表附件非空 且（考核方式=无需考核 或 考核合格人数已填））占比。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.standard_check.engine import window_for
from app.modules.safety.service.standard_check.metrics import (
    MetricContext as Ctx,
    get_metric,
)

YEAR = window_for("年度", date(2026, 10, 22))
Q4 = window_for("季度", date(2026, 10, 22))


class FakeTrainingClient:
    def __init__(self, items, *, config_error: bool = False) -> None:
        self._items = items
        self._config_error = config_error

    async def list_all_records(self, **kwargs):
        if self._config_error:
            raise BitableConfigError("未配置: training_behavior/training")
        return self._items


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 12, tzinfo=UTC).timestamp() * 1000)


def _tr(
    name: str,
    *,
    status: str = "已完成",
    planned: date | None = None,
    held: date | None = None,
    attendance: bool = False,
    assessment: str | None = "考试",
    passed: str | None = None,
) -> dict:
    fields: dict = {"培训名称": name, "状态": status, "考核方式": assessment or ""}
    if planned is not None:
        fields["计划日期"] = _ms(planned)
    if held is not None:
        fields["实施日期"] = _ms(held)
    if attendance:
        fields["签到表"] = [{"file_token": "ft-1", "name": "签到表.jpg"}]
    if passed is not None:
        fields["考核合格人数"] = passed
    return {"record_id": name, "fields": fields}


class TestCompletionRate:
    async def test_ratio_excludes_cancelled_and_out_of_window(self) -> None:
        items = [
            _tr("A", status="已完成", planned=date(2026, 3, 1)),
            _tr("B", status="已完成", planned=date(2026, 5, 1)),
            _tr("C", status="进行中", planned=date(2026, 9, 1)),
            _tr("D", status="已取消", planned=date(2026, 6, 1)),   # 分母排除
            _tr("E", status="已完成", planned=date(2025, 6, 1)),   # 窗口外
        ]
        m = get_metric("training.completion_rate")
        out = await m.compute(YEAR, Ctx(opener=lambda d, k: FakeTrainingClient(items)))
        assert out.value == 67.0  # 2/3
        assert "计划 3 项" in out.evidence[0]["title"]

    async def test_not_connected_is_no_data(self) -> None:
        m = get_metric("training.completion_rate")
        out = await m.compute(
            YEAR, Ctx(opener=lambda d, k: FakeTrainingClient([], config_error=True))
        )
        assert out.value is None
        assert "training" in out.no_data_reason

    async def test_no_planned_rows_is_no_data(self) -> None:
        m = get_metric("training.completion_rate")
        out = await m.compute(YEAR, Ctx(opener=lambda d, k: FakeTrainingClient([])))
        assert out.value is None
        assert out.no_data_reason


class TestRecordIntegrity:
    async def test_intact_ratio_by_quarter(self) -> None:
        items = [
            # 完整：签到+合格人数
            _tr("A", held=date(2026, 10, 5), attendance=True, passed="18"),
            # 完整：签到+无需考核
            _tr("B", held=date(2026, 10, 20), attendance=True, assessment="无需考核"),
            # 缺签到
            _tr("C", held=date(2026, 10, 8), attendance=False, passed="10"),
            # 考核未填合格人数
            _tr("D", held=date(2026, 10, 9), attendance=True, assessment="考试",
                passed=None),
            # 窗口外（Q4 之外）
            _tr("E", held=date(2026, 6, 1), attendance=True, passed="9"),
            # 未完成不计
            _tr("F", status="进行中", held=date(2026, 10, 10), attendance=True),
        ]
        m = get_metric("training.record_integrity")
        out = await m.compute(Q4, Ctx(opener=lambda d, k: FakeTrainingClient(items)))
        assert out.value == 50.0  # 2/4
        assert "已完成 4 项" in out.evidence[0]["title"]

    async def test_not_connected_is_no_data(self) -> None:
        m = get_metric("training.record_integrity")
        out = await m.compute(
            Q4, Ctx(opener=lambda d, k: FakeTrainingClient([], config_error=True))
        )
        assert out.value is None
        assert "training" in out.no_data_reason

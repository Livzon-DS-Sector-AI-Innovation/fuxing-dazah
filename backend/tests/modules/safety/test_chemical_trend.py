"""危化品库存趋势/异动查询 — 单测（db_session 真库 + 事务回滚）。

种子数据全部落在 2099 年（真库不会有该日期的 daily 快照），聚合/窗口断言
只取本用例日期，天然隔离真机数据；阈值经 env 固定（app_config DB 层由
conftest autouse stub 为空，env 层即最高优先级）。

覆盖：
- daily_trend_points：逐日聚合总量/条目/预警，排除 weekly 与软删除行
- material_changes：surge/decline 双阈值、新出现按绝对量、小波动 normal、
  小额消失 removed、Δ=0 不出条目、D8 断源 compare_skipped
- change_trend：窗口逐日两两对比计数 + 断源日记 0 并标记
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.safety.chemical_inventory import trend
from app.modules.safety.models import ChemicalInventorySnapshot


def _snap(
    d: date, dept: str, name: str, total_t: str | None, *,
    kind: str = "daily", source: str | None = "sheet", risk: str = "normal",
    deleted: bool = False,
) -> ChemicalInventorySnapshot:
    return ChemicalInventorySnapshot(
        snapshot_date=d,
        snapshot_kind=kind,
        department=dept,
        storage_location="测试库",
        material_name=name,
        quantity=Decimal("1"),
        unit="kg",
        total_quantity_t=Decimal(total_t) if total_t is not None else None,
        risk_flag=risk,
        source=source,
        is_deleted=deleted,
    )


@pytest.fixture(autouse=True)
def _fixed_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """阈值固定为代码默认口径（比例 30% 且绝对量 1.0 T），屏蔽本地 env 渗入。"""
    monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SURGE_RATIO", "0.30")
    monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SURGE_ABS_T", "1.0")


async def test_daily_trend_points_aggregates(db_session) -> None:
    d1, d2 = date(2099, 1, 1), date(2099, 1, 2)
    db_session.add_all([
        _snap(d1, "dept_a", "物料甲", "10", risk="warn"),
        _snap(d1, "dept_a", "物料乙", "5"),
        # 同键软删除行不计入（999 那份是软删残影）
        _snap(d1, "dept_b", "物料丙", "999", risk="warn", deleted=True),
        _snap(d1, "dept_b", "物料丙", "3"),
    ])
    db_session.add_all([
        _snap(d2, "dept_a", "物料甲", "12", risk="warn"),
        _snap(d2, "dept_a", "物料乙", "5", risk="warn"),
        _snap(d2, "dept_b", "物料丙", "3"),
        _snap(d2, "dept_a", "物料丁", "20", kind="weekly"),
    ])
    await db_session.flush()

    points = {p["date"]: p for p in await trend.daily_trend_points(db_session, days=10)}

    assert points[date(2099, 1, 1).isoformat()] == {
        "date": "2099-01-01", "total_t": 18.0, "item_count": 3, "warn_count": 1,
    }
    assert points[date(2099, 1, 2).isoformat()] == {
        "date": "2099-01-02", "total_t": 20.0, "item_count": 3, "warn_count": 2,
    }


async def test_material_changes_flags(db_session) -> None:
    prev_d, cur_d = date(2099, 2, 1), date(2099, 2, 2)
    db_session.add_all([
        # surge：+10T（≥1T 且 +100% ≥30%）
        _snap(prev_d, "dept_a", "物料甲", "10"),
        _snap(cur_d, "dept_a", "物料甲", "20"),
        # decline：-5T（≥1T 且 -50% 绝对值 ≥30%）
        _snap(prev_d, "dept_a", "物料乙", "10"),
        _snap(cur_d, "dept_a", "物料乙", "5"),
        # 新出现但 ≥1T：按日报口径归 surge（prev<=0 仅按绝对量）
        _snap(cur_d, "dept_b", "物料丙", "5"),
        # 小额消失（<1T）：removed 而非 decline
        _snap(prev_d, "dept_b", "物料丁", "0.5"),
        # 小波动（<1T）：normal
        _snap(prev_d, "dept_c", "物料戊", "2"),
        _snap(cur_d, "dept_c", "物料戊", "2.2"),
        # 持平：不出条目
        _snap(prev_d, "dept_c", "物料己", "3"),
        _snap(cur_d, "dept_c", "物料己", "3"),
    ])
    await db_session.flush()

    result = await trend.material_changes(db_session, target_date=cur_d)

    assert result["target_date"] == cur_d.isoformat()
    assert result["base_date"] == prev_d.isoformat()
    assert result["compare_skipped"] is False
    assert result["thresholds"] == {"ratio": 0.3, "abs_t": 1.0}
    assert result["summary"] == {
        "surge_count": 2, "decline_count": 1, "new_count": 0,
        "removed_count": 1, "total_materials": 5,  # 今日在账：甲/乙/丙/戊/己（含持平的己）
    }
    by_key = {(i["department"], i["material_name"]): i for i in result["items"]}
    assert by_key[("dept_a", "物料甲")]["flag"] == "surge"
    assert by_key[("dept_a", "物料甲")]["delta_t"] == 10.0
    assert by_key[("dept_a", "物料甲")]["ratio"] == 1.0
    assert by_key[("dept_a", "物料乙")]["flag"] == "decline"
    assert by_key[("dept_b", "物料丙")]["flag"] == "surge"
    assert by_key[("dept_b", "物料丙")]["ratio"] is None  # prev<=0 无比例
    assert by_key[("dept_b", "物料丁")]["flag"] == "removed"
    assert by_key[("dept_c", "物料戊")]["flag"] == "normal"
    assert ("dept_c", "物料己") not in by_key
    # 按 |Δ| 降序：甲(+10) 第一
    assert result["items"][0]["material_name"] == "物料甲"


async def test_material_changes_d8_source_break(db_session) -> None:
    prev_d, cur_d = date(2099, 2, 10), date(2099, 2, 11)
    db_session.add_all([
        _snap(prev_d, "dept_a", "物料甲", "10", source="bitable"),
        _snap(cur_d, "dept_a", "物料甲", "20", source="sheet"),
    ])
    await db_session.flush()

    result = await trend.material_changes(db_session, target_date=cur_d)

    assert result["compare_skipped"] is True
    assert result["items"] == []
    assert result["summary"]["surge_count"] == 0
    assert result["summary"]["decline_count"] == 0
    assert result["summary"]["total_materials"] == 1  # 今日在账仍真实统计


async def test_change_trend_counts_and_source_break(db_session) -> None:
    d1, d2, d3 = date(2099, 4, 1), date(2099, 4, 2), date(2099, 4, 3)
    db_session.add_all([
        _snap(d1, "dept_a", "物料甲", "10"),
        _snap(d1, "dept_a", "物料乙", "10"),
        # d2 vs d1：甲 +10T → surge；乙持平
        _snap(d2, "dept_a", "物料甲", "20"),
        _snap(d2, "dept_a", "物料乙", "10"),
        # d3 vs d2：乙 -5T → decline；甲持平。source 切换 → 断源，计 0 并标记
        _snap(d3, "dept_a", "物料甲", "20", source="bitable"),
        _snap(d3, "dept_a", "物料乙", "5", source="bitable"),
    ])
    await db_session.flush()

    points = {p["date"]: p for p in await trend.change_trend(db_session, days=2)}

    # 窗口 = 最近 2 个快照日（d1 仅作 d2 的基线）
    assert set(points) == {d2.isoformat(), d3.isoformat()}
    assert points[d2.isoformat()] == {
        "date": d2.isoformat(), "surge_count": 1, "decline_count": 0, "compare_skipped": False,
    }
    assert points[d3.isoformat()] == {
        "date": d3.isoformat(), "surge_count": 0, "decline_count": 0, "compare_skipped": True,
    }


async def test_change_trend_insufficient_history(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口内不足 2 个快照日（无基线）→ 空列表而非报错。

    真库总有历史 daily 快照，窗口取近端日期桩化为单日，直接验证守卫分支。
    """
    async def _single_date(_db, _days):
        return [date(2099, 5, 1)]

    monkeypatch.setattr(trend, "_recent_daily_dates", _single_date)

    points = await trend.change_trend(db_session, days=30)

    assert points == []

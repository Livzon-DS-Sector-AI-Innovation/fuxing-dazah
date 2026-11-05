"""T02 页面筛选 + facility_map 读口径（B2 筛选/下游）单测（RED 先行）。

覆盖 spec S3 / B2-2：
- 台账 ``list_ledger`` 的等级/类型/类别筛选命中 ``effective_*``（人工优先、
  AI fallback），human≠AI 时必须取人工值；
- ``facility_map.hazard_rows_for_day`` 的 hazard_level = effective_level。

视图直接用 ``bitable_repo.to_view`` 从 fake Bitable 记录构造（与生产直读
同源），不 mock 内部实现。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.safety.service.facility_map.service import hazard_rows_for_day
from app.modules.safety.service.hazard_direct import bitable_repo
from app.modules.safety.service.hazard_direct.page_query import list_ledger

_CHECK_MS = int(datetime(2026, 10, 27, 1, 30, tzinfo=UTC).timestamp() * 1000)


def _view(
    no: str,
    *,
    manual_level: object = None,
    ai_level: object = None,
    manual_type: object = None,
    ai_type: object = None,
    manual_category: object = None,
    ai_category: object = None,
    discovered_at_ms: int = _CHECK_MS,
) -> bitable_repo.HazardView:
    """fake Bitable 记录 → HazardView（含人工/AI 双轨字段）。"""
    fields: dict[str, object] = {
        bitable_repo.F_NO: f"HZ-{no}",
        bitable_repo.F_DESC: f"描述{no}",
        bitable_repo.F_DATE: discovered_at_ms,
        bitable_repo.F_RECTIFY_STATUS: "未关闭",
    }
    if manual_level is not None:
        fields[bitable_repo.F_LEVEL_MANUAL] = manual_level
    if ai_level is not None:
        fields[bitable_repo.F_LEVEL_AI] = ai_level
    if manual_type is not None:
        fields[bitable_repo.F_TYPE_MANUAL] = manual_type
    if ai_type is not None:
        fields[bitable_repo.F_TYPE_AI] = ai_type
    if manual_category is not None:
        fields[bitable_repo.F_CATEGORY_MANUAL] = manual_category
    if ai_category is not None:
        fields[bitable_repo.F_CATEGORY_AI] = ai_category
    return bitable_repo.to_view({"record_id": f"rec-{no}", "fields": fields})


def _nos(items: list[bitable_repo.HazardView]) -> set[str]:
    return {v.hazard_no for v in items}


# ═══════════════════════════════════════════════════════════════
# S3：list_ledger 筛选按 effective_*（human≠AI 取人工）
# ═══════════════════════════════════════════════════════════════


class TestLevelFilterEffective:
    def test_human_level_wins_over_ai(self) -> None:
        """A 人工较大/AI 一般；B 仅 AI 一般 → 筛「较大」只命中 A，筛「一般」只命中 B。"""
        views = [
            _view("A", manual_level="较大隐患", ai_level="一般隐患"),
            _view("B", ai_level="一般隐患"),
        ]
        items, total = list_ledger(views, hazard_level="serious")
        assert total == 1 and _nos(items) == {"HZ-A"}

        items, total = list_ledger(views, hazard_level="general")
        assert total == 1 and _nos(items) == {"HZ-B"}

    def test_chinese_filter_value_still_matches_en_effective(self) -> None:
        """前端筛选值兼容中文：effective 输出 EN，按别名集合匹配。"""
        views = [_view("A", manual_level="较大隐患", ai_level="一般隐患")]
        items, total = list_ledger(views, hazard_level="较大隐患")
        assert total == 1 and _nos(items) == {"HZ-A"}

    def test_ai_fallback_filter_and_source(self) -> None:
        """人工缺失 → AI 值命中，source=ai 可判定。"""
        view = _view("B", ai_level="重大隐患")
        assert view.effective_level_source == "ai"
        items, total = list_ledger([view], hazard_level="major")
        assert total == 1 and _nos(items) == {"HZ-B"}


class TestTypeCategoryFilterEffective:
    def test_type_human_wins_over_ai(self) -> None:
        views = [
            _view(
                "A",
                manual_type="物的不安全状态",
                ai_type="人的不安全行为",
            ),
            _view("B", ai_type="人的不安全行为"),
        ]
        items, total = list_ledger(views, hazard_type="unsafe_condition")
        assert total == 1 and _nos(items) == {"HZ-A"}

        items, total = list_ledger(views, hazard_type="unsafe_action")
        assert total == 1 and _nos(items) == {"HZ-B"}

    def test_category_human_wins_over_ai(self) -> None:
        views = [
            _view(
                "A",
                manual_category="设备设施",
                ai_category="应急管理",
            ),
            _view("B", ai_category="应急管理"),
        ]
        items, total = list_ledger(views, hazard_category="equipment")
        assert total == 1 and _nos(items) == {"HZ-A"}

        items, total = list_ledger(views, hazard_category="emergency_mgmt")
        assert total == 1 and _nos(items) == {"HZ-B"}


# ═══════════════════════════════════════════════════════════════
# 风险分区图第七路：hazard_level = effective_level
# ═══════════════════════════════════════════════════════════════


_TARGET = date(2026, 10, 27)


class TestFacilityMapHazardLevelEffective:
    def test_human_level_used_when_mismatch(self) -> None:
        view = _view("A", manual_level="较大隐患", ai_level="一般隐患")
        out = hazard_rows_for_day([view], _TARGET, _TARGET)
        assert out["open"] == [
            {
                "hazard_no": "HZ-A",
                "hazard_desc": "描述A",
                "hazard_level": "serious",  # 人工优先（旧实现会给出 AI 的 general）
                "progress": None,
            }
        ]

    def test_ai_fallback_when_manual_missing(self) -> None:
        view = _view("B", ai_level="重大隐患")
        out = hazard_rows_for_day([view], _TARGET, _TARGET)
        assert out["open"][0]["hazard_level"] == "major"

    def test_empty_levels_yield_none(self) -> None:
        view = _view("C")
        out = hazard_rows_for_day([view], _TARGET, _TARGET)
        assert out["open"][0]["hazard_level"] is None

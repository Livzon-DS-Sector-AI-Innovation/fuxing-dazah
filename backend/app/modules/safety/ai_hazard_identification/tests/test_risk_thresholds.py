"""Ticket 02 — 风险等级阈值统一 160/70/20 的边界测试。

平台风险等级判定口径从 320/160/70 统一到 Bitable 公式的 160/70/20：
    D ≥ 160         → level_1（重大/公司级）
    70 ≤ D < 160    → level_2（较大/部门级）
    20 ≤ D < 70     → level_3（一般/班组·岗位级）
    D < 20          → level_4（低风险）

get_risk_level 使用闭区间 [min_d, max_d]，精确边界值 160/70/20 归上一档；
scripts 3/5/7 的 RISK_LEVEL_RANGES 使用半开区间 [min_d, max_d)。
"""

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.rules import (
    RISK_LEVEL_RANGES as RANGES_3,
)
from app.modules.safety.ai_hazard_identification.script5_residual_risk.rules import (
    RISK_LEVEL_RANGES as RANGES_5,
)
from app.modules.safety.ai_hazard_identification.script7_post_risk.rules import (
    RISK_LEVEL_RANGES as RANGES_7,
)
from app.modules.safety.schemas.hazard_identifications import (
    RISK_LEVELS,
    get_risk_level,
)


class TestRiskLevelsConfig:
    """RISK_LEVELS 配置应改为 160/70/20 档位。"""

    def test_levels_ordered_by_min_d(self):
        keys = [rl["key"] for rl in RISK_LEVELS]
        assert keys == ["level_1", "level_2", "level_3", "level_4"]

    def test_min_d_values(self):
        min_ds = {rl["key"]: rl["min_d"] for rl in RISK_LEVELS}
        assert min_ds == {"level_1": 160, "level_2": 70, "level_3": 20, "level_4": 0}

    def test_max_d_values(self):
        max_ds = {rl["key"]: rl["max_d"] for rl in RISK_LEVELS}
        assert max_ds == {"level_1": 99999, "level_2": 159, "level_3": 69, "level_4": 19}

    def test_level_1_is_company_level(self):
        lvl1 = RISK_LEVELS[0]
        assert lvl1["control_level"] == "公司级"
        assert lvl1["responsible_person"] == "公司主要负责人"

    def test_level_2_is_department_level(self):
        lvl2 = RISK_LEVELS[1]
        assert lvl2["control_level"] == "部门级"

    def test_level_3_is_team_level(self):
        lvl3 = RISK_LEVELS[2]
        assert lvl3["control_level"] == "班组/岗位级"


class TestGetRiskLevelBoundaries:
    """get_risk_level 精确边界（闭区间，整数边界归上一档）。"""

    def test_d_160_is_level_1(self):
        assert get_risk_level(160)["key"] == "level_1"

    def test_d_159_is_level_2(self):
        assert get_risk_level(159)["key"] == "level_2"

    def test_d_70_is_level_2(self):
        assert get_risk_level(70)["key"] == "level_2"

    def test_d_69_is_level_3(self):
        assert get_risk_level(69)["key"] == "level_3"

    def test_d_20_is_level_3(self):
        assert get_risk_level(20)["key"] == "level_3"

    def test_d_19_is_level_4(self):
        assert get_risk_level(19)["key"] == "level_4"

    def test_d_0_is_level_4(self):
        assert get_risk_level(0)["key"] == "level_4"

    def test_high_value_is_level_1(self):
        assert get_risk_level(10000)["key"] == "level_1"

    def test_mid_level_2(self):
        assert get_risk_level(100)["key"] == "level_2"

    def test_mid_level_3(self):
        assert get_risk_level(50)["key"] == "level_3"


class TestScriptRiskLevelRanges:
    """脚本 3/5/7 的 RISK_LEVEL_RANGES 同步 160/70/20 半开区间。"""

    def test_script3_ranges(self):
        assert RANGES_3 == {
            "level_1": (160, float("inf")),
            "level_2": (70, 160),
            "level_3": (20, 70),
            "level_4": (0, 20),
        }

    def test_script5_ranges(self):
        assert RANGES_5 == {
            "level_1": (160, float("inf")),
            "level_2": (70, 160),
            "level_3": (20, 70),
            "level_4": (0, 20),
        }

    def test_script7_ranges(self):
        assert RANGES_7 == {
            "level_1": (160, float("inf")),
            "level_2": (70, 160),
            "level_3": (20, 70),
            "level_4": (0, 20),
        }

    def test_ranges_consistent_with_get_risk_level(self):
        """半开区间一致性：整数边界归上一档（level_1 边界无限大）。"""
        for d, expected in [
            (160, "level_1"),
            (159, "level_2"),
            (70, "level_2"),
            (69, "level_3"),
            (20, "level_3"),
            (19, "level_4"),
        ]:
            level_key = get_risk_level(d)["key"]
            assert level_key == expected, f"D={d} 应归 {expected}"

"""班组轮换与组别过滤测试：自定义轮换顺序 team_order + 按创建顺序滑窗兜底 + 看板组别过滤。"""

from app.modules.quality.repository import (
    filter_board_by_groups,
    shift_duty_teams,
)


def _teams(*names: str) -> list[dict]:
    return [{"id": f"id-{i}", "name": n, "member_ids": []} for i, n in enumerate(names)]


class TestCustomTeamOrder:
    def test_slides_along_custom_order(self):
        """轮换按自定义顺序滑窗：每 3 天滑一位，当班 2 个班。"""
        teams = _teams("甲班", "乙班", "丙班")
        order = ["丙班", "甲班", "乙班"]
        cases = {
            "2026-10-26": ["丙班", "甲班"],  # k=0
            "2026-10-28": ["丙班", "甲班"],  # 同周期
            "2026-10-29": ["甲班", "乙班"],  # k=1
            "2026-11-01": ["乙班", "丙班"],  # k=2
            "2026-11-04": ["丙班", "甲班"],  # k=3 回绕
        }
        for on_date, expected in cases.items():
            duty = shift_duty_teams(teams, "2026-10-26", 3, 2, on_date, order)
            assert [t["name"] for t in duty] == expected, on_date

    def test_unlisted_teams_not_rotated(self):
        """未勾选的班组不参与轮换。"""
        teams = _teams("甲班", "乙班", "丙班")
        duty = shift_duty_teams(teams, "2026-10-26", 3, 1, "2026-10-26", ["甲班", "丙班"])
        assert [t["name"] for t in duty] == ["甲班"]
        duty = shift_duty_teams(teams, "2026-10-26", 3, 1, "2026-10-29", ["甲班", "丙班"])
        assert [t["name"] for t in duty] == ["丙班"]

    def test_missing_names_skipped(self):
        """顺序里不存在的班组名自动跳过。"""
        teams = _teams("甲班", "乙班")
        duty = shift_duty_teams(teams, "2026-10-26", 3, 2, "2026-10-26", ["甲班", "丁班", "乙班"])
        assert [t["name"] for t in duty] == ["甲班", "乙班"]

    def test_before_start_date_is_first_slot(self):
        teams = _teams("甲班", "乙班", "丙班")
        duty = shift_duty_teams(teams, "2026-10-26", 3, 2, "2026-10-20", ["甲班", "乙班", "丙班"])
        assert [t["name"] for t in duty] == ["甲班", "乙班"]

    def test_empty_teams(self):
        assert shift_duty_teams([], "2026-10-26", 3, 2, "2026-10-26", ["甲班"]) == []

    def test_all_names_missing_returns_empty(self):
        teams = _teams("甲班")
        assert shift_duty_teams(teams, "2026-10-26", 3, 2, "2026-10-26", ["丁班"]) == []


class TestLegacySlidingWindow:
    def test_slides_by_creation_order(self):
        """不设轮换顺序时按创建顺序滑窗（旧行为）。"""
        teams = _teams("甲班", "乙班", "丙班")
        cases = {
            "2026-10-26": ["甲班", "乙班"],
            "2026-10-29": ["乙班", "丙班"],
            "2026-11-01": ["丙班", "甲班"],
            "2026-11-04": ["甲班", "乙班"],
        }
        for on_date, expected in cases.items():
            duty = shift_duty_teams(teams, "2026-10-26", 3, 2, on_date, None)
            assert [t["name"] for t in duty] == expected, on_date

    def test_empty_order_falls_back(self):
        teams = _teams("甲班", "乙班", "丙班")
        duty = shift_duty_teams(teams, "2026-10-26", 3, 2, "2026-10-29", [])
        assert [t["name"] for t in duty] == ["乙班", "丙班"]


MAPPING = {"仪器组": ["杂质", "含量"], "生物组": ["微生物", "效价"], "理化组": ["pH", "干燥失重"]}


class TestFilterBoardByGroups:
    def _items(self) -> list[dict]:
        return [
            {
                "plan_id": 1, "sops": [
                    {"sop_no": "SOP.03.001", "items": ["有关物质", "含量"]},
                    {"sop_no": "SOP.03.002", "items": ["pH"]},
                ],
                "assignments": [
                    {"sop_no": "SOP.03.001", "assignee_id": "u1", "assignee_name": "张三"},
                    {"sop_no": "SOP.03.002", "assignee_id": "u2", "assignee_name": "李四"},
                ],
            },
            {
                "plan_id": 2, "sops": [{"sop_no": "SOP.03.003", "items": ["微生物限度"]}],
                "assignments": [],
            },
            {
                "plan_id": 3, "sops": [{"sop_no": "SOP.03.004", "items": ["细菌内毒素"]}],
                "assignments": [{"sop_no": "SOP.03.004", "assignee_id": "u3", "assignee_name": "王五"}],
            },
        ]

    def test_keeps_only_own_group_sops_and_assignments(self):
        items = filter_board_by_groups(self._items(), {"仪器组"}, MAPPING)
        assert [i["plan_id"] for i in items] == [1]
        assert [s["sop_no"] for s in items[0]["sops"]] == ["SOP.03.001"]
        assert [a["sop_no"] for a in items[0]["assignments"]] == ["SOP.03.001"]

    def test_plan_without_visible_sops_dropped(self):
        items = filter_board_by_groups(self._items(), {"生物组"}, MAPPING)
        assert [i["plan_id"] for i in items] == [2]

    def test_unmatched_items_fall_back_to_lc_group(self):
        """未命中关键词的项目回退理化组，只有理化组成员可见。"""
        items = filter_board_by_groups(self._items(), {"理化组"}, MAPPING)
        assert [i["plan_id"] for i in items] == [1, 3]
        assert [s["sop_no"] for s in items[0]["sops"]] == ["SOP.03.002"]

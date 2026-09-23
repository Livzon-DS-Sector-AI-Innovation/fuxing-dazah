"""oh 直读视图对象单测（Ticket 01）——字段映射 / 派生状态 / 跳行规则 / 常量列。"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.oh_direct.views import (
    hazard_factor_view_from_record,
    position_view_from_record,
)


def _segment(text: str) -> list[dict[str, Any]]:
    """search 富文本段形态（Bitable search 文本列返回形态）。"""
    return [{"text": text, "type": "text"}]


class TestPositionView:
    def test_normal_row(self) -> None:
        view = position_view_from_record(
            "recA",
            {"部门": _segment("生产部"), "岗位": _segment("合成操作工"),
             "危害因素": ["噪声", "氨", "噪声"]},
        )
        assert view is not None
        assert view.id == "recA"
        assert view.feishu_record_id == "recA"
        assert view.department == "生产部"
        assert view.position == "合成操作工"
        assert view.hazard_factors == ["噪声", "氨"]  # 去重保序（spec D8）
        assert view.hazard_factors_status == "filled"

    def test_both_empty_skipped(self) -> None:
        assert position_view_from_record("recB", {"部门": [], "岗位": ""}) is None
        assert position_view_from_record("recB", {}) is None

    def test_only_department_kept_with_empty_status(self) -> None:
        view = position_view_from_record("recC", {"部门": _segment("质检部")})
        assert view is not None
        assert view.department == "质检部"
        assert view.position is None
        assert view.hazard_factors is None
        assert view.hazard_factors_status == "empty"

    def test_job_title_dead_column_none(self) -> None:
        # 「职务」列在 Bitable 表不存在（spec §0.3 探针坐实）→ 恒 None
        view = position_view_from_record("recD", {"部门": _segment("生产部")})
        assert view is not None
        assert view.job_title is None

    def test_job_title_future_column_naturally_picked(self) -> None:
        # 死列恢复后 bd_fields.text 天然取到，无需改代码
        view = position_view_from_record(
            "recD", {"部门": _segment("生产部"), "职务": _segment("班长")},
        )
        assert view is not None
        assert view.job_title == "班长"

    def test_constant_columns(self) -> None:
        view = position_view_from_record("recE", {"部门": _segment("生产部")})
        assert view is not None
        assert view.source == "bitable"
        assert view.notes is None
        assert view.created_at is None
        assert view.updated_at is None
        assert view.is_deleted is False


class TestHazardFactorView:
    def test_normal_row(self) -> None:
        view = hazard_factor_view_from_record(
            "recF",
            {"危害因素名称": _segment("氨"), "呼吸防护用品": _segment("半面罩")},
        )
        assert view is not None
        assert view.id == "recF"
        assert view.factor_name == "氨"
        assert view.ppe_respiratory == "半面罩"

    def test_empty_name_skipped(self) -> None:
        assert hazard_factor_view_from_record("recG", {"危害因素名称": ""}) is None
        assert hazard_factor_view_from_record("recG", {}) is None

    def test_ppe_missing_none(self) -> None:
        view = hazard_factor_view_from_record("recH", {"危害因素名称": _segment("噪声")})
        assert view is not None
        assert view.ppe_respiratory is None

    def test_constant_columns(self) -> None:
        view = hazard_factor_view_from_record("recI", {"危害因素名称": _segment("氨")})
        assert view is not None
        assert view.source == "bitable"
        assert view.notes is None
        assert view.created_at is None
        assert view.is_deleted is False

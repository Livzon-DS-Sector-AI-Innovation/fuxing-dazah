"""chemical_inventory 直读视图接缝单测（Ticket 01）。

覆盖：InventoryView 与 ORM 字段同名契约、枚举映射抽纯后 handler re-export 等价、
映射纯函数值形态（探针实测：富文本数组/select str/多选 list[str]/数字/毫秒日期）、
未映射标签透传（单位列脏选项口径）、规则引擎吃视图零改动、镜像口径排序等价。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.safety.chemical_inventory.enum_maps import (
    _ALERT_TYPE_ENUM_TO_LABEL,
    _ALERT_TYPE_LABEL_TO_ENUM,
    _DEPT_ENUM_TO_LABEL,
    _DEPT_LABEL_TO_ENUM,
    _HAZARD_ENUM_TO_LABEL,
    _HAZARD_LABEL_TO_ENUM,
    _RISK_FLAG_ENUM_TO_LABEL,
    _RISK_FLAG_LABEL_TO_ENUM,
    _UNIT_ENUM_TO_LABEL,
    _UNIT_LABEL_TO_ENUM,
    _map_inventory_fields,
)
from app.modules.safety.chemical_inventory.rules import ChemicalRiskRuleEngine
from app.modules.safety.models import ChemicalInventoryRecord
from app.modules.safety.service.chemical_inventory_direct.views import (
    InventoryView,
    sort_like_inventory,
    view_from_record_id,
)

# 直读视图不承载的 ORM 列：审计列与软删标记（镜像查询恒过滤 is_deleted）
_VIEW_OMITTED_ORM_COLUMNS = {"created_by", "updated_by", "is_deleted"}


def _orm_column_names() -> set[str]:
    return {c.name for c in ChemicalInventoryRecord.__table__.columns}


# 探针实测的 Bitable 原始值形态
def _make_fields() -> dict[str, object]:
    return {
        "部门": "仓储部",
        "存放部位": [{"text": "23#仓库五-1区", "type": "text"}],
        "物料名称": [{"text": "乙醇", "type": "text"}],
        "包装规格": [{"text": "160Kg/桶", "type": "text"}],
        "库存数量": 7920,
        "单位": "kg",
        "现场物料总量(T)": 7.92,
        "库存上限": 5,
        "上限单位": "T",
        "危险性": ["易燃"],
        "品类": [{"text": "溶剂", "type": "text"}],
        "最后更新时间": 1789903843000,
        "风险标记": "预警",
        "风险说明": ["超量", "单位异常"],
    }


class TestEnumMapsExtracted:
    def test_label_enum_round_trip(self) -> None:
        for label_to_enum, enum_to_label in (
            (_DEPT_LABEL_TO_ENUM, _DEPT_ENUM_TO_LABEL),
            (_UNIT_LABEL_TO_ENUM, _UNIT_ENUM_TO_LABEL),
            (_HAZARD_LABEL_TO_ENUM, _HAZARD_ENUM_TO_LABEL),
            (_RISK_FLAG_LABEL_TO_ENUM, _RISK_FLAG_ENUM_TO_LABEL),
            (_ALERT_TYPE_LABEL_TO_ENUM, _ALERT_TYPE_ENUM_TO_LABEL),
        ):
            for label, enum in label_to_enum.items():
                assert enum_to_label[enum] == label

    def test_unit_passthrough_semantics(self) -> None:
        """单位列脏选项（'槽车'/'500g/瓶'/'易制毒' 等）未映射标签必须原样透传。"""
        mapped = _map_inventory_fields({"单位": "槽车"})
        assert mapped["unit"] == "槽车"

    def test_dept_passthrough_semantics(self) -> None:
        mapped = _map_inventory_fields({"部门": "未知部门"})
        assert mapped["department"] == "未知部门"


class TestMapInventoryFields:
    def test_full_mapping_shapes(self) -> None:
        mapped = _map_inventory_fields(_make_fields())
        assert mapped["department"] == "warehouse"
        assert mapped["storage_location"] == "23#仓库五-1区"
        assert mapped["material_name"] == "乙醇"
        assert mapped["package_spec"] == "160Kg/桶"
        assert mapped["quantity"] == Decimal("7920")
        assert mapped["unit"] == "kg"
        assert mapped["total_quantity_t"] == Decimal("7.92")
        assert mapped["max_limit"] == Decimal("5")
        assert mapped["max_limit_unit"] == "T"
        assert mapped["hazard_classes"] == ["flammable"]
        assert mapped["category"] == "溶剂"
        assert mapped["last_updated_at"] == datetime.fromtimestamp(
            1789903843000 / 1000, tz=UTC
        )
        assert mapped["risk_flag"] == "warn"
        assert mapped["risk_note"] == ["over_limit", "unit_anomaly"]

    def test_absent_fields_dropped(self) -> None:
        mapped = _map_inventory_fields({"物料名称": [{"text": "丙酮", "type": "text"}]})
        assert mapped == {"material_name": "丙酮"}


class TestViewSeam:
    def test_view_fields_cover_orm_columns(self) -> None:
        view_fields = {f.name for f in InventoryView.__dataclass_fields__.values()}
        missing = _orm_column_names() - _VIEW_OMITTED_ORM_COLUMNS - view_fields
        assert not missing, f"视图缺少 ORM 同名字段: {sorted(missing)}"

    def test_view_from_record_id(self) -> None:
        view = view_from_record_id("rec1", _make_fields())
        assert view is not None
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.department == "warehouse"
        assert view.material_name == "乙醇"
        assert view.quantity == Decimal("7920")
        assert view.hazard_classes == ["flammable"]
        assert view.risk_flag == "warn"
        # 数据新鲜度信号：updated_at 取 Bitable「最后更新时间」（type=1002 自动字段）
        assert view.updated_at == datetime.fromtimestamp(1789903843000 / 1000, tz=UTC)
        assert view.last_updated_at == view.updated_at

    def test_view_defaults_parity(self) -> None:
        """空行缺字段的视图默认值与镜像 ORM 插入默认一致。"""
        view = view_from_record_id("rec2", {"物料名称": [{"text": "丙酮", "type": "text"}]})
        assert view is not None
        assert view.department == ""
        assert view.risk_flag == "normal"
        assert view.risk_note is None
        assert view.is_deleted is False

    def test_engine_runs_on_view_unchanged(self) -> None:
        """ChemicalRiskRuleEngine duck-typing 直接吃视图（与 ORM 输出一致）。"""
        common: dict[str, Any] = dict(
            department="warehouse",
            storage_location="危库1",
            material_name="乙醇",
            package_spec="160Kg/桶",
            quantity=Decimal("10"),
            unit="kg",
            total_quantity_t=Decimal("0.5"),
            max_limit=Decimal("0.4"),
            max_limit_unit="T",
            hazard_classes=["flammable"],
            category="溶剂",
        )
        orm_row = ChemicalInventoryRecord(**common)
        view = InventoryView(id="recT", feishu_record_id="recT", **common)

        alerts_orm = ChemicalRiskRuleEngine().scan([orm_row])
        alerts_view = ChemicalRiskRuleEngine().scan([view])
        assert [(a.alert_type, a.description) for a in alerts_orm] == [
            (a.alert_type, a.description) for a in alerts_view
        ]
        assert [a.alert_type for a in alerts_view] == ["over_limit", "unit_anomaly"]

    def test_handler_reexports_are_same_objects(self) -> None:
        """handler re-export 与抽纯后的 enum_maps 是同一对象（既有引用方零改动）。"""
        from app.modules.safety.feishu import chemical_inventory_bitable_handler as h

        assert getattr(h, "_DEPT_ENUM_TO_LABEL") is _DEPT_ENUM_TO_LABEL
        assert getattr(h, "_UNIT_ENUM_TO_LABEL") is _UNIT_ENUM_TO_LABEL
        assert getattr(h, "_map_inventory_fields") is _map_inventory_fields
        assert callable(getattr(h, "_text"))


class TestSortLikeInventory:
    def _view(self, vid: str, dept: str, name: str) -> InventoryView:
        return InventoryView(id=vid, feishu_record_id=vid, department=dept, material_name=name)

    def test_matches_repo_ordering_contract(self) -> None:
        """镜像 list_inventory_records ORDER BY department, material_name。"""
        b_m = self._view("bm", "extraction_1", "甲醇")
        a_z = self._view("az", "warehouse", "乙醇")
        a_b = self._view("ab", "warehouse", "丙酮")
        assert sort_like_inventory([b_m, a_z, a_b]) == [b_m, a_b, a_z]

    def test_stable_within_tie(self) -> None:
        """同键组内保持输入顺序（Bitable 无次级时间戳，稳定排序即可）。"""
        v1 = self._view("v1", "qc", "氯化钠")
        v2 = self._view("v2", "qc", "氯化钠")
        assert sort_like_inventory([v2, v1]) == [v2, v1]

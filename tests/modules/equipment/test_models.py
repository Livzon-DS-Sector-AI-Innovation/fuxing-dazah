"""Tests for equipment ORM models."""

import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Index

from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    Location,
)


class TestEquipmentCategoryModel:
    """Tests for EquipmentCategory model."""

    def test_instantiation(self) -> None:
        """Model can be instantiated with required fields."""
        cat = EquipmentCategory(
            name="反应釜",
            code="REACTOR",
        )
        assert cat.name == "反应釜"
        assert cat.code == "REACTOR"
        assert cat.parent_id is None
        assert cat.description is None

    def test_instantiation_with_optional_fields(self) -> None:
        """Model accepts optional fields."""
        cat = EquipmentCategory(
            name="反应釜",
            code="REACTOR",
            description="用于化学反应的设备",
        )
        assert cat.description == "用于化学反应的设备"

    def test_parent_child_linking(self) -> None:
        """Parent and child categories can be linked via relationship attributes."""
        parent = EquipmentCategory(name="通用设备", code="GENERAL")
        child = EquipmentCategory(name="反应釜", code="REACTOR")

        child.parent = parent
        assert child.parent is parent
        assert child in parent.children

    def test_partial_unique_index_excludes_deleted(self) -> None:
        """软删除安全的部分唯一索引：仅对未删除记录约束 (code, department_id)。"""
        index = next(
            c
            for c in EquipmentCategory.__table_args__
            if isinstance(c, Index)
            and c.name == "uq_equipment_categories_code_dept"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "code" in col_names
        assert "department_id" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_schema_is_equipment(self) -> None:
        """Table belongs to the equipment schema."""
        assert EquipmentCategory.__table_args__[-1]["schema"] == "equipment"


class TestLocationModel:
    """Tests for Location model."""

    def test_instantiation(self) -> None:
        """Model can be instantiated with required fields."""
        loc = Location(name="一号车间", code="WORKSHOP-01")
        assert loc.name == "一号车间"
        assert loc.code == "WORKSHOP-01"
        assert loc.parent_id is None

    def test_parent_child_linking(self) -> None:
        """Parent and child locations can be linked via relationship attributes."""
        parent = Location(name="工厂", code="FACTORY")
        child = Location(name="一号车间", code="WORKSHOP-01")

        child.parent = parent
        assert child.parent is parent
        assert child in parent.children

    def test_partial_unique_index_excludes_deleted(self) -> None:
        """软删除安全的部分唯一索引：仅对未删除记录约束 (code, department_id)。"""
        index = next(
            c
            for c in Location.__table_args__
            if isinstance(c, Index) and c.name == "uq_locations_code_dept"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "code" in col_names
        assert "department_id" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_schema_is_equipment(self) -> None:
        """位置表属于 equipment schema。"""
        assert Location.__table_args__[-1]["schema"] == "equipment"


class TestEquipmentModel:
    """Tests for Equipment model."""

    def _make_location(self) -> Location:
        return Location(name="一号车间", code="WORKSHOP-01")

    def test_instantiation(self) -> None:
        """Model can be instantiated with required fields."""
        equip = Equipment(
            equipment_no="EQ-001",
            name="500L反应釜",
            location_id=uuid.uuid4(),
            status="完好",
        )
        assert equip.equipment_no == "EQ-001"
        assert equip.name == "500L反应釜"
        assert equip.status == "完好"

    def test_date_fields_accept_date_objects(self) -> None:
        """production_date and commissioning_date accept datetime.date values."""
        equip = Equipment(
            equipment_no="EQ-002",
            name="干燥机",
            location_id=uuid.uuid4(),
            production_date=date(2024, 1, 15),
            commissioning_date=date(2024, 3, 1),
        )
        assert equip.production_date == date(2024, 1, 15)
        assert equip.commissioning_date == date(2024, 3, 1)

    def test_date_fields_accept_none(self) -> None:
        """production_date and commissioning_date default to None."""
        equip = Equipment(
            equipment_no="EQ-003",
            name="离心机",
            location_id=uuid.uuid4(),
        )
        assert equip.production_date is None
        assert equip.commissioning_date is None

    def test_partial_unique_index_excludes_deleted(self) -> None:
        """软删除安全的部分唯一索引：仅对未删除记录约束 equipment_no。"""
        index = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, Index) and c.name == "uq_equipments_equipment_no"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "equipment_no" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_status_check_constraint_exists(self) -> None:
        """CheckConstraint validates status values."""
        constraint = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, CheckConstraint) and c.name == "ck_equipments_status"
        )
        assert "完好" in constraint.sqltext.text
        assert "备用" in constraint.sqltext.text
        assert "故障待检" in constraint.sqltext.text
        assert "维修中" in constraint.sqltext.text
        assert "报废" in constraint.sqltext.text

    def test_running_status_check_constraint_exists(self) -> None:
        """CheckConstraint 限定 running_status 取值为 开机/停机。"""
        constraint = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, CheckConstraint)
            and c.name == "ck_equipments_running_status"
        )
        assert "开机" in constraint.sqltext.text
        assert "停机" in constraint.sqltext.text

    def test_importance_check_constraint_exists(self) -> None:
        """CheckConstraint 限定 importance 取值为 高/中/低。"""
        constraint = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, CheckConstraint) and c.name == "ck_equipments_importance"
        )
        assert "高" in constraint.sqltext.text
        assert "中" in constraint.sqltext.text
        assert "低" in constraint.sqltext.text

    def test_schema_is_equipment(self) -> None:
        """设备主表属于 equipment schema。"""
        assert Equipment.__table_args__[-1]["schema"] == "equipment"

    def test_relationships(self) -> None:
        """Equipment exposes location and category_links relationships."""
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-004",
            name="离心机",
            location_id=uuid.uuid4(),
        )
        equip.location = loc
        assert equip.location is loc

        # 分类通过关联表 EquipmentCategoryLink 建立多对多关系
        cat = EquipmentCategory(name="反应釜", code="REACTOR")
        link = EquipmentCategoryLink(
            equipment_id=uuid.uuid4(),
            category_id=uuid.uuid4(),
        )
        link.category = cat
        equip.category_links.append(link)
        assert link in equip.category_links
        assert equip.category_links[0].category is cat

    def test_optional_fields_default_to_none(self) -> None:
        """Optional fields default to None when not provided."""
        equip = Equipment(
            equipment_no="EQ-005",
            name="测试设备",
            location_id=uuid.uuid4(),
        )
        assert equip.model is None
        assert equip.specification is None
        assert equip.manufacturer is None
        assert equip.supplier is None
        assert equip.description is None
        assert equip.warranty_expire_date is None
        assert equip.asset_value is None
        assert equip.depreciation_years is None
        assert equip.technical_params is None

    def test_new_fields_default_to_none(self) -> None:
        """新字段默认为 None"""
        equip = Equipment(
            equipment_no="EQ-NEW-001",
            name="测试设备",
            location_id=uuid.uuid4(),
        )
        assert equip.warranty_expire_date is None
        assert equip.asset_value is None
        assert equip.depreciation_years is None
        assert equip.technical_params is None

    def test_new_fields_accept_values(self) -> None:
        """新字段可以赋值"""
        equip = Equipment(
            equipment_no="EQ-NEW-002",
            name="测试设备",
            location_id=uuid.uuid4(),
            warranty_expire_date=date(2027, 12, 31),
            asset_value=150000.00,
            depreciation_years=10,
            technical_params={"power": "380V", "capacity": "500L"},
        )
        assert equip.warranty_expire_date == date(2027, 12, 31)
        assert equip.asset_value == 150000.00
        assert equip.depreciation_years == 10
        assert equip.technical_params == {"power": "380V", "capacity": "500L"}


class TestEquipmentCategoryLinkModel:
    """Tests for EquipmentCategoryLink join model."""

    def test_partial_unique_index_excludes_deleted(self) -> None:
        """软删除安全的部分唯一索引：仅对未删除记录约束 (equipment_id, category_id)。"""
        index = next(
            c
            for c in EquipmentCategoryLink.__table_args__
            if isinstance(c, Index) and c.name == "uq_equipment_category_links"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "equipment_id" in col_names
        assert "category_id" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_schema_is_equipment(self) -> None:
        """关联表属于 equipment schema。"""
        assert EquipmentCategoryLink.__table_args__[-1]["schema"] == "equipment"

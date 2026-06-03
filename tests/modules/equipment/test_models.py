"""Tests for equipment ORM models."""

from datetime import date

from sqlalchemy import CheckConstraint, UniqueConstraint

from app.modules.equipment.models import Equipment, EquipmentCategory, Location


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

    def test_unique_constraint_includes_is_deleted(self) -> None:
        """Unique constraint on code includes is_deleted column."""
        constraint = next(
            c
            for c in EquipmentCategory.__table_args__
            if isinstance(c, UniqueConstraint)
            and c.name == "uq_equipment_categories_code"
        )
        col_names = {col.name for col in constraint.columns}
        assert "code" in col_names
        assert "is_deleted" in col_names

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

    def test_unique_constraint_includes_is_deleted(self) -> None:
        """Unique constraint on code includes is_deleted column."""
        constraint = next(
            c
            for c in Location.__table_args__
            if isinstance(c, UniqueConstraint) and c.name == "uq_locations_code"
        )
        col_names = {col.name for col in constraint.columns}
        assert "code" in col_names
        assert "is_deleted" in col_names


class TestEquipmentModel:
    """Tests for Equipment model."""

    def _make_category(self) -> EquipmentCategory:
        return EquipmentCategory(name="反应釜", code="REACTOR")

    def _make_location(self) -> Location:
        return Location(name="一号车间", code="WORKSHOP-01")

    def test_instantiation(self) -> None:
        """Model can be instantiated with required fields."""
        cat = self._make_category()
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-001",
            name="500L反应釜",
            category_id=cat.id,
            location_id=loc.id,
            status="在用",
        )
        assert equip.equipment_no == "EQ-001"
        assert equip.name == "500L反应釜"
        assert equip.status == "在用"

    def test_date_fields_accept_date_objects(self) -> None:
        """production_date and commissioning_date accept datetime.date values."""
        cat = self._make_category()
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-002",
            name="干燥机",
            category_id=cat.id,
            location_id=loc.id,
            production_date=date(2024, 1, 15),
            commissioning_date=date(2024, 3, 1),
        )
        assert equip.production_date == date(2024, 1, 15)
        assert equip.commissioning_date == date(2024, 3, 1)

    def test_date_fields_accept_none(self) -> None:
        """production_date and commissioning_date default to None."""
        cat = self._make_category()
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-003",
            name="离心机",
            category_id=cat.id,
            location_id=loc.id,
        )
        assert equip.production_date is None
        assert equip.commissioning_date is None

    def test_unique_constraint_includes_is_deleted(self) -> None:
        """Unique constraint on equipment_no includes is_deleted column."""
        constraint = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, UniqueConstraint)
            and c.name == "uq_equipments_equipment_no"
        )
        col_names = {col.name for col in constraint.columns}
        assert "equipment_no" in col_names
        assert "is_deleted" in col_names

    def test_status_check_constraint_exists(self) -> None:
        """CheckConstraint validates status values."""
        constraint = next(
            c
            for c in Equipment.__table_args__
            if isinstance(c, CheckConstraint) and c.name == "ck_equipments_status"
        )
        assert "在用" in constraint.sqltext.text
        assert "备用" in constraint.sqltext.text
        assert "维修中" in constraint.sqltext.text
        assert "停用" in constraint.sqltext.text
        assert "报废" in constraint.sqltext.text

    def test_relationships(self) -> None:
        """Equipment has category and location relationships."""
        cat = self._make_category()
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-004",
            name="离心机",
            category_id=cat.id,
            location_id=loc.id,
        )
        equip.category = cat
        equip.location = loc
        assert equip.category is cat
        assert equip.location is loc

    def test_optional_fields_default_to_none(self) -> None:
        """Optional fields default to None when not provided."""
        cat = self._make_category()
        loc = self._make_location()
        equip = Equipment(
            equipment_no="EQ-005",
            name="测试设备",
            category_id=cat.id,
            location_id=loc.id,
        )
        assert equip.model is None
        assert equip.specification is None
        assert equip.manufacturer is None
        assert equip.supplier is None
        assert equip.description is None

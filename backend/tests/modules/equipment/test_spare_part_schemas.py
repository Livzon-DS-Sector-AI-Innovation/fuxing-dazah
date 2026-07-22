"""备件模块 Pydantic Schema 验证测试。

覆盖所有备件相关 Schema 的字段校验、默认值、类型约束。
不涉及数据库操作，纯 Pydantic 模型层测试。
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.equipment.schemas.spare_part import (
    EquipmentSparePartCreate,
    EquipmentSparePartResponse,
    SparePartCreate,
    SparePartResponse,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockResponse,
    StockWarningResponse,
)


class TestSparePartCreate:
    """SparePartCreate 创建备件请求 Schema 测试。"""

    def test_valid_with_required_fields(self) -> None:
        """传入必填字段 code/name/unit 时校验通过。"""
        data = SparePartCreate(code="SP-001", name="密封圈", unit="个")
        assert data.code == "SP-001"
        assert data.name == "密封圈"
        assert data.unit == "个"

    def test_valid_with_all_fields(self) -> None:
        """传入所有字段时校验通过。"""
        dept_id = uuid.uuid4()
        data = SparePartCreate(
            code="SP-002",
            name="轴承",
            specification="6205-2RS",
            unit="个",
            category="机械类",
            default_supplier="某轴承厂",
            unit_price=25.50,
            is_active=True,
            department_id=dept_id,
        )
        assert data.specification == "6205-2RS"
        assert data.unit_price == 25.50
        assert data.department_id == dept_id

    def test_defaults(self) -> None:
        """可选字段使用正确的默认值。"""
        data = SparePartCreate(code="SP-003", name="滤芯", unit="根")
        assert data.specification is None
        assert data.category is None
        assert data.default_supplier is None
        assert data.unit_price is None
        assert data.is_active is True
        assert data.department_id is None

    def test_code_required(self) -> None:
        """缺少 code 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            SparePartCreate(name="密封圈", unit="个")  # type: ignore[call-arg]

    def test_name_required(self) -> None:
        """缺少 name 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            SparePartCreate(code="SP-001", unit="个")  # type: ignore[call-arg]

    def test_unit_required(self) -> None:
        """缺少 unit 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            SparePartCreate(code="SP-001", name="密封圈")  # type: ignore[call-arg]

    def test_code_max_length_50(self) -> None:
        """code 字段最大长度为 50。"""
        data = SparePartCreate(code="A" * 50, name="密封圈", unit="个")
        assert len(data.code) == 50

        with pytest.raises(ValidationError):
            SparePartCreate(code="A" * 51, name="密封圈", unit="个")

    def test_code_min_length_1(self) -> None:
        """code 字段最小长度为 1，空字符串不通过。"""
        with pytest.raises(ValidationError):
            SparePartCreate(code="", name="密封圈", unit="个")

    def test_name_max_length_200(self) -> None:
        """name 字段最大长度为 200。"""
        data = SparePartCreate(code="SP", name="A" * 200, unit="个")
        assert len(data.name) == 200

        with pytest.raises(ValidationError):
            SparePartCreate(code="SP", name="A" * 201, unit="个")

    def test_unit_max_length_20(self) -> None:
        """unit 字段最大长度为 20。"""
        data = SparePartCreate(code="SP", name="密封圈", unit="A" * 20)
        assert len(data.unit) == 20

        with pytest.raises(ValidationError):
            SparePartCreate(code="SP", name="密封圈", unit="A" * 21)

    def test_specification_max_length_200(self) -> None:
        """specification 字段最大长度为 200。"""
        with pytest.raises(ValidationError):
            SparePartCreate(
                code="SP", name="密封圈", unit="个",
                specification="A" * 201,
            )

    def test_category_max_length_50(self) -> None:
        """category 字段最大长度为 50。"""
        with pytest.raises(ValidationError):
            SparePartCreate(
                code="SP", name="密封圈", unit="个",
                category="A" * 51,
            )

    def test_default_supplier_max_length_200(self) -> None:
        """default_supplier 字段最大长度为 200。"""
        with pytest.raises(ValidationError):
            SparePartCreate(
                code="SP", name="密封圈", unit="个",
                default_supplier="A" * 201,
            )

    def test_unit_price_ge_0(self) -> None:
        """unit_price 必须 >= 0。"""
        data = SparePartCreate(
            code="SP", name="密封圈", unit="个", unit_price=0
        )
        assert data.unit_price == 0

        with pytest.raises(ValidationError):
            SparePartCreate(
                code="SP", name="密封圈", unit="个", unit_price=-0.01
            )


class TestSparePartUpdate:
    """SparePartUpdate 更新备件请求 Schema 测试。"""

    def test_all_fields_optional(self) -> None:
        """所有字段均为可选，空对象可校验通过。"""
        data = SparePartUpdate()
        assert data.code is None
        assert data.name is None
        assert data.unit is None

    def test_partial_update_single_field(self) -> None:
        """支持单字段部分更新。"""
        data = SparePartUpdate(name="新名称")
        assert data.name == "新名称"
        assert data.code is None

    def test_code_min_length_validation(self) -> None:
        """更新时 code 同样有 min_length=1 约束。"""
        with pytest.raises(ValidationError):
            SparePartUpdate(code="")

    def test_unit_price_ge_0_in_update(self) -> None:
        """更新时 unit_price 同样有 ge=0 约束。"""
        with pytest.raises(ValidationError):
            SparePartUpdate(unit_price=-1)


class TestSparePartResponse:
    """SparePartResponse 备件响应 Schema 测试。"""

    def test_from_attributes_config(self) -> None:
        """Schema 配置了 from_attributes=True，可从 ORM 对象构造。"""
        assert SparePartResponse.model_config.get("from_attributes") is True

    def test_required_fields_present(self) -> None:
        """响应包含所有必要字段类型标注。"""
        fields = SparePartResponse.model_fields
        assert "id" in fields
        assert "code" in fields
        assert "name" in fields
        assert "unit" in fields
        assert "is_active" in fields
        assert "current_qty" in fields
        assert "min_qty" in fields
        assert "equipment_count" in fields
        assert "created_at" in fields
        assert "updated_at" in fields


class TestStockInboundRequest:
    """StockInboundRequest 入库请求 Schema 测试。"""

    def test_valid_minimal(self) -> None:
        """最少字段（只传入 quantity）校验通过。"""
        data = StockInboundRequest(quantity=10)
        assert data.quantity == 10
        assert data.warehouse_location is None
        assert data.remark is None

    def test_valid_with_all_fields(self) -> None:
        """传入所有字段校验通过。"""
        data = StockInboundRequest(
            quantity=100, warehouse_location="A-01", remark="采购入库"
        )
        assert data.quantity == 100
        assert data.warehouse_location == "A-01"
        assert data.remark == "采购入库"

    def test_quantity_required(self) -> None:
        """缺少 quantity 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            StockInboundRequest()  # type: ignore[call-arg]

    def test_quantity_must_be_ge_1(self) -> None:
        """quantity 必须 >= 1（入库数量至少为 1）。"""
        with pytest.raises(ValidationError):
            StockInboundRequest(quantity=0)

        with pytest.raises(ValidationError):
            StockInboundRequest(quantity=-1)


class TestStockAdjustRequest:
    """StockAdjustRequest 盘点调整请求 Schema 测试。"""

    def test_valid_minimal(self) -> None:
        """最少字段（只传入 new_qty）校验通过。"""
        data = StockAdjustRequest(new_qty=50)
        assert data.new_qty == 50
        assert data.remark is None

    def test_valid_with_remark(self) -> None:
        """传入备注时校验通过。"""
        data = StockAdjustRequest(new_qty=30, remark="月度盘点调整")
        assert data.new_qty == 30
        assert data.remark == "月度盘点调整"

    def test_new_qty_required(self) -> None:
        """缺少 new_qty 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            StockAdjustRequest()  # type: ignore[call-arg]

    def test_new_qty_must_be_ge_0(self) -> None:
        """new_qty 必须 >= 0（库存不能为负）。"""
        data = StockAdjustRequest(new_qty=0)
        assert data.new_qty == 0

        with pytest.raises(ValidationError):
            StockAdjustRequest(new_qty=-1)


class TestStockResponse:
    """StockResponse 库存响应 Schema 测试。"""

    def test_from_attributes_config(self) -> None:
        """Schema 配置了 from_attributes=True。"""
        assert StockResponse.model_config.get("from_attributes") is True

    def test_required_fields_present(self) -> None:
        """响应包含库存核心字段。"""
        fields = StockResponse.model_fields
        assert "id" in fields
        assert "spare_part_id" in fields
        assert "warehouse_location" in fields
        assert "current_qty" in fields
        assert "safety_qty" in fields
        assert "min_order_qty" in fields


class TestStockWarningResponse:
    """StockWarningResponse 库存预警响应 Schema 测试。"""

    def test_required_fields_present(self) -> None:
        """预警响应包含备件信息、库存信息和短缺量。"""
        fields = StockWarningResponse.model_fields
        assert "spare_part" in fields
        assert "stock" in fields
        assert "shortage" in fields


class TestEquipmentSparePartCreate:
    """EquipmentSparePartCreate 设备-备件关联请求 Schema 测试。"""

    def test_valid_minimal(self) -> None:
        """只传入 equipment_id 时使用默认 quantity=1。"""
        eq_id = uuid.uuid4()
        data = EquipmentSparePartCreate(equipment_id=eq_id)
        assert data.equipment_id == eq_id
        assert data.quantity == 1

    def test_valid_with_quantity(self) -> None:
        """传入自定义数量校验通过。"""
        data = EquipmentSparePartCreate(
            equipment_id=uuid.uuid4(), quantity=5
        )
        assert data.quantity == 5

    def test_equipment_id_required(self) -> None:
        """缺少 equipment_id 字段时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            EquipmentSparePartCreate()  # type: ignore[call-arg]

    def test_quantity_must_be_ge_1(self) -> None:
        """quantity 必须 >= 1。"""
        with pytest.raises(ValidationError):
            EquipmentSparePartCreate(
                equipment_id=uuid.uuid4(), quantity=0
            )

        with pytest.raises(ValidationError):
            EquipmentSparePartCreate(
                equipment_id=uuid.uuid4(), quantity=-1
            )


class TestEquipmentSparePartResponse:
    """EquipmentSparePartResponse 设备-备件关联响应 Schema 测试。"""

    def test_from_attributes_config(self) -> None:
        """Schema 配置了 from_attributes=True。"""
        assert (
            EquipmentSparePartResponse.model_config.get("from_attributes")
            is True
        )

    def test_required_fields_present(self) -> None:
        """响应包含关联核心字段。"""
        fields = EquipmentSparePartResponse.model_fields
        assert "id" in fields
        assert "equipment_id" in fields
        assert "spare_part_id" in fields
        assert "quantity" in fields

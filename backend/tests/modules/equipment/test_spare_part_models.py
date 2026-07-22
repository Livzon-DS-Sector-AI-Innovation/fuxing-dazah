"""备件模块 ORM 模型测试。

覆盖 SparePart、EquipmentSparePart、SparePartStock、SparePartTransaction
四个模型的：实例化、字段默认值、索引定义、约束定义、schema 归属。
"""

import uuid

from sqlalchemy import CheckConstraint, Index

from app.modules.equipment.models.spare_part import (
    EquipmentSparePart,
    SparePart,
    SparePartStock,
    SparePartTransaction,
)


class TestSparePartModel:
    """SparePart 备件主数据表模型测试。"""

    def test_instantiation_with_required_fields(self) -> None:
        """使用必填字段 code/name/unit 实例化模型。"""
        sp = SparePart(code="SP-001", name="密封圈", unit="个")
        assert sp.code == "SP-001"
        assert sp.name == "密封圈"
        assert sp.unit == "个"

    def test_instantiation_with_all_fields(self) -> None:
        """使用所有字段（含可选字段）实例化模型。"""
        dept_id = uuid.uuid4()
        sp = SparePart(
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
        assert sp.specification == "6205-2RS"
        assert sp.category == "机械类"
        assert sp.default_supplier == "某轴承厂"
        assert sp.unit_price == 25.50
        assert sp.is_active is True
        assert sp.department_id == dept_id

    def test_optional_fields_default_to_none(self) -> None:
        """可选字段在未传入时默认为 None。"""
        sp = SparePart(code="SP-003", name="滤芯", unit="根")
        assert sp.specification is None
        assert sp.category is None
        assert sp.default_supplier is None
        assert sp.unit_price is None
        assert sp.department_id is None

    def test_is_active_server_default_is_true(self) -> None:
        """is_active 字段 server_default 为 'true'（DB 层默认启用）。"""
        col = SparePart.__table__.c.is_active
        assert col.server_default is not None
        assert "true" in str(col.server_default.arg)

    def test_code_partial_unique_index(self) -> None:
        """code 字段有软删除安全的部分唯一索引 uq_spare_parts_code。"""
        index = next(
            c
            for c in SparePart.__table_args__
            if isinstance(c, Index) and c.name == "uq_spare_parts_code"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "code" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_schema_is_equipment(self) -> None:
        """备件主表属于 equipment schema。"""
        assert SparePart.__table_args__[-1]["schema"] == "equipment"


class TestEquipmentSparePartModel:
    """EquipmentSparePart 设备-备件关联表模型测试。"""

    def test_instantiation(self) -> None:
        """使用必填字段实例化关联模型。"""
        eq_id = uuid.uuid4()
        sp_id = uuid.uuid4()
        link = EquipmentSparePart(
            equipment_id=eq_id, spare_part_id=sp_id, quantity=3
        )
        assert link.equipment_id == eq_id
        assert link.spare_part_id == sp_id
        assert link.quantity == 3

    def test_quantity_default_is_one(self) -> None:
        """quantity 字段 Python 端 default=1。"""
        col = EquipmentSparePart.__table__.c.quantity
        assert col.default is not None
        assert col.default.arg == 1

    def test_partial_unique_index(self) -> None:
        """(equipment_id, spare_part_id) 有软删除安全的部分唯一索引。"""
        index = next(
            c
            for c in EquipmentSparePart.__table_args__
            if isinstance(c, Index)
            and c.name == "uq_equipment_spare_parts_eq_sp"
        )
        assert index.unique is True
        col_names = {col.name for col in index.columns}
        assert "equipment_id" in col_names
        assert "spare_part_id" in col_names
        where = index.dialect_kwargs.get("postgresql_where")
        assert where is not None
        assert "is_deleted" in where.text

    def test_schema_is_equipment(self) -> None:
        """关联表属于 equipment schema。"""
        assert EquipmentSparePart.__table_args__[-1]["schema"] == "equipment"

    def test_relationships_exist(self) -> None:
        """模型定义了 equipment 和 spare_part 两个 relationship。"""
        assert hasattr(EquipmentSparePart, "equipment")
        assert hasattr(EquipmentSparePart, "spare_part")


class TestSparePartStockModel:
    """SparePartStock 备件库存表模型测试。"""

    def test_instantiation_with_required_fields(self) -> None:
        """使用必填字段 spare_part_id 实例化模型。"""
        sp_id = uuid.uuid4()
        stock = SparePartStock(spare_part_id=sp_id)
        assert stock.spare_part_id == sp_id

    def test_instantiation_with_all_fields(self) -> None:
        """使用所有字段实例化库存模型。"""
        sp_id = uuid.uuid4()
        stock = SparePartStock(
            spare_part_id=sp_id,
            warehouse_location="A-01-03",
            current_qty=100,
            safety_qty=20,
            min_order_qty=10,
        )
        assert stock.warehouse_location == "A-01-03"
        assert stock.current_qty == 100
        assert stock.safety_qty == 20
        assert stock.min_order_qty == 10

    def test_field_server_defaults(self) -> None:
        """库存数值字段有正确的 server_default：current_qty=0, safety_qty=0, min_order_qty=1。"""
        assert SparePartStock.__table__.c.current_qty.server_default is not None
        assert "0" in str(SparePartStock.__table__.c.current_qty.server_default.arg)
        assert SparePartStock.__table__.c.safety_qty.server_default is not None
        assert "0" in str(SparePartStock.__table__.c.safety_qty.server_default.arg)
        assert SparePartStock.__table__.c.min_order_qty.server_default is not None
        assert "1" in str(SparePartStock.__table__.c.min_order_qty.server_default.arg)

    def test_warehouse_location_defaults_to_none(self) -> None:
        """库位字段默认为 None。"""
        stock = SparePartStock(spare_part_id=uuid.uuid4())
        assert stock.warehouse_location is None

    def test_spare_part_id_is_unique(self) -> None:
        """spare_part_id 字段有 unique=True 约束（一个备件一条库存）。"""
        col = SparePartStock.__table__.c.spare_part_id
        assert col.unique is True

    def test_schema_is_equipment(self) -> None:
        """库存表属于 equipment schema。"""
        assert SparePartStock.__table_args__[-1]["schema"] == "equipment"

    def test_relationship_exists(self) -> None:
        """模型定义了 spare_part relationship。"""
        assert hasattr(SparePartStock, "spare_part")


class TestSparePartTransactionModel:
    """SparePartTransaction 备件库存流水表模型测试。"""

    def test_instantiation(self) -> None:
        """使用必填字段实例化流水模型。"""
        sp_id = uuid.uuid4()
        txn = SparePartTransaction(
            spare_part_id=sp_id,
            transaction_type="入库",
            quantity=50,
        )
        assert txn.spare_part_id == sp_id
        assert txn.transaction_type == "入库"
        assert txn.quantity == 50

    def test_instantiation_with_outbound(self) -> None:
        """出库类型流水使用负数量。"""
        txn = SparePartTransaction(
            spare_part_id=uuid.uuid4(),
            transaction_type="出库",
            quantity=-5,
            work_order_id=uuid.uuid4(),
            remark="维修消耗",
        )
        assert txn.transaction_type == "出库"
        assert txn.quantity == -5
        assert txn.remark == "维修消耗"

    def test_instantiation_with_adjustment(self) -> None:
        """盘点调整类型流水。"""
        txn = SparePartTransaction(
            spare_part_id=uuid.uuid4(),
            transaction_type="盘点调整",
            quantity=10,
            remark="月度盘点",
        )
        assert txn.transaction_type == "盘点调整"
        assert txn.remark == "月度盘点"

    def test_optional_work_order_id_defaults_to_none(self) -> None:
        """work_order_id 字段默认为 None。"""
        txn = SparePartTransaction(
            spare_part_id=uuid.uuid4(),
            transaction_type="入库",
            quantity=10,
        )
        assert txn.work_order_id is None

    def test_optional_remark_defaults_to_none(self) -> None:
        """remark 字段默认为 None。"""
        txn = SparePartTransaction(
            spare_part_id=uuid.uuid4(),
            transaction_type="入库",
            quantity=10,
        )
        assert txn.remark is None

    def test_transaction_type_check_constraint(self) -> None:
        """transaction_type 有 CheckConstraint 限定为 入库/出库/盘点调整。"""
        constraint = next(
            c
            for c in SparePartTransaction.__table_args__
            if isinstance(c, CheckConstraint)
            and c.name == "ck_spare_part_transactions_type"
        )
        text_content = constraint.sqltext.text
        assert "入库" in text_content
        assert "出库" in text_content
        assert "盘点调整" in text_content

    def test_schema_is_equipment(self) -> None:
        """流水表属于 equipment schema。"""
        assert SparePartTransaction.__table_args__[-1]["schema"] == "equipment"

    def test_relationships_exist(self) -> None:
        """模型定义了 spare_part 和 work_order 两个 relationship。"""
        assert hasattr(SparePartTransaction, "spare_part")
        assert hasattr(SparePartTransaction, "work_order")

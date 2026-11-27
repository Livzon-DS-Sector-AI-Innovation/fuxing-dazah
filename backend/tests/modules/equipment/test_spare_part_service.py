"""备件模块 Service 层业务逻辑测试。

使用 mock repository 验证 service 层的业务流程、校验规则、
异常处理。不直接操作数据库，聚焦业务逻辑正确性。
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    AppException,
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.spare_part import (
    SparePart,
    SparePartStock,
    SparePartTransaction,
)
from app.modules.equipment.schemas.spare_part import (
    SparePartCreate,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockOutboundRequest,
)
from app.modules.equipment.service.spare_part import (
    adjust_stock,
    create_spare_part,
    delete_spare_part,
    get_spare_part_by_id,
    get_spare_parts,
    get_stock_by_spare_part_id,
    get_stock_warnings,
    import_spare_parts_from_excel,
    inbound_stock,
    outbound_stock,
    update_spare_part,
    update_stock_settings,
)


def _make_spare_part(
    code: str = "SP-001",
    name: str = "密封圈",
    unit: str = "个",
    department_id: uuid.UUID | None = None,
) -> SparePart:
    """创建一个测试用 SparePart ORM 对象。"""
    sp = SparePart(
        id=uuid.uuid4(),
        code=code,
        name=name,
        unit=unit,
        department_id=department_id,
        is_active=True,
    )
    return sp


def _make_stock(
    spare_part_id: uuid.UUID,
    current_qty: int = 50,
    safety_qty: int = 10,
    warehouse_location: str | None = None,
) -> SparePartStock:
    """创建一个测试用 SparePartStock ORM 对象。"""
    return SparePartStock(
        id=uuid.uuid4(),
        spare_part_id=spare_part_id,
        current_qty=current_qty,
        safety_qty=safety_qty,
        min_order_qty=5,
        warehouse_location=warehouse_location,
    )


def _make_ctx(data_scope: str = "all") -> EquipmentAccessContext:
    """创建一个无限制（超管）的访问上下文（带可见部门，满足建档归属校验）。"""
    from app.platform.identity.models import User

    user = User(
        id=uuid.uuid4(),
        name="测试用户",
        employee_no="EMP-TEST",
    )
    return EquipmentAccessContext(
        user=user,
        data_scope=data_scope,
        visible_department_ids=[uuid.uuid4()],
    )


# ==================== create_spare_part ====================


class TestCreateSparePart:
    """create_spare_part 创建备件业务逻辑测试。"""

    @pytest.fixture
    def create_data(self) -> SparePartCreate:
        return SparePartCreate(code="SP-001", name="密封圈", unit="个")

    @pytest.fixture
    def ctx(self) -> EquipmentAccessContext:
        return _make_ctx()

    async def test_creates_spare_part_and_stock(
        self, create_data: SparePartCreate, ctx: EquipmentAccessContext
    ) -> None:
        """创建备件成功后，同时自动创建一条库存记录。"""
        mock_sp = _make_spare_part()
        mock_stock = _make_stock(mock_sp.id)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_spare_part",
                new_callable=AsyncMock,
                return_value=mock_sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_stock",
                new_callable=AsyncMock,
                return_value=mock_stock,
            ),
        ):
            result = await create_spare_part(
                db=AsyncMock(), data=create_data, ctx=ctx,
            )
            assert result is mock_sp

    async def test_raises_duplicate_on_existing_code(
        self, create_data: SparePartCreate, ctx: EquipmentAccessContext
    ) -> None:
        """备件编码已存在时抛出 DuplicateException。"""
        with patch(
            "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with pytest.raises(DuplicateException):
                await create_spare_part(
                    db=AsyncMock(), data=create_data, ctx=ctx,
                )

    async def test_auto_sets_department_id_from_context(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """未传 department_id 时自动使用用户所在部门 ID。"""
        dept_id = uuid.uuid4()
        ctx.visible_department_ids = [dept_id]

        data = SparePartCreate(code="SP-002", name="轴承", unit="个")
        assert data.department_id is None  # 未显式指定

        mock_sp = _make_spare_part(department_id=dept_id)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_spare_part",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_stock",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = mock_sp
            await create_spare_part(db=AsyncMock(), data=data, ctx=ctx)
            # 验证 repo.create_spare_part 收到的 data 包含 department_id
            call_data = mock_create.call_args[0][1]
            assert call_data["department_id"] == dept_id

    async def test_keeps_explicit_department_id(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """用户显式指定 department_id 时不覆盖。"""
        explicit_dept = uuid.uuid4()
        ctx.visible_department_ids = [uuid.uuid4()]  # 另一个部门

        data = SparePartCreate(
            code="SP-003", name="滤芯", unit="根",
            department_id=explicit_dept,
        )

        mock_sp = _make_spare_part(department_id=explicit_dept)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_spare_part",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_stock",
                new_callable=AsyncMock,
            ),
        ):
            mock_create.return_value = mock_sp
            await create_spare_part(db=AsyncMock(), data=data, ctx=ctx)
            call_data = mock_create.call_args[0][1]
            assert call_data["department_id"] == explicit_dept

    async def test_no_department_id_when_context_has_none(
        self, create_data: SparePartCreate
    ) -> None:
        """ctx.visible_department_ids 为空且未显式指定部门时拒绝建档（防无主备件）。"""
        ctx_empty = _make_ctx()
        ctx_empty.visible_department_ids = []

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await create_spare_part(
                    db=AsyncMock(), data=create_data, ctx=ctx_empty,
                )
            assert "归属部门" in exc_info.value.message


# ==================== get_spare_part_by_id ====================


class TestGetSparePartById:
    """get_spare_part_by_id 获取单个备件逻辑测试。"""

    async def test_returns_spare_part_when_found(self) -> None:
        """备件存在时返回 ORM 对象。"""
        sp = _make_spare_part()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
            new_callable=AsyncMock,
            return_value=sp,
        ):
            result = await get_spare_part_by_id(db=AsyncMock(), spare_part_id=sp.id)
            assert result is sp

    async def test_raises_not_found_when_none(self) -> None:
        """备件不存在时抛出 NotFoundException。"""
        fake_id = uuid.uuid4()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(NotFoundException):
                await get_spare_part_by_id(db=AsyncMock(), spare_part_id=fake_id)


# ==================== get_spare_parts ====================


class TestGetSpareParts:
    """get_spare_parts 分页列表逻辑测试。"""

    async def test_returns_list_and_total(self) -> None:
        """正常返回备件列表和总数，并批量填充 department_name。"""
        sp = _make_spare_part(department_id=uuid.uuid4())

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_parts",
                new_callable=AsyncMock,
                return_value=([sp], 1),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_department_info",
                new_callable=AsyncMock,
                return_value={"name": "生产部"},
            ),
        ):
            result, total = await get_spare_parts(
                db=AsyncMock(), ctx=_make_ctx(),
            )
            assert len(result) == 1
            assert total == 1

    async def test_passes_filters_to_repo(self) -> None:
        """将 category/keyword/is_active/department_id 透传给 repository。"""
        dept_id = uuid.uuid4()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_parts",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], 0)
            await get_spare_parts(
                db=AsyncMock(),
                ctx=_make_ctx(),
                category="机械类",
                keyword="轴承",
                is_active=True,
                department_id=dept_id,
                page=2,
                page_size=10,
            )
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["category"] == "机械类"
            assert call_kwargs["keyword"] == "轴承"
            assert call_kwargs["is_active"] is True
            assert call_kwargs["department_id"] == dept_id
            assert call_kwargs["page"] == 2
            assert call_kwargs["page_size"] == 10

    async def test_batch_fills_department_name(self) -> None:
        """部门名称按去重后的 ID 集合一次批量查询填充。"""
        dept_a = uuid.uuid4()
        dept_b = uuid.uuid4()
        sp1 = _make_spare_part(code="SP-A", department_id=dept_a)
        sp2 = _make_spare_part(code="SP-B", department_id=dept_a)
        sp3 = _make_spare_part(code="SP-C", department_id=dept_b)

        async def mock_dept_names(
            db: object, dept_ids: list[uuid.UUID]
        ) -> dict[uuid.UUID, str]:
            assert set(dept_ids) == {dept_a, dept_b}
            return {dept_a: "生产部", dept_b: "质量部"}

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_parts",
                new_callable=AsyncMock,
                return_value=([sp1, sp2, sp3], 3),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_department_names_by_ids",
                new_callable=AsyncMock,
                side_effect=mock_dept_names,
            ),
        ):
            await get_spare_parts(db=AsyncMock(), ctx=_make_ctx())
            assert sp1.department_name == "生产部"
            assert sp2.department_name == "生产部"
            assert sp3.department_name == "质量部"


# ==================== update_spare_part ====================


class TestUpdateSparePart:
    """update_spare_part 更新备件业务逻辑测试。"""

    @pytest.fixture
    def ctx(self) -> EquipmentAccessContext:
        return _make_ctx()

    async def test_updates_and_returns_spare_part(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """更新成功返回更新后的备件。"""
        sp = _make_spare_part()
        update_data = SparePartUpdate(name="新名称")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_spare_part",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await update_spare_part(
                db=AsyncMock(), spare_part_id=sp.id,
                data=update_data, ctx=ctx,
            )
            assert result is sp

    async def test_raises_not_found_when_spare_part_missing(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """备件不存在时抛出 NotFoundException。"""
        fake_id = uuid.uuid4()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(NotFoundException):
                await update_spare_part(
                    db=AsyncMock(), spare_part_id=fake_id,
                    data=SparePartUpdate(name="X"), ctx=ctx,
                )

    async def test_raises_duplicate_on_code_conflict(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """更新 code 为已存在的编码时抛出 DuplicateException。"""
        sp = _make_spare_part(code="OLD")
        update_data = SparePartUpdate(code="EXISTING")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            with pytest.raises(DuplicateException):
                await update_spare_part(
                    db=AsyncMock(), spare_part_id=sp.id,
                    data=update_data, ctx=ctx,
                )

    async def test_code_check_excludes_self(
        self, ctx: EquipmentAccessContext
    ) -> None:
        """修改 code 时排除自身 ID 进行唯一性检查。"""
        sp = _make_spare_part(code="OLD")
        update_data = SparePartUpdate(code="NEW")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
            ) as mock_exists,
            patch(
                "app.modules.equipment.service.spare_part.repo.update_spare_part",
                new_callable=AsyncMock,
                return_value=sp,
            ),
        ):
            mock_exists.return_value = False
            await update_spare_part(
                db=AsyncMock(), spare_part_id=sp.id,
                data=update_data, ctx=ctx,
            )
            # 验证 exclude_id 被正确传入
            call_kwargs = mock_exists.call_args[1]
            assert call_kwargs["exclude_id"] == sp.id


# ==================== delete_spare_part ====================


class TestDeleteSparePart:
    """delete_spare_part 删除备件业务逻辑测试。"""

    async def test_deletes_and_returns_true(self) -> None:
        """库存为 0 时正常删除返回 True。"""
        sp = _make_spare_part()
        ctx = _make_ctx()

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=_make_stock(sp.id, current_qty=0),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.delete_equipment_spare_parts_by_spare_part",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.delete_spare_part",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await delete_spare_part(
                db=AsyncMock(), spare_part_id=sp.id, ctx=ctx,
            )
            assert result is True

    async def test_raises_not_found_when_missing(self) -> None:
        """备件不存在时抛出 NotFoundException。"""
        fake_id = uuid.uuid4()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(NotFoundException):
                await delete_spare_part(
                    db=AsyncMock(), spare_part_id=fake_id,
                    ctx=_make_ctx(),
                )


# ==================== get_stock_by_spare_part_id ====================


class TestGetStockBySparePartId:
    """get_stock_by_spare_part_id 获取库存逻辑测试。"""

    async def test_returns_stock_when_found(self) -> None:
        """库存记录存在时返回 ORM 对象。"""
        stock = _make_stock(uuid.uuid4())
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
            new_callable=AsyncMock,
            return_value=stock,
        ):
            result = await get_stock_by_spare_part_id(
                db=AsyncMock(), spare_part_id=stock.spare_part_id,
            )
            assert result is stock

    async def test_raises_not_found_when_none(self) -> None:
        """库存记录不存在时抛出 NotFoundException。"""
        fake_id = uuid.uuid4()
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(NotFoundException):
                await get_stock_by_spare_part_id(
                    db=AsyncMock(), spare_part_id=fake_id,
                )


# ==================== inbound_stock ====================


class TestInboundStock:
    """inbound_stock 入库业务逻辑测试。"""

    @pytest.fixture
    def sp_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.fixture
    def sp(self) -> SparePart:
        return _make_spare_part()

    async def test_increases_stock_and_creates_transaction(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """入库成功后库存增加且创建入库流水。"""
        stock = _make_stock(sp_id, current_qty=100)
        data = StockInboundRequest(quantity=50, remark="采购到货")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            result = await inbound_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            assert result is stock

            # 验证流水记录参数
            txn_data = mock_txn.call_args[0][1]
            assert txn_data["spare_part_id"] == sp_id
            assert txn_data["transaction_type"] == "入库"
            assert txn_data["quantity"] == 50
            assert txn_data["remark"] == "采购到货"

    async def test_updates_warehouse_location_when_provided(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """入库时如果传入库位，更新库存库位字段。"""
        stock = _make_stock(sp_id, warehouse_location=None)
        data = StockInboundRequest(quantity=10, warehouse_location="B-02")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ),
        ):
            await inbound_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            assert stock.warehouse_location == "B-02"

    async def test_does_not_overwrite_location_when_not_provided(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """入库时不传入库位，保留原有库位不变。"""
        stock = _make_stock(sp_id, warehouse_location="A-01")
        data = StockInboundRequest(quantity=10)  # 未传 warehouse_location

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ),
        ):
            await inbound_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            assert stock.warehouse_location == "A-01"


# ==================== outbound_stock ====================


class TestOutboundStock:
    """outbound_stock 出库业务逻辑测试。"""

    async def test_decreases_stock_and_creates_outbound_transaction(self) -> None:
        """库存充足时出库成功，库存减少并创建出库流水（备注透传）。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=50)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            result = await outbound_stock(
                db=AsyncMock(), spare_part_id=sp.id,
                data=StockOutboundRequest(quantity=5, remark="车间领用"),
            )
            assert result is stock

            txn_data = mock_txn.call_args[0][1]
            assert txn_data["transaction_type"] == "出库"
            assert txn_data["quantity"] == -5
            assert txn_data["remark"] == "车间领用"

    async def test_raises_when_stock_insufficient(self) -> None:
        """库存不足时抛出 AppException。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=10)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
        ):
            with pytest.raises(AppException) as exc:
                await outbound_stock(
                    db=AsyncMock(), spare_part_id=sp.id,
                    data=StockOutboundRequest(quantity=20),
                )
            assert "库存不足" in exc.value.message
            assert "10" in exc.value.message

    async def test_exact_qty_outbound_ok(self) -> None:
        """出库数量等于当前库存时允许（清空库存）。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=5)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ),
        ):
            result = await outbound_stock(
                db=AsyncMock(), spare_part_id=sp.id,
                data=StockOutboundRequest(quantity=5),
            )
            assert result is stock

    async def test_forbidden_when_ctx_lacks_department_ownership(self) -> None:
        """受限 ctx 对其他部门备件出库时抛 ForbiddenException。"""
        other_dept = uuid.uuid4()
        sp = _make_spare_part(department_id=other_dept)
        stock = _make_stock(sp.id, current_qty=50)

        ctx = EquipmentAccessContext(
            user=_make_ctx().user,
            data_scope="department",
            visible_department_ids=[uuid.uuid4()],
        )

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
        ):
            with pytest.raises(ForbiddenException):
                await outbound_stock(
                    db=AsyncMock(), spare_part_id=sp.id,
                    data=StockOutboundRequest(quantity=5), ctx=ctx,
                )


# ==================== adjust_stock ====================


class TestAdjustStock:
    """adjust_stock 盘点调整业务逻辑测试。"""

    @pytest.fixture
    def sp_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.fixture
    def sp(self, sp_id: uuid.UUID) -> SparePart:
        return _make_spare_part()

    async def test_increase_adjustment(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """盘点调整为更大数量时创建正差异流水。"""
        stock = _make_stock(sp_id, current_qty=50)
        data = StockAdjustRequest(new_qty=80, remark="盘盈")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            await adjust_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            txn_data = mock_txn.call_args[0][1]
            assert txn_data["transaction_type"] == "盘点调整"
            assert txn_data["quantity"] == 30  # diff = 80 - 50

    async def test_decrease_adjustment(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """盘点调整为更小数量时创建负差异流水。"""
        stock = _make_stock(sp_id, current_qty=50)
        data = StockAdjustRequest(new_qty=20, remark="盘亏")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            await adjust_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            txn_data = mock_txn.call_args[0][1]
            assert txn_data["quantity"] == -30  # diff = 20 - 50

    async def test_no_change_skips_transaction(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """盘点数量与当前库存一致时不创建流水记录。"""
        stock = _make_stock(sp_id, current_qty=50)
        data = StockAdjustRequest(new_qty=50)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
            ) as mock_update,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            stock.current_qty = 50  # reset after mock
            await adjust_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            mock_update.assert_not_called()
            mock_txn.assert_not_called()

    async def test_adjust_to_zero(
        self, sp_id: uuid.UUID, sp: SparePart
    ) -> None:
        """盘点调整到 0 是合法的。"""
        stock = _make_stock(sp_id, current_qty=10)
        data = StockAdjustRequest(new_qty=0, remark="清零")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.update_stock_qty",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            await adjust_stock(
                db=AsyncMock(), spare_part_id=sp_id, data=data,
            )
            txn_data = mock_txn.call_args[0][1]
            assert txn_data["quantity"] == -10


# ==================== get_stock_warnings ====================


class TestGetStockWarnings:
    """get_stock_warnings 库存预警业务逻辑测试。"""

    async def test_returns_warnings_with_shortage_calculation(self) -> None:
        """返回库存低于安全库存的备件列表，shortage = safety_qty - current_qty。"""
        from datetime import datetime

        now = datetime.now()
        sp = SparePart(
            id=uuid.uuid4(),
            code="SP-WARN",
            name="预警备件",
            unit="个",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        stock = SparePartStock(
            id=uuid.uuid4(),
            spare_part_id=sp.id,
            current_qty=5,
            safety_qty=20,
            min_order_qty=1,
        )

        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_warnings",
            new_callable=AsyncMock,
            return_value=[(sp, stock)],
        ):
            result = await get_stock_warnings(db=AsyncMock(), ctx=_make_ctx())
            assert len(result) == 1
            assert result[0].shortage == 15  # 20 - 5
            assert result[0].spare_part_id == sp.id
            assert result[0].code == "SP-WARN"
            assert result[0].current_qty == 5
            assert result[0].min_qty == 20

    async def test_returns_empty_list_when_no_warnings(self) -> None:
        """无预警时返回空列表。"""
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_warnings",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_stock_warnings(db=AsyncMock(), ctx=_make_ctx())
            assert result == []


# ==================== import_spare_parts_from_excel ====================


def _make_import_workbook(rows: list[list[object]]) -> bytes:
    """构造一个备件导入 xlsx：第1行表头、第2行示例、第3行起数据。"""
    import io

    import openpyxl as _openpyxl

    wb = _openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "备件管理"
    headers = [
        "备件编码 *", "备件名称 *", "规格型号", "计量单位 *",
        "备件分类", "默认供应商", "参考单价（元）", "初始库存数量", "安全库存",
    ]
    ws.append(headers)
    ws.append(["SP-001", "轴承密封圈", "Φ50×Φ34×7", "个", "机械密封", "示例供应商", "85.50", "50", "10"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestImportSparePartsFromExcel:
    """import_spare_parts_from_excel 导入业务逻辑测试（真库，随 db_session 回滚）。"""

    @pytest.fixture
    async def imp_user(self, db_session):
        """在测试库中创建真实用户（导入写 created_by 有外键约束）。"""
        from app.platform.identity.models import User

        user = User(name="导入测试用户", employee_no=f"EMP-IMP-{uuid.uuid4().hex[:8]}")
        db_session.add(user)
        await db_session.flush()
        return user

    @pytest.fixture
    def imp_ctx(self, imp_user) -> EquipmentAccessContext:
        return EquipmentAccessContext(
            user=imp_user,
            data_scope="all",
            visible_department_ids=[uuid.uuid4()],
        )

    async def test_new_code_with_quantity_creates_stock_and_transaction(
        self, db_session, imp_ctx
    ) -> None:
        """新编码带数量导入：建档、库存落数量、写初始库存入库流水。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content = _make_import_workbook([
            [code, "进口轴承", "6204-2RS", "个", "轴承类", "XX供应商", 12.5, 30, 8],
        ])

        result = await import_spare_parts_from_excel(
            db_session, content, ctx=imp_ctx
        )
        assert result.imported == 1
        assert result.skipped == 0

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == code)
        )
        spare_part = sp.scalar_one()
        assert float(spare_part.unit_price) == 12.5

        stock = await db_session.execute(
            select(SparePartStock).where(SparePartStock.spare_part_id == spare_part.id)
        )
        stock_row = stock.scalar_one()
        assert stock_row.current_qty == 30
        assert stock_row.safety_qty == 8

        txns = await db_session.execute(
            select(SparePartTransaction).where(
                SparePartTransaction.spare_part_id == spare_part.id
            )
        )
        txn_list = txns.scalars().all()
        assert len(txn_list) == 1
        assert txn_list[0].transaction_type == "入库"
        assert txn_list[0].quantity == 30
        assert txn_list[0].remark == "Excel导入初始库存"

    async def test_new_code_zero_quantity_no_transaction(self, db_session, imp_ctx) -> None:
        """新编码数量为空/0：建档库存为0，不产生流水。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content = _make_import_workbook([
            [code, "国产轴承", None, "个", None, None, None, None, None],
        ])

        result = await import_spare_parts_from_excel(
            db_session, content, ctx=imp_ctx
        )
        assert result.imported == 1

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == code)
        )
        spare_part = sp.scalar_one()
        stock = await db_session.execute(
            select(SparePartStock).where(SparePartStock.spare_part_id == spare_part.id)
        )
        stock_row = stock.scalar_one()
        assert stock_row.current_qty == 0

        txns = await db_session.execute(
            select(SparePartTransaction).where(
                SparePartTransaction.spare_part_id == spare_part.id
            )
        )
        assert txns.scalars().all() == []

    async def test_existing_code_accumulates_stock_and_refreshes_price(
        self, db_session, imp_ctx
    ) -> None:
        """已有编码：数量累加入库 + 写入库流水 + 刷新参考单价。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content1 = _make_import_workbook([
            [code, "进口轴承", "6204-2RS", "个", "轴承类", None, 12.5, 30, None],
        ])
        await import_spare_parts_from_excel(db_session, content1, ctx=imp_ctx)

        # 第二次导入同编码，数量 20、新单价 15.8
        content2 = _make_import_workbook([
            [code, "进口轴承", "6204-2RS", "个", "轴承类", None, 15.8, 20, None],
        ])
        result = await import_spare_parts_from_excel(
            db_session, content2, ctx=imp_ctx
        )
        assert result.imported == 1
        assert result.skipped == 0

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == code)
        )
        spare_part = sp.scalar_one()
        assert float(spare_part.unit_price) == 15.8

        stock = await db_session.execute(
            select(SparePartStock).where(SparePartStock.spare_part_id == spare_part.id)
        )
        stock_row = stock.scalar_one()
        assert stock_row.current_qty == 50  # 30 + 20

        txns = await db_session.execute(
            select(SparePartTransaction).where(
                SparePartTransaction.spare_part_id == spare_part.id
            ).order_by(SparePartTransaction.created_at)
        )
        txn_list = txns.scalars().all()
        assert len(txn_list) == 2
        remarks = [t.remark for t in txn_list]
        assert "Excel导入初始库存" in remarks
        assert "Excel导入入库" in remarks
        inbound_txn = next(t for t in txn_list if t.remark == "Excel导入入库")
        assert inbound_txn.quantity == 20

    async def test_existing_code_zero_quantity_warns_and_skips(
        self, db_session, imp_ctx
    ) -> None:
        """已有编码且数量为空：警告并跳过，不动库存。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content1 = _make_import_workbook([
            [code, "进口轴承", None, "个", None, None, None, 30, None],
        ])
        await import_spare_parts_from_excel(db_session, content1, ctx=imp_ctx)

        content2 = _make_import_workbook([
            [code, "进口轴承", None, "个", None, None, None, None, None],
        ])
        result = await import_spare_parts_from_excel(
            db_session, content2, ctx=imp_ctx
        )
        assert result.imported == 0
        assert result.skipped == 1
        assert any("未入库" in w.message for w in result.warnings)

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == code)
        )
        spare_part = sp.scalar_one()
        stock = await db_session.execute(
            select(SparePartStock).where(SparePartStock.spare_part_id == spare_part.id)
        )
        assert stock.scalar_one().current_qty == 30

    async def test_invalid_quantity_warns_and_skips(self, db_session, imp_ctx) -> None:
        """数量非法（非数字/负数/小数）：该行警告跳过。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content = _make_import_workbook([
            [f"{code}-A", "备件A", None, "个", None, None, None, "abc", None],
            [f"{code}-B", "备件B", None, "个", None, None, None, -5, None],
            [f"{code}-C", "备件C", None, "个", None, None, None, 3.5, None],
        ])

        result = await import_spare_parts_from_excel(
            db_session, content, ctx=imp_ctx
        )
        assert result.imported == 0
        assert result.skipped == 3
        assert len(result.warnings) == 3

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == f"{code}-A")
        )
        assert sp.scalar_one_or_none() is None

    async def test_existing_code_other_department_errors(
        self, db_session, imp_user
    ) -> None:
        """已有编码归属其他部门且 ctx 无写权限：错误行跳过，库存不变。"""
        dept_a, dept_b = uuid.uuid4(), uuid.uuid4()
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        owner_ctx = EquipmentAccessContext(
            user=imp_user,
            data_scope="department",
            visible_department_ids=[dept_a],
        )
        content1 = _make_import_workbook([
            [code, "进口轴承", None, "个", None, None, None, 30, None],
        ])
        await import_spare_parts_from_excel(db_session, content1, ctx=owner_ctx)

        sp = await db_session.execute(
            select(SparePart).where(SparePart.code == code)
        )
        spare_part = sp.scalar_one()
        assert spare_part.department_id == dept_a

        other_ctx = EquipmentAccessContext(
            user=imp_user,
            data_scope="department",
            visible_department_ids=[dept_b],
        )
        content2 = _make_import_workbook([
            [code, "进口轴承", None, "个", None, None, None, 10, None],
        ])
        result = await import_spare_parts_from_excel(
            db_session, content2, ctx=other_ctx
        )
        assert result.imported == 0
        assert result.skipped == 1
        assert result.errors and "无权" in result.errors[0].message

        stock = await db_session.execute(
            select(SparePartStock).where(SparePartStock.spare_part_id == spare_part.id)
        )
        assert stock.scalar_one().current_qty == 30

    async def test_missing_required_fields_warns(self, db_session, imp_ctx) -> None:
        """缺少必填项：警告跳过。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content = _make_import_workbook([
            [code, None, None, None, None, None, None, 10, None],
        ])

        result = await import_spare_parts_from_excel(
            db_session, content, ctx=imp_ctx
        )
        assert result.imported == 0
        assert result.skipped == 1
        assert any("缺少必填项" in w.message for w in result.warnings)

    async def test_missing_sheet_raises(self, db_session, imp_ctx) -> None:
        """缺少「备件管理」工作表时抛 ValueError。"""
        import io

        import openpyxl as _openpyxl

        wb = _openpyxl.Workbook()
        wb.active.title = "其他"
        buf = io.BytesIO()
        wb.save(buf)

        with pytest.raises(ValueError):
            await import_spare_parts_from_excel(
                db_session, buf.getvalue(), ctx=imp_ctx
            )

    async def test_overwrite_mode_replaces_filled_fields_only(
        self, db_session, imp_ctx
    ) -> None:
        """覆盖模式：表格填了的字段以表格为准，库存按差值调整并写盘点流水。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承", "6204-2RS", "个", "轴承类", "老供应商", 12.5, 30, 8],
            ]),
            ctx=imp_ctx,
        )

        # 第二次：名称/单价/数量/安全库存都改，规格与供应商留空 → 保持原值
        result = await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承A", None, "个", "轴承类", None, 15.8, 50, 25],
            ]),
            ctx=imp_ctx,
            mode="overwrite",
        )
        assert result.imported == 1
        assert result.skipped == 0

        spare_part = (
            await db_session.execute(
                select(SparePart).where(SparePart.code == code)
            )
        ).scalar_one()
        assert spare_part.name == "进口轴承A"
        assert spare_part.specification == "6204-2RS"
        assert spare_part.default_supplier == "老供应商"
        assert float(spare_part.unit_price) == 15.8

        stock = (
            await db_session.execute(
                select(SparePartStock).where(
                    SparePartStock.spare_part_id == spare_part.id
                )
            )
        ).scalar_one()
        assert stock.current_qty == 50  # 覆盖为表值，不是 30 + 50
        assert stock.safety_qty == 25

        txns = (
            await db_session.execute(
                select(SparePartTransaction)
                .where(SparePartTransaction.spare_part_id == spare_part.id)
                .order_by(SparePartTransaction.created_at)
            )
        ).scalars().all()
        adjust = next(t for t in txns if t.transaction_type == "盘点调整")
        assert adjust.quantity == 20  # 50 - 30

    async def test_overwrite_mode_reimport_does_not_double_stock(
        self, db_session, imp_ctx
    ) -> None:
        """覆盖模式下重传同一份文件：库存不再翻倍（重复导入幂等）。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        content = _make_import_workbook([
            [code, "进口轴承", None, "个", None, None, 12.5, 50, 10],
        ])
        await import_spare_parts_from_excel(db_session, content, ctx=imp_ctx)
        await import_spare_parts_from_excel(
            db_session, content, ctx=imp_ctx, mode="overwrite"
        )

        spare_part = (
            await db_session.execute(
                select(SparePart).where(SparePart.code == code)
            )
        ).scalar_one()
        stock = (
            await db_session.execute(
                select(SparePartStock).where(
                    SparePartStock.spare_part_id == spare_part.id
                )
            )
        ).scalar_one()
        assert stock.current_qty == 50

    async def test_overwrite_mode_blank_quantity_keeps_stock(
        self, db_session, imp_ctx
    ) -> None:
        """覆盖模式：数量留空表示不改库存，也不产生盘点流水。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承", None, "个", None, None, None, 30, 8],
            ]),
            ctx=imp_ctx,
        )

        result = await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承", None, "个", None, None, None, None, 40],
            ]),
            ctx=imp_ctx,
            mode="overwrite",
        )
        assert result.imported == 1

        spare_part = (
            await db_session.execute(
                select(SparePart).where(SparePart.code == code)
            )
        ).scalar_one()
        stock = (
            await db_session.execute(
                select(SparePartStock).where(
                    SparePartStock.spare_part_id == spare_part.id
                )
            )
        ).scalar_one()
        assert stock.current_qty == 30  # 数量留空不动
        assert stock.safety_qty == 40  # 安全库存填了就覆盖

        txns = (
            await db_session.execute(
                select(SparePartTransaction).where(
                    SparePartTransaction.spare_part_id == spare_part.id
                )
            )
        ).scalars().all()
        assert not [t for t in txns if t.transaction_type == "盘点调整"]

    async def test_accumulate_mode_ignores_invalid_safety_qty(
        self, db_session, imp_ctx
    ) -> None:
        """累加模式：安全库存非法只警告，不再连累该行数量入库（该列本就不写）。"""
        code = f"SP-IMP-{uuid.uuid4().hex[:6].upper()}"
        await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承", None, "个", None, None, None, 30, None],
            ]),
            ctx=imp_ctx,
        )

        result = await import_spare_parts_from_excel(
            db_session,
            _make_import_workbook([
                [code, "进口轴承", None, "个", None, None, None, 20, "abc"],
            ]),
            ctx=imp_ctx,
        )
        assert result.imported == 1
        assert result.skipped == 0
        assert any("安全库存" in w.message for w in result.warnings)

        spare_part = (
            await db_session.execute(
                select(SparePart).where(SparePart.code == code)
            )
        ).scalar_one()
        stock = (
            await db_session.execute(
                select(SparePartStock).where(
                    SparePartStock.spare_part_id == spare_part.id
                )
            )
        ).scalar_one()
        assert stock.current_qty == 50  # 30 + 20

    async def test_invalid_mode_raises(self, db_session, imp_ctx) -> None:
        """未知导入模式抛 ValueError（API 层转 400）。"""
        with pytest.raises(ValueError):
            await import_spare_parts_from_excel(
                db_session,
                _make_import_workbook([]),
                ctx=imp_ctx,
                mode="bogus",
            )


# ==================== create_spare_part 库存初始化 ====================


class TestCreateSparePartStockInit:
    """建档时的库存设置（期初库存/安全库存/库位）与期初流水。"""

    async def test_create_with_initial_qty_and_settings(self) -> None:
        """建档带库存设置：库存行落数值，期初 > 0 时写「期初库存」入库流水。"""
        data = SparePartCreate(
            code="SP-INIT-001", name="轴承", unit="个",
            initial_qty=50, safety_qty=10, min_order_qty=5,
            warehouse_location="A-01",
        )
        ctx = _make_ctx()

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_spare_part",
                new_callable=AsyncMock,
                return_value=_make_spare_part(),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_stock",
                new_callable=AsyncMock,
            ) as mock_stock,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            await create_spare_part(db=AsyncMock(), data=data, ctx=ctx)

            stock_data = mock_stock.call_args[0][1]
            assert stock_data["current_qty"] == 50
            assert stock_data["safety_qty"] == 10
            assert stock_data["min_order_qty"] == 5
            assert stock_data["warehouse_location"] == "A-01"

            txn_data = mock_txn.call_args[0][1]
            assert txn_data["transaction_type"] == "入库"
            assert txn_data["quantity"] == 50
            assert txn_data["remark"] == "期初库存"
            assert txn_data["created_by"] == ctx.user.id

    async def test_create_without_initial_qty_skips_transaction(self) -> None:
        """期初为 0 时不写流水，其余库存设置照常落库。"""
        data = SparePartCreate(
            code="SP-INIT-002", name="密封圈", unit="个",
            safety_qty=8,
        )

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.exists_spare_part_by_code",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_spare_part",
                new_callable=AsyncMock,
                return_value=_make_spare_part(),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.create_stock",
                new_callable=AsyncMock,
            ) as mock_stock,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            await create_spare_part(db=AsyncMock(), data=data, ctx=_make_ctx())

            stock_data = mock_stock.call_args[0][1]
            assert stock_data["current_qty"] == 0
            assert stock_data["safety_qty"] == 8
            mock_txn.assert_not_called()


# ==================== delete_spare_part 校验 ====================


class TestDeleteSparePartGuards:
    """删除备件的守卫逻辑：库存非零拒绝、关联与库存行级联软删。"""

    async def test_rejects_when_stock_positive(self) -> None:
        """库存 > 0 时拒绝删除，提示先归零。"""
        sp = _make_spare_part()

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=_make_stock(sp.id, current_qty=7),
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await delete_spare_part(
                    db=AsyncMock(), spare_part_id=sp.id, ctx=_make_ctx(),
                )
            assert "盘点归零" in exc_info.value.message

    async def test_cascades_links_and_stock(self) -> None:
        """库存为 0 删除时，设备关联与库存行同步软删。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=0)
        db = AsyncMock()

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.delete_equipment_spare_parts_by_spare_part",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_cascade,
            patch(
                "app.modules.equipment.service.spare_part.repo.delete_spare_part",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await delete_spare_part(
                db=db, spare_part_id=sp.id, ctx=_make_ctx(),
            )
            assert result is True
            mock_cascade.assert_called_once()
            assert stock.is_deleted is True


# ==================== inbound_stock 停用守卫 ====================


class TestInboundInactiveGuard:
    """停用备件拒绝入库。"""

    async def test_rejects_inactive_spare_part(self) -> None:
        sp = _make_spare_part()
        sp.is_active = False

        with patch(
            "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
            new_callable=AsyncMock,
            return_value=sp,
        ):
            with pytest.raises(AppException) as exc_info:
                await inbound_stock(
                    db=AsyncMock(),
                    spare_part_id=sp.id,
                    data=StockInboundRequest(quantity=10),
                    ctx=_make_ctx(),
                )
            assert "停用" in exc_info.value.message


# ==================== update_stock_settings ====================


class TestUpdateStockSettings:
    """update_stock_settings 库存设置业务逻辑测试。"""

    async def test_updates_fields_without_transaction(self) -> None:
        """更新安全库存/采购批量/库位，不产生数量流水。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=50, safety_qty=10)

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ) as mock_get_stock,
            patch(
                "app.modules.equipment.service.spare_part.repo.create_transaction",
                new_callable=AsyncMock,
            ) as mock_txn,
        ):
            from app.modules.equipment.schemas.spare_part import (
                StockSettingsRequest,
            )

            result = await update_stock_settings(
                db=AsyncMock(),
                spare_part_id=sp.id,
                data=StockSettingsRequest(
                    safety_qty=30, min_order_qty=4, warehouse_location="C-03",
                ),
                ctx=_make_ctx(),
            )
            assert result is stock
            assert stock.safety_qty == 30
            assert stock.min_order_qty == 4
            assert stock.warehouse_location == "C-03"
            # 第一次读取带 for_update 行锁（末次为返回前的 re-fetch）
            assert mock_get_stock.call_args_list[0].kwargs.get("for_update") is True
            mock_txn.assert_not_called()

    async def test_unset_fields_keep_original(self) -> None:
        """未传的字段保持原值不变。"""
        sp = _make_spare_part()
        stock = _make_stock(sp.id, safety_qty=10, warehouse_location="A-01")

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
                new_callable=AsyncMock,
                return_value=stock,
            ),
        ):
            from app.modules.equipment.schemas.spare_part import (
                StockSettingsRequest,
            )

            await update_stock_settings(
                db=AsyncMock(),
                spare_part_id=sp.id,
                data=StockSettingsRequest(safety_qty=25),
                ctx=_make_ctx(),
            )
            assert stock.safety_qty == 25
            assert stock.warehouse_location == "A-01"
            assert stock.min_order_qty == 5  # _make_stock 默认


# ==================== get_stock_warnings 建议补货量 ====================


class TestStockWarningsSuggested:
    """预警响应的建议补货量按最小采购批量向上取整。"""

    async def test_suggested_qty_rounds_up_to_batch(self) -> None:
        sp = _make_spare_part()
        stock = _make_stock(sp.id, current_qty=5, safety_qty=20)
        stock.min_order_qty = 4  # 缺口 15 → 建议补 16

        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_warnings",
            new_callable=AsyncMock,
            return_value=[(sp, stock)],
        ):
            warnings = await get_stock_warnings(db=AsyncMock(), ctx=_make_ctx())

        assert len(warnings) == 1
        w = warnings[0]
        assert w.shortage == 15
        assert w.min_order_qty == 4
        assert w.suggested_qty == 16
        assert w.warehouse_location == stock.warehouse_location

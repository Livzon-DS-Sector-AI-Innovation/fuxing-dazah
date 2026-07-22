"""备件模块 Service 层业务逻辑测试。

使用 mock repository 验证 service 层的业务流程、校验规则、
异常处理。不直接操作数据库，聚焦业务逻辑正确性。
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.spare_part import SparePart, SparePartStock
from app.modules.equipment.schemas.spare_part import (
    SparePartCreate,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
)
from app.modules.equipment.service.spare_part import (
    adjust_stock,
    create_spare_part,
    delete_spare_part,
    get_spare_part_by_id,
    get_spare_parts,
    get_stock_by_spare_part_id,
    get_stock_warnings,
    inbound_stock,
    outbound_stock,
    update_spare_part,
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
    """创建一个无限制（超管）的访问上下文。"""
    from app.platform.identity.models import User

    user = User(
        id=uuid.uuid4(),
        name="测试用户",
        employee_no="EMP-TEST",
    )
    return EquipmentAccessContext(user=user, data_scope=data_scope)


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
        """ctx.visible_department_ids 为空时不自动设置 department_id。"""
        ctx_empty = _make_ctx()
        ctx_empty.visible_department_ids = []

        mock_sp = _make_spare_part(department_id=None)

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
            await create_spare_part(
                db=AsyncMock(), data=create_data, ctx=ctx_empty,
            )
            call_data = mock_create.call_args[0][1]
            assert call_data.get("department_id") is None


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
        """批量查询部门名称并缓存去重。"""
        dept_a = uuid.uuid4()
        dept_b = uuid.uuid4()
        sp1 = _make_spare_part(code="SP-A", department_id=dept_a)
        sp2 = _make_spare_part(code="SP-B", department_id=dept_a)
        sp3 = _make_spare_part(code="SP-C", department_id=dept_b)

        call_count = 0

        async def mock_dept_info(
            db: object, dept_id: uuid.UUID
        ) -> dict[str, str] | None:
            nonlocal call_count
            call_count += 1
            if dept_id == dept_a:
                return {"name": "生产部"}
            if dept_id == dept_b:
                return {"name": "质量部"}
            return None

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_parts",
                new_callable=AsyncMock,
                return_value=([sp1, sp2, sp3], 3),
            ),
            patch(
                "app.modules.equipment.service.spare_part.repo.get_department_info",
                new_callable=AsyncMock,
                side_effect=mock_dept_info,
            ),
        ):
            await get_spare_parts(db=AsyncMock(), ctx=_make_ctx())
            # dept_a 被查询两次但缓存命中只调用一次 repo，dept_b 一次
            assert call_count == 2


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
        """正常删除返回 True。"""
        sp = _make_spare_part()
        ctx = _make_ctx()

        with (
            patch(
                "app.modules.equipment.service.spare_part.repo.get_spare_part_by_id",
                new_callable=AsyncMock,
                return_value=sp,
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
        """库存充足时出库成功，库存减少并创建出库流水。"""
        sp_id = uuid.uuid4()
        stock = _make_stock(sp_id, current_qty=50)

        with (
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
                db=AsyncMock(), spare_part_id=sp_id, quantity=5,
            )
            assert result is stock

            txn_data = mock_txn.call_args[0][1]
            assert txn_data["transaction_type"] == "出库"
            assert txn_data["quantity"] == -5

    async def test_raises_when_stock_insufficient(self) -> None:
        """库存不足时抛出 AppException。"""
        sp_id = uuid.uuid4()
        stock = _make_stock(sp_id, current_qty=10)

        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_by_spare_part_id",
            new_callable=AsyncMock,
            return_value=stock,
        ):
            with pytest.raises(AppException) as exc:
                await outbound_stock(
                    db=AsyncMock(), spare_part_id=sp_id, quantity=20,
                )
            assert "库存不足" in exc.value.message
            assert "10" in exc.value.message

    async def test_exact_qty_outbound_ok(self) -> None:
        """出库数量等于当前库存时允许（清空库存）。"""
        sp_id = uuid.uuid4()
        stock = _make_stock(sp_id, current_qty=5)

        with (
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
                db=AsyncMock(), spare_part_id=sp_id, quantity=5,
            )
            assert result is stock


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
            result = await get_stock_warnings(db=AsyncMock())
            assert len(result) == 1
            assert result[0].shortage == 15  # 20 - 5
            assert result[0].spare_part.id == sp.id
            assert result[0].stock.id == stock.id

    async def test_returns_empty_list_when_no_warnings(self) -> None:
        """无预警时返回空列表。"""
        with patch(
            "app.modules.equipment.service.spare_part.repo.get_stock_warnings",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_stock_warnings(db=AsyncMock())
            assert result == []

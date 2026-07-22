"""备件模块 Repository 层数据访问测试。

使用真实数据库（通过 db_session fixture 的 rollback 机制）
验证 repository 函数的 CRUD、过滤、分页、关联查询逻辑。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.equipment import Equipment, Location
from app.modules.equipment.repository.spare_part import (
    create_equipment_spare_part,
    create_spare_part,
    create_stock,
    create_transaction,
    delete_equipment_spare_part,
    delete_spare_part,
    exists_spare_part_by_code,
    get_available_spare_parts,
    get_equipment_spare_parts,
    get_spare_part_by_code,
    get_spare_part_by_id,
    get_spare_part_equipments,
    get_spare_parts,
    get_stock_by_spare_part_id,
    get_stock_warnings,
    update_spare_part,
    update_stock_qty,
)
from app.platform.identity.models import User


def _make_ctx(data_scope: str = "all") -> EquipmentAccessContext:
    """创建一个无数据范围限制的访问上下文。"""
    return EquipmentAccessContext(
        user=User(
            id=uuid.uuid4(),
            name="测试用户",
            employee_no="EMP-REPO-TEST",
        ),
        data_scope=data_scope,
    )


def _rand_suffix() -> str:
    """生成随机后缀避免测试数据冲突。"""
    return uuid.uuid4().hex[:8]


# ==================== SparePart CRUD ====================


class TestSparePartCrud:
    """备件主数据 CRUD 测试。"""

    async def test_create_and_get_by_id(self, db_session: AsyncSession) -> None:
        """创建备件后能通过 ID 查询到完整数据。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-CRUD-{_rand_suffix()}",
            "name": "测试备件",
            "unit": "个",
            "specification": "TEST-V1",
            "category": "测试类",
        })
        assert sp.id is not None
        assert sp.code is not None

        found = await get_spare_part_by_id(db_session, sp.id)
        assert found is not None
        assert found.name == "测试备件"
        assert found.specification == "TEST-V1"
        assert found.category == "测试类"
        assert found.unit == "个"

    async def test_get_by_id_returns_none_for_deleted(
        self, db_session: AsyncSession
    ) -> None:
        """软删除后备件通过 get_by_id 返回 None（被 is_deleted 过滤）。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-DEL-{_rand_suffix()}",
            "name": "待删除备件",
            "unit": "个",
        })
        await delete_spare_part(db_session, sp.id)

        found = await get_spare_part_by_id(db_session, sp.id)
        assert found is None

    async def test_get_by_id_returns_none_for_nonexistent(
        self, db_session: AsyncSession
    ) -> None:
        """查询不存在的 ID 返回 None。"""
        result = await get_spare_part_by_id(db_session, uuid.uuid4())
        assert result is None

    async def test_update_spare_part(self, db_session: AsyncSession) -> None:
        """更新备件字段后能查询到新值。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-UPD-{_rand_suffix()}",
            "name": "原始名称",
            "unit": "个",
        })
        updated = await update_spare_part(db_session, sp.id, {
            "name": "更新后名称",
            "unit_price": 99.99,
        })
        assert updated is not None
        assert updated.name == "更新后名称"
        assert updated.unit_price is not None
        assert float(updated.unit_price) == 99.99

        # 验证持久化
        found = await get_spare_part_by_id(db_session, sp.id)
        assert found is not None
        assert found.name == "更新后名称"

    async def test_update_nonexistent_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """更新不存在的备件返回 None。"""
        result = await update_spare_part(
            db_session, uuid.uuid4(), {"name": "X"}
        )
        assert result is None

    async def test_delete_is_soft_delete(self, db_session: AsyncSession) -> None:
        """删除操作仅设置 is_deleted=True，不物理删除。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-SOFT-{_rand_suffix()}",
            "name": "软删除备件",
            "unit": "个",
        })
        result = await delete_spare_part(db_session, sp.id)
        assert result is True

        # get_by_id 过滤软删除
        assert await get_spare_part_by_id(db_session, sp.id) is None

    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession
    ) -> None:
        """删除不存在的备件返回 False。"""
        result = await delete_spare_part(db_session, uuid.uuid4())
        assert result is False


# ==================== Code Uniqueness ====================


class TestSparePartCodeUniqueness:
    """备件编码唯一性约束测试。"""

    async def test_exists_by_code_returns_true_for_existing(
        self, db_session: AsyncSession
    ) -> None:
        """已存在的编码返回 True。"""
        code = f"SP-UNIQ-{_rand_suffix()}"
        await create_spare_part(db_session, {
            "code": code, "name": "唯一编码备件", "unit": "个",
        })
        assert await exists_spare_part_by_code(db_session, code) is True

    async def test_exists_by_code_returns_false_for_nonexistent(
        self, db_session: AsyncSession
    ) -> None:
        """不存在的编码返回 False。"""
        assert (
            await exists_spare_part_by_code(
                db_session, f"NONEXIST-{_rand_suffix()}"
            )
            is False
        )

    async def test_exists_by_code_excludes_self(
        self, db_session: AsyncSession
    ) -> None:
        """排除自身 ID 后，自己的编码不算冲突。"""
        code = f"SP-SELF-{_rand_suffix()}"
        sp = await create_spare_part(db_session, {
            "code": code, "name": "自己", "unit": "个",
        })
        assert (
            await exists_spare_part_by_code(
                db_session, code, exclude_id=sp.id
            )
            is False
        )

    async def test_exists_by_code_ignores_deleted(
        self, db_session: AsyncSession
    ) -> None:
        """已删除的备件编码不参与唯一性检查（支持删后重建）。"""
        code = f"SP-RECREATE-{_rand_suffix()}"
        sp = await create_spare_part(db_session, {
            "code": code, "name": "原始", "unit": "个",
        })
        await delete_spare_part(db_session, sp.id)
        # 删除后编码应视为不存在
        assert await exists_spare_part_by_code(db_session, code) is False

    async def test_get_by_code_returns_active_only(
        self, db_session: AsyncSession
    ) -> None:
        """按编码查询只返回启用且未删除的备件。"""
        code = f"SP-ACTIVE-{_rand_suffix()}"
        sp = await create_spare_part(db_session, {
            "code": code, "name": "活跃备件", "unit": "个",
        })
        found = await get_spare_part_by_code(db_session, code)
        assert found is not None
        assert found.id == sp.id

    async def test_get_by_code_skips_inactive(
        self, db_session: AsyncSession
    ) -> None:
        """停用的备件不通过 get_by_code 返回。"""
        code = f"SP-INACT-{_rand_suffix()}"
        sp = await create_spare_part(db_session, {
            "code": code, "name": "停用备件", "unit": "个",
        })
        # 手动停用
        await update_spare_part(db_session, sp.id, {"is_active": False})

        found = await get_spare_part_by_code(db_session, code)
        assert found is None


# ==================== List with Filters ====================


class TestGetSparePartsList:
    """备件分页列表查询测试。"""

    async def test_pagination(self, db_session: AsyncSession) -> None:
        """分页查询返回正确的 page 数据和 total。"""
        suffix = _rand_suffix()
        for i in range(5):
            await create_spare_part(db_session, {
                "code": f"SP-PAGE-{suffix}-{i}",
                "name": f"分页备件{i}",
                "unit": "个",
            })

        results, total = await get_spare_parts(
            db_session, _make_ctx(), page=1, page_size=3,
        )
        assert len(results) <= 3
        assert total >= 5

    async def test_filter_by_category(self, db_session: AsyncSession) -> None:
        """按分类筛选备件列表。"""
        suffix = _rand_suffix()
        await create_spare_part(db_session, {
            "code": f"SP-CAT-A-{suffix}",
            "name": "机械备件",
            "unit": "个",
            "category": "机械类",
        })
        await create_spare_part(db_session, {
            "code": f"SP-CAT-B-{suffix}",
            "name": "电气备件",
            "unit": "个",
            "category": "电气类",
        })

        results, total = await get_spare_parts(
            db_session, _make_ctx(), category="机械类",
        )
        assert total >= 1
        for sp in results:
            assert sp.category == "机械类"

    async def test_filter_by_keyword_code(self, db_session: AsyncSession) -> None:
        """按编码关键词搜索备件。"""
        suffix = _rand_suffix()
        code = f"SP-KW-{suffix}"
        await create_spare_part(db_session, {
            "code": code, "name": "关键词备件", "unit": "个",
        })
        await create_spare_part(db_session, {
            "code": f"OTHER-{suffix}",
            "name": "其他备件",
            "unit": "个",
        })

        results, total = await get_spare_parts(
            db_session, _make_ctx(), keyword="SP-KW",
        )
        assert total >= 1
        for sp in results:
            assert "SP-KW" in sp.code

    async def test_filter_by_keyword_name(self, db_session: AsyncSession) -> None:
        """按名称关键词搜索备件（ILIKE 匹配）。"""
        suffix = _rand_suffix()
        await create_spare_part(db_session, {
            "code": f"SP-NK-{suffix}",
            "name": "高温密封圈",
            "unit": "个",
        })
        await create_spare_part(db_session, {
            "code": f"SP-NK2-{suffix}",
            "name": "普通垫片",
            "unit": "个",
        })

        results, total = await get_spare_parts(
            db_session, _make_ctx(), keyword="密封",
        )
        assert total >= 1
        for sp in results:
            assert "密封" in sp.name

    async def test_filter_by_is_active(self, db_session: AsyncSession) -> None:
        """按启用状态筛选备件。"""
        suffix = _rand_suffix()
        await create_spare_part(db_session, {
            "code": f"SP-ON-{suffix}",
            "name": "启用备件",
            "unit": "个",
        })
        sp2 = await create_spare_part(db_session, {
            "code": f"SP-OFF-{suffix}",
            "name": "停用备件",
            "unit": "个",
        })
        await update_spare_part(db_session, sp2.id, {"is_active": False})

        active_results, active_total = await get_spare_parts(
            db_session, _make_ctx(), is_active=True,
        )
        assert active_total >= 1
        for sp in active_results:
            assert sp.is_active is True

        inactive_results, _ = await get_spare_parts(
            db_session, _make_ctx(), is_active=False,
        )
        for sp in inactive_results:
            assert sp.is_active is False

    async def test_batch_fills_equipment_count_and_stock(
        self, db_session: AsyncSession
    ) -> None:
        """列表查询批量填充 equipment_count、current_qty、min_qty。"""
        suffix = _rand_suffix()
        sp = await create_spare_part(db_session, {
            "code": f"SP-BATCH-{suffix}",
            "name": "批量填充备件",
            "unit": "个",
        })
        # 创建库存
        await create_stock(db_session, {
            "spare_part_id": sp.id,
            "current_qty": 30,
            "safety_qty": 10,
        })

        results, _ = await get_spare_parts(
            db_session, _make_ctx(),
        )
        # 找到我们创建的备件
        found = next((r for r in results if r.id == sp.id), None)
        assert found is not None
        assert found.equipment_count == 0  # type: ignore[attr-defined]  # 无关联设备
        assert found.current_qty == 30  # type: ignore[attr-defined]
        assert found.min_qty == 10  # type: ignore[attr-defined]  # safety_qty


# ==================== Stock Operations ====================


class TestStockOperations:
    """库存记录 CRUD 测试。"""

    async def test_create_and_get_stock(self, db_session: AsyncSession) -> None:
        """创建库存后能通过 spare_part_id 查询。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-STK-{_rand_suffix()}",
            "name": "库存测试备件",
            "unit": "个",
        })
        stock = await create_stock(db_session, {
            "spare_part_id": sp.id,
            "current_qty": 100,
            "safety_qty": 20,
            "warehouse_location": "A-01",
        })
        assert stock.id is not None

        found = await get_stock_by_spare_part_id(db_session, sp.id)
        assert found is not None
        assert found.current_qty == 100
        assert found.safety_qty == 20
        assert found.warehouse_location == "A-01"

    async def test_get_stock_returns_none_for_nonexistent(
        self, db_session: AsyncSession
    ) -> None:
        """不存在的备件库存查询返回 None。"""
        result = await get_stock_by_spare_part_id(db_session, uuid.uuid4())
        assert result is None

    async def test_update_stock_qty_increase(
        self, db_session: AsyncSession
    ) -> None:
        """更新库存数量——入库增加当前库存。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-QTY-{_rand_suffix()}",
            "name": "入库测试",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id, "current_qty": 50,
        })

        updated = await update_stock_qty(db_session, sp.id, 30)
        assert updated is not None
        assert updated.current_qty == 80  # 50 + 30

    async def test_update_stock_qty_decrease(
        self, db_session: AsyncSession
    ) -> None:
        """更新库存数量——出库减少当前库存。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-DEC-{_rand_suffix()}",
            "name": "出库测试",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id, "current_qty": 50,
        })

        updated = await update_stock_qty(db_session, sp.id, -20)
        assert updated is not None
        assert updated.current_qty == 30  # 50 - 20

    async def test_update_stock_qty_nonexistent_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """更新不存在的库存返回 None。"""
        result = await update_stock_qty(db_session, uuid.uuid4(), 10)
        assert result is None


# ==================== Transactions ====================


class TestTransactions:
    """库存流水记录测试。"""

    async def test_create_inbound_transaction(
        self, db_session: AsyncSession
    ) -> None:
        """创建入库流水记录。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-TXN-{_rand_suffix()}",
            "name": "流水测试",
            "unit": "个",
        })
        txn = await create_transaction(db_session, {
            "spare_part_id": sp.id,
            "transaction_type": "入库",
            "quantity": 50,
            "remark": "采购入库",
        })
        assert txn.id is not None
        assert txn.transaction_type == "入库"
        assert txn.quantity == 50
        assert txn.remark == "采购入库"

    async def test_create_outbound_transaction(
        self, db_session: AsyncSession
    ) -> None:
        """创建出库流水记录（含负数量）。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-OUT-{_rand_suffix()}",
            "name": "出库流水",
            "unit": "个",
        })
        txn = await create_transaction(db_session, {
            "spare_part_id": sp.id,
            "transaction_type": "出库",
            "quantity": -5,
        })
        assert txn.transaction_type == "出库"
        assert txn.quantity == -5

    async def test_create_adjust_transaction(
        self, db_session: AsyncSession
    ) -> None:
        """创建盘点调整流水记录。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-ADJ-{_rand_suffix()}",
            "name": "盘点流水",
            "unit": "个",
        })
        txn = await create_transaction(db_session, {
            "spare_part_id": sp.id,
            "transaction_type": "盘点调整",
            "quantity": 10,
            "remark": "盘盈",
        })
        assert txn.transaction_type == "盘点调整"
        assert txn.quantity == 10


# ==================== Stock Warnings ====================


class TestStockWarnings:
    """库存预警查询测试。"""

    async def test_returns_below_safety_stock(
        self, db_session: AsyncSession
    ) -> None:
        """当前库存低于安全库存且安全库存 > 0 时出现在预警列表中。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-WARN-{_rand_suffix()}",
            "name": "预警备件",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id,
            "current_qty": 5,
            "safety_qty": 20,
        })

        warnings = await get_stock_warnings(db_session)
        sp_ids_in_warnings = [sp.id for sp, _stock in warnings]
        assert sp.id in sp_ids_in_warnings

    async def test_excludes_above_safety_stock(
        self, db_session: AsyncSession
    ) -> None:
        """库存充足时不出现在预警列表中。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-SAFE-{_rand_suffix()}",
            "name": "充足备件",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id,
            "current_qty": 100,
            "safety_qty": 20,
        })

        warnings = await get_stock_warnings(db_session)
        sp_ids = [sp.id for sp, _stock in warnings]
        assert sp.id not in sp_ids

    async def test_excludes_zero_safety_stock(
        self, db_session: AsyncSession
    ) -> None:
        """安全库存为 0 时不预警（不关心库存下限）。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-NOSAFE-{_rand_suffix()}",
            "name": "无安全库存备件",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id,
            "current_qty": 0,
            "safety_qty": 0,
        })

        warnings = await get_stock_warnings(db_session)
        sp_ids = [sp.id for sp, _stock in warnings]
        assert sp.id not in sp_ids

    async def test_excludes_deleted_spare_part(
        self, db_session: AsyncSession
    ) -> None:
        """已删除的备件不出现在预警列表中。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-DELWARN-{_rand_suffix()}",
            "name": "删除预警备件",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id, "current_qty": 1, "safety_qty": 10,
        })
        await delete_spare_part(db_session, sp.id)

        warnings = await get_stock_warnings(db_session)
        sp_ids = [sp.id for sp, _stock in warnings]
        assert sp.id not in sp_ids


# ==================== Equipment-SparePart Associations ====================


class TestEquipmentSparePartLinks:
    """设备-备件关联测试。"""

    @staticmethod
    async def _create_test_equipment(
        db_session: AsyncSession,
    ) -> Equipment:
        """创建测试用设备记录（满足 FK 约束）。"""
        suffix = _rand_suffix()
        location = Location(name="测试车间", code=f"LOC-{suffix}")
        db_session.add(location)
        await db_session.flush()

        equipment = Equipment(
            equipment_no=f"EQ-{suffix}",
            name="测试设备",
            location_id=location.id,
            status="完好",
        )
        db_session.add(equipment)
        await db_session.flush()
        await db_session.refresh(equipment)
        return equipment

    async def test_create_and_get_links(
        self, db_session: AsyncSession
    ) -> None:
        """创建关联后能通过 equipment_id 查询到关联列表。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-LINK-{_rand_suffix()}",
            "name": "关联备件",
            "unit": "个",
        })
        eq = await self._create_test_equipment(db_session)

        link = await create_equipment_spare_part(db_session, {
            "equipment_id": eq.id,
            "spare_part_id": sp.id,
            "quantity": 3,
        })
        assert link.id is not None
        assert link.quantity == 3

        links = await get_equipment_spare_parts(db_session, eq.id)
        assert len(links) >= 1
        assert any(item.spare_part_id == sp.id for item in links)

    async def test_get_spare_part_equipments(
        self, db_session: AsyncSession
    ) -> None:
        """通过备件 ID 反向查询关联的设备列表。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-REV-{_rand_suffix()}",
            "name": "反向查询",
            "unit": "个",
        })
        eq = await self._create_test_equipment(db_session)
        await create_equipment_spare_part(db_session, {
            "equipment_id": eq.id,
            "spare_part_id": sp.id,
            "quantity": 2,
        })

        links = await get_spare_part_equipments(db_session, sp.id)
        assert len(links) >= 1
        assert any(item.equipment_id == eq.id for item in links)

    async def test_delete_link_is_soft_delete(
        self, db_session: AsyncSession
    ) -> None:
        """删除关联是软删除，删除后查询不到。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-ULINK-{_rand_suffix()}",
            "name": "解绑测试",
            "unit": "个",
        })
        eq = await self._create_test_equipment(db_session)
        link = await create_equipment_spare_part(db_session, {
            "equipment_id": eq.id,
            "spare_part_id": sp.id,
            "quantity": 1,
        })

        result = await delete_equipment_spare_part(db_session, link.id)
        assert result is True

        links = await get_equipment_spare_parts(db_session, eq.id)
        assert all(item.id != link.id for item in links)

    async def test_delete_nonexistent_link_returns_false(
        self, db_session: AsyncSession
    ) -> None:
        """删除不存在的关联返回 False。"""
        result = await delete_equipment_spare_part(db_session, uuid.uuid4())
        assert result is False

    async def test_get_spare_part_equipments_empty(
        self, db_session: AsyncSession
    ) -> None:
        """备件无关联设备时返回空列表。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-NOLINK-{_rand_suffix()}",
            "name": "无关联备件",
            "unit": "个",
        })
        links = await get_spare_part_equipments(db_session, sp.id)
        assert links == []


# ==================== Available Spare Parts Logic ====================


class TestAvailableSpareParts:
    """get_available_spare_parts 设备可用备件逻辑测试。"""

    async def test_global_spare_part_available(
        self, db_session: AsyncSession
    ) -> None:
        """无任何设备关联的启用备件对任意设备可见（全局可用）。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-GLOBAL-{_rand_suffix()}",
            "name": "全局备件",
            "unit": "个",
        })
        eq_id = uuid.uuid4()

        available = await get_available_spare_parts(db_session, eq_id)
        sp_ids = [s.id for s in available]
        assert sp.id in sp_ids

    async def test_linked_spare_part_available_to_linked_equipment(
        self, db_session: AsyncSession
    ) -> None:
        """关联了某设备的备件对该设备可见。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-LINKED-{_rand_suffix()}",
            "name": "已关联备件",
            "unit": "个",
        })
        eq = await TestEquipmentSparePartLinks._create_test_equipment(db_session)
        await create_equipment_spare_part(db_session, {
            "equipment_id": eq.id,
            "spare_part_id": sp.id,
            "quantity": 1,
        })

        available = await get_available_spare_parts(db_session, eq.id)
        sp_ids = [s.id for s in available]
        assert sp.id in sp_ids

    async def test_linked_spare_part_not_available_to_other_equipment(
        self, db_session: AsyncSession
    ) -> None:
        """关联了设备 A 的备件对未关联的设备 B 不可见。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-EXCL-{_rand_suffix()}",
            "name": "独占备件",
            "unit": "个",
        })
        eq_a = await TestEquipmentSparePartLinks._create_test_equipment(db_session)
        eq_b_id = uuid.uuid4()  # 设备 B 不存在，get_available_spare_parts 不检查设备存在性
        await create_equipment_spare_part(db_session, {
            "equipment_id": eq_a.id,
            "spare_part_id": sp.id,
            "quantity": 1,
        })

        available_b = await get_available_spare_parts(db_session, eq_b_id)
        sp_ids_b = [s.id for s in available_b]
        assert sp.id not in sp_ids_b

    async def test_inactive_spare_part_not_available(
        self, db_session: AsyncSession
    ) -> None:
        """停用的备件不出现在可用列表中。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-DISABLED-{_rand_suffix()}",
            "name": "停用全局备件",
            "unit": "个",
        })
        await update_spare_part(db_session, sp.id, {"is_active": False})
        eq_id = uuid.uuid4()

        available = await get_available_spare_parts(db_session, eq_id)
        sp_ids = [s.id for s in available]
        assert sp.id not in sp_ids

    async def test_batch_fills_stock_qty(
        self, db_session: AsyncSession
    ) -> None:
        """可用备件列表批量填充 current_qty。"""
        sp = await create_spare_part(db_session, {
            "code": f"SP-STKQ-{_rand_suffix()}",
            "name": "库存查询备件",
            "unit": "个",
        })
        await create_stock(db_session, {
            "spare_part_id": sp.id, "current_qty": 42,
        })

        available = await get_available_spare_parts(db_session, uuid.uuid4())
        found = next((s for s in available if s.id == sp.id), None)
        assert found is not None
        assert found.current_qty == 42  # type: ignore[attr-defined]

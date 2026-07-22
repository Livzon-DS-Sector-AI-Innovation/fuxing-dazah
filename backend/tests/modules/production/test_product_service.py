"""产品主数据业务逻辑测试。

覆盖业务场景：
- 产品更新：修改名称、单位、备注；更新不存在的产品抛 NotFoundException
- 产品删除：无关联批次时软删除成功；有关联未完成批次时拒绝删除（AppException）；
  删除不存在的产品抛 NotFoundException
- 产品列表：分页查询、关键词过滤
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.production.models import Batch
from app.modules.production.schemas import ProductCreate, ProductUpdate
from app.modules.production.service import route_service
from tests.modules.production.conftest import rand_code


class TestProductUpdate:
    async def test_update_name(self, db_session: AsyncSession) -> None:
        """更新产品名称：传入新名称后 product_name 应变更。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        new_name = rand_code("新产品")
        updated = await route_service.update_product(
            db_session, product.id, ProductUpdate(product_name=new_name), user=None,
        )
        assert updated.product_name == new_name

    async def test_update_nonexistent_rejected(self, db_session: AsyncSession) -> None:
        """更新不存在的产品抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await route_service.update_product(
                db_session, uuid.uuid4(), ProductUpdate(product_name="x"), user=None,
            )

    async def test_update_unit_and_remark(self, db_session: AsyncSession) -> None:
        """同时更新产品的单位和备注字段。"""
        product = await route_service.create_product(
            db_session,
            ProductCreate(product_name=rand_code("产品"), unit="kg"),
            user=None,
        )
        updated = await route_service.update_product(
            db_session,
            product.id,
            ProductUpdate(unit="L", remark="测试备注"),
            user=None,
        )
        assert updated.unit == "L"
        assert updated.remark == "测试备注"


class TestProductDelete:
    async def test_delete_without_batches_succeeds(
        self, db_session: AsyncSession,
    ) -> None:
        """无关联批次的產品可正常软删除，删除后仓库查询返回 None。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        await route_service.delete_product(db_session, product.id, user=None)
        # 软删除后查不到
        from app.modules.production.repository.product import get_product
        deleted = await get_product(db_session, product.id)
        assert deleted is None

    async def test_delete_with_unfinished_batches_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """存在未完成批次的產品不可删除，抛出 AppException 并说明未完成批次数量。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        db_session.add(
            Batch(
                batch_no=rand_code("B"),
                product_id=product.id,
                route_id=uuid.uuid4(),
                status="pending",
            )
        )
        await db_session.flush()
        with pytest.raises(AppException, match="未完成批次"):
            await route_service.delete_product(db_session, product.id, user=None)

    async def test_delete_nonexistent_rejected(self, db_session: AsyncSession) -> None:
        """删除不存在的产品抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await route_service.delete_product(db_session, uuid.uuid4(), user=None)


class TestProductList:
    async def test_list_paged(self, db_session: AsyncSession) -> None:
        """产品的分页列表查询，按名称关键词能检索到刚创建的产品。"""
        name = rand_code("列表产品")
        await route_service.create_product(
            db_session, ProductCreate(product_name=name), user=None,
        )
        _items, total = await route_service.list_products_paged(
            db_session, keyword=name, page=1, page_size=10,
        )
        assert total >= 1
        assert any(p.product_name == name for p in _items)

    async def test_list_keyword_filter(self, db_session: AsyncSession) -> None:
        """关键词精确匹配时只返回该产品。"""
        kw = rand_code("KW")
        await route_service.create_product(
            db_session, ProductCreate(product_name=kw, product_code=kw), user=None,
        )
        _items, total = await route_service.list_products_paged(
            db_session, keyword=kw, page=1, page_size=10,
        )
        assert total == 1

"""中间体字典 CRUD 业务逻辑测试。

覆盖业务场景：
- 创建：基本创建、编码重复拒绝（DuplicateException）、关联产品、
  标记为成品必须关联产品（Schema 层校验）、关联不存在的产品拒绝
- 更新：修改名称；更新不存在的条目；设置 is_product 必须同时有 product_id；
  关联有效产品
- 删除：软删除后查不到；删除不存在条目拒绝；软删除后同编码可重新创建
- 列表：分页查询、关键词过滤（编码/名称模糊匹配）
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.production.schemas import (
    IntermediateTypeCreate,
    IntermediateTypeUpdate,
    ProductCreate,
)
from app.modules.production.service import intermediate_service, route_service
from tests.modules.production.conftest import rand_code


class TestCreateIntermediateType:
    async def test_create_basic(self, db_session: AsyncSession) -> None:
        """正常创建中间体类型，返回 code 和 name 与输入一致。"""
        result = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(
                code=rand_code("IM"), name="发酵液", category="中间体",
            ),
            user=None,
        )
        assert result.code.startswith("IM-")
        assert result.name == "发酵液"

    async def test_create_duplicate_code_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """同一 code 创建两次，第二次抛出 DuplicateException。"""
        code = rand_code("IM")
        await intermediate_service.create_intermediate_type(
            db_session, IntermediateTypeCreate(code=code, name="A"), user=None,
        )
        with pytest.raises(DuplicateException):
            await intermediate_service.create_intermediate_type(
                db_session, IntermediateTypeCreate(code=code, name="B"), user=None,
            )

    async def test_create_with_product(self, db_session: AsyncSession) -> None:
        """创建标记为成品的中间体并关联产品，返回含 product_name。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        result = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(
                code=rand_code("IM"), name="成品A", is_product=True,
                product_id=product.id,
            ),
            user=None,
        )
        assert result.is_product is True
        assert result.product_name == product.product_name

    def test_create_is_product_without_product_rejected(self) -> None:
        """Schema 层校验：is_product=True 但没有 product_id 时抛出 ValidationError。"""
        with pytest.raises(ValueError, match="标记为成品时必须关联产品"):
            IntermediateTypeCreate(
                code=rand_code("IM"), name="成品", is_product=True,
            )

    async def test_create_with_nonexistent_product_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """关联不存在的 product_id 时抛出 NotFoundException。"""
        with pytest.raises(NotFoundException, match="产品"):
            await intermediate_service.create_intermediate_type(
                db_session,
                IntermediateTypeCreate(
                    code=rand_code("IM"), name="X", product_id=uuid.uuid4(),
                ),
                user=None,
            )


class TestUpdateIntermediateType:
    async def test_update_name(self, db_session: AsyncSession) -> None:
        """更新中间体的名称字段，返回更新后的名称。"""
        obj = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(code=rand_code("IM"), name="旧名"),
            user=None,
        )
        updated = await intermediate_service.update_intermediate_type(
            db_session, obj.id, IntermediateTypeUpdate(name="新名"), user=None,
        )
        assert updated.name == "新名"

    async def test_update_nonexistent_rejected(self, db_session: AsyncSession) -> None:
        """更新不存在的中间体抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await intermediate_service.update_intermediate_type(
                db_session, uuid.uuid4(), IntermediateTypeUpdate(name="x"), user=None,
            )

    async def test_update_set_is_product_requires_product(
        self, db_session: AsyncSession,
    ) -> None:
        """Schema 层校验：IntermediateTypeUpdate 设 is_product=True 无 product_id 时抛 ValidationError。"""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IntermediateTypeUpdate(is_product=True)

    async def test_update_product_id_to_valid(self, db_session: AsyncSession) -> None:
        """更新中间体关联到有效产品，返回 product_name 正确填充。"""
        product = await route_service.create_product(
            db_session, ProductCreate(product_name=rand_code("产品")), user=None,
        )
        obj = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(code=rand_code("IM"), name="X"),
            user=None,
        )
        updated = await intermediate_service.update_intermediate_type(
            db_session, obj.id,
            IntermediateTypeUpdate(product_id=product.id),
            user=None,
        )
        assert updated.product_name == product.product_name


class TestDeleteIntermediateType:
    async def test_soft_delete(self, db_session: AsyncSession) -> None:
        """软删除后通过 get_detail 查询抛出 NotFoundException。"""
        obj = await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(code=rand_code("IM"), name="X"),
            user=None,
        )
        await intermediate_service.delete_intermediate_type(
            db_session, obj.id, user=None,
        )
        with pytest.raises(NotFoundException):
            await intermediate_service.get_intermediate_type_detail(
                db_session, obj.id,
            )

    async def test_delete_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """删除不存在的中间体抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await intermediate_service.delete_intermediate_type(
                db_session, uuid.uuid4(), user=None,
            )

    async def test_delete_then_recreate_same_code(
        self, db_session: AsyncSession,
    ) -> None:
        """软删除后同一 code 可再次创建，新记录的 id 与旧的不同。"""
        code = rand_code("IM")
        obj1 = await intermediate_service.create_intermediate_type(
            db_session, IntermediateTypeCreate(code=code, name="A"), user=None,
        )
        await intermediate_service.delete_intermediate_type(
            db_session, obj1.id, user=None,
        )
        obj2 = await intermediate_service.create_intermediate_type(
            db_session, IntermediateTypeCreate(code=code, name="B"), user=None,
        )
        assert obj2.id != obj1.id
        assert obj2.code == code


class TestListIntermediateTypes:
    async def test_list_paged(self, db_session: AsyncSession) -> None:
        """分页查询中间体列表，关键词匹配 code 能检索到结果。"""
        code = rand_code("IM")
        await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(code=code, name="测试中间体"),
            user=None,
        )
        _items, total = await intermediate_service.list_intermediate_types_paged(
            db_session, keyword=code, page=1, page_size=10,
        )
        assert total >= 1

    async def test_keyword_filter(self, db_session: AsyncSession) -> None:
        """按名称关键词精确匹配只返回一条记录。"""
        code = rand_code("IM")
        await intermediate_service.create_intermediate_type(
            db_session,
            IntermediateTypeCreate(code=code, name="唯一名称"),
            user=None,
        )
        _items, total = await intermediate_service.list_intermediate_types_paged(
            db_session, keyword="唯一名称", page=1, page_size=10,
        )
        assert total == 1

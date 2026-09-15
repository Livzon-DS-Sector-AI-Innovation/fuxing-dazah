"""生产模块跨模块 public_api 的轻量契约测试。"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.public_api import (
    get_intermediate_type_briefs,
    get_product_briefs,
)


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> Iterator[object]:
        return iter(self._rows)


class _Db:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def execute(self, _statement: Any) -> _ScalarResult:
        return _ScalarResult(self.rows)


async def test_product_briefs_preserve_input_order_and_skip_missing() -> None:
    """产品摘要按输入 ID 顺序返回，并跳过不存在或重复的来源对象。"""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    db = _Db(
        [
            SimpleNamespace(
                id=second_id,
                product_code="P-2",
                product_name="产品二",
                is_deleted=False,
            ),
            SimpleNamespace(
                id=first_id,
                product_code=None,
                product_name="产品一",
                is_deleted=False,
            ),
        ]
    )

    result = await get_product_briefs(cast(AsyncSession, db), [first_id, uuid.uuid4(), second_id, first_id])

    assert [item.id for item in result] == [first_id, second_id]
    assert result[0].product_code is None
    assert result[0].product_name == "产品一"
    assert result[1].code == "P-2"
    assert result[1].is_active is True


async def test_product_briefs_accept_uuid_strings() -> None:
    """生产产品公共接口兼容 UUID 字符串选择器。"""
    product_id = uuid.uuid4()
    db = _Db(
        [
            SimpleNamespace(
                id=product_id,
                product_code="P-STRING",
                product_name="字符串 ID 产品",
                is_deleted=False,
            )
        ]
    )

    result = await get_product_briefs(cast(AsyncSession, db), [str(product_id)])

    assert [item.id for item in result] == [product_id]


async def test_intermediate_type_briefs_expose_type_snapshot_fields() -> None:
    """中间体类型摘要提供 QA 来源快照所需的编码、名称和分类字段。"""
    type_id = uuid.uuid4()
    db = _Db(
        [
            SimpleNamespace(
                id=type_id,
                code="MAT-01",
                name="中间体一",
                category="粉体",
                is_product=False,
                product_id=None,
                is_deleted=False,
            )
        ]
    )

    result = await get_intermediate_type_briefs(cast(AsyncSession, db), [type_id])

    assert len(result) == 1
    assert result[0].intermediate_type_code == "MAT-01"
    assert result[0].intermediate_type_name == "中间体一"
    assert result[0].category == "粉体"

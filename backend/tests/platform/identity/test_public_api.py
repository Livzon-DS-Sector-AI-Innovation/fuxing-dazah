"""身份平台部门 public_api 契约测试。"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.public_api import get_department_briefs


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


async def test_department_briefs_accept_local_and_feishu_ids() -> None:
    """部门公共接口同时支持本地 UUID 和飞书部门 ID 查询。"""
    local_id = uuid.uuid4()
    external_id = "oc_dept_quality"
    db = _Db(
        [
            SimpleNamespace(
                id=local_id,
                feishu_department_id=external_id,
                name="质量部",
                parent_feishu_department_id=None,
                path='[{"name":"质量部"}]',
                status_is_deleted=False,
                is_deleted=False,
            )
        ]
    )

    result = await get_department_briefs(cast(AsyncSession, db), [external_id, local_id])

    assert len(result) == 1
    assert result[0].id == local_id
    assert result[0].department_id == local_id
    assert result[0].code == external_id
    assert result[0].is_active is True


async def test_empty_department_selectors_do_not_query_database() -> None:
    """没有部门选择器时直接返回空结果，不访问数据库。"""
    class _FailingDb:
        async def execute(self, _statement: Any) -> Any:
            raise AssertionError("empty selector must return before querying")

    assert await get_department_briefs(cast(AsyncSession, _FailingDb())) == []

"""身份平台的稳定只读公共接口。

业务模块需要引用组织架构时，只依赖本文件中的摘要契约，不直接依赖
``identity.repository`` 或 ``identity.models`` 的实现细节。部门以飞书部门 ID
为外部稳定身份；返回的 ``name``/``path`` 是查询时的当前值，业务模块如需
历史追溯应自行保存快照。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.platform.identity.models import Department, User
from app.platform.identity.repository import active_department_filters
from app.shared.sql import escape_like


@dataclass(frozen=True, slots=True)
class DepartmentBrief:
    """飞书组织部门摘要，供业务模块做选择和存在性校验。"""

    id: uuid.UUID
    feishu_department_id: str
    name: str
    parent_feishu_department_id: str | None = None
    path: str | None = None
    status_is_deleted: bool = False
    is_deleted: bool = False

    @property
    def department_id(self) -> uuid.UUID:
        """兼容调用方使用 ``department_id`` 的命名。"""
        return self.id

    @property
    def code(self) -> str:
        """部门的跨模块可读编码采用飞书部门 ID。"""
        return self.feishu_department_id

    @property
    def is_active(self) -> bool:
        return not self.is_deleted and not self.status_is_deleted


def _department_brief(row: Department) -> DepartmentBrief:
    return DepartmentBrief(
        id=row.id,
        feishu_department_id=row.feishu_department_id,
        name=row.name,
        parent_feishu_department_id=row.parent_feishu_department_id,
        path=row.path,
        status_is_deleted=bool(row.status_is_deleted),
        is_deleted=bool(row.is_deleted),
    )


def _try_uuid(value: object) -> uuid.UUID | None:
    """将字符串形式的本地 UUID 安全解析出来。

    飞书 ID 通常不是 UUID；对 UUID 字符串做解析可以让 ``get_department_briefs``
    同时兼容本地 UUID 和飞书 ID 输入，而不会把任意字符串绑定到 UUID 列导致
    asyncpg 类型转换错误。
    """
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return None


def _ordered_briefs(
    selectors: Sequence[object],
    rows: Iterable[DepartmentBrief],
) -> list[DepartmentBrief]:
    """按传入选择器顺序返回部门，并去掉重复项。"""
    by_id = {row.id: row for row in rows}
    by_feishu = {row.feishu_department_id: row for row in rows}
    result: list[DepartmentBrief] = []
    seen: set[uuid.UUID] = set()
    for selector in selectors:
        row: DepartmentBrief | None = None
        parsed = _try_uuid(selector)
        if parsed is not None:
            row = by_id.get(parsed)
        if row is None and isinstance(selector, str):
            row = by_feishu.get(selector)
        if row is not None and row.id not in seen:
            seen.add(row.id)
            result.append(row)
    return result


def _selector_values(value: Sequence[uuid.UUID | str] | uuid.UUID | str | None) -> list[object]:
    """将单值或序列统一为选择器列表。"""
    if value is None:
        return []
    if isinstance(value, (uuid.UUID, str)):
        return [value]
    return list(value)


async def get_department_briefs(
    db: AsyncSession,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None = None,
    *,
    feishu_ids: Sequence[str] | str | None = None,
    feishu_department_ids: Sequence[str] | str | None = None,
    include_deleted: bool = False,
) -> list[DepartmentBrief]:
    """按本地 UUID 或飞书部门 ID 批量获取部门摘要。

    ``ids`` 可传 ``uuid.UUID``、本地 UUID 字符串或飞书部门 ID 字符串；也可
    使用显式的 ``feishu_ids``/``feishu_department_ids`` 参数。默认只返回当前
    可用部门，不存在或已删除的选择器会被省略，便于调用方做整批存在性校验。
    """
    selectors = _selector_values(ids)
    selectors.extend(_selector_values(feishu_ids))
    selectors.extend(_selector_values(feishu_department_ids))
    if not selectors:
        return []

    local_ids: list[uuid.UUID] = []
    external_ids: list[str] = []
    for selector in selectors:
        parsed = _try_uuid(selector)
        if parsed is not None:
            local_ids.append(parsed)
        elif isinstance(selector, str) and selector:
            external_ids.append(selector)

    predicates = active_department_filters(include_deleted=include_deleted)
    identity_filter: list[ColumnElement[bool]] = []
    if local_ids:
        identity_filter.append(Department.id.in_(local_ids))
    if external_ids:
        identity_filter.append(
            Department.feishu_department_id.in_(external_ids)
        )
    if not identity_filter:
        return []

    stmt = select(Department).where(or_(*identity_filter), *predicates)
    rows = [_department_brief(row) for row in (await db.execute(stmt)).scalars()]
    return _ordered_briefs(selectors, rows)


async def get_department_brief(
    db: AsyncSession,
    department_id: uuid.UUID | str,
    *,
    include_deleted: bool = False,
) -> DepartmentBrief | None:
    """按本地 UUID 或飞书部门 ID 获取单个摘要。"""
    rows = await get_department_briefs(
        db, [department_id], include_deleted=include_deleted,
    )
    return rows[0] if rows else None


async def list_departments(
    db: AsyncSession,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 100,
    *,
    include_deleted: bool = False,
) -> tuple[list[DepartmentBrief], int]:
    """按名称/飞书 ID 搜索部门摘要并返回 ``(items, total)``。"""
    page = max(page, 1)
    page_size = max(page_size, 1)
    predicates = active_department_filters(include_deleted=include_deleted)
    value = keyword.strip() if keyword else ""
    if value:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        pattern = f"%{escape_like(value)}%"
        predicates.append(
            or_(
                Department.name.ilike(pattern, escape="\\"),
                Department.feishu_department_id.ilike(pattern, escape="\\"),
                Department.path.ilike(pattern, escape="\\"),
            )
        )

    count_stmt = select(func.count(Department.id)).select_from(Department)
    if predicates:
        count_stmt = count_stmt.where(*predicates)
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = select(Department)
    if predicates:
        stmt = stmt.where(*predicates)
    stmt = (
        stmt.order_by(Department.order, Department.name, Department.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = [_department_brief(row) for row in (await db.execute(stmt)).scalars()]
    return rows, total


async def list_department_briefs(
    db: AsyncSession,
    keyword: str | None = None,
    *,
    include_deleted: bool = False,
) -> list[DepartmentBrief]:
    """返回部门摘要列表（不分页），适合表单下拉和引用选择器。"""
    items, _ = await list_departments(
        db,
        keyword=keyword,
        page=1,
        page_size=10000,
        include_deleted=include_deleted,
    )
    return items


async def get_user_names(
    db: AsyncSession, user_ids: Iterable[uuid.UUID | str | None]
) -> dict[uuid.UUID, str]:
    """按 ID 批量取用户姓名。

    列表页展示操作者/负责人时用，一次查完避免逐行查库。查不到的 ID（已删除或
    不存在）不出现在结果里，调用方自行回退到显示 ID。
    """
    wanted = {uid for uid in (_try_uuid(value) for value in user_ids) if uid is not None}
    if not wanted:
        return {}
    result = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {row.id: row.name for row in result}


__all__ = [
    "DepartmentBrief",
    "get_department_briefs",
    "get_department_brief",
    "get_user_names",
    "list_departments",
    "list_department_briefs",
]

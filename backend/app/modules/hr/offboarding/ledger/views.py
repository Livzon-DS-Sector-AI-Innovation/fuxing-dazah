"""离职台账保存视图（个人维度）：常用筛选条件 + 导出字段一键调用（方案 §3.8）。

视图只属于创建它的人（owner_user_id），别人看不到也改不了；同一人同名视图只允许一个。
筛选条件与字段 key 存的就是列表查询 / 导出用的参数名，调用时原样回传。
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.ledger.export import COLUMN_BY_KEY
from app.modules.hr.offboarding.models import DepartureSavedView


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def view_dict(view: DepartureSavedView) -> dict[str, Any]:
    return {
        "id": str(view.id),
        "name": view.name,
        "filters": view.filters or {},
        "columns": view.columns or [],
        "is_default": view.is_default,
        "created_at": _iso(view.created_at),
    }


def _clean_columns(columns: list[str] | None) -> list[str]:
    """丢掉注册表里已经不存在的字段 key，旧视图不会把导出带崩。"""
    return [key for key in (columns or []) if key in COLUMN_BY_KEY]


async def _owned_view(db: AsyncSession, owner_id: UUID, view_id: UUID) -> DepartureSavedView:
    view = await repo.get_saved_view(db, view_id)
    if view is None or view.owner_user_id != owner_id:
        raise NotFoundException("保存视图", str(view_id))
    return view


async def _ensure_name_free(
    db: AsyncSession, owner_id: UUID, name: str, *, exclude_id: UUID | None = None,
) -> None:
    for view in await repo.list_saved_views(db, owner_id):
        if view.name == name and view.id != exclude_id:
            raise AppException(message=f"已有名为「{name}」的视图")


async def list_views(db: AsyncSession, owner_id: UUID) -> list[DepartureSavedView]:
    return await repo.list_saved_views(db, owner_id)


async def create_view(
    db: AsyncSession, owner_id: UUID, *, name: str, filters: dict[str, Any] | None,
    columns: list[str] | None, is_default: bool = False,
) -> DepartureSavedView:
    name = name.strip()
    if not name:
        raise AppException(message="视图名称不能为空")
    await _ensure_name_free(db, owner_id, name)
    if is_default:
        await repo.clear_default_saved_views(db, owner_id)
    view = DepartureSavedView(
        owner_user_id=owner_id, name=name, filters=filters or {},
        columns=_clean_columns(columns), is_default=is_default,
    )
    db.add(view)
    await db.commit()
    return view


async def update_view(
    db: AsyncSession, owner_id: UUID, view_id: UUID, *, name: str | None = None,
    filters: dict[str, Any] | None = None, columns: list[str] | None = None,
    is_default: bool | None = None,
) -> DepartureSavedView:
    view = await _owned_view(db, owner_id, view_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise AppException(message="视图名称不能为空")
        await _ensure_name_free(db, owner_id, name, exclude_id=view.id)
        view.name = name
    if filters is not None:
        view.filters = filters
    if columns is not None:
        view.columns = _clean_columns(columns)
    if is_default is not None:
        if is_default:
            await repo.clear_default_saved_views(db, owner_id)
        view.is_default = is_default
    await db.commit()
    return view


async def delete_view(db: AsyncSession, owner_id: UUID, view_id: UUID) -> None:
    view = await _owned_view(db, owner_id, view_id)
    view.is_deleted = True
    await db.commit()

"""部门管理业务工作流。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.meter import repository as repo
from app.modules.meter.models import Department
from app.modules.meter.schemas import DepartmentCreate, DepartmentUpdate


async def get_personnel_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    """从平台 identity.users 查询所有用户，作为负责人候选人列表。"""
    from sqlalchemy import select as sa_select

    from app.platform.identity.models import User

    stmt = sa_select(User).where(
        User.is_deleted == False,  # noqa: E712
    ).order_by(User.name)
    result = await db.execute(stmt)
    users = result.scalars().all()

    return [
        {
            "name": u.name,
            "feishu_open_id": u.feishu_open_id or "",
            "department": u.department,
        }
        for u in users
    ]


async def create_department(
    db: AsyncSession, data: DepartmentCreate
) -> Department:
    name = data.name.strip()
    if not name:
        raise ValueError("部门名称不能为空")
    existing = await repo.get_department_by_source_and_name(db, data.source, name)
    if existing:
        raise DuplicateException("部门名称", name)
    return await repo.create_department(db, {
        "source": data.source,
        "name": name,
        "heads": data.heads or [],
    })


async def list_departments(
    db: AsyncSession, source: str | None = None
) -> list[dict[str, Any]]:
    depts = await repo.list_departments(db, source=source)
    results: list[dict[str, Any]] = []
    for d in depts:
        counts = await repo.count_records_by_department(db, d.name)
        record_count = counts["instrument_count"] if d.source == "instrument" else counts["gas_detector_count"]
        results.append({
            "id": str(d.id),
            "source": d.source,
            "name": d.name,
            "heads": d.heads or [],
            "auto_notify_enabled": d.auto_notify_enabled,
            "record_count": record_count,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        })
    return results


async def update_department(
    db: AsyncSession, dept_id: UUID, data: DepartmentUpdate
) -> Department:
    dept = await repo.get_department_by_id(db, dept_id)
    if dept is None:
        raise NotFoundException("部门", str(dept_id))

    new_name = data.name.strip()
    if not new_name:
        raise ValueError("部门名称不能为空")
    if new_name != dept.name:
        # 检查新名称是否与其他记录冲突
        conflict = await repo.get_department_by_source_and_name(
            db, dept.source, new_name, exclude_id=dept_id
        )
        if conflict:
            raise DuplicateException("部门名称", new_name)

        # 联动更新对应表中所有匹配记录
        await repo.rename_department_in_records(db, dept.name, new_name, dept.source)

    # 构建更新字段
    update_fields: dict[str, Any] = {"name": new_name}
    if data.heads is not None:
        update_fields["heads"] = data.heads
    if data.auto_notify_enabled is not None:
        update_fields["auto_notify_enabled"] = data.auto_notify_enabled

    updated = await repo.update_department(db, dept_id, update_fields)
    if updated is None:
        raise NotFoundException("部门", str(dept_id))
    return updated


async def delete_department(db: AsyncSession, dept_id: UUID) -> None:
    dept = await repo.get_department_by_id(db, dept_id)
    if dept is None:
        raise NotFoundException("部门", str(dept_id))

    # 检查是否还有本来源的记录使用该部门名
    counts = await repo.count_records_by_department(db, dept.name)
    total = counts["instrument_count"] if dept.source == "instrument" else counts["gas_detector_count"]
    if total > 0:
        raise DuplicateException(
            "部门", f"{dept.name}（仍有 {total} 条记录使用，无法删除）"
        )

    deleted = await repo.soft_delete_department(db, dept_id)
    if not deleted:
        raise NotFoundException("部门", str(dept_id))


# ═══════════════════════════════════════════
# 检定到期飞书通知
# ═══════════════════════════════════════════

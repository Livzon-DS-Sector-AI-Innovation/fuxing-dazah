"""用户多部门访问权限管理接口"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope, require_hr_access

router = APIRouter(tags=["HR-多部门访问控制"])


@router.get("/my-scope", summary="调试：查看当前用户的数据范围")
async def my_scope(
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """返回当前用户的有效数据范围信息（调试用）。"""
    return success_response(data={
        "data_scope": hr_scope.data_scope,
        "own_department": hr_scope.department,
        "scoped_departments": sorted(hr_scope.scoped_departments) if hr_scope.scoped_departments else None,
        "is_unrestricted": hr_scope.is_unrestricted,
        "employee_number": hr_scope.employee_number,
    })


@router.get("/training-admins", summary="培训管理员候选列表（来自部门培训人员表）")
async def list_training_admins(
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage")),
):
    """从部门培训人员表的 training_admin 字段中提取人名，匹配 identity.users 返回可选用户列表。"""
    from app.modules.hr.models import DeptTrainingPersonnel
    from app.platform.identity.models import User as IdentityUser

    # 查出所有非空 training_admin 值并拼接为一个长字符串用于匹配
    rows = (await session.execute(
        select(DeptTrainingPersonnel.training_admin).where(
            DeptTrainingPersonnel.is_deleted == False,  # noqa: E712
            DeptTrainingPersonnel.training_admin.isnot(None),
            DeptTrainingPersonnel.training_admin != "",
        )
    )).scalars().all()
    all_admin_text = "".join(rows)

    # 查出 identity.users 中名字出现在 training_admin 文本中的用户
    users = (await session.execute(
        select(IdentityUser).where(
            IdentityUser.is_deleted == False,  # noqa: E712
        ).order_by(IdentityUser.name)
    )).scalars().all()

    data = [
        {"id": str(u.id), "name": u.name, "employee_no": u.employee_no}
        for u in users
        if u.name in all_admin_text
    ]

    return success_response(data=data)


class UserDepartmentAccessCreate(BaseModel):
    user_id: UUID
    department: str


@router.get("/user-department-access", summary="列出所有多部门访问授权")
async def list_user_dept_access(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage")),
):
    from app.modules.hr.models import HrUserDepartmentAccess
    from app.platform.identity.models import User as IdentityUser

    base = (
        select(HrUserDepartmentAccess, IdentityUser.name)
        .outerjoin(IdentityUser, HrUserDepartmentAccess.user_id == IdentityUser.id)
        .where(HrUserDepartmentAccess.is_deleted == False)  # noqa: E712
        .order_by(HrUserDepartmentAccess.created_at.desc())
    )
    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0
    rows = (await session.execute(
        base.offset((page - 1) * page_size).limit(page_size)
    )).all()
    data = [
        {
            "id": str(row[0].id),
            "user_id": str(row[0].user_id),
            "user_name": row[1],
            "department": row[0].department,
            "created_at": str(row[0].created_at) if row[0].created_at else None,
        }
        for row in rows
    ]
    return paginated_response(data=data, page=page, page_size=page_size, total=total)


@router.post("/user-department-access", summary="添加多部门访问授权")
async def create_user_dept_access(
    payload: UserDepartmentAccessCreate,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage")),
):
    from app.modules.hr.models import HrUserDepartmentAccess

    existing = (await session.execute(
        select(HrUserDepartmentAccess).where(
            HrUserDepartmentAccess.user_id == payload.user_id,
            HrUserDepartmentAccess.department == payload.department,
            HrUserDepartmentAccess.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该用户已拥有此部门的访问权限")

    record = HrUserDepartmentAccess(
        user_id=payload.user_id,
        department=payload.department,
    )
    session.add(record)
    await session.commit()
    return success_response(message="授权已添加", status_code=201)


@router.delete("/user-department-access/{mapping_id}", summary="移除多部门访问授权")
async def delete_user_dept_access(
    mapping_id: UUID,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage")),
):
    from app.modules.hr.models import HrUserDepartmentAccess

    record = (await session.execute(
        select(HrUserDepartmentAccess).where(
            HrUserDepartmentAccess.id == mapping_id,
            HrUserDepartmentAccess.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "授权记录不存在")
    record.is_deleted = True
    await session.commit()
    return success_response(message="授权已移除")

"""人事模块组合式访问依赖。

将权限检查 + 数据范围解析打包为 HrAccessContext，供 API 端点统一使用。

数据范围语义（HR 的"体现部门"无层级概念，department_and_children 等同 department）：
- all: 不过滤
- department / department_and_children: 只能访问登录人所在体现部门的数据
- self_only: 只能访问本人（按工号匹配员工档案）的数据

登录人部门的判定方式：用飞书账号上的工号反查 hr.employees 的体现部门，
保证与 HR 台账口径一致，避免飞书组织架构部门名与体现部门对不上的问题。
"""

import re
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenException
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission, require_user
from app.platform.permission.repository import PermissionRepository

_perm_repo = PermissionRepository()


@dataclass
class HrAccessContext:
    """人事模块访问上下文——用户信息 + 数据范围。"""

    user: User
    data_scope: str  # "all" | "department" | "department_and_children" | "self_only"
    department: str | None  # 登录人在员工档案中的体现部门（数据范围受限时解析）
    employee_number: str | None
    scoped_departments: frozenset[str] = frozenset()  # 多部门数据范围（含本部门 + hr.user_department_access）

    @property
    def is_unrestricted(self) -> bool:
        return self.data_scope == "all"

    @property
    def scoped_department(self) -> str | None:
        """需要按部门过滤时返回部门名，否则 None。
        多部门时返回第一个部门（向后兼容），仍建议新代码使用 scoped_departments。"""
        if self.data_scope in ("department", "department_and_children"):
            if self.scoped_departments:
                return next(iter(self.scoped_departments))
            return self.department
        return None

    def ensure_can_access_employee(self, employee) -> None:
        """校验单条员工记录是否在数据范围内，越界抛 403。"""
        if self.is_unrestricted:
            return
        if self.data_scope == "self_only":
            if employee.employee_number != self.employee_number:
                raise ForbiddenException("数据范围限制：仅可访问本人记录")
        elif self.scoped_departments:
            if employee.department not in self.scoped_departments:
                raise ForbiddenException("数据范围限制：仅可访问授权部门员工")
        elif employee.department != self.department:
            raise ForbiddenException("数据范围限制：仅可访问本部门员工")

    def apply_list_scope(self, stmt, employee):
        """对关联了员工表的列表查询施加数据范围过滤。

        - all：原样返回（调用方可继续使用前端传入的 department 筛选参数）
        - self_only：按工号过滤到本人
        - department / department_and_children：按体现部门过滤（支持多部门）
        """
        if self.is_unrestricted:
            return stmt
        if self.data_scope == "self_only":
            return stmt.where(employee.employee_number == self.employee_number)
        # 「未分类」人员按实际部门归属授权部门
        if self.scoped_departments:
            return stmt.where(or_(
                employee.department.in_(self.scoped_departments),
                and_(employee.department == "未分类", employee.actual_department.in_(self.scoped_departments)),
            ))
        return stmt.where(or_(
            employee.department == self.department,
            and_(employee.department == "未分类", employee.actual_department == self.department),
        ))

    def ensure_dept_writable(self, departments: list[str | None]) -> None:
        """校验写入的部门是否在数据范围内，越界抛 403。

        - all：放行
        - department / department_and_children：部门必须都在 scoped_departments 内
        - self_only：无部门数据可写，直接拒绝
        """
        if self.is_unrestricted:
            return
        scoped = self.scoped_departments
        if not scoped:
            raise ForbiddenException("数据范围限制：仅可操作本人相关数据")
        for d in departments:
            if d and d not in scoped:
                raise ForbiddenException(f"数据范围限制：您无权操作部门 '{d}' 的数据")

    def resolve_export_department(self, requested: str | None) -> str | None:
        """文档导出时按数据范围收敛部门参数。"""
        if self.is_unrestricted:
            return requested
        if not self.scoped_departments:
            raise ForbiddenException("数据范围限制：无法确定您的部门，请联系管理员")
        if requested and requested not in self.scoped_departments:
            raise ForbiddenException(f"数据范围限制：您无权访问部门 '{requested}'")
        return requested or (next(iter(self.scoped_departments)) if len(self.scoped_departments) == 1 else None)


async def check_sensitive_permission(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> bool:
    """检查当前用户是否有敏感信息查看权限"""
    from app.platform.identity.deps import get_current_user
    from app.core.config import get_settings as _gs
    user = await get_current_user(request, db=db, settings=_gs())
    if user is None:
        return False
    perms = await _perm_repo.get_user_permission_codes(db, user.id)
    return "hr:profile:sensitive" in perms


def require_hr_access(*codes: str):
    """组合依赖工厂：权限检查 + 数据范围解析。

    用法:
        ctx: HrAccessContext = Depends(require_hr_access("hr:profile:read"))

    从首个权限码解析 resource（如 "hr:profile:read" → "profile"），
    传递给数据范围计算，确保只有拥有该 resource 权限的角色参与范围合并。
    """
    perm_dep = require_permission(*codes)
    _resource = codes[0].split(":")[1] if codes and ":" in codes[0] else None

    async def _dependency(
        user: User = Depends(perm_dep),
        db: AsyncSession = Depends(get_db),
    ) -> HrAccessContext:
        scope = await _perm_repo.get_effective_data_scope(
            db, user.id, "hr", resource=_resource,
        )
        department: str | None = None
        if scope != "all":
            # 飞书部门为主（权限管理体现的部门），取叶子部门名
            if user.department:
                department = user.department.rsplit("/", 1)[-1] if "/" in user.department else user.department
            # 飞书无部门时兜底查员工档案
            if not department and user.employee_no:
                from app.modules.hr.repository import EmployeeRepository
                emp = await EmployeeRepository(db).get_by_employee_number(user.employee_no)
                if emp:
                    department = emp.department

        # 计算多部门数据范围：员工档案部门 + user_department_access 合并
        scoped_departments: frozenset[str] = frozenset()
        if scope in ("department", "department_and_children"):
            dept_set: set[str] = set()
            if department:
                dept_set.add(department)
            from app.modules.hr.models import HrUserDepartmentAccess
            extra_depts = (await db.execute(
                select(HrUserDepartmentAccess.department).where(
                    HrUserDepartmentAccess.user_id == user.id,
                    HrUserDepartmentAccess.is_deleted == False,  # noqa: E712
                )
            )).scalars().all()
            dept_set.update(extra_depts)
            scoped_departments = frozenset(dept_set)

        return HrAccessContext(
            user=user,
            data_scope=scope,
            department=department,
            employee_number=user.employee_no,
            scoped_departments=scoped_departments,
        )

    return _dependency


def _resource_for_path(path: str, method: str) -> str | None:
    """按路径+方法在 _HR_PATH_PERMISSIONS 中查找权限码，提取 resource 段。

    用于数据范围按 resource 计算：只有拥有该 resource 权限的角色参与范围合并，
    避免用户凭其他资源的 data_scope=all 角色在整个 HR 模块被抬权。
    """
    for pattern, val in _HR_PATH_PERMISSIONS:
        if re.search(pattern, path):
            code = val.get(method) or val.get("*") if isinstance(val, dict) else val
            if code and ":" in code:
                return code.split(":")[1]
            return None
    return None


async def get_hr_scope(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HrAccessContext:
    """列表/导出接口的数据范围依赖（权限码校验由 router 级 require_hr_basic 把守，此处不重复）。

    fail-closed 语义：
    - 未登录 → 403（HR 所有端点都在 require_hr_basic 门禁之后，匿名访问本身就是异常）
    - department / department_and_children 但部门无法解析（员工档案无此工号且飞书部门为空）→ 403
    - self_only → 不解 department，由 apply_list_scope / ensure_can_access_employee 按工号过滤
    """
    from app.platform.identity.deps import get_current_user
    user = await get_current_user(request, db=db, settings=settings)
    if user is None:
        raise ForbiddenException("请先登录")
    resource = _resource_for_path(request.url.path, request.method)
    scope = await _perm_repo.get_effective_data_scope(db, user.id, "hr", resource=resource)
    import logging
    _log = logging.getLogger(__name__)
    _log.info("get_hr_scope: user=%s path=%s method=%s resource=%s scope=%s", user.name, request.url.path, request.method, resource, scope)
    department: str | None = None
    if scope in ("department", "department_and_children"):
        # 飞书部门为主（权限管理体现的部门），取叶子部门名
        if user.department:
            department = user.department.rsplit("/", 1)[-1] if "/" in user.department else user.department
        # 飞书无部门时兜底查员工档案
        if not department and user.employee_no:
            from app.modules.hr.repository import EmployeeRepository
            emp = await EmployeeRepository(db).get_by_employee_number(user.employee_no)
            if emp:
                department = emp.department
        if not department:
            raise ForbiddenException("数据范围限制：无法确定您的部门，请联系管理员")

    # 计算多部门数据范围：飞书部门 + user_department_access 合并
    scoped_departments: frozenset[str] = frozenset()
    if scope in ("department", "department_and_children"):
        dept_set: set[str] = set()
        if department:
            dept_set.add(department)
        from app.modules.hr.models import HrUserDepartmentAccess
        extra_depts = (await db.execute(
            select(HrUserDepartmentAccess.department).where(
                HrUserDepartmentAccess.user_id == user.id,
                HrUserDepartmentAccess.is_deleted == False,  # noqa: E712
            )
        )).scalars().all()
        dept_set.update(extra_depts)
        scoped_departments = frozenset(dept_set)

    return HrAccessContext(
        user=user,
        data_scope=scope,
        department=department,
        employee_number=user.employee_no,
        scoped_departments=scoped_departments,
    )


# ── 路径 → 权限码映射（用于自动权限校验） ──
# 规则：key 是正则，匹配 URL 路径；value 是 method→权限码 或 直接权限码
_HR_PATH_PERMISSIONS: list[tuple[str, str | dict[str, str]]] = [
    # 员工档案
    (r"/employees/export", "hr:profile:export"),
    (r"/employees/upload", "hr:profile:export"),
    (r"/employees/by-number", "hr:profile:read"),
    (r"/employees/batch-regularize", "hr:profile:update"),
    (r"/employees/.*/probation-extensions", "hr:profile:read"),
    (r"/employees/.*/onboarding-training-record", "hr:training:document"),
    (r"/employees/.*/prejob-training-plan", "hr:training:document"),
    (r"/employees/.*/training-registration", "hr:profile:export"),
    (r"/employees/training-candidates", "hr:profile:read"),
    (r"/employees/probation-expiring", "hr:profile:read"),
    (r"/employees", {"GET": "hr:profile:read", "POST": "hr:profile:create",
                     "PUT": "hr:profile:update", "DELETE": "hr:profile:delete"}),
    # 花名册
    (r"/roster", "hr:roster:read"),
    # 组织架构
    (r"/departments/", {"GET": "hr:org:read", "POST": "hr:org:manage",
                        "PUT": "hr:org:manage", "DELETE": "hr:org:manage"}),
    (r"/departments$", {"GET": "hr:org:read", "POST": "hr:org:manage",
                        "PUT": "hr:org:manage", "DELETE": "hr:org:manage"}),
    # 班组（组织架构）& 职位 & 内训师 & SOP/岗位培训（培训内容）
    (r"/teams", {"GET": "hr:org:read", "POST": "hr:org:manage",
                 "PUT": "hr:org:manage", "DELETE": "hr:org:manage"}),
    (r"/positions", {"GET": "hr:position:read", "POST": "hr:position:manage",
                     "PUT": "hr:position:manage", "DELETE": "hr:position:manage"}),
    (r"/position-trainings", {"GET": "hr:training:read", "POST": "hr:training:manage",
                              "PUT": "hr:training:manage", "DELETE": "hr:training:manage"}),
    (r"/trainers", {"GET": "hr:trainer:read", "POST": "hr:trainer:manage",
                    "PUT": "hr:trainer:manage", "DELETE": "hr:trainer:manage"}),
    (r"/sop-catalog", {"GET": "hr:training:read", "POST": "hr:training:manage",
                       "PUT": "hr:training:manage", "DELETE": "hr:training:manage"}),
    # SOP培训文件登记表（查看/编辑对所有人开放）
    # SOP培训二级表（查看开放；编辑/转培训需培训管理权限；批量生成材料需培训文档权限）
    (r"/sop-training-entries/batch-transfer", {"POST": "hr:training:manage"}),
    (r"/sop-training-entries/batch-materials", {"POST": "hr:training:document"}),
    (r"/sop-training-entries", {"PUT": "hr:training:manage", "POST": "hr:training:manage"}),
    (r"/dept-training-personnel", {"GET": "hr:training:read", "POST": "hr:training:manage",
                                    "PUT": "hr:training:manage", "DELETE": "hr:training:manage"}),
    # 入职管理
    (r"/onboarding-applications/.*/approve", "hr:onboarding:approve"),
    (r"/onboarding-applications", {"GET": "hr:onboarding:read", "POST": "hr:onboarding:manage",
                                   "PUT": "hr:onboarding:manage", "DELETE": "hr:onboarding:manage"}),
    (r"/offboarding-applications/.*/approve", "hr:onboarding:approve"),
    (r"/offboarding-applications", {"GET": "hr:onboarding:read", "POST": "hr:onboarding:manage",
                                    "PUT": "hr:onboarding:manage", "DELETE": "hr:onboarding:manage"}),
    (r"/onboarding-records", {"GET": "hr:onboarding:read", "POST": "hr:onboarding:manage",
                              "PUT": "hr:onboarding:manage", "DELETE": "hr:onboarding:manage"}),
    # 离职管理
    (r"/departure-records", {"GET": "hr:departure:read", "POST": "hr:departure:manage",
                             "PUT": "hr:departure:manage", "DELETE": "hr:departure:manage"}),
    (r"/offboarding-records", {"GET": "hr:departure:read", "POST": "hr:departure:manage",
                               "PUT": "hr:departure:manage", "DELETE": "hr:departure:manage"}),
    # 培训台账
    (r"/training-ledgers/admin/stats", "hr:training:read"),
    (r"/training-ledgers/admin/departments", "hr:training:read"),
    (r"/training-ledgers/admin/subjects", "hr:training:read"),
    (r"/training-ledgers/admin", "hr:training:read"),
    (r"/training-ledgers/batch-scores", "hr:training:manage"),
    (r"/training-ledgers/export", "hr:training:read"),
    (r"/training-ledgers/pages", {"GET": "hr:training:read", "POST": "hr:training:manage"}),
    (r"/training-ledgers", {"GET": "hr:training:read", "POST": "hr:training:manage",
                            "PUT": "hr:training:manage", "DELETE": "hr:training:manage"}),
    # 培训年度计划
    (r"/annual-training-plan", "hr:training:plan"),
    (r"/annual-plan-items", "hr:training:plan"),
    # 问答考核
    (r"/qa-assessments/.*/sync-ledger", "hr:training:manage"),
    (r"/qa-assessments/.*/export-", "hr:training:export"),
    (r"/qa-assessments/.*/scores", "hr:training:manage"),
    (r"/qa-assessments", {"GET": "hr:training:assessment",
                           "POST": "hr:training:manage",
                           "PUT": "hr:training:manage",
                           "DELETE": "hr:training:manage"}),
    # 共享题库
    (r"/question-bank", {"GET": "hr:training:questionbank",
                          "POST": "hr:training:manage",
                          "DELETE": "hr:training:manage"}),
    # 笔试试卷
    (r"/exam-papers", "hr:training:exam"),
    # 培训文档生成 & AI 出题
    (r"/training-sign-in-sheet", "hr:training:document"),
    (r"/training-notification/generate-assessment", "hr:training:manage"),
    (r"/training-notification/export-", "hr:training:export"),
    (r"/training-notification", "hr:training:document"),
    (r"/onboarding-evaluation", "hr:training:document"),
    (r"/training-evaluations/export-admin", "hr:training:export"),
    (r"/training-evaluations", "hr:training:document"),
    (r"/training-evaluation", "hr:training:document"),
    # 培训登记表
    (r"/training-registration", "hr:roster:read"),
    # 员工异动
    (r"/transfers", "hr:profile:transfer"),
    # 人事看板
    (r"/dashboard/stats", "hr:profile:read"),
    # 招聘管理 — 注意：具体路径必须在通用路径之前（re.search 首匹配即 break）
    (r"/candidates/pending-review", "hr:recruitment:read"),
    (r"/candidates/.*/push-review", "hr:recruitment:manage"),
    (r"/candidates/.*/decide-review", "hr:recruitment:manage"),
    (r"/candidates/.*/onboard", "hr:recruitment:manage"),
    (r"/recruitment/stats", "hr:recruitment:read"),
    (r"/recruitment", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                       "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
    (r"/candidates", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                      "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
    (r"/job-requirements/.*/candidates/comparison", "hr:recruitment:read"),
    (r"/job-requirements", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                            "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
    # 系统设置
    (r"/system-settings", {"GET": "hr:settings:manage", "PUT": "hr:settings:manage", "POST": "hr:settings:manage"}),
    (r"/user-department-access", {"GET": "hr:settings:manage", "POST": "hr:settings:manage",
                                   "DELETE": "hr:settings:manage"}),
    (r"/data-management", {"GET": "hr:settings:manage", "POST": "hr:settings:manage"}),
]


async def require_hr_basic(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """HR 模块智能门禁：根据请求路径+方法自动匹配权限码并校验。

    挂在 router 级别，自动对所有 HR 端点生效。
    """
    from app.platform.permission.deps import get_user_permissions

    perms = await get_user_permissions(str(user.id), db)

    path = request.url.path
    method = request.method

    # 在映射表中查找匹配的权限码
    required_perm: str | None = None
    for pattern, val in _HR_PATH_PERMISSIONS:
        if re.search(pattern, path):
            if isinstance(val, dict):
                required_perm = val.get(method) or val.get("*")
            else:
                required_perm = val
            break

    if required_perm and required_perm not in perms:
        raise ForbiddenException(f"缺少权限: {required_perm}")

    # 未匹配到的路径，有任意 hr: 权限即可
    if not any(p.startswith("hr:") for p in perms):
        raise ForbiddenException("无HR模块访问权限，请联系管理员分配角色")
    return user

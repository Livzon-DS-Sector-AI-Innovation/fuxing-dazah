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
from sqlalchemy.ext.asyncio import AsyncSession

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

    @property
    def is_unrestricted(self) -> bool:
        return self.data_scope == "all"

    @property
    def scoped_department(self) -> str | None:
        """需要按部门过滤时返回部门名，否则 None。"""
        if self.data_scope in ("department", "department_and_children"):
            return self.department
        return None

    def ensure_can_access_employee(self, employee) -> None:
        """校验单条员工记录是否在数据范围内，越界抛 403。"""
        if self.is_unrestricted:
            return
        if self.data_scope == "self_only":
            if employee.employee_number != self.employee_number:
                raise ForbiddenException("数据范围限制：仅可访问本人记录")
        elif employee.department != self.department:
            raise ForbiddenException("数据范围限制：仅可访问本部门员工")

    def resolve_export_department(self, requested: str | None) -> str | None:
        """文档导出时按数据范围收敛部门参数。"""
        if self.is_unrestricted:
            return requested
        if not self.scoped_department:
            raise ForbiddenException("数据范围限制：无法确定您的部门，请联系管理员")
        return self.scoped_department


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
            if user.employee_no:
                from app.modules.hr.repository import EmployeeRepository
                emp = await EmployeeRepository(db).get_by_employee_number(user.employee_no)
                if emp:
                    department = emp.department
            # 员工档案里找不到 → 用飞书用户表的部门兜底（取叶子部门名）
            if not department and user.department:
                department = user.department.rsplit("/", 1)[-1] if "/" in user.department else user.department
        return HrAccessContext(
            user=user,
            data_scope=scope,
            department=department,
            employee_number=user.employee_no,
        )

    return _dependency


# ── 路径 → 权限码映射（用于自动权限校验） ──
# 规则：key 是正则，匹配 URL 路径；value 是 method→权限码 或 直接权限码
_HR_PATH_PERMISSIONS: list[tuple[str, str | dict[str, str]]] = [
    # 员工档案
    (r"/employees/upload", "hr:employee:export"),
    (r"/employees/by-number", "hr:employee:read"),
    (r"/employees/batch-regularize", "hr:employee:update"),
    (r"/employees/.*/probation-extensions", "hr:employee:read"),
    (r"/employees/.*/onboarding-training-record", "hr:training:document"),
    (r"/employees/.*/prejob-training-plan", "hr:training:document"),
    (r"/employees/.*/training-registration", "hr:employee:export"),
    (r"/employees/training-candidates", "hr:employee:read"),
    (r"/employees/probation-expiring", "hr:employee:read"),
    (r"/employees", {"GET": "hr:employee:read", "POST": "hr:employee:create",
                     "PUT": "hr:employee:update", "DELETE": "hr:employee:delete"}),
    # 花名册
    (r"/roster", "hr:employee:export"),
    # 组织架构
    (r"/departments/", {"GET": "hr:org:read", "POST": "hr:org:manage",
                        "PUT": "hr:org:manage", "DELETE": "hr:org:manage"}),
    (r"/departments$", {"GET": "hr:org:read", "POST": "hr:org:manage",
                        "PUT": "hr:org:manage", "DELETE": "hr:org:manage"}),
    # 班组 & 职位 & 内训师 & SOP（系统设置）
    (r"/teams", "hr:settings:manage"),
    (r"/positions", "hr:settings:manage"),
    (r"/position-trainings", "hr:settings:manage"),
    (r"/trainers", "hr:settings:manage"),
    (r"/sop-catalog", "hr:settings:manage"),
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
    # 问答考核
    (r"/qa-assessments", "hr:training:assessment"),
    # 共享题库
    (r"/question-bank", "hr:training:questionbank"),
    # 笔试试卷
    (r"/exam-papers", "hr:training:exam"),
    # 培训文档生成
    (r"/training-sign-in-sheet", "hr:training:document"),
    (r"/training-notification", "hr:training:document"),
    (r"/onboarding-evaluation", "hr:training:document"),
    (r"/training-evaluations", "hr:training:document"),
    (r"/training-evaluation", "hr:training:document"),
    # 培训登记表
    (r"/training-registration", "hr:employee:export"),
    # 员工异动
    (r"/transfers", "hr:employee:transfer"),
    # 人事看板
    (r"/dashboard-stats", "hr:dashboard:read"),
    # 招聘管理
    (r"/recruitment", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                       "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
    (r"/candidates", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                      "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
    (r"/job-requirements", {"GET": "hr:recruitment:read", "POST": "hr:recruitment:manage",
                            "PUT": "hr:recruitment:manage", "DELETE": "hr:recruitment:manage"}),
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

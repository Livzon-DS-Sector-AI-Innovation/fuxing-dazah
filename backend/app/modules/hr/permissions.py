"""人事模块权限声明。"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 部门管理 ──
    PermissionDef("hr:department:read", "查看部门", "hr", "department", "read"),
    PermissionDef("hr:department:create", "新增部门", "hr", "department", "create"),
    PermissionDef("hr:department:update", "编辑部门", "hr", "department", "update"),
    PermissionDef("hr:department:delete", "删除部门", "hr", "department", "delete"),
    # ── 员工档案 ──
    PermissionDef("hr:profile:read", "查看员工档案", "hr", "profile", "read"),
    PermissionDef("hr:profile:create", "新增员工", "hr", "profile", "create"),
    PermissionDef("hr:profile:update", "编辑员工", "hr", "profile", "update"),
    PermissionDef("hr:profile:delete", "删除员工", "hr", "profile", "delete"),
    # ── 招聘管理 ──
    PermissionDef("hr:recruitment:read", "查看招聘", "hr", "recruitment", "read"),
    PermissionDef("hr:recruitment:create", "新增候选人", "hr", "recruitment", "create"),
    PermissionDef("hr:recruitment:update", "编辑候选人", "hr", "recruitment", "update"),
    PermissionDef("hr:recruitment:delete", "删除候选人", "hr", "recruitment", "delete"),
    # ── 入职台账 ──
    PermissionDef("hr:onboarding:read", "查看入职台账", "hr", "onboarding", "read"),
    PermissionDef("hr:onboarding:create", "新增入职记录", "hr", "onboarding", "create"),
    PermissionDef("hr:onboarding:update", "编辑入职记录", "hr", "onboarding", "update"),
    PermissionDef("hr:onboarding:delete", "删除入职记录", "hr", "onboarding", "delete"),
    # ── 离职台账 ──
    PermissionDef("hr:departure:read", "查看离职台账", "hr", "departure", "read"),
    PermissionDef("hr:departure:create", "新增离职记录", "hr", "departure", "create"),
    PermissionDef("hr:departure:update", "编辑离职记录", "hr", "departure", "update"),
    PermissionDef("hr:departure:delete", "删除离职记录", "hr", "departure", "delete"),
    # ── 培训管理 ──
    PermissionDef("hr:training:read", "查看培训", "hr", "training", "read"),
    PermissionDef("hr:training:create", "新增培训", "hr", "training", "create"),
    PermissionDef("hr:training:update", "编辑培训", "hr", "training", "update"),
    PermissionDef("hr:training:delete", "删除培训", "hr", "training", "delete"),
    # ── 人事看板 ──
    PermissionDef("hr:dashboard:read", "查看人事看板", "hr", "dashboard", "read"),
    # ── 花名册 ──
    PermissionDef("hr:roster:read", "查看员工花名册", "hr", "roster", "read"),
]

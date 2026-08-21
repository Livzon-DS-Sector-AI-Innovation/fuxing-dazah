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
    PermissionDef("hr:profile:export", "导出员工数据", "hr", "profile", "export"),
    PermissionDef("hr:profile:transfer", "管理员工异动", "hr", "profile", "transfer"),
    # ── 招聘管理 ──
    PermissionDef("hr:recruitment:read", "查看招聘", "hr", "recruitment", "read"),
    PermissionDef("hr:recruitment:manage", "管理招聘", "hr", "recruitment", "manage"),
    # ── 入职管理 ──
    PermissionDef("hr:onboarding:read", "查看入职台账", "hr", "onboarding", "read"),
    PermissionDef("hr:onboarding:manage", "管理入职记录", "hr", "onboarding", "manage"),
    PermissionDef("hr:onboarding:approve", "审批入职申请", "hr", "onboarding", "approve"),
    # ── 离职台账 ──
    PermissionDef("hr:departure:read", "查看离职台账", "hr", "departure", "read"),
    PermissionDef("hr:departure:manage", "管理离职记录", "hr", "departure", "manage"),
    # ── 培训管理 ──
    PermissionDef("hr:training:read", "查看培训", "hr", "training", "read"),
    PermissionDef("hr:training:manage", "管理培训（新增/编辑/删除）", "hr", "training", "manage"),
    PermissionDef("hr:training:export", "导出培训文档", "hr", "training", "export"),
    PermissionDef("hr:training:document", "生成培训文档", "hr", "training", "document"),
    PermissionDef("hr:training:assessment", "问答实操考核", "hr", "training", "assessment"),
    PermissionDef("hr:training:questionbank", "管理共享题库", "hr", "training", "questionbank"),
    PermissionDef("hr:training:exam", "管理笔试试卷", "hr", "training", "exam"),
    PermissionDef("hr:training:plan", "管理年度培训计划", "hr", "training", "plan"),
    # ── 花名册 ──
    PermissionDef("hr:roster:read", "查看员工花名册", "hr", "roster", "read"),
    # ── 组织架构 ──
    PermissionDef("hr:org:read", "查看组织架构", "hr", "org", "read"),
    PermissionDef("hr:org:manage", "管理组织架构", "hr", "org", "manage"),
    # ── 系统设置 ──
    PermissionDef("hr:settings:read", "查看系统设置", "hr", "settings", "read"),
    PermissionDef("hr:settings:manage", "管理系统设置", "hr", "settings", "manage"),
    # ── 岗位管理 ──
    PermissionDef("hr:position:read", "查看岗位管理", "hr", "position", "read"),
    PermissionDef("hr:position:manage", "管理岗位", "hr", "position", "manage"),
    # ── 内训师管理 ──
    PermissionDef("hr:trainer:read", "查看内训师", "hr", "trainer", "read"),
    PermissionDef("hr:trainer:manage", "管理内训师", "hr", "trainer", "manage"),
    # ── 绩效考核 ──
    PermissionDef("hr:performance:read", "查看绩效考核", "hr", "performance", "read"),
    PermissionDef("hr:performance:manage", "管理绩效考核", "hr", "performance", "manage"),
    # ── 敏感信息 ──
    PermissionDef("hr:profile:sensitive", "查看员工敏感信息（身份证等）", "hr", "profile", "sensitive"),
    # ── 职称评审 ──
    PermissionDef("hr:title:read", "查看职称评审", "hr", "title", "read"),
    PermissionDef("hr:title:manage", "管理职称评审（批次配置/评委指定）", "hr", "title", "manage"),
    PermissionDef("hr:title:scores:read", "查看职称评审分数（保密：各评委原始分）", "hr", "title", "scores:read"),
    PermissionDef("hr:title:judge", "职称评审评委投票", "hr", "title", "judge"),
]

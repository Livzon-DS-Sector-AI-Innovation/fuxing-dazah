export interface SubMenuItem {
  key: string
  label: string
  path: string
  children?: SubMenuItem[]   // 嵌套子菜单 → Ant Design SubMenu
  group?: boolean            // 分组标题式（antd Menu group 类型）：children 平铺展示不折叠
  disabled?: boolean         // 灰显占位，功能未开发
  permissions?: string[]     // 权限码，用于前端菜单可见性控制
  roles?: string[]           // 角色码（如 super_admin），与 permissions 同时声明时取 AND
}

export interface ModuleMenu {
  key: string
  label: string
  icon: string
  path: string
  children: SubMenuItem[]
  permissions?: string[]     // 权限码，用于前端菜单可见性控制
  clickableTitle?: boolean   // 侧边栏模块标题可点击跳转模块首页（无二级菜单的模块用）
}

/** QA 知识库读门禁：qa:all:read + 知识库资源的任意写码（写码隐含读）。 */
const QA_KNOWLEDGE_PERMISSIONS = [
  "qa:all:read",
  "qa:master:*",
  "qa:document:*",
  "qa:version:*",
  "qa:relation:*",
  "qa:config:*",
]

export const moduleMenus: ModuleMenu[] = [
  {
    key: "production",
    label: "生产管理",
    icon: "factory",
    path: "/production",
    permissions: ["production:*:read"],
    children: [
      { key: "dashboard", label: "生产看板", path: "/production" },
      { key: "planning-center", label: "计划中枢", path: "/production/planning-center" },
      { key: "master-data", label: "主数据管理", path: "/production/master-data" },
      {
        key: "notification-config",
        label: "通知配置",
        path: "/production/notification-config",
        permissions: ["production:notification:manage"],
      },
      {
        key: "manufacturing-unit",
        label: "制造单元",
        path: "",
        children: [
          { key: "workbench", label: "工作台", path: "/production/workbench" },
          { key: "process", label: "工艺路径", path: "/production/process" },
          { key: "batches", label: "批次管理", path: "/production/batches" },
        ],
      },
      { key: "materials", label: "产出物流水", path: "/production/materials" },
      { key: "analytics", label: "数据汇总", path: "/production/analytics" },
    ],
  },
  {
    key: "equipment",
    label: "设备管理",
    icon: "cog",
    path: "/equipment",
    permissions: ["equipment:*:read"],
    children: [
      { key: "stats", label: "设备仪表盘", path: "/equipment/stats", children: [
        { key: "stats-dashboard", label: "仪表盘概览", path: "/equipment/stats" },
        { key: "stats-analytics", label: "巡检分析", path: "/equipment/stats/analytics" },
        { key: "stats-availability", label: "设备分析", path: "/equipment/stats/availability" },
      ] },
      { key: "assets", label: "设备台账", path: "/equipment/assets" },
      { key: "maintenance", label: "维护保养", path: "/equipment/maintenance" },
      { key: "inspection", label: "设备巡检", path: "/equipment/inspection" },
      { key: "spare-parts", label: "备件管理", path: "/equipment/spare-parts" },
      { key: "personnel", label: "人员配置", path: "/equipment/personnel" },
    ],
  },
  {
    key: "energy",
    label: "能源管理",
    icon: "bolt",
    path: "/energy",
    permissions: ["energy:*:read"],
    children: [
      { key: "visualization", label: "可视化视图", path: "/energy/visualization" },
      { key: "collect-history", label: "采集历史", path: "/energy/collect-history" },
      { key: "type-config", label: "能源配置", path: "/energy/type-config" },
      { key: "devices", label: "数据源配置", path: "/energy/devices" },
      { key: "alerts", label: "预警管理", path: "/energy/alerts" },
      { key: "alert-process", label: "预警处理", path: "/energy/alert-process" },
      { key: "collect-logs", label: "采集日志", path: "/energy/collect-logs" },
    ],
  },
  {
    key: "meter",
    label: "仪表管理",
    icon: "gauge",
    path: "/meter",
    permissions: ["meter:*:read"],
    children: [
      // 总览/部门管理是管理侧功能，跟 meter:config:manage 走；
      // 台账两项对通配码与对应资源码可见，纯查询角色（只授资源码）看不到上面两项
      { key: "overview", label: "仪表总览", path: "/meter", permissions: ["meter:config:manage"] },
      { key: "instruments", label: "标准计量器具", path: "/meter/instruments", permissions: ["meter:*:read", "meter:instrument:read"] },
      { key: "gas-detectors", label: "有毒有害可燃探测器", path: "/meter/gas-detectors", permissions: ["meter:*:read", "meter:gas-detector:read"] },
      { key: "departments", label: "部门管理", path: "/meter/departments", permissions: ["meter:config:manage"] },
    ],
  },

  {
    key: "rd",
    label: "研发管理",
    icon: "beaker",
    path: "/rd",
    permissions: ["research:*:read"],
    children: [
      { key: "projects", label: "研发项目", path: "/rd/projects" },
      { key: "experiments", label: "实验记录", path: "/rd/experiments" },
      { key: "reports", label: "研发报告", path: "/rd/reports" },
    ],
  },
  {
    key: "registration",
    label: "注册管理",
    icon: "document",
    path: "/registration",
    permissions: ["registration:*:read"],
    children: [
      { key: "filing", label: "注册申报", path: "/registration/filing" },
      { key: "regulation", label: "法规跟踪", path: "/registration/regulation" },
      { key: "documents", label: "文件管理", path: "/registration/documents" },
    ],
  },
  {
    key: "quality",
    label: "质量管理",
    icon: "check-circle",
    path: "/quality/dashboard",
    permissions: ["quality:*:read"],
    children: [
      {
        key: "quality-materials-group",
        label: "物料管理",
        path: "/quality/materials",
        permissions: ["quality:material:read"],
        children: [
          { key: "quality-material-containers", label: "物料赋码", path: "/quality/materials", permissions: ["quality:material:read"] },
          { key: "quality-material-requests", label: "物料请验", path: "/quality/materials/requests", permissions: ["quality:material:read"] },
          { key: "quality-material-scan", label: "扫码操作台", path: "/quality/materials/scan", permissions: ["quality:material:manage"] },
        ],
      },
      { key: "quality-lab-items", label: "试剂/仪器台账", path: "/quality/lab-items", permissions: ["quality:material:read"] },
      { key: "quality-micro", label: "微生物登记", path: "/quality/micro", permissions: ["quality:material:read"] },
      { key: "quality-retained", label: "留样台账", path: "/quality/retained", permissions: ["quality:material:read"] },
      { key: "quality-env", label: "环境监测", path: "/quality/env", permissions: ["quality:env:read"] },
      {
        key: "quality-coa-group",
        label: "COA管理",
        path: "/quality/dashboard",
        children: [
          { key: "quality-dashboard", label: "质量总览", path: "/quality/dashboard", permissions: ["quality:report:read"] },
          { key: "lc-parser", label: "液相解析", path: "/quality", permissions: ["quality:lc:read"] },
          { key: "quality-task", label: "检验填报", path: "/quality/task", permissions: ["quality:task:read"] },
          { key: "quality-board", label: "任务看板", path: "/quality/board", permissions: ["quality:task:read"] },
          { key: "quality-summary", label: "汇总统计", path: "/quality/summary", permissions: ["quality:report:read"] },
          { key: "quality-standards", label: "产品标准", path: "/quality/standards", permissions: ["quality:task:read"] },
          { key: "quality-templates", label: "报告模板", path: "/quality/templates", permissions: ["quality:report:read"] },
          { key: "quality-report", label: "报告单", path: "/quality/report", permissions: ["quality:report:read"] },
          { key: "quality-serial", label: "报告单流水", path: "/quality/serial", permissions: ["quality:report:read"] },
          // 批放行：检验→报告链路末端，列表读口径与报告单一致（放行/退回操作按 task:review 在页内 gate）
          { key: "quality-release", label: "批放行", path: "/quality/release", permissions: ["quality:report:read"] },
        ],
      },
    ],
  },
  {
    key: "qa",
    label: "QA",
    icon: "document",
    path: "/qa",
    // 任一 QA 权限即可见（qa:*:* 是前端菜单匹配模式，不是权限码）；
    // 子项各自按后端读门禁过滤。
    permissions: ["qa:*:*"],
    children: [
      { key: "overview", label: "概览", path: "/qa", permissions: QA_KNOWLEDGE_PERMISSIONS },
      { key: "master-data", label: "质量主数据", path: "/qa/master-data", permissions: QA_KNOWLEDGE_PERMISSIONS },
      { key: "documents", label: "批准文件台账", path: "/qa/documents", permissions: QA_KNOWLEDGE_PERMISSIONS },
      // 偏差/CAPA 有独立读码；持 qa:all:read 的 QA 人员同样可见。
      { key: "deviation", label: "偏差管理", path: "/qa/deviation", permissions: ["qa:all:read", "qa:deviation:read", "qa:deviation:create", "qa:deviation:update"] },
      { key: "capa", label: "CAPA 管理", path: "/qa/capa", permissions: ["qa:all:read", "qa:capa:read", "qa:capa:create", "qa:capa:update"] },
      // 年度产品回顾（PQR）：一级分组 + 三个二级入口，各按权限显隐。
      // 可见性口径 = 「读得动该页」：所有 PQR 写码（enter/manage/export/lock）
      // 在后端隐含 PQR 读取；纯 read 用户也可进录入页只读查看（写按钮按 enter 单独 gate）。
      {
        key: "apr",
        label: "年度产品回顾",
        path: "/qa/apr",
        children: [
          { key: "apr-config", label: "模板配置", path: "/qa/apr/config", permissions: ["qa:apr:manage"] },
          { key: "apr-entry", label: "数据录入", path: "/qa/apr/entry", permissions: ["qa:all:read", "qa:apr:read", "qa:apr:enter", "qa:apr:manage", "qa:apr:export", "qa:apr:lock"] },
          { key: "apr-summary", label: "汇总分析", path: "/qa/apr/summary", permissions: ["qa:all:read", "qa:apr:read", "qa:apr:enter", "qa:apr:manage", "qa:apr:export", "qa:apr:lock"] },
        ],
      },
      // COA 客户标准与出具登记：独立读码（同偏差/PQR 口径），
      // manage/issue 写权限在后端隐含读，前端可见性同口径放行。
      {
        key: "coa",
        label: "COA",
        path: "/qa/coa",
        children: [
          { key: "coa-standards", label: "客户标准配置", path: "/qa/coa/standards", permissions: ["qa:all:read", "qa:coa:read", "qa:coa:manage", "qa:coa:issue"] },
          { key: "coa-issuance", label: "出具登记", path: "/qa/coa/issuance", permissions: ["qa:all:read", "qa:coa:read", "qa:coa:manage", "qa:coa:issue"] },
        ],
      },
      { key: "audit", label: "操作日志", path: "/qa/audit", permissions: ["qa:audit:read"] },
    ],
  },
  {
    key: "admin",
    label: "行政管理",
    icon: "building",
    path: "/admin",
    permissions: ["administration:*:read"],
    children: [
      { key: "notice", label: "公告通知", path: "/admin/notice" },
      { key: "meeting", label: "会议管理", path: "/admin/meeting" },
      { key: "approval", label: "文件审批", path: "/admin/approval" },
    ],
  },
  {
    key: "hr",
    label: "人事管理",
    icon: "users",
    path: "/hr",
    permissions: ["hr:*:read", "hr:title:judge"],
    children: [
      // 权限码与后端 hr/deps.py 路由映射对齐；未声明的项对能进 HR 模块的人恒可见（点入后端 403），
      // 因此每个页面都要声明，才能支持"只给培训权限、其余页面全屏蔽"这类纯角色
      { key: "dashboard", label: "人事看板", path: "/hr/dashboard", permissions: ["hr:profile:read"] },
      { key: "departments", label: "部门管理", path: "/hr/departments", permissions: ["hr:org:read"] },
      {
        // 人员全周期：编制 → 入职 → 在职档案 → 离职（用户拍板：作为 HR 板块内的分组菜单）
        key: "lifecycle",
        label: "人员管理",
        path: "/hr/profile",
        children: [
          { key: "headcount", label: "编制管理", path: "/hr/headcount", permissions: ["hr:profile:read"] },
          { key: "profile", label: "员工档案", path: "/hr/profile", permissions: ["hr:profile:read"] },
          { key: "certificates", label: "证件资料库", path: "/hr/certificates", permissions: ["hr:certificate:read"] },
          { key: "labor-contracts", label: "劳动合同", path: "/hr/labor-contracts", permissions: ["hr:contract:read"] },
          { key: "onboarding", label: "入职台账", path: "/hr/onboarding", permissions: ["hr:onboarding:read"] },
          { key: "departure", label: "离职台账", path: "/hr/departure", permissions: ["hr:departure:read"] },
          { key: "hr-incidents", label: "工伤/纠纷台账", path: "/hr/incidents", permissions: ["hr:incident:read"] },
        ],
      },
      { key: "recruitment", label: "招聘管理", path: "/hr/recruitment", permissions: ["hr:recruitment:read"] },
      {
        // 培训五区按业务动线：计划 → 执行 → 记录 → 资源 → 配置（分组标题式，页面项平铺不折叠）
        key: "training",
        label: "培训管理",
        path: "/hr/training",
        children: [
          {
            key: "training-plan", label: "培训计划", path: "/hr/training", group: true,
            children: [
              { key: "training-annual-plan", label: "年度培训计划", path: "/hr/training/annual-plan", permissions: ["hr:training:plan"] },
            ],
          },
          {
            key: "training-execution", label: "培训执行", path: "/hr/training", group: true,
            children: [
              { key: "training-notification", label: "培训通知", path: "/hr/training/notification", permissions: ["hr:training:document"] },
              { key: "onboarding-training", label: "新员工入职培训", path: "/hr/training/onboarding", permissions: ["hr:training:document"] },
            ],
          },
          {
            key: "training-records", label: "培训记录", path: "/hr/training", group: true,
            children: [
              { key: "training-ledger", label: "培训台账", path: "/hr/training/ledger", permissions: ["hr:training:read"] },
              { key: "training-qa-assessments", label: "考核历史", path: "/hr/training/qa-assessments", permissions: ["hr:training:assessment"] },
            ],
          },
          {
            key: "training-resources", label: "培训资源", path: "/hr/training", group: true,
            children: [
              { key: "training-question-bank", label: "题库", path: "/hr/training/question-bank", permissions: ["hr:training:questionbank"] },
              { key: "training-ai-exam", label: "AI 出题", path: "/hr/training/ai-exam", permissions: ["hr:training:exam"] },
              { key: "sop-master", label: "SOP培训登记表", path: "/hr/training/sop-master", permissions: ["hr:training:read"] },
              { key: "sop-secondary", label: "SOP培训二级表", path: "/hr/training/sop-secondary", permissions: ["hr:training:read"] },
            ],
          },
          {
            key: "training-config", label: "培训配置", path: "/hr/training", group: true,
            children: [
              { key: "trainers", label: "内训师", path: "/hr/training/trainers", permissions: ["hr:trainer:read"] },
              { key: "training-personnel", label: "培训人员名单", path: "/hr/training/personnel", permissions: ["hr:training:read"] },
              { key: "sop-catalog", label: "SOP目录", path: "/hr/training/sop-catalog", permissions: ["hr:training:read"] },
            ],
          },
        ],
      },
      { key: "performance", label: "绩效考核", path: "/hr/performance",
        permissions: ["hr:performance:read"],
        children: [
          { key: "performance-list", label: "考核列表", path: "/hr/performance" },
          { key: "performance-categories", label: "项目配置", path: "/hr/performance/categories", permissions: ["hr:performance:manage"] },
        ],
      },
      {
        // 两页收进折叠子菜单（同培训管理/绩效考核）：管理端评审 + 评委投票；
        // 纯评委只见「评审投票」子项（父项随子项权限过滤存活）
        key: "title",
        label: "职称评审",
        path: "/hr/title-review",
        children: [
          { key: "title-review", label: "评审管理", path: "/hr/title-review", permissions: ["hr:title:read"] },
          { key: "title-judge", label: "评审投票", path: "/hr/title-judge", permissions: ["hr:title:judge"] },
        ],
      },
      // 权限码与后端 hr/deps.py 路由映射对齐：资料下载→roster、系统配置→settings:manage
      { key: "printing", label: "资料下载", path: "/hr/printing", permissions: ["hr:roster:read"] },
      {
        // SOP 目录已归位培训配置区；系统设置只剩系统配置/岗位管理
        key: "settings",
        label: "系统设置",
        path: "/hr/settings",
        permissions: ["hr:settings:manage", "hr:position:read"],
        children: [
          { key: "system-config", label: "系统配置", path: "/hr/settings", permissions: ["hr:settings:manage"] },
          { key: "positions", label: "岗位管理", path: "/hr/positions", permissions: ["hr:position:read"] },
        ],
      },
    ],
  },
  {
    key: "warehouse",
    label: "仓储管理",
    icon: "archive",
    path: "/warehouse",
    permissions: ["warehouse:*:read"],
    children: [
      { key: "inventory", label: "库存管理", path: "/warehouse/inventory" },
      { key: "inout", label: "出入库记录", path: "/warehouse/inout" },
      { key: "stocktake", label: "库存盘点", path: "/warehouse/stocktake" },
    ],
  },
  {
    key: "purchasing",
    label: "采购管理",
    icon: "cart",
    path: "/purchasing",
    permissions: ["procurement:*:read"],
    children: [
      { key: "request", label: "采购申请", path: "/purchasing/request" },
      { key: "supplier", label: "供应商管理", path: "/purchasing/supplier" },
      { key: "order", label: "采购订单", path: "/purchasing/order" },
    ],
  },
  {
    key: "permission",
    label: "权限管理",
    icon: "lock",
    // 根路由按权限分流到进得去的子页
    path: "/permission",
    permissions: ["permission:role:manage", "permission:role:delegate", "permission:user:assign", "permission:user:view"],
    children: [
      // permission:role:manage 是总开关；delegate 只能管理自身范围内的角色
      { key: "roles", label: "角色管理", path: "/permission/roles", permissions: ["permission:role:manage", "permission:role:delegate"] },
      { key: "users", label: "用户权限", path: "/permission/users", permissions: ["permission:role:manage", "permission:user:assign", "permission:user:view"] },
    ],
  },
  {
    key: "toolbox",
    label: "工具箱",
    icon: "tool",
    path: "/toolbox",
    children: [
      {
        key: "usage-permissions",
        label: "使用权限",
        path: "/toolbox/permissions",
        roles: ["super_admin"], // 仅系统超级管理员可见（与权限码解耦）
      },
    ],
    clickableTitle: true, // 标题可点击回模块首页
    // 不设 permissions：所有登录用户可见
  },
]

export function getModuleByKey(key: string): ModuleMenu | undefined {
  return moduleMenus.find((m) => m.key === key)
}

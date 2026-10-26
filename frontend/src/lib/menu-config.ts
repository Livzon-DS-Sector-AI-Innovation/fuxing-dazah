export interface SubMenuItem {
  key: string
  label: string
  path: string
  children?: SubMenuItem[]   // 嵌套子菜单 → Ant Design SubMenu
  disabled?: boolean         // 灰显占位，功能未开发
  permissions?: string[]     // 权限码，用于前端菜单可见性控制
  group?: string             // 侧边栏分组标题（相邻同名项归入同组，渲染为组头）
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
      { key: "overview", label: "仪表总览", path: "/meter" },
      { key: "instruments", label: "标准计量器具", path: "/meter/instruments" },
      { key: "gas-detectors", label: "有毒有害可燃探测器", path: "/meter/gas-detectors" },
      { key: "departments", label: "部门管理", path: "/meter/departments" },
    ],
  },

  // ═══════════════════════════════════════════════════════
  // 安全管理模块 — 按 GB/T 33000-2025 体系要素分组（3.0 只读监控口径）
  // 分组平铺（group 字段，同仓储模式）；标签纯文字，不带体系编号；
  // 四期起四新域（goals/training-behavior/facilities/incidents）为真实页面
  // （统计+台账+健康度卡，未接入态即设计）；全流程监督三期已上线（/safety/supervision）。
  // ═══════════════════════════════════════════════════════
  {
    key: "safety",
    label: "安全管理",
    icon: "shield",
    path: "/safety",
    permissions: ["safety:*:read"],
    clickableTitle: true,
    children: [
      // ── 工作台 ──
      { key: "overview", label: "总览驾驶舱", path: "/safety", group: "工作台" },
      // ── 体系治理 ──
      { key: "goals", label: "目标责任与绩效", path: "/safety/goals", group: "体系治理" },
      { key: "knowledge-base", label: "法规标准与规程", path: "/safety/knowledge-base", group: "体系治理" },
      // ── 风险管控 ──
      { key: "risk-grading", label: "风险分级管控", path: "/safety/hazard-identification/ledger", group: "风险管控" },
      // ── 隐患治理 ──
      { key: "hazard-ledger", label: "隐患排查与治理", path: "/safety/hazard-ledger", group: "隐患治理" },
      // ── 人员管理 ──
      { key: "cert-warnings", label: "人员准入与资质", path: "/safety/cert-warnings", group: "人员管理" },
      { key: "training-behavior", label: "教育培训与行为管控", path: "/safety/training-behavior", group: "人员管理" },
      // ── 现场管理 ──
      { key: "occupational-health", label: "职业健康管理", path: "/safety/occupational-health", group: "现场管理" },
      { key: "facilities", label: "设备设施管理", path: "/safety/facilities", group: "现场管理" },
      { key: "chemicals", label: "危化品与 MSDS 管理", path: "/safety/chemicals", group: "现场管理" },
      { key: "special-ops", label: "特殊作业管理", path: "/safety/special-ops", group: "现场管理" },
      // 监护补贴申报数据（平台作业票+四/五/六部申报台账口径）与特殊作业台账分域：
      // 2026-10-26 从特殊作业管理页迁出独立，避免「补贴申报≠特殊作业台账」语义混淆
      { key: "subsidy", label: "监护补贴申报", path: "/safety/subsidy", group: "现场管理" },
      { key: "risk-reporting", label: "风险作业报备", path: "/safety/risk-reporting", group: "现场管理" },
      { key: "alarms", label: "监测报警与预警", path: "/safety/alarms", group: "现场管理" },
      { key: "ehs-change", label: "EHS 变更管理", path: "/safety/ehs-change", group: "现场管理" },
      { key: "contractor-admission", label: "相关方管理", path: "/safety/contractor-admission", group: "现场管理" },
      // ── 应急处置 ──
      { key: "emergency-drill", label: "应急管理", path: "/safety/emergency-drill", group: "应急处置" },
      // ── 检查监督 ──
      { key: "supervision", label: "全流程监督", path: "/safety/supervision", group: "检查监督" },
      // ── 持续改进 ──
      { key: "incidents", label: "事故事件管理", path: "/safety/incidents", group: "持续改进" },
      // ── 系统（三期合并为 /safety/system 六 Tab 单页，旧 5 入口 301；agent-chat 保留独立入口） ──
      { key: "system", label: "系统配置", path: "/safety/system", group: "系统" },
      { key: "agent-chat", label: "AI 助手对话", path: "/safety/agent-chat", group: "系统" },
    ],
  },

  {
    key: "rd",
    label: "研发管理",
    icon: "beaker",
    path: "/rd",
    permissions: ["research:*:read"],
    children: [
      // 研发模块尚未实现，入口置灰，避免点击后跳到 404 导致侧边栏整体消失
      { key: "projects", label: "研发项目", path: "/rd/projects", disabled: true },
      { key: "experiments", label: "实验记录", path: "/rd/experiments", disabled: true },
      { key: "reports", label: "研发报告", path: "/rd/reports", disabled: true },
    ],
  },
  {
    key: "registration",
    label: "注册管理",
    icon: "document",
    path: "/registration",
    permissions: ["registration:*:read"],
    children: [
      // 注册模块尚未实现，入口置灰，避免点击后跳到 404 导致侧边栏整体消失
      { key: "filing", label: "注册申报", path: "/registration/filing", disabled: true },
      { key: "regulation", label: "法规跟踪", path: "/registration/regulation", disabled: true },
      { key: "documents", label: "文件管理", path: "/registration/documents", disabled: true },
    ],
  },
  {
    key: "quality",
    label: "质量管理",
    icon: "check-circle",
    path: "/quality",
    permissions: ["quality:*:read"],
    children: [
      { key: "lc-parser", label: "🧪 液相解析", path: "/quality" },
      { key: "lc-calc", label: "📊 计算表", path: "/quality/calculator" },
      // 以下质量子页面尚未落地，入口置灰，避免点到 404 后丢失侧边栏
      { key: "inspection", label: "质量检验", path: "/quality/inspection", disabled: true },
      { key: "deviation", label: "偏差管理", path: "/quality/deviation", disabled: true },
      { key: "capa", label: "CAPA管理", path: "/quality/capa", disabled: true },
      { key: "change", label: "变更控制", path: "/quality/change", disabled: true },
    ],
  },
  {
    key: "admin",
    label: "行政管理",
    icon: "building",
    path: "/admin",
    permissions: ["administration:*:read"],
    children: [
      // 行政模块尚未实现，入口置灰，避免点击后跳到 404 导致侧边栏整体消失
      { key: "notice", label: "公告通知", path: "/admin/notice", disabled: true },
      { key: "meeting", label: "会议管理", path: "/admin/meeting", disabled: true },
      { key: "approval", label: "文件审批", path: "/admin/approval", disabled: true },
    ],
  },
  {
    key: "hr",
    label: "人事管理",
    icon: "users",
    path: "/hr",
    permissions: ["hr:*:read", "hr:title:judge"],
    children: [
      { key: "dashboard", label: "📊 人事看板", path: "/hr/dashboard" },
      { key: "departments", label: "部门管理", path: "/hr/departments" },
      { key: "profile", label: "员工档案", path: "/hr/profile" },
      { key: "recruitment", label: "招聘管理", path: "/hr/recruitment", permissions: ["hr:recruitment:read"] },
      { key: "onboarding", label: "入职台账", path: "/hr/onboarding" },
      { key: "departure", label: "离职台账", path: "/hr/departure" },
      {
        key: "training",
        label: "培训管理",
        path: "/hr/training",
        children: [
          { key: "onboarding-training", label: "新员工入职培训", path: "/hr/training/onboarding" },
          { key: "training-notification", label: "培训通知", path: "/hr/training/notification" },
          { key: "sop-master", label: "SOP培训登记表", path: "/hr/training/sop-master" },
          { key: "sop-secondary", label: "SOP培训二级表", path: "/hr/training/sop-secondary" },
          { key: "training-ai-exam", label: "AI 出题", path: "/hr/training/ai-exam", permissions: ["hr:training:exam"] },
          { key: "training-annual-plan", label: "年度培训计划", path: "/hr/training/annual-plan" },
          { key: "training-ledger", label: "培训台账", path: "/hr/training/ledger" },
          { key: "training-question-bank", label: "题库大全", path: "/hr/training/question-bank", permissions: ["hr:training:questionbank"] },
          { key: "training-qa-assessments", label: "问答考核历史", path: "/hr/training/qa-assessments", permissions: ["hr:training:assessment"] },
          { key: "trainers", label: "内训师管理", path: "/hr/training/trainers", permissions: ["hr:trainer:read"] },
        ],
      },
      { key: "performance", label: "📋 绩效考核", path: "/hr/performance",
        permissions: ["hr:performance:read"],
        children: [
          { key: "performance-list", label: "考核列表", path: "/hr/performance" },
          { key: "performance-categories", label: "项目配置", path: "/hr/performance/categories" },
        ],
      },
      { key: "title-review", label: "职称评审", path: "/hr/title-review", permissions: ["hr:title:read"] },
      { key: "title-judge", label: "职称评审投票", path: "/hr/title-judge", permissions: ["hr:title:judge"] },
      // 权限码与后端 hr/deps.py 路由映射对齐：资料下载→roster、系统配置→settings:manage、SOP→training:read
      { key: "printing", label: "资料下载", path: "/hr/printing", permissions: ["hr:roster:read"] },
      {
        key: "settings",
        label: "系统设置",
        path: "/hr/settings",
        permissions: ["hr:settings:manage", "hr:position:read", "hr:trainer:read", "hr:training:read"],
        children: [
          { key: "system-config", label: "系统配置", path: "/hr/settings", permissions: ["hr:settings:manage"] },
          { key: "positions", label: "岗位管理", path: "/hr/positions", permissions: ["hr:position:read"] },
          { key: "sop-catalog", label: "SOP管理", path: "/hr/training/sop-catalog", permissions: ["hr:training:read"] },
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
      { key: "dashboard", label: "驾驶舱", path: "/warehouse", group: "工作台" },
      { key: "board", label: "作业看板", path: "/warehouse/board", group: "工作台" },
      { key: "quick-register", label: "快速登记", path: "/warehouse/quick-register", group: "工作台" },
      { key: "inventory", label: "库存管理", path: "/warehouse/inventory", group: "库存" },
      { key: "location-map", label: "库位地图", path: "/warehouse/location-map", group: "库存" },
      { key: "stocktake", label: "库存盘点", path: "/warehouse/stocktake", group: "库存" },
      { key: "inout", label: "出入库记录", path: "/warehouse/inout", group: "流转" },
      { key: "reconciliation", label: "对账中心", path: "/warehouse/reconciliation", group: "流转" },
      { key: "intelligence", label: "智能中心", path: "/warehouse/intelligence", group: "分析" },
      { key: "reports", label: "报表中心", path: "/warehouse/reports", group: "分析" },
      { key: "system", label: "系统配置", path: "/warehouse/system", permissions: ["warehouse:system-config:read"], group: "系统" },
    ],
  },
  {
    key: "purchasing",
    label: "采购管理",
    icon: "cart",
    path: "/purchasing",
    permissions: ["procurement:*:read"],
    children: [
      // 采购模块尚未实现，入口置灰，避免点击后跳到 404 导致侧边栏整体消失
      { key: "request", label: "采购申请", path: "/purchasing/request", disabled: true },
      { key: "supplier", label: "供应商管理", path: "/purchasing/supplier", disabled: true },
      { key: "order", label: "采购订单", path: "/purchasing/order", disabled: true },
    ],
  },
  {
    key: "permission",
    label: "权限管理",
    icon: "lock",
    path: "/permission/roles",
    permissions: ["permission:role:manage"],
    children: [
      { key: "roles", label: "角色管理", path: "/permission/roles" },
      { key: "users", label: "用户权限", path: "/permission/users" },
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
        permissions: ["permission:role:manage"], // 仅系统超级管理员可见
      },
    ],
    clickableTitle: true, // 标题可点击回模块首页
    // 不设 permissions：所有登录用户可见
  },
]

export function getModuleByKey(key: string): ModuleMenu | undefined {
  return moduleMenus.find((m) => m.key === key)
}

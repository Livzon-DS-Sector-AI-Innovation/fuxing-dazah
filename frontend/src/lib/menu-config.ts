export interface SubMenuItem {
  key: string
  label: string
  path: string
  children?: SubMenuItem[]   // 嵌套子菜单 → Ant Design SubMenu
  disabled?: boolean         // 灰显占位，功能未开发
  permissions?: string[]     // 权限码，用于前端菜单可见性控制
}

export interface ModuleMenu {
  key: string
  label: string
  icon: string
  path: string
  children: SubMenuItem[]
  permissions?: string[]     // 权限码，用于前端菜单可见性控制
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
      { key: "workbench", label: "工作台", path: "/production/workbench" },
      { key: "process", label: "产品工艺", path: "/production/process" },
      { key: "materials", label: "产出物管理", path: "/production/materials" },
      { key: "batches", label: "批次管理", path: "/production/batches" },
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
      { key: "type-config", label: "能源配置", path: "/energy/type-config" },
      { key: "devices", label: "数据源配置", path: "/energy/devices" },
      { key: "alerts", label: "预警管理", path: "/energy/alerts" },
      { key: "collect-logs", label: "采集日志", path: "/energy/collect-logs" },
      { key: "collect-history", label: "采集历史", path: "/energy/collect-history" },
      { key: "visualization", label: "可视化视图", path: "/energy/visualization" },
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
  // 安全管理模块 — 按化工安全生产管理体系分级
  // ═══════════════════════════════════════════════════════
  {
    key: "safety",
    label: "安全管理",
    icon: "shield",
    path: "/safety",
    permissions: ["safety:*:read"],
    children: [
            // ── 系统配置 ──
      {
        key: "system-config",
        label: "系统配置",
        path: "",
        children: [],
      },
      // ── 作业安全 ──
      {
        key: "ops-safety",
        label: "作业安全",
        path: "",
        children: [
          { key: "special-ops-mgmt", label: "特殊作业管理", path: "/safety/special-ops" },
          { key: "daily-risk-report", label: "关键风险作业报备", path: "/safety/risk-reporting" },
        ],
      },
      // ── 风险与隐患 ──
      {
        key: "risk-hazard",
        label: "风险与隐患",
        path: "",
        children: [
          {
            key: "risk-grading",
            label: "风险分级管控",
            path: "",
            children: [
              { key: "hazard-identification", label: "危险源辨识工作流", path: "/safety/hazard-identification" },
              { key: "hazard-ledger", label: "危险源辨识台账", path: "/safety/hazard-identification/ledger" },
            ],
          },
                    {
            key: "hazard-inspection",
            label: "隐患排查治理",
            path: "",
            children: [
              { key: "hazard-inspection-ledger", label: "隐患台账", path: "/safety/hazard-ledger" },
            ],
          },
          {
            key: "regulation",
            label: "安全操规管理",
            path: "",
            children: [
              { key: "regulation-list", label: "安全操规台账", path: "/safety/regulation" },
              { key: "regulation-generator", label: "标准化生成", path: "/safety/regulation/generator" },
            ],
          },
          {
            key: "ehs-change",
            label: "EHS变更管理",
            path: "",
            children: [
              { key: "ehs-change-apply", label: "EHS变更申请", path: "/safety/ehs-change" },
              { key: "ehs-change-accept", label: "EHS变更验收", path: "/safety/ehs-change" },
            ],
          },

        ],
      },

      // ── 应急与事故 ──
      {
        key: "emergency-accident",
        label: "应急与事故",
        path: "",
        children: [
          { key: "accident-ledger", label: "事故台账", path: "/safety/accident" },
          { key: "emergency-plan", label: "应急预案管理", path: "", disabled: true },
          { key: "emergency-drill", label: "应急演练管理", path: "", disabled: true },
        ],
      },

      // ── 人员资质与培训 ──
      {
        key: "personnel-training",
        label: "人员资质与培训",
        path: "",
        children: [
          { key: "training", label: "安全培训管理", path: "/safety/training" },
          { key: "personnel-qual", label: "厂内人员资质", path: "/safety/special-ops/personnel" },
          { key: "contractor", label: "承包商管理", path: "/safety/contractor" },
        ],
      },

      // ── 职业健康与环境 ──
      {
        key: "oh-env",
        label: "职业健康与环境",
        path: "",
        children: [
          { key: "oh-monitor", label: "职业危害因素监测", path: "/safety/occupational-health" },
          { key: "oh-exam", label: "职业健康体检", path: "/safety/occupational-health" },
          { key: "ppe", label: "劳动防护用品管理", path: "", disabled: true },
        ],
      },

      // ── 法规与安全信息 ──
      {
        key: "regulation-info",
        label: "法规与安全信息",
        path: "",
        children: [
          { key: "knowledge-base", label: "安全知识库", path: "/safety/knowledge-base" },
          { key: "info-query", label: "信息查询", path: "/safety/info-query" },
          { key: "compliance-eval", label: "合规性评价记录", path: "", disabled: true },
        ],
      },
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
    path: "/quality",
    permissions: ["quality:*:read"],
    children: [
      { key: "lc-parser", label: "🧪 液相解析", path: "/quality" },
      { key: "lc-calc", label: "📊 计算表", path: "/quality/calculator" },
      { key: "inspection", label: "质量检验", path: "/quality/inspection" },
      { key: "deviation", label: "偏差管理", path: "/quality/deviation" },
      { key: "capa", label: "CAPA管理", path: "/quality/capa" },
      { key: "change", label: "变更控制", path: "/quality/change" },
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
    permissions: ["hr:*:read"],
    children: [
      { key: "dashboard", label: "📊 人事看板", path: "/hr" },
      { key: "departments", label: "部门管理", path: "/hr/departments" },
      { key: "profile", label: "员工档案", path: "/hr/profile" },
      { key: "recruitment", label: "招聘管理", path: "/hr/recruitment" },
      { key: "onboarding", label: "入职台账", path: "/hr/onboarding" },
      { key: "departure", label: "离职台账", path: "/hr/departure" },
      {
        key: "training",
        label: "培训管理",
        path: "/hr/training",
        children: [
          { key: "onboarding-training", label: "新员工入职培训", path: "/hr/training/onboarding" },
          { key: "training-notification", label: "培训通知", path: "/hr/training/notification" },
          { key: "training-ai-exam", label: "AI 出题", path: "/hr/training/ai-exam" },
          { key: "training-annual-plan", label: "年度培训计划", path: "/hr/training/annual-plan" },
          { key: "training-ledger", label: "培训台账", path: "/hr/training/ledger" },
          { key: "training-question-bank", label: "题库大全", path: "/hr/training/question-bank" },
        ],
      },
      { key: "printing", label: "资料下载", path: "/hr/printing", permissions: ["hr:settings:read"] },
      {
        key: "settings",
        label: "系统设置",
        path: "/hr/settings",
        permissions: ["hr:settings:read", "hr:position:read", "hr:trainer:read"],
        children: [
          { key: "system-config", label: "系统配置", path: "/hr/settings", permissions: ["hr:settings:read"] },
          { key: "positions", label: "岗位管理", path: "/hr/positions", permissions: ["hr:position:read"] },
          { key: "sop-catalog", label: "SOP管理", path: "/hr/training/sop-catalog", permissions: ["hr:settings:read"] },
          { key: "trainers", label: "内训师管理", path: "/hr/training/trainers", permissions: ["hr:trainer:read"] },
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
    path: "/permission/roles",
    permissions: ["permission:role:manage"],
    children: [
      { key: "roles", label: "角色管理", path: "/permission/roles" },
      { key: "users", label: "用户权限", path: "/permission/users" },
    ],
  },
]

export function getModuleByKey(key: string): ModuleMenu | undefined {
  return moduleMenus.find((m) => m.key === key)
}

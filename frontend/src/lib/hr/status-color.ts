// HR 状态 → 颜色共享映射（此前散落各组件硬编码，同一状态曾出现两套色：
// 招聘列表用一套 hex、漏斗图另一套 hex，已录用/待入职审批同状态不同色）。
// 候选人状态用 hex（列表状态点/图例/漏斗进度条同源取色）；
// 员工在职状态用 antd Tag 预设色名。新页面一律从这里取色，勿再内联。

/** 招聘候选人状态 → hex（Tag color / 状态点 / 漏斗进度条通用） */
export const CANDIDATE_STATUS_COLORS: Record<string, string> = {
  '待筛选': '#a4a097',
  '已筛选': '#0075de',
  '待部门审核': '#dd5b00',
  '面试中': '#7b3ff2',
  '已面试': '#2a9d99',
  '录用中': '#1aae39',
  '已录用': '#5645d4',
  '待入职审批': '#e8b830',
  '已入职': '#389e0d',
  '已拒绝': '#ff4d4f',
}

export function candidateStatusColor(status?: string | null): string {
  return (status && CANDIDATE_STATUS_COLORS[status]) || '#8c8c8c'
}

/** 员工在职状态 → antd Tag 预设色名 */
export const EMPLOYEE_STATUS_TAG_COLORS: Record<string, string> = {
  在职: 'success',
  试用期: 'warning',
  离职: 'default',
  待审批: 'processing',
  病假: 'error',
  产假: 'magenta',
  产假复岗: 'purple',
}

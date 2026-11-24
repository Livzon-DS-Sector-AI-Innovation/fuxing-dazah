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

/** 离职类型统一口径（此前表单 4 项/颜色 7 项/DDL 注释 5 项三套并存）：
 *  并集覆盖 DDL 注释（辞职/辞退/合同到期/退休/其他）+ 表单历史项（自离）
 *  + 飞书同步单选值（个人原因/退休返聘到期）。
 *  筛选选项仍以服务端 distinct 聚合为准（库中实际值为权威）。 */
export const DEPARTURE_TYPE_OPTIONS = [
  '辞职',
  '辞退',
  '合同到期',
  '退休',
  '自离',
  '个人原因',
  '退休返聘到期',
  '其他',
] as const

/** 离职类型 → antd Tag 预设色名（自离/辞退同属异常离场归 error） */
export const DEPARTURE_TYPE_TAG_COLORS: Record<string, string> = {
  辞职: 'default',
  辞退: 'error',
  自离: 'error',
  个人原因: 'default',
  合同到期: 'warning',
  退休: 'success',
  退休返聘到期: 'success',
  其他: 'processing',
}

/** 月度绩效考核状态 → antd Tag 预设色名（此前考核列表与详情各维护一份 STATUS_MAP，
 *  现列表/详情状态标签与状态筛选下拉统一从这里取值） */
export const PERFORMANCE_STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  self_submitted: { label: '待领导评分', color: 'processing' },
  leader_scored: { label: '已完成', color: 'success' },
}

/** AI 初筛 / 胜任度报告的推荐等级 → antd Tag 预设色名
 *  （此前招聘列表、详情页、筛简历面板、报告卡各写一套，同一个「不推荐」有灰有红） */
export const RECOMMENDATION_LEVEL_TAG_COLORS: Record<string, string> = {
  强烈推荐: 'green',
  推荐: 'blue',
  待定: 'orange',
  不推荐: 'red',
}

/** 面试安排状态 → antd Tag 预设色名（此前「待安排」与「已安排」同为蓝色，分不清） */
export const INTERVIEW_STATUS_TAG_COLORS: Record<string, string> = {
  待安排: 'default',
  已安排: 'processing',
  已完成: 'success',
  已取消: 'error',
}

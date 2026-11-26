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

/** 分类胶囊配色（bg 胶囊底色 / text 胶囊文字 / dot 列表里的色点）。
 *  培训人员分类按分类清单顺序取色、循环使用：底色是 DESIGN.md 的过渡色 card-tint-*，
 *  文字取同色系深一档（与状态色同一思路：浅底上要用深字才够对比度）。 */
export const CLASSIFICATION_CHIP_PALETTE: { bg: string; text: string; dot: string }[] = [
  { bg: 'var(--color-tint-lavender)', text: '#391c57', dot: '#7b3ff2' },
  { bg: 'var(--color-tint-peach)', text: '#793400', dot: '#dd5b00' },
  { bg: 'var(--color-tint-mint)', text: '#12812a', dot: '#1aae39' },
  { bg: 'var(--color-tint-sky)', text: '#005bab', dot: '#0075de' },
  { bg: 'var(--color-tint-rose)', text: '#a02e6d', dot: '#e5399f' },
  { bg: 'var(--color-tint-gray)', text: '#5d5b54', dot: '#a4a097' },
]

/** 不在分类清单里的残留标签（分类已删、标签还在）：中性描边，提示可清理 */
export const ORPHAN_TAG_CHIP_COLOR = {
  bg: 'var(--color-surface-soft)', text: '#5d5b54', dot: '#bbb8b1',
}

/** 分类名 → 胶囊配色。names 传分类清单的名称顺序，清单外的名字一律按残留标签处理 */
export function classificationChipColors(
  names: string[],
): Record<string, { bg: string; text: string; dot: string }> {
  const map: Record<string, { bg: string; text: string; dot: string }> = {}
  names.forEach((name, i) => {
    map[name] = CLASSIFICATION_CHIP_PALETTE[i % CLASSIFICATION_CHIP_PALETTE.length]
  })
  return map
}

/** 离职办理状态 → antd Tag 预设色名。轮到 HR 动手的环节（开证 / 送达）用 warning，
 *  外部处理中的（审批 / 会签）用 processing。看板、办理抽屉、台账「办理状态」列三处同源。 */
export const OFFBOARDING_STATUS_TAG_COLORS: Record<string, string> = {
  draft: 'default',
  approving: 'processing',
  clearing: 'processing',
  cert_issuing: 'warning',
  delivering: 'warning',
  signed: 'cyan',
  closed: 'success',
  canceled: 'error',
}

/** 离职办结单允许的离职类型（后端 OffboardingCase.TYPE_LABELS）。
 *  注意与 DEPARTURE_TYPE_OPTIONS 不是一回事：台账的离职类型取值更杂（飞书源表带进来的），
 *  办结单只认这 5 种，选了别的后端会直接拒绝。新建 / 编辑办理时用这一份。 */
export const OFFBOARDING_CASE_TYPE_OPTIONS: readonly string[] = ['辞职', '辞退', '合同到期', '退休', '其他']

/** 离职办理状态文案；'none' 是台账筛选里「未发起办理」的取值 */
export const OFFBOARDING_STATUS_LABELS: Record<string, string> = {
  none: '未发起',
  draft: '待发起审批',
  approving: '离职审批中',
  clearing: '清退会签中',
  cert_issuing: '待开具证明',
  delivering: '证明送达中',
  signed: '已签字确认',
  closed: '已办结',
  canceled: '已取消',
}

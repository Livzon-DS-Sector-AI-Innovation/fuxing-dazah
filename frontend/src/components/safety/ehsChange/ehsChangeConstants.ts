/**
 * EHS 变更管理 常量与语义色映射（DESIGN tokens）
 * 数据源单一：状态/来源/AI结论 的视觉配置与筛选选项都从这里派生。
 */
import type { CSSProperties } from 'react'
import { statusPill } from '../shared-styles'
import type { EhsChange } from '@/types/safety'

// ── 状态 → 语义色 pill（label 与多维表格「申请状态」一致）──
export const STATUS_UI: Record<string, { label: string; pill: CSSProperties }> = {
  draft: { label: '草稿', pill: statusPill('#a4a097', '#f0eeec') },
  under_review: { label: '审批中', pill: statusPill('#dd5b00', '#ffe8d4') },
  approved: { label: '已通过', pill: statusPill('#1aae39', '#d9f3e1') },
  rejected: { label: '已拒绝', pill: statusPill('#e03131', '#fde0ec') },
  withdrawn: { label: '已撤回', pill: statusPill('#787671', '#f0eeec') },
  cancelled: { label: '已取消', pill: statusPill('#a4a097', '#f0eeec') },
  terminated: { label: '已终止', pill: statusPill('#787671', '#f0eeec') },
  in_progress: { label: '实施中', pill: statusPill('#0075de', '#dcecfa') },
  commissioned: { label: '已投用', pill: statusPill('#5645d4', '#e6e0f5') },
  closed: { label: '已关闭', pill: statusPill('#787671', '#f0eeec') },
}

export const STATUS_FILTER = [
  { value: '', label: '全部状态' },
  ...Object.entries(STATUS_UI).map(([value, v]) => ({ value, label: v.label })),
]

// ── 来源 ──
export const SOURCE_UI: Record<string, { label: string; pill: CSSProperties }> = {
  manual: { label: '平台', pill: statusPill('#787671', '#f0eeec') },
  bitable: { label: '飞书', pill: statusPill('#0075de', '#dcecfa') },
}

export const SOURCE_FILTER = [
  { value: '', label: '全部来源' },
  { value: 'manual', label: '平台' },
  { value: 'bitable', label: '飞书' },
]

// ── AI 审核结论 ──
export const AI_CONCLUSION_UI: Record<string, CSSProperties> = {
  审核通过: statusPill('#1aae39', '#d9f3e1'),
  需补充完善: statusPill('#dd5b00', '#ffe8d4'),
  审核不通过: statusPill('#e03131', '#fde0ec'),
}

export const AI_CONCLUSION_FILTER = [
  { value: '', label: '全部结论' },
  { value: '审核通过', label: '审核通过' },
  { value: '需补充完善', label: '需补充完善' },
  { value: '审核不通过', label: '审核不通过' },
]

/** 取变更的总体 AI 审核结论（优先级 不通过 > 需补充 > 通过） */
export function getAiConclusion(change: EhsChange): string | null {
  const r = change.ai_review_result
  if (!r) return null
  const dims = [r.risk, r.reason, r.plan, r.effect]
  for (const dim of dims) {
    const c = dim?.conclusion
    if (c && c === '审核不通过') return c
  }
  for (const dim of dims) {
    const c = dim?.conclusion
    if (c && c === '需补充完善') return c
  }
  for (const dim of dims) {
    const c = dim?.conclusion
    if (c && c === '审核通过') return c
  }
  return null
}

// ── 变更类型/等级/时效 label ──
export const CHANGE_TYPE_LABEL: Record<string, string> = {
  process_tech: '工艺技术变更',
  equipment_facility: '设备设施变更',
  management: '管理变更',
}

export const CHANGE_GRADE_UI: Record<string, { label: string; pill: CSSProperties }> = {
  major: { label: '重大变更', pill: statusPill('#e03131', '#fde0ec') },
  general: { label: '一般变更', pill: statusPill('#0075de', '#dcecfa') },
}

export const CHANGE_DURATION_LABEL: Record<string, string> = {
  permanent: '永久性',
  temporary: '临时性',
  emergency: '紧急',
}

/** 从验收「关联审批」文本提取申请编号（首个空格前的编号串，用于追溯跳转） */
export function extractRelatedApprovalNo(relatedApproval: string | undefined): string | null {
  if (!relatedApproval) return null
  const match = relatedApproval.trim().match(/^([0-9A-Za-z-]+)/)
  return match ? match[1] : null
}

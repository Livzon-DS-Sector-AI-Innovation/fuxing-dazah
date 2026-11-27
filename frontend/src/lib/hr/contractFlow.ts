// 劳动合同前端纯逻辑：行内「下一步」、环节卡片、步骤条状态映射、通知留痕文案。
// 口径与后端 repository.todo_expr 一致（每个待办对应行上一个动作），不碰组件，便于 Node 直跑用例。

import type { ContractNotice, ContractProgressStep, ContractTodoKey, LaborContract } from '@/types/hr'

export type RowActionKind = 'decide' | 'renew' | 'stamp' | 'deliver' | 'archive' | 'transfer'

export interface RowAction {
  kind: RowActionKind
  /** 行内按钮文字 */
  label: string
  /** 给办事员看的一句说明：这一步谁做什么 */
  hint: string
}

/** 环节卡片：五项待办 + 到期未续签（存量提示）；键名与后端 /labor-contracts/stats 一致。
 *  员工到人事办公室领取合同即签收，没有领取后的线上签字 */
export const CONTRACT_TODO_CARDS: { key: ContractTodoKey; title: string; hint: string }[] = [
  { key: 'pending_dept_approval', title: '待部门审批', hint: '部门负责人登记同意或不同意续签' },
  { key: 'to_renew', title: '待续签', hint: '部门已同意，办理续签生成新合同' },
  { key: 'to_stamp', title: '待盖章', hint: '员工签字、公司盖章' },
  { key: 'to_deliver', title: '待领取', hint: '盖章后通知员工领取原件，领取即签收' },
  { key: 'to_archive', title: '待归档', hint: '员工已领取：上传扫描件归档' },
  { key: 'expired_unrenewed', title: '到期未续签', hint: '登记部门意见，或转入离职办理' },
]

type RowShape = Pick<
  LaborContract,
  'status' | 'origin' | 'dept_decision' | 'stamped_at' | 'delivered_at' | 'archive_status'
>

const RENEW: RowAction = { kind: 'renew', label: '办理续签', hint: '部门已同意续签：办理续签，生成新合同' }
const ARCHIVE: RowAction = { kind: 'archive', label: '上传扫描件', hint: '员工已领取合同：上传扫描件归档' }

/** 合同现在该做什么（与后端待办口径一致）；不需要处理的返回 null */
export function rowNextAction(row: RowShape): RowAction | null {
  if (row.status === 'terminated' || row.status === 'superseded') return null
  if (row.status === 'expired_unrenewed') {
    return { kind: 'transfer', label: '转离职办理', hint: '合同已到期未续签：登记部门意见，或为员工发起离职办理' }
  }
  if (row.status === 'pending_renewal') {
    if (row.dept_decision === 'agree') return RENEW
    if (row.dept_decision === 'disagree') return null
    return { kind: 'decide', label: '登记部门意见', hint: '等部门负责人给出同意 / 不同意续签的意见' }
  }
  if (row.status === 'renewing') return RENEW
  // status = active
  if (row.delivered_at) return row.archive_status === 'archived' ? null : ARCHIVE
  if (row.stamped_at) return { kind: 'deliver', label: '登记已领取', hint: '已盖章：员工到人事办公室领取原件后登记' }
  if (row.origin === 'renewal') return { kind: 'stamp', label: '登记盖章', hint: '续签的新合同：员工签字、公司盖章后登记' }
  return null
}

/** 步骤条条目（antd Steps 的 items） */
export interface StepItem {
  title: string
  status: 'wait' | 'process' | 'finish' | 'error'
  disabled: boolean
  content?: string
}

/** 后端的六步进度 → 步骤条。后端可能给出多个「进行中」（如存量合同同时在部门审批与归档）：
 *  只把第一个画成进行中，其余按等待处理；跳过的置灰。 */
export function toStepItems(progress: ContractProgressStep[] | undefined | null): StepItem[] {
  let seenCurrent = false
  return (progress || []).map((step) => {
    const content = [step.note, step.at ? formatAt(step.at) : ''].filter(Boolean).join(' · ') || undefined
    if (step.state === 'done') return { title: step.title, status: 'finish', disabled: false, content }
    if (step.state === 'skipped') return { title: step.title, status: 'wait', disabled: true, content }
    if (step.state === 'current' && !seenCurrent) {
      seenCurrent = true
      return { title: step.title, status: 'process', disabled: false, content }
    }
    return { title: step.title, status: 'wait', disabled: false, content }
  })
}

/** ISO 时间 → MM-DD HH:mm（本地时区）；空值返回空串 */
function formatAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const NOTICE_KIND_LABELS: Record<string, string> = {
  dept_approval: '部门审批提醒',
  renew: '续签通知',
  collect: '领取通知',
}

/** 通知类型文案；存量留痕里早期下线的类型（如签字提醒）统一按「历史通知」展示 */
export function noticeKindLabel(kind: string): string {
  return NOTICE_KIND_LABELS[kind] ?? '历史通知'
}

export interface NoticeStatusMeta {
  label: string
  color: string
}

/** 通知留痕状态：skipped 多为「员工没有飞书账号」，要看 error_message 说明原因 */
export function noticeStatusMeta(status: ContractNotice['status']): NoticeStatusMeta {
  if (status === 'sent') return { label: '已送达', color: 'success' }
  if (status === 'failed') return { label: '发送失败', color: 'error' }
  return { label: '未发送', color: 'default' }
}

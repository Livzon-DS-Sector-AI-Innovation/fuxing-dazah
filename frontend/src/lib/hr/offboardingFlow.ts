// 离职办理的纯逻辑：步骤条节点与位置、各状态「下一步」提示、短信文案、清退发起时点。
// 只做文案与位置计算，不碰组件，便于用 Node 直跑用例。

import type { OffboardingCaseStatus } from '@/types/hr'

/** 步骤条七节点：与抽屉里各环节面板的「第 N 步」一一对应。
 *  系统只在公司内网可达，员工签字不走外部链接：到人事办公室在公司电脑上手写签名，或在纸质件上签字后登记 */
export const STEPPER_STAGES: { key: OffboardingCaseStatus; title: string }[] = [
  { key: 'draft', title: '提交审批' },
  { key: 'approving', title: '部门审批' },
  { key: 'clearing', title: '清退会签' },
  { key: 'cert_issuing', title: '开具证明' },
  { key: 'delivering', title: '送达证明' },
  { key: 'signed', title: '员工签收' },
  { key: 'closed', title: '办结归档' },
]

/** 步骤条当前位置。员工签收后（signed）前六步都已完成，停在最后一步「办结归档」 */
export function stepperIndex(
  status: OffboardingCaseStatus,
): { current: number; status: 'process' | 'finish' | 'error' } {
  if (status === 'canceled') return { current: 0, status: 'error' }
  if (status === 'closed') return { current: 6, status: 'finish' }
  if (status === 'signed') return { current: 6, status: 'process' }
  const index = STEPPER_STAGES.findIndex((stage) => stage.key === status)
  return { current: Math.max(index, 0), status: 'process' }
}

/** 各状态下「现在轮到谁做什么」——列表的「下一步」列和空状态引导共用 */
export const NEXT_STEP_HINT: Record<OffboardingCaseStatus, string> = {
  draft: 'HR：提交部门审批',
  approving: '部门负责人审批；通过后 HR 登记办结',
  clearing: '四个部门清退会签；全部完成后 HR 登记办结',
  cert_issuing: 'HR：核对信息并开具证明',
  delivering: 'HR：把证明交给员工，员工签字后登记签收',
  signed: '员工已签收；HR 确认后办结',
  closed: '已办结，档案与各台账已同步',
  canceled: '已取消；如仍需办理请重新发起',
}

const DEFAULT_CONTACT = '人力资源部'

/** 签收方式的展示文案。存量数据里的 mail / 空值是早期线上签字留下的，一律按手写签名展示 */
export function signWayLabel(channel: string | null | undefined): string {
  return channel === 'paper' ? '纸质签收登记' : '当面手写签名'
}

/** 短信文案：替换 {联系人}。只做通知、不带链接（员工在手机上打不开本系统的链接）。
 *  模板里写成「…人力资源部{联系人}」而联系人没配具体人（缺省就是「人力资源部」）时只留一个，不重复成叠字 */
export function renderSmsText(
  template: string | null | undefined,
  contact: string | null | undefined,
): string | null {
  if (!template) return null
  const name = contact?.trim() || DEFAULT_CONTACT
  return template
    .replace(/人力资源部\{联系人\}/g, name === DEFAULT_CONTACT ? DEFAULT_CONTACT : `${DEFAULT_CONTACT}${name}`)
    .replace(/\{联系人\}/g, name)
}

export interface SmsStatusMeta {
  label: string
  sent: boolean
}

/** 短信状态口径：manual 是 HR 用手机 / 飞书发出后登记的；早期残留的 not_configured 视同未发送 */
export function smsStatusMeta(status: string | null | undefined): SmsStatusMeta {
  if (status === 'manual') return { label: '已发送（人工登记）', sent: true }
  if (status === 'sent') return { label: '已发送', sent: true }
  if (status === 'failed') return { label: '发送失败', sent: false }
  return { label: '未发送', sent: false }
}

function cnDate(iso: string): { month: number; day: number } {
  const [, month, day] = iso.split('-').map(Number)
  return { month, day }
}

/** 清退交接什么时候发起：建议发起日 = 离职日前 2 天 */
export function clearanceTimingText(
  dueDate: string | null | undefined,
  today: Date = new Date(),
): string | null {
  if (!dueDate) return null
  const { month, day } = cnDate(dueDate)
  const [year, m, d] = dueDate.split('-').map(Number)
  const days = Math.round(
    (new Date(year, m - 1, d).getTime()
      - new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) / 86_400_000,
  )
  const label = `${month}月${day}日`
  if (days > 0) return `建议 ${label} 发起（离职日前 2 天），还有 ${days} 天`
  if (days === 0) return `建议发起日是 ${label}，今天可以发起`
  return `建议发起日是 ${label}，已过 ${-days} 天，请尽快发起`
}

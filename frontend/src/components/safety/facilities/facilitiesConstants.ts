/**
 * 设备设施管理共用常量（facilities-frontend，DESIGN §14.1）。
 *
 * 台账 Tab 与任务中心共用一套状态/逾期口径，勿在组件内散落硬编码——
 * 后续安全附件/特种设备台账接入时在此各自补待办文案。
 */

/** 任务状态基础映射（issued 为全台账默认文案，专属文案见下方覆盖表） */
export const FACILITY_TASK_STATUS_UI: Record<string, { label: string; color: string }> = {
  issued: { label: '待闭环', color: 'orange' },
  closed: { label: '已闭环', color: 'green' },
  cancelled: { label: '已取消', color: 'default' },
}

/**
 * 各台账 issued 态专属文案（2026-10-20 拍板：消防器材到期=待更换；
 * 与后端 notify._PENDING_TEXT 同口径），其余台账默认「待闭环」。
 */
const PENDING_TEXT_BY_BIZ: Record<string, string> = {
  fire_equipment: '待更换',
}

export function facilityStatusUI(
  status: string,
  bizType?: string | null,
): { label: string; color: string } {
  if (status === 'issued' && bizType && PENDING_TEXT_BY_BIZ[bizType]) {
    return { label: PENDING_TEXT_BY_BIZ[bizType], color: FACILITY_TASK_STATUS_UI.issued.color }
  }
  return FACILITY_TASK_STATUS_UI[status] ?? { label: status, color: 'default' }
}

/** 逾期档位阈值（口径同速递格子 facility_check）：逾期 >7 天红、0-7 天橙 */
export const OVERDUE_SEVERE_DAYS = 7
export const OVERDUE_RED = '#e2585d'
export const OVERDUE_WARN = '#d9822b'

/** 逾期天数 → 档位色（非逾期返回 null，临期橙色由各表自持阈值渲染） */
export function overdueColor(days: number): string | null {
  if (days >= 0) return null
  return Math.abs(days) > OVERDUE_SEVERE_DAYS ? OVERDUE_RED : OVERDUE_WARN
}

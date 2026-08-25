import dayjs from 'dayjs'

// ponytail: 消除 CreatePlanOrderModal/DemandFormModal 两处重复的日期序列化
const DATE_KEYS = ['scheduled_start', 'scheduled_end', 'planned_start', 'planned_end', 'demand_date']

export function serializeDates(vals: Record<string, unknown>): Record<string, unknown> {
  const result = { ...vals }
  for (const key of DATE_KEYS) {
    if (result[key] && dayjs.isDayjs(result[key])) {
      result[key] = (result[key] as dayjs.Dayjs).format('YYYY-MM-DD')
    }
  }
  return result
}

// ponytail: 消除 PlanItemTable/PlanOrderDetailDrawer 两处重复的批生成节奏规则
// 序列语义：参考项占位置 0（偏移 0 天），新批次从位置 seqIdx=1 起；
// 第 p 位所在组 = floor(p/n)，组起点偏移 floor(p/n)*m 天，组内第 p%n 批再间隔 (p%n)*k 天。
export function batchRhythmOverlaps(groupSize: number, intervalDays: number, gapDays: number): boolean {
  // 一组内最后一批偏移 (n-1)*k 天，下一组起点偏移 m 天：两者重叠即组间排程重叠
  return (groupSize - 1) * gapDays >= intervalDays
}

export function batchRhythmWarning(groupSize: number, intervalDays: number, gapDays: number): string | null {
  return batchRhythmOverlaps(groupSize, intervalDays, gapDays)
    ? `配置不合理：${groupSize} 批间隔 ${gapDays} 天会超过每组周期 ${intervalDays} 天，排程将重叠`
    : null
}

export function batchGenDayOffset(seqIdx: number, groupSize: number, intervalDays: number, gapDays: number): number {
  const pos = seqIdx - 1 // 参考项为位置 0，新批次从位置 1 起
  return Math.floor(pos / groupSize) * intervalDays + (pos % groupSize) * gapDays
}

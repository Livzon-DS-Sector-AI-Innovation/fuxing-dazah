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

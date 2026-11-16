'use server'

import type { HeadcountData } from '@/types/hr'
import { fetchHrApi } from './_helpers'

// ─── 编制数（部门定编） ───

/** 部门定编一览（在编实时统计 + 缺编 + 岗位明细 + 汇总指标） */
export async function fetchHeadcountPlans(): Promise<{ data: HeadcountData }> {
  return fetchHrApi('/hr/headcount/plans', { errorMessage: '加载编制数据失败' })
}

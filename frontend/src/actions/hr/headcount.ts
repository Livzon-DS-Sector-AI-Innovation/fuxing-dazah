'use server'

import type { HeadcountData } from '@/types/hr'
import { fetchHrApi, fetchHrDownload } from './_helpers'

// ─── 编制数（部门定编） ───

/** 部门定编一览（在编实时统计 + 缺编 + 岗位明细 + 汇总指标） */
export async function fetchHeadcountPlans(): Promise<{ data: HeadcountData }> {
  return fetchHrApi('/hr/headcount/plans', { errorMessage: '加载编制数据失败' })
}

// 导出编制对账（Excel，keyword 与前端搜索框同口径按部门模糊过滤，末行合计）
export async function exportHeadcountPlans(keyword?: string): Promise<{ base64: string; filename: string }> {
  const qs = keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''
  const { base64, filename } = await fetchHrDownload(`/hr/headcount/plans/export${qs}`, {
    errorMessage: '导出编制对账失败',
  })
  return { base64, filename: filename || `编制对账_${new Date().toISOString().slice(0, 10)}.xlsx` }
}

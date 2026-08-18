// energy 模块前端报错上报（fire-and-forget，后端写日志文件）
// 后端接口：POST /api/v1/energy/client-error-logs

export interface EnergyClientErrorReport {
  message: string
  stack?: string
  page_url?: string
  api_url?: string
  status?: number
  component?: string
  occurred_at?: string
}

// 与 lib/api/energy.ts 保持一致：优先 NEXT_PUBLIC_API_BASE_URL，否则走 rewrites 代理
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || ''

/** 上报 energy 前端错误。上报失败（后端不可达）时回退 console，避免递归上报。 */
export function reportEnergyError(report: EnergyClientErrorReport): void {
  const payload: EnergyClientErrorReport = {
    ...report,
    occurred_at: report.occurred_at ?? new Date().toISOString(),
  }
  fetch(`${API_BASE}/api/v1/energy/client-error-logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  }).catch(() => {
    console.error('[energy] 前端错误上报失败', payload)
  })
}

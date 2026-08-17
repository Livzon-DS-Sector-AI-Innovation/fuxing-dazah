// 工具箱首页：服务端拉取工具列表

import { apiGet } from '@/lib/http-client'

import { ToolGrid } from '@/components/toolbox'
import type { ToolInfo } from '@/types/toolbox'

export const dynamic = 'force-dynamic'

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

export default async function ToolboxPage() {
  let tools: ToolInfo[] = []
  try {
    tools = await apiGet<ToolInfo[]>(`${API_BASE}/api/v1/toolbox/tools`, { cache: 'no-store' })
  } catch {
    tools = []
  }
  return (
    <div>
      <h1 className="px-6 pt-6 text-[20px] font-semibold text-[var(--color-charcoal)]">工具箱</h1>
      {tools.length === 0 ? (
        <p className="px-6 pt-4 text-[var(--color-stone)]">暂无可用工具</p>
      ) : (
        <ToolGrid tools={tools} />
      )}
    </div>
  )
}

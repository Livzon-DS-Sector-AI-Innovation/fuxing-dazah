// 工具箱首页：服务端拉取工具列表

import { apiGet } from '@/lib/http-client'

import { ToolGrid } from '@/components/toolbox'
import WebThreads from '@/components/WebThreads'
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
    <div className="relative min-h-[calc(100%+3rem)] -m-6">
      {/* WebThreads 背景：铺满当前内容区并开启鼠标交互；背景画布接收鼠标事件，视觉上仍在内容下层 */}
      <div className="absolute inset-0 z-0">
        <WebThreads
          color1="#5227FF"
          color2="#FF9FFC"
          color3="#FFFFFF"
          speed={0.35}
          threadCount={6}
          frequency={6.5}
          spread={0.33}
          taper={2.8}
          position={0.14}
          fanMode="center"
          glow={0.02}
          falloff={0.6}
          thickness={1.1}
          brightness={0.6}
          opacity={0.35}
          mirror={true}
          shimmer={false}
          grain={true}
          grainIntensity={0.06}
          mouseInteraction={true}
          mouseStrength={0.27}
        />
      </div>

      {/* 内容层：pointer-events-none 让空白/间隙的事件穿透到背景画布，仅工具卡片保持可点击 */}
      <div className="relative z-10 pointer-events-none">
        <h1 className="px-6 pt-6 text-[20px] font-semibold text-[var(--color-charcoal)]">花篮</h1>
        {tools.length === 0 ? (
          <p className="px-6 pt-4 text-[var(--color-stone)]">暂无可用工具</p>
        ) : (
          <ToolGrid tools={tools} />
        )}
      </div>
    </div>
  )
}

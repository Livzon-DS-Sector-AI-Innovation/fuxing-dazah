import { AgentAssistant } from '@/components/warehouse/AgentAssistant'
import type { ReactNode } from 'react'

/** 仓储模块布局：挂载 AI 悬浮助手（仅 /warehouse 路由组）。 */
export default function WarehouseLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <AgentAssistant />
    </>
  )
}

'use client'

import { App } from 'antd'
import { TopNav } from "./TopNav"
import { Sidebar } from "./Sidebar"
import { usePermission } from '@/hooks/usePermission'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  // 在根布局触发权限加载，确保所有子页面渲染时权限数据已就绪。
  // 后续页面中的 usePermission() 调用直接从 store 读取缓存结果。
  usePermission()

  return (
    <div className="relative h-screen flex flex-col overflow-hidden">
      {/* 玻璃的衬底：fixed 脱离文档流，不参与下面的 flex 布局 */}
      <div className="ambient-backdrop" aria-hidden />
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <App className="flex-1 overflow-hidden">
          <main className="app-main relative z-10 h-full overflow-y-auto p-6">
            {children}
          </main>
        </App>
      </div>
    </div>
  )
}

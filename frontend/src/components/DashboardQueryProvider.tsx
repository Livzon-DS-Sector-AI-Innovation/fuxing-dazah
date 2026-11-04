'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

/**
 * 全局 React Query Provider（dashboard 布局层挂载）。
 * 各模块此前自行包 Provider（PersonnelQueryProvider / KnowledgeQueryProvider 等），
 * safety 模块合并后大量组件直接使用 useQuery，统一在此提供兜底，
 * 避免每页各自包装、漏包即运行时 "No QueryClient set"。
 */

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 5 分钟：后端已有 TTL 缓存 + 定时预热，前端窗口内切页/回看直接
        // 用缓存，不再每 30s 过期就重打一遍重接口（2026-11-02 性能修复）
        staleTime: 5 * 60 * 1000,
        retry: 1,
      },
    },
  })
}

export function DashboardQueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient)

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

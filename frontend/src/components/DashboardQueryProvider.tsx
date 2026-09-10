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
        staleTime: 30 * 1000,
        retry: 1,
      },
    },
  })
}

export function DashboardQueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient)

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

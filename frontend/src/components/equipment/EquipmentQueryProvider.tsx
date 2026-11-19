'use client'

import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

/** 设备模块的 React Query 客户端；巡检执行页用 useQuery 取已提交记录，避免 effect 里手工 setState。 */
export function EquipmentQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
      }),
  )
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

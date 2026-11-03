'use client'

import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

/** QA 模块的 React Query 客户端；偏差/CAPA 页面用 useQuery 取数，避免 effect 里手工 setState。 */
export function QaQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
      }),
  )
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

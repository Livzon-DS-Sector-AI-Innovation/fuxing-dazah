import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntdApp } from 'antd'
import type { ReactNode } from 'react'
import { render } from '@testing-library/react'

/**
 * 组件测试通用渲染：自带独立 QueryClient（关闭 retry 避免错误态用例反复重试）
 * 与 antd App 上下文（组件内 App.useApp() 可用）。
 */
export function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const utils = render(
    <AntdApp>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </AntdApp>,
  )
  return { ...utils, queryClient }
}

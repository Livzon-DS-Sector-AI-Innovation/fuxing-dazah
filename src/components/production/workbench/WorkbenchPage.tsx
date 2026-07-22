'use client'

import { Suspense } from 'react'
import { ConfigProvider, App, Skeleton } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { WorkbenchInner } from './WorkbenchInner'

export function WorkbenchPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
            <WorkbenchInner />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

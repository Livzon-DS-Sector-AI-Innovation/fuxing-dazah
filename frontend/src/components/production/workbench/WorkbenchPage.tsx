'use client'

import { Suspense } from 'react'
import { ConfigProvider, App, Skeleton } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { WorkbenchInner } from './WorkbenchInner'
import styles from './Workbench.module.css'

export function WorkbenchPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider
        theme={antdTheme}
        locale={zhCN}
        modal={{ classNames: { root: styles.surface, container: styles.dialog, header: styles.dialogHeader, body: styles.dialogBody, footer: styles.dialogFooter } }}
      >
        <App className={styles.surface}>
          <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} />}>
            <WorkbenchInner />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

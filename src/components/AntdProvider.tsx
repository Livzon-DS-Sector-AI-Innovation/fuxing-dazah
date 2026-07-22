'use client'

import { ConfigProvider, App } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

dayjs.locale('zh-cn')

interface AntdProviderProps {
  children: React.ReactNode
}

export function AntdProvider({ children }: AntdProviderProps) {
  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>{children}</App>
    </ConfigProvider>
  )
}

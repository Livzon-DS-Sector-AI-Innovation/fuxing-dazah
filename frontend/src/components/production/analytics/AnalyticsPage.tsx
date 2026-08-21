'use client'

import { ConfigProvider, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { StageSummaryTable } from './StageSummaryTable'
import { FieldTrendChart } from './FieldTrendChart'

export function AnalyticsPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <div style={{ padding: 24 }}>
          <div style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
              数据汇总
            </h2>
            <span style={{ color: '#787671', fontSize: 14 }}>
              工段汇总矩阵与批次字段趋势分析
            </span>
          </div>
          <Tabs
            items={[
              { key: 'summary', label: '工段汇总', children: <StageSummaryTable /> },
              { key: 'trend', label: '字段趋势', children: <FieldTrendChart /> },
            ]}
          />
        </div>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

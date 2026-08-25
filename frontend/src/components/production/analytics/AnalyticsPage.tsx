'use client'

import { useState } from 'react'
import { ConfigProvider, Empty, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import type { Product } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { ProductSidebar, CARD_STYLE } from '../shared/ProductSidebar'
import { StageSummaryTable } from './StageSummaryTable'
import { FieldTrendChart } from './FieldTrendChart'

export function AnalyticsPage() {
  const [product, setProduct] = useState<Product | null>(null)

  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <div>
          <div style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
              数据汇总
            </h2>
            <span style={{ color: '#787671', fontSize: 14 }}>
              工段汇总矩阵与批次字段趋势分析
            </span>
          </div>
          <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
            <ProductSidebar
              selectedId={product?.id ?? null}
              onSelect={p => setProduct(p)}
            />
            <div style={{ ...CARD_STYLE, flex: 1, minWidth: 0, padding: 16, minHeight: 560 }}>
              {product ? (
                <Tabs
                  items={[
                    {
                      key: 'summary',
                      label: '工段汇总',
                      children: (
                        <StageSummaryTable
                          key={`summary-${product.id}`}
                          productId={product.id}
                        />
                      ),
                    },
                    {
                      key: 'trend',
                      label: '字段趋势',
                      children: (
                        <FieldTrendChart
                          key={`trend-${product.id}`}
                          productId={product.id}
                        />
                      ),
                    },
                  ]}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="请在左侧选择产品，查看数据汇总"
                  style={{ padding: '80px 0' }}
                />
              )}
            </div>
          </div>
        </div>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

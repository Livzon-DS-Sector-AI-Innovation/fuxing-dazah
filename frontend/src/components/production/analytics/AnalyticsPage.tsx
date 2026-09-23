'use client'

import { useState } from 'react'
import { ConfigProvider, Empty, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { antdTheme } from '@/lib/antd-theme'
import type { Product } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { ProductSidebar, CARD_STYLE } from '../shared/ProductSidebar'
import { PageGuideButton } from '../shared/PageGuideButton'
import { StageSummaryTable } from './StageSummaryTable'
import { FieldTrendChart } from './FieldTrendChart'
import { PageHeading } from '@/components/shared/PageHeading'

export function AnalyticsPage() {
  const [product, setProduct] = useState<Product | null>(null)

  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <div>
          <PageHeading
            title="数据汇总"
            subtitle="工段汇总矩阵与批次字段趋势分析"
            actions={<PageGuideButton />}
          />
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

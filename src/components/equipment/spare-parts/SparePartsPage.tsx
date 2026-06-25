'use client'

import { useEffect, useCallback } from 'react'
import { App, ConfigProvider, Button, Spin } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { PlusOutlined } from '@ant-design/icons'
import { SparePart, StockWarning } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import { fetchSparePartsClient, fetchStockWarningsClient } from '@/lib/api/equipment-client'
import { SparePartTable } from './SparePartTable'
import { SparePartDrawer } from './SparePartDrawer'
import { StockInboundDrawer } from './StockInboundDrawer'

interface SparePartsPageProps {
  initialSpareParts: SparePart[]
  initialSparePartTotal: number
  initialStockWarnings: StockWarning[]
}

export function SparePartsPage({
  initialSpareParts,
  initialSparePartTotal,
  initialStockWarnings,
}: SparePartsPageProps) {
  const {
    sparePartPage, sparePartPageSize, sparePartKeyword,
    setSpareParts, setSparePartTotal, setSparePartLoading, setStockWarnings,
    openSparePartDrawer,
  } = useEquipmentStore()

  useEffect(() => {
    setSpareParts(initialSpareParts)
    setSparePartTotal(initialSparePartTotal)
    setStockWarnings(initialStockWarnings)
  }, [initialSpareParts, initialSparePartTotal, initialStockWarnings, setSpareParts, setSparePartTotal, setStockWarnings])

  const fetchData = useCallback(async () => {
    setSparePartLoading(true)
    try {
      const [partsRes, warnings] = await Promise.all([
        fetchSparePartsClient({
          keyword: sparePartKeyword || undefined,
          page: sparePartPage, page_size: sparePartPageSize,
        }),
        fetchStockWarningsClient(),
      ])
      setSpareParts(partsRes.items)
      setSparePartTotal(partsRes.total)
      setStockWarnings(warnings)
    } catch (e) {
      console.error('获取备件数据失败:', e)
    } finally {
      setSparePartLoading(false)
    }
  }, [sparePartKeyword, sparePartPage, sparePartPageSize, setSpareParts, setSparePartTotal, setSparePartLoading, setStockWarnings])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        <div style={{ marginBottom: 24 }}>
          <h2 style={{
            fontSize: 22, fontWeight: 600, color: '#1a1a1a',
            margin: 0, marginBottom: 4, lineHeight: 1.3,
          }}>
            备件管理
          </h2>
          <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
            备件库存 · 入库管理 · 库存预警 · 物料追踪
          </p>
        </div>
        <div
          style={{
            background: '#ffffff',
            padding: 20,
            borderRadius: 12,
            border: '1px solid #e5e3df',
          }}
        >
          <SparePartTable onRefresh={fetchData} />
        </div>

        <SparePartDrawer onRefresh={fetchData} />
        <StockInboundDrawer onRefresh={fetchData} />
      </App>
    </ConfigProvider>
  )
}

'use client'

import { useEffect, useCallback, useState } from 'react'
import { App, ConfigProvider, Tabs, Table } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import type { ColumnsType } from 'antd/es/table'
import { SparePart, StockWarning, OutboundTransaction } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import { fetchSparePartsClient, fetchStockWarningsClient, fetchOutboundTransactionsClient } from '@/lib/api/equipment-client'
import { SparePartTable } from './SparePartTable'
import { SparePartDrawer } from './SparePartDrawer'
import { SparePartEquipmentDrawer } from './SparePartEquipmentDrawer'

const txColumns: ColumnsType<OutboundTransaction> = [
  { title: '备件编码', dataIndex: 'spare_part_code', key: 'spare_part_code', width: 110, render: (v: string | null) => v || '-' },
  { title: '备件名称', dataIndex: 'spare_part_name', key: 'spare_part_name', width: 130 },
  { title: '规格', dataIndex: 'specification', key: 'specification', width: 100, render: (v: string | null) => v || '-' },
  { title: '数量', dataIndex: 'quantity', key: 'quantity', width: 60, render: (v: number) => Math.abs(v) },
  { title: '单位', dataIndex: 'unit', key: 'unit', width: 60, render: (v: string | null) => v || '-' },
  { title: '工单编号', dataIndex: 'work_order_no', key: 'work_order_no', width: 150, render: (v: string | null) => v || '-' },
  { title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 120, render: (v: string | null) => v || '-' },
  { title: '消耗时间', dataIndex: 'consumed_at', key: 'consumed_at', width: 140, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
]

interface SparePartsPageProps {
  initialSpareParts: SparePart[]
  initialSparePartTotal: number
  initialStockWarnings: StockWarning[]
  userDepartmentName?: string | null
}

export function SparePartsPage({
  initialSpareParts,
  initialSparePartTotal,
  initialStockWarnings,
  userDepartmentName,
}: SparePartsPageProps) {
  const {
    sparePartPage, sparePartPageSize, sparePartKeyword,
    setSpareParts, setSparePartTotal, setSparePartLoading, setStockWarnings,
  } = useEquipmentStore()

  // Tab 切换
  const [tab, setTab] = useState('parts')

  // 消耗流水
  const [transactions, setTransactions] = useState<OutboundTransaction[]>([])
  const [txLoading, setTxLoading] = useState(false)
  const [txTotal, setTxTotal] = useState(0)
  const [txPage, setTxPage] = useState(1)

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

  const fetchTransactions = useCallback(async (page = 1) => {
    setTxLoading(true)
    try {
      const result = await fetchOutboundTransactionsClient(page, 10)
      setTransactions(result.items)
      setTxTotal(result.total)
      setTxPage(page)
    } catch { /* ignore */ } finally {
      setTxLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab === 'consumption') fetchTransactions()
  }, [tab, fetchTransactions])

  const tabItems = [
    {
      key: 'parts',
      label: '备件管理',
      children: <SparePartTable onRefresh={fetchData} />,
    },
    {
      key: 'consumption',
      label: '消耗流水',
      children: (
        <Table<OutboundTransaction>
          columns={txColumns}
          dataSource={transactions}
          rowKey="id"
          size="small"
          loading={txLoading}
          scroll={{ x: 'max-content' }}
          pagination={{
            current: txPage,
            pageSize: 10,
            total: txTotal,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => fetchTransactions(p),
          }}
        />
      ),
    },
  ]

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        {/* ── 页面标题 ── */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{
            fontSize: 22, fontWeight: 600, color: '#1a1a1a',
            margin: 0, marginBottom: 4, lineHeight: 1.3,
          }}>
            备件管理
          </h2>
          <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
            备件主数据 · 设备关联 · 消耗追踪
          </p>
        </div>

        <div style={{ background: '#ffffff', padding: 20, borderRadius: 12, border: '1px solid #e5e3df' }}>
          <Tabs activeKey={tab} onChange={setTab} items={tabItems} />
        </div>

        <SparePartDrawer onRefresh={fetchData} userDepartmentName={userDepartmentName} />
        <SparePartEquipmentDrawer onRefresh={fetchData} />
      </App>
    </ConfigProvider>
  )
}

'use client'

import { useEffect, useCallback, useState, useRef } from 'react'
import { App, ConfigProvider, Tabs, Table, Tag, Select, Input, Space, DatePicker, Button } from 'antd'
import { CloseCircleOutlined } from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { SparePart, StockWarning, OutboundTransaction } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { antdTheme } from '@/lib/antd-theme'
import { fetchSparePartsClient, fetchStockWarningsClient, fetchOutboundTransactionsClient } from '@/lib/api/equipment-client'
import { SparePartTable } from './SparePartTable'
import { SparePartDrawer } from './SparePartDrawer'
import { SparePartEquipmentDrawer } from './SparePartEquipmentDrawer'
import { StockInboundDrawer } from './StockInboundDrawer'
import { StockOutboundDrawer } from './StockOutboundDrawer'
import { StockAdjustDrawer } from './StockAdjustDrawer'
import { StockSettingsDrawer } from './StockSettingsDrawer'
import { StockWarningTable } from './StockWarningTable'
import { SparePartImportModal } from './SparePartImportModal'
import { PageHeading } from '@/components/shared/PageHeading'
import { PageGuideButton } from '../shared/PageGuideButton'

const { RangePicker } = DatePicker

const txColumns: ColumnsType<OutboundTransaction> = [
  { title: '时间', dataIndex: 'consumed_at', key: 'consumed_at', width: 140, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
  { title: '备件编码', dataIndex: 'spare_part_code', key: 'spare_part_code', width: 110, render: (v: string | null) => v || '-' },
  { title: '备件名称', dataIndex: 'spare_part_name', key: 'spare_part_name', width: 130 },
  { title: '规格', dataIndex: 'specification', key: 'specification', width: 100, render: (v: string | null) => v || '-' },
  {
    title: '类型', dataIndex: 'transaction_type', key: 'transaction_type', width: 80,
    render: (v: string | null) => {
      if (v === '入库') return <Tag color="green">入库</Tag>
      if (v === '出库') return <Tag color="red">出库</Tag>
      if (v === '盘点调整') return <Tag color="orange">盘点调整</Tag>
      return v || '-'
    },
  },
  {
    title: '数量', dataIndex: 'quantity', key: 'quantity', width: 70, align: 'right',
    render: (v: number) => (
      <span style={{ fontWeight: 600, color: v >= 0 ? '#2f9e44' : '#e03131' }}>
        {v >= 0 ? `+${v}` : v}
      </span>
    ),
  },
  { title: '单位', dataIndex: 'unit', key: 'unit', width: 55, render: (v: string | null) => v || '-' },
  { title: '操作人', dataIndex: 'operator_name', key: 'operator_name', width: 90, render: (v: string | null) => v || '-' },
  { title: '备注', dataIndex: 'remark', key: 'remark', width: 150, ellipsis: true, render: (v: string | null) => v || '-' },
  { title: '工单编号', dataIndex: 'work_order_no', key: 'work_order_no', width: 140, render: (v: string | null) => v || '-' },
  { title: '设备', dataIndex: 'equipment_name', key: 'equipment_name', width: 120, render: (v: string | null) => v || '-' },
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
    sparePartStatusFilter, sparePartLowStockFilter,
    setSpareParts, setSparePartTotal, setSparePartLoading, setStockWarnings,
  } = useEquipmentStore()

  // Tab 切换
  const [tab, setTab] = useState('parts')
  // 导入弹窗
  const [importModalOpen, setImportModalOpen] = useState(false)

  // 库存流水
  const [transactions, setTransactions] = useState<OutboundTransaction[]>([])
  const [txLoading, setTxLoading] = useState(false)
  const [txTotal, setTxTotal] = useState(0)
  const [txPage, setTxPage] = useState(1)
  const [txPageSize, setTxPageSize] = useState(10)
  const [txTypeFilter, setTxTypeFilter] = useState<string | undefined>()
  const [txKeyword, setTxKeyword] = useState('')
  const [txDateRange, setTxDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [txSparePartId, setTxSparePartId] = useState<string | null>(null)
  const [txSparePartLabel, setTxSparePartLabel] = useState<SparePart | null>(null)

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
          is_active: sparePartStatusFilter === 'active' ? true : sparePartStatusFilter === 'inactive' ? false : undefined,
          low_stock: sparePartLowStockFilter === 'low' ? true : undefined,
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
  }, [sparePartKeyword, sparePartStatusFilter, sparePartLowStockFilter, sparePartPage, sparePartPageSize, setSpareParts, setSparePartTotal, setSparePartLoading, setStockWarnings])

  // 服务端已预取初值：首次挂载且筛选为默认时跳过重复拉取；
  // 客户端导航返回（store 里筛选仍在）则照常拉取
  const initialLoadRef = useRef(true)
  useEffect(() => {
    // 只有挂载后的第一次渲染可以跳过拉取；此后任何筛选变化都必须重新拉取，
    // 否则「带残留筛选挂载 → 清空筛选」会命中 pristine 分支导致表格停在旧结果
    if (initialLoadRef.current) {
      initialLoadRef.current = false
      const pristine = !sparePartKeyword && sparePartPage === 1 && sparePartPageSize === 20
        && !sparePartStatusFilter && !sparePartLowStockFilter
      if (pristine) return
    }
    fetchData()
  }, [fetchData, sparePartKeyword, sparePartPage, sparePartPageSize, sparePartStatusFilter, sparePartLowStockFilter])

  const fetchTransactions = useCallback(async (page = 1, type?: string, keyword?: string, options?: { sparePartId?: string | null; dateRange?: [Dayjs | null, Dayjs | null] | null; pageSize?: number }) => {
    setTxLoading(true)
    try {
      const sparePartId = options?.sparePartId !== undefined ? options.sparePartId : txSparePartId
      const range = options?.dateRange !== undefined ? options.dateRange : txDateRange
      const result = await fetchOutboundTransactionsClient(page, options?.pageSize ?? txPageSize, type, keyword, {
        sparePartId: sparePartId || undefined,
        dateFrom: range?.[0] ? range[0].startOf('day').toISOString() : undefined,
        dateTo: range?.[1] ? range[1].endOf('day').toISOString() : undefined,
      })
      setTransactions(result.items)
      setTxTotal(result.total)
      setTxPage(page)
    } catch { /* ignore */ } finally {
      setTxLoading(false)
    }
  }, [txSparePartId, txDateRange, txPageSize])

  const handleTabChange = (key: string) => {
    setTab(key)
    // 带上当前筛选，否则切回页签后控件仍显示筛选值但请求丢掉了 type/keyword
    if (key === 'consumption') fetchTransactions(1, txTypeFilter, txKeyword)
  }

  // 台账行「查看流水」：带备件过滤切到流水 Tab
  const handleViewTransactions = useCallback((sparePartId: string) => {
    const part = useEquipmentStore.getState().spareParts.find(p => p.id === sparePartId) ?? null
    setTxSparePartLabel(part)
    setTxSparePartId(sparePartId)
    setTab('consumption')
    fetchTransactions(1, txTypeFilter, txKeyword, { sparePartId })
  }, [fetchTransactions, txTypeFilter, txKeyword])

  const clearTxSparePart = () => {
    setTxSparePartLabel(null)
    setTxSparePartId(null)
    fetchTransactions(1, txTypeFilter, txKeyword, { sparePartId: null })
  }

  const tabItems = [
    {
      key: 'parts',
      label: '备件管理',
      children: <SparePartTable onRefresh={fetchData} onImportClick={() => setImportModalOpen(true)} onViewTransactions={handleViewTransactions} />,
    },
    {
      key: 'consumption',
      label: '出入库记录',
      children: (
        <div>
          <Space style={{ marginBottom: 12 }} wrap>
            {txSparePartId && txSparePartLabel && (
              <Tag closable onClose={clearTxSparePart} color="purple">
                只看：{txSparePartLabel.code} {txSparePartLabel.name}
              </Tag>
            )}
            <Select
              placeholder="全部类型"
              allowClear
              style={{ width: 110 }}
              value={txTypeFilter}
              onChange={(v) => { setTxTypeFilter(v); fetchTransactions(1, v, txKeyword) }}
              options={[
                { label: '入库', value: '入库' },
                { label: '出库', value: '出库' },
                { label: '盘点调整', value: '盘点调整' },
              ]}
            />
            <RangePicker
              value={txDateRange}
              onChange={(range) => {
                setTxDateRange(range as [Dayjs | null, Dayjs | null] | null)
                fetchTransactions(1, txTypeFilter, txKeyword, { dateRange: range as [Dayjs | null, Dayjs | null] | null })
              }}
              placeholder={['开始日期', '结束日期']}
            />
            <Input.Search
              placeholder="搜索备件编码或名称"
              allowClear
              style={{ width: 220 }}
              value={txKeyword}
              onSearch={(v) => { setTxKeyword(v); fetchTransactions(1, txTypeFilter, v) }}
              onChange={(e) => { if (!e.target.value) { setTxKeyword(''); fetchTransactions(1, txTypeFilter, '') } }}
            />
            {(txDateRange || txTypeFilter || txKeyword || txSparePartId) && (
              <Button
                type="text" size="small" icon={<CloseCircleOutlined />}
                onClick={() => {
                  setTxTypeFilter(undefined); setTxKeyword(''); setTxDateRange(null)
                  setTxSparePartLabel(null); setTxSparePartId(null)
                  fetchTransactions(1, undefined, '', { sparePartId: null, dateRange: null })
                }}
              >
                重置
              </Button>
            )}
          </Space>
          <Table<OutboundTransaction>
            columns={txColumns}
            dataSource={transactions}
            rowKey="id"
            size="small"
            loading={txLoading}
            scroll={{ x: 'max-content' }}
            pagination={{
              current: txPage,
              pageSize: txPageSize,
              total: txTotal,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, s) => {
                if (s !== txPageSize) setTxPageSize(s)
                fetchTransactions(p, txTypeFilter, txKeyword, { pageSize: s })
              },
            }}
          />
        </div>
      ),
    },
    {
      key: 'warnings',
      label: '库存预警',
      children: <StockWarningTable />,
    },
  ]

  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <App>
        {/* ── 页面标题 ── */}
        <PageHeading
          title="备件管理"
          subtitle="备件主数据 · 库存预警 · 出入库追踪"
          actions={<PageGuideButton />}
        />

        <div style={{ background: '#ffffff', padding: 20, borderRadius: 12, border: '1px solid #e5e3df' }}>
          <Tabs activeKey={tab} onChange={handleTabChange} items={tabItems} />
        </div>

        <SparePartDrawer onRefresh={fetchData} userDepartmentName={userDepartmentName} />
        <SparePartEquipmentDrawer onRefresh={fetchData} />
        <StockInboundDrawer onRefresh={fetchData} />
        <StockOutboundDrawer onRefresh={fetchData} />
        <StockAdjustDrawer onRefresh={fetchData} />
        <StockSettingsDrawer onRefresh={fetchData} />
        <SparePartImportModal
          open={importModalOpen}
          onClose={() => setImportModalOpen(false)}
          onImported={fetchData}
        />
      </App>
    </ConfigProvider>
  )
}

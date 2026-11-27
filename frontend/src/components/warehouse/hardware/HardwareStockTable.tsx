'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Drawer, Input, Segmented, Select, Table, Upload } from 'antd'
import type { TableColumnsType } from 'antd'
import { DownloadOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchHardwareStockClient,
  fetchHardwareStockDetailClient,
  fetchHardwareStockSummaryClient,
  exportHardwareStockUrl,
  importHardwareMaterials,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_MANAGED_CLASS_LABEL,
  type HardwareStockRow,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { EmptyGuide, QueryFilter, SectionCard, StatCard, StatusTag } from '@/components/warehouse'
import { MOVEMENT_DIRECTION_LABEL, MOVEMENT_DIRECTION_TONE } from './constants'
import { formatQty } from './format'

const CATEGORIES = [
  '金属管道', '金属管件', '金属阀门', '食品级垫片',
  '金属轴承', 'UPVC管件', 'ABS管件',
  '仪器仪表', '化玻试剂', '劳保用品', '耗材', '其他',
]

export function HardwareStockTable() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:material:manage')

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [scope, setScope] = useState<'stocked' | 'all'>('stocked')
  const [lowOnly, setLowOnly] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)

  const { data: summary } = useQuery({
    queryKey: ['warehouse', 'hardware', 'summary'],
    queryFn: fetchHardwareStockSummaryClient,
  })

  const { data: res, isLoading, isError, refetch } = useQuery({
    queryKey: ['warehouse', 'hardware', 'stock', { page, pageSize, keyword, category, scope, lowOnly }],
    queryFn: () =>
      fetchHardwareStockClient({
        keyword: keyword || undefined,
        category,
        managed_class: scope === 'all' ? '' : 'stocked',
        low_only: lowOnly,
        page,
        pageSize,
      }),
    placeholderData: keepPreviousData,
  })

  useEffect(() => {
    if (isError) message.error('获取五金库库存失败')
  }, [isError, message])

  const rows: HardwareStockRow[] = res?.items ?? []

  const columns: TableColumnsType<HardwareStockRow> = [
    {
      title: '编码',
      dataIndex: ['material', 'code'],
      width: 95,
      render: (v: string | null) => <span className="text-[12px] font-mono">{v || '待回填'}</span>,
    },
    { title: '类别', dataIndex: 'category', width: 88 },
    {
      title: '物资名称',
      dataIndex: 'name',
      width: 165,
      ellipsis: true,
      render: (v: string, r) => (
        <a onClick={() => setDetailId(r.material.id)}>{v}</a>
      ),
    },
    { title: '规格型号', dataIndex: 'spec', width: 140, ellipsis: true, render: (v) => v || '-' },
    { title: '单位', dataIndex: 'unit', width: 56 },
    {
      title: '位号',
      dataIndex: ['material', 'location_no'],
      width: 70,
      render: (v: string | null) => v || '—',
    },
    {
      title: '在手',
      dataIndex: 'on_hand',
      width: 78,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) => formatQty(v),
    },
    {
      title: '预扣',
      dataIndex: 'reserved',
      width: 72,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) =>
        Number(v) > 0 ? <span className="text-amber-600">{formatQty(v)}</span> : '0',
    },
    {
      title: '可用',
      dataIndex: 'available',
      width: 82,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown, r) => (
        <span className={r.is_low ? 'font-semibold text-red-600' : 'font-medium'}>
          {formatQty(v)}
        </span>
      ),
    },
    {
      title: '安全库存',
      dataIndex: 'safety_stock',
      width: 86,
      align: 'right',
      className: 'tabular-nums',
      render: (v: unknown) => formatQty(v),
    },
    {
      title: '状态',
      dataIndex: 'is_low',
      width: 92,
      filters: [
        { text: '预警', value: 'low' },
        { text: '正常', value: 'ok' },
      ],
      onFilter: (value, record) => (value === 'low' ? record.is_low : !record.is_low),
      render: (isLow: boolean, r) =>
        isLow ? (
          <StatusTag tone="danger" label={`缺 ${formatQty(r.low_gap)}`} />
        ) : (
          <StatusTag tone="ok" label="正常" />
        ),
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="物料总数" value={(summary?.total_materials ?? 0).toLocaleString()} sub="种" />
        <StatCard label="共用类物料" value={(summary?.stocked_materials ?? 0).toLocaleString()} sub="种" />
        <StatCard
          label="安全库存预警"
          value={(summary?.low_count ?? 0).toLocaleString()}
          sub="种"
          tone={(summary?.low_count ?? 0) > 0 ? 'danger' : 'default'}
        />
        <StatCard
          label="在手总量（件）"
          value={formatQty(summary?.on_hand_total ?? 0)}
        />
      </div>

      {(summary?.low_count ?? 0) > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`${summary?.low_count} 种物资可用量低于安全库存`}
          description={summary?.low_materials
            .slice(0, 6)
            .map((m) => `${m.name}${m.spec ? ` ${m.spec}` : ''}（可用 ${formatQty(m.available)} / 安全 ${formatQty(m.safety_stock)}）`)
            .join('；')}
        />
      )}

      <SectionCard title="库存明细">
        <QueryFilter
          common={
            <>
              <Input
                allowClear
                prefix={<SearchOutlined style={{ color: '#999' }} />}
                placeholder="名称 / 规格 / 编码关键词（如 DN25 阀门）"
                style={{ width: 280 }}
                value={keyword}
                onChange={(e) => {
                  setKeyword(e.target.value)
                  setPage(1)
                }}
              />
              <Select
                allowClear
                placeholder="类别"
                style={{ width: 130 }}
                value={category}
                onChange={(v) => {
                  setCategory(v)
                  setPage(1)
                }}
                options={CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
              <Segmented
                value={scope}
                onChange={(v) => {
                  setScope(v as 'stocked' | 'all')
                  setPage(1)
                }}
                options={[
                  { value: 'stocked', label: '共用类' },
                  { value: 'all', label: '全部' },
                ]}
              />
              <Segmented
                value={lowOnly ? 'low' : 'none'}
                onChange={(v) => {
                  setLowOnly(v === 'low')
                  setPage(1)
                }}
                options={[
                  { value: 'none', label: '全部' },
                  { value: 'low', label: '仅看预警' },
                ]}
              />
              <Button icon={<DownloadOutlined />} href={exportHardwareStockUrl()} target="_blank">
                导出库存
              </Button>
            </>
          }
          advanced={
            <>
              {canManage ? (
                <Upload
                  accept=".xlsx"
                  showUploadList={false}
                  beforeUpload={async (file) => {
                    setImporting(true)
                    try {
                      const stats = await importHardwareMaterials(file)
                      message.success(
                        `导入完成：新建 ${stats.created} / 更新 ${stats.updated} / 跳过 ${stats.skipped}`,
                      )
                      refetch()
                    } catch (e) {
                      message.error(e instanceof Error ? e.message : '导入失败')
                    } finally {
                      setImporting(false)
                    }
                    return false
                  }}
                >
                  <Button icon={<UploadOutlined />} loading={importing}>
                    导入物资清单
                  </Button>
                </Upload>
              ) : null}
            </>
          }
        />

        <Table<HardwareStockRow>
          size="middle"
          rowKey={(r) => r.material.id}
          loading={isLoading}
          columns={columns}
          dataSource={rows}
          locale={{ emptyText: <EmptyGuide compact title="暂无库存数据" description="导入物资清单或调整筛选条件" /> }}
          pagination={{
            current: page,
            pageSize,
            total: res?.total ?? 0,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p)
              setPageSize(ps)
            },
          }}
          scroll={{ x: 920 }}
        />
      </SectionCard>

      <HardwareStockDrawer materialId={detailId} onClose={() => setDetailId(null)} />
    </div>
  )
}

function HardwareStockDrawer({
  materialId,
  onClose,
}: {
  materialId: string | null
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'stock-detail', materialId],
    queryFn: () => fetchHardwareStockDetailClient(materialId!),
    enabled: !!materialId,
  })

  const m = data?.stock.material
  const demands = useMemo(
    () =>
      Object.entries(m?.monthly_demands ?? {}).map(([dept, qty]) => `${dept}: ${formatQty(qty)}`).join('　') || '-',
    [m],
  )

  return (
    <Drawer
      open={!!materialId}
      onClose={onClose}
      size={640}
      title={m ? `${m.name}${m.spec ? ` · ${m.spec}` : ''}` : '物料库存'}
      loading={isLoading}
    >
      {data && m && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="可用" value={formatQty(data.stock.available)} sub={m.unit}
              tone={data.stock.is_low ? 'danger' : 'default'} />
            <StatCard label="在手" value={formatQty(data.stock.on_hand)} sub={m.unit} />
            <StatCard label="预扣" value={formatQty(data.stock.reserved)} sub={m.unit} />
          </div>
          <div className="text-[13px] leading-6 text-[var(--color-charcoal)]">
            <div>编码：{m.code || '待回填'}</div>
            <div>类别：{m.category}（{HARDWARE_MANAGED_CLASS_LABEL[m.managed_class]}）</div>
            <div>位号：{m.location_no || '—'}</div>
            <div>安全库存：{formatQty(m.safety_stock)} {m.unit}{data.stock.is_low && <span className="ml-2"><StatusTag tone="danger" label={`缺口 ${formatQty(data.stock.low_gap)}`} /></span>}</div>
            <div>月需求：{demands}</div>
            <div>采购周期：{m.lead_time_days != null ? `${m.lead_time_days} 天` : '-'}</div>
          </div>

          <SectionCard title={`批次明细（共 ${data.lots.length} 批）`}>
            <Table
              size="small"
              rowKey="lot_id"
              dataSource={data.lots}
              pagination={false}
              columns={[
                { title: '批次号', dataIndex: 'lot_no', width: 130, className: 'font-mono' },
                { title: '来源入库单', dataIndex: 'receipt_no', width: 140, className: 'font-mono' },
                {
                  title: '到货',
                  dataIndex: 'arrived_at',
                  width: 100,
                  render: (v: string | null) => (v ? dayjs(v).format('MM-DD') : '-'),
                },
                { title: '库位', dataIndex: 'location_code', width: 90, render: (v) => v || '-' },
                {
                  title: '剩余/总量',
                  width: 120,
                  align: 'right',
                  className: 'tabular-nums',
                  render: (_: unknown, r) =>
                    `${formatQty(r.remaining_quantity)} / ${formatQty(r.quantity)}`,
                },
              ]}
            />
          </SectionCard>

          <SectionCard title="近期流水">
            <Table
              size="small"
              rowKey="id"
              dataSource={data.recent_movements}
              pagination={false}
              columns={[
                {
                  title: '方向',
                  dataIndex: 'direction',
                  width: 70,
                  render: (v: string) => (
                    <StatusTag
                      tone={MOVEMENT_DIRECTION_TONE[v as keyof typeof MOVEMENT_DIRECTION_TONE] ?? 'default'}
                      label={MOVEMENT_DIRECTION_LABEL[v as keyof typeof MOVEMENT_DIRECTION_LABEL] ?? v}
                    />
                  ),
                },
                { title: '数量', dataIndex: 'quantity', width: 80, align: 'right', className: 'tabular-nums', render: (v: unknown) => formatQty(v) },
                { title: '经办', dataIndex: 'operator', width: 90, render: (v) => v || '-' },
                {
                  title: '时间',
                  dataIndex: 'occurred_at',
                  width: 130,
                  render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
                },
                { title: '单号', dataIndex: 'movement_no', width: 150, className: 'font-mono' },
              ]}
            />
          </SectionCard>
        </div>
      )}
    </Drawer>
  )
}

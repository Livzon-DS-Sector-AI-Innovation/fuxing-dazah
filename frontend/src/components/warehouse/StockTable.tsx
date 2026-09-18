'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  DatePicker,
  Drawer,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Timeline,
} from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import type { TableColumnsType } from 'antd'
import {
  MATERIAL_CATEGORY_LABEL,
  MaterialCategory,
  MOVEMENT_DIRECTION_LABEL,
  STOCK_STATUS_LABEL,
  STOCK_STATUS_TRANSITIONS,
  StockRecord,
  StockStatus,
} from '@/types/warehouse'
import {
  fetchLocationsClient,
  fetchMovementsClient,
  fetchStocksClient,
} from '@/lib/api/warehouse'
import { changeStockStatus } from '@/actions/warehouse'
import { expiryTone } from '@/lib/warehouse-expiry'
import { QueryFilter } from './QueryFilter'
import { StatusTag } from './ui/StatusTag'

const DIRECTION_COLOR: Record<string, string> = {
  inbound: 'green',
  outbound: 'red',
  adjust: 'orange',
}

const STOCK_STATUS_TONE = {
  normal: 'ok',
  quarantine: 'warn',
  frozen: 'danger',
} as const

/** 后端 StockResponse.status 恒有值；兼容缺省时按 normal 展示 */
const statusOf = (value: StockStatus | undefined): StockStatus => value ?? 'normal'

/** QC 取样/出报列只读文本（空值占位 -） */
const QcCell = (value: string | null | undefined) => (
  <span className="text-[13px] text-[var(--color-charcoal)]">{value || '-'}</span>
)

export function StockTable(props: {
  /** 驾驶舱下钻带入的初始筛选 */
  initialKeyword?: string
  initialCategory?: string
} = {}) {
  const { message } = App.useApp()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState(props.initialKeyword ?? '')
  const [category, setCategory] = useState<MaterialCategory | undefined>(
    props.initialCategory as MaterialCategory | undefined,
  )
  const [locationId, setLocationId] = useState<string | undefined>(undefined)
  const [batchNo, setBatchNo] = useState('')
  const [expiryRange, setExpiryRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [statusFilter, setStatusFilter] = useState<StockStatus | undefined>(undefined)
  const [detail, setDetail] = useState<{ id: string; code: string; name: string } | null>(null)
  const [statusTarget, setStatusTarget] = useState<{ record: StockRecord; next: StockStatus } | null>(
    null,
  )
  const [reason, setReason] = useState('')

  const expiryFrom = expiryRange?.[0]?.format('YYYY-MM-DD') ?? undefined
  const expiryTo = expiryRange?.[1]?.format('YYYY-MM-DD') ?? undefined
  const hasFilters = Boolean(
    keyword || category || locationId || batchNo || expiryFrom || expiryTo || statusFilter,
  )

  const {
    data: res,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['warehouse', 'stocks', { page, pageSize, keyword, category, locationId, batchNo, expiryFrom, expiryTo, statusFilter }],
    queryFn: () =>
      fetchStocksClient({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category,
        location_id: locationId,
        batch_no: batchNo || undefined,
        expiry_from: expiryFrom,
        expiry_to: expiryTo,
        status: statusFilter,
      }),
    placeholderData: keepPreviousData,
  })

  const queryClient = useQueryClient()

  const statusMutation = useMutation({
    mutationFn: (vars: { stockId: string; next: StockStatus; reason: string }) =>
      changeStockStatus(vars.stockId, { new_status: vars.next, reason: vars.reason }),
    onSuccess: () => {
      message.success('库存状态已变更')
      setStatusTarget(null)
      setReason('')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'stocks'] })
    },
    onError: (e: unknown) => {
      message.error(e instanceof Error ? e.message : '状态变更失败')
    },
  })

  const { data: locations } = useQuery({
    queryKey: ['warehouse', 'locations'],
    queryFn: () => fetchLocationsClient(),
  })

  useEffect(() => {
    if (isError) message.error('获取库存列表失败')
  }, [isError, message])

  const { data: timeline, isLoading: timelineLoading } = useQuery({
    queryKey: ['warehouse', 'movements', { material_id: detail?.id }],
    queryFn: () =>
      fetchMovementsClient({
        material_id: detail!.id,
        page: 1,
        page_size: 200,
        occurred_from: new Date(Date.now() - 90 * 86_400_000).toISOString(),
      }),
    enabled: !!detail,
  })

  const columns: TableColumnsType<StockRecord> = [
    {
      title: '物料 / 批次',
      dataIndex: 'material_name',
      width: 250,
      render: (_, record) => (
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
            {record.material_name}
          </div>
          <div className="truncate text-[12px] leading-4 text-[var(--color-steel)]">
            {record.material_code} · {record.batch_no || '无批次'}
          </div>
        </div>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 80,
      render: (value: MaterialCategory | null) =>
        value ? <Tag color="blue">{MATERIAL_CATEGORY_LABEL[value] ?? value}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 84,
      render: (value: StockStatus | undefined) => {
        const status = statusOf(value)
        return <StatusTag tone={STOCK_STATUS_TONE[status]} label={STOCK_STATUS_LABEL[status]} />
      },
    },
    {
      title: 'QC 取样',
      dataIndex: 'qc_sample_status',
      width: 90,
      render: QcCell,
    },
    {
      title: 'QC 出报',
      dataIndex: 'qc_report_status',
      width: 118,
      render: QcCell,
    },
    {
      title: 'QA 放行',
      dataIndex: 'qc_release_status',
      width: 96,
      render: (value: string | null | undefined) => {
        if (!value) return <span className="text-[13px] text-[var(--color-stone)]">-</span>
        const tone = value === '放行' ? 'ok' : value === '条件放行' ? 'warn' : 'danger'
        return <StatusTag tone={tone} label={value} />
      },
    },
    {
      title: '效期',
      dataIndex: 'expiry_date',
      width: 150,
      render: (value: string | null) => {
        if (!value) return <span className="text-[var(--color-stone)]">未录入</span>
        const tone = expiryTone(value)
        const days = dayjs(value).startOf('day').diff(dayjs().startOf('day'), 'day')
        const chipTone = days < 0 ? 'expired' : tone === 'danger' ? 'danger' : tone === 'warning' ? 'warn' : 'ok'
        const label = days < 0 ? `已过期 ${Math.abs(days)} 天` : days < 30 ? `剩 ${days} 天` : dayjs(value).format('YYYY-MM-DD')
        return (
          <span className="inline-flex items-center gap-1.5">
            <span className="text-[13px] tabular-nums text-[var(--color-charcoal)]">
              {dayjs(value).format('YYYY-MM-DD')}
            </span>
            <StatusTag tone={chipTone} label={label} />
          </span>
        )
      },
    },
    { title: '库位', dataIndex: 'location_name', width: 130 },
    {
      title: '库存数量',
      key: 'quantity',
      width: 150,
      align: 'right',
      render: (_, record) => {
        const low =
          record.safety_stock != null &&
          record.safety_stock > 0 &&
          record.quantity < record.safety_stock
        return (
          <span className="tabular-nums" style={{ color: low ? 'var(--wh-danger)' : undefined, fontWeight: low ? 600 : 500 }}>
            {record.quantity} {record.unit ?? ''}
            {low && (
              <StatusTag tone="danger" label="低于安全库存" bordered />
            )}
          </span>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_, record) => {
        const current = statusOf(record.status)
        return (
          <span onClick={e => e.stopPropagation()}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={() => {
                setStatusTarget({ record, next: STOCK_STATUS_TRANSITIONS[current][0] })
                setReason('')
              }}
            >
              状态流转
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: '0 0 0 8px' }}
              onClick={() =>
                setDetail({ id: record.material_id, code: record.material_code, name: record.material_name })
              }
            >
              流水
            </Button>
          </span>
        )
      },
    },
  ]

  return (
    <div>
      <QueryFilter
        common={
          <>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索物料/批次"
              style={{ width: 220 }}
              onChange={e => {
                setKeyword(e.target.value)
                setPage(1)
              }}
            />
            <Select
              allowClear
              placeholder="全部分类"
              style={{ width: 140 }}
              value={category}
              onChange={value => {
                setCategory(value)
                setPage(1)
              }}
              options={Object.entries(MATERIAL_CATEGORY_LABEL).map(([value, label]) => ({
                value,
                label,
              }))}
            />
            <Select
              allowClear
              placeholder="全部库位"
              style={{ width: 180 }}
              value={locationId}
              onChange={value => {
                setLocationId(value)
                setPage(1)
              }}
              options={(locations ?? []).map(loc => ({ value: loc.id, label: `${loc.code} ${loc.name}` }))}
            />
            <Select
              allowClear
              placeholder="全部状态"
              style={{ width: 120 }}
              value={statusFilter}
              onChange={value => {
                setStatusFilter(value)
                setPage(1)
              }}
              options={(Object.keys(STOCK_STATUS_LABEL) as StockStatus[]).map(value => ({
                value,
                label: STOCK_STATUS_LABEL[value],
              }))}
            />
          </>
        }
        advanced={
          <>
            <Input
              allowClear
              placeholder="批次号"
              style={{ width: 180 }}
              onChange={e => {
                setBatchNo(e.target.value)
                setPage(1)
              }}
            />
            <DatePicker.RangePicker
              placeholder={['效期从', '效期至']}
              onChange={values => {
                setExpiryRange(values as [Dayjs | null, Dayjs | null] | null)
                setPage(1)
              }}
            />
          </>
        }
      />

      {isError && (
        <Alert
          type="error"
          showIcon
          message="获取库存列表失败"
          description="网络异常或服务不可用，请重试。"
          style={{ marginBottom: 12 }}
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      )}

      <Table<StockRecord>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={res?.items ?? []}
        loading={isLoading}
        locale={{
          emptyText: hasFilters ? '无匹配结果，请调整筛选条件' : '暂无库存数据',
        }}
        onRow={record => ({
          onClick: () =>
            setDetail({ id: record.material_id, code: record.material_code, name: record.material_name }),
          style: { cursor: 'pointer' },
        })}
        pagination={{
          current: page,
          pageSize,
          total: res?.total ?? 0,
          showSizeChanger: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 1400 }}
      />

      <Drawer
        title={detail ? `物料流水：${detail.code} ${detail.name}` : '物料流水'}
        open={!!detail}
        width={560}
        onClose={() => setDetail(null)}
        destroyOnHidden
      >
        <Timeline
          items={(timeline?.items ?? []).map(mv => ({
            color: DIRECTION_COLOR[mv.direction] ?? 'blue',
            children: (
              <span>
                <Tag color={DIRECTION_COLOR[mv.direction]}>
                  {MOVEMENT_DIRECTION_LABEL[mv.direction] ?? mv.direction}
                </Tag>
                {dayjs(mv.occurred_at).format('YYYY-MM-DD HH:mm')} · {mv.quantity} {mv.unit} ·{' '}
                {mv.movement_no}
              </span>
            ),
          }))}
        />
        {timelineLoading && <Spin />}
        {!timelineLoading && (timeline?.items.length ?? 0) === 0 && (
          <span style={{ color: 'var(--ant-color-text-secondary, #999)' }}>该物料暂无流水</span>
        )}
      </Drawer>

      <Modal
        title={
          statusTarget
            ? `状态流转：${statusTarget.record.material_code} 批次 ${statusTarget.record.batch_no || '-'}`
            : '状态流转'
        }
        open={!!statusTarget}
        onCancel={() => {
          setStatusTarget(null)
          setReason('')
        }}
        onOk={() => {
          if (!statusTarget) return
          statusMutation.mutate({
            stockId: statusTarget.record.id,
            next: statusTarget.next,
            reason,
          })
        }}
        okText="确认变更"
        cancelText="取消"
        okButtonProps={{ loading: statusMutation.isPending }}
        destroyOnHidden
      >
        {statusTarget && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <span>
              当前状态：
              <StatusTag
                tone={STOCK_STATUS_TONE[statusOf(statusTarget.record.status)]}
                label={STOCK_STATUS_LABEL[statusOf(statusTarget.record.status)]}
              />
            </span>
            <Select
              style={{ width: '100%' }}
              value={statusTarget.next}
              onChange={value => setStatusTarget({ ...statusTarget, next: value })}
              options={STOCK_STATUS_TRANSITIONS[statusOf(statusTarget.record.status)].map(
                value => ({ value, label: STOCK_STATUS_LABEL[value] }),
              )}
            />
            <Input.TextArea
              rows={3}
              maxLength={500}
              showCount
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="变更原因（可选）"
            />
          </Space>
        )}
      </Modal>
    </div>
  )
}

'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  DatePicker,
  Drawer,
  Input,
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
  StockRecord,
} from '@/types/warehouse'
import {
  fetchLocationsClient,
  fetchMovementsClient,
  fetchStocksClient,
} from '@/lib/api/warehouse'
import { EXPIRY_TONE_COLOR, expiryTone } from '@/lib/warehouse-expiry'
import { QueryFilter } from './QueryFilter'

const DIRECTION_COLOR: Record<string, string> = {
  inbound: 'green',
  outbound: 'red',
  adjust: 'orange',
}

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
  const [detail, setDetail] = useState<{ id: string; code: string; name: string } | null>(null)

  const expiryFrom = expiryRange?.[0]?.format('YYYY-MM-DD') ?? undefined
  const expiryTo = expiryRange?.[1]?.format('YYYY-MM-DD') ?? undefined
  const hasFilters = Boolean(keyword || category || locationId || batchNo || expiryFrom || expiryTo)

  const {
    data: res,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['warehouse', 'stocks', { page, pageSize, keyword, category, locationId, batchNo, expiryFrom, expiryTo }],
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
      }),
    placeholderData: keepPreviousData,
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
    { title: '物料编码', dataIndex: 'material_code', width: 140 },
    { title: '物料名称', dataIndex: 'material_name', width: 180 },
    {
      title: '分类',
      dataIndex: 'category',
      width: 90,
      render: (value: MaterialCategory | null) =>
        value ? <Tag color="blue">{MATERIAL_CATEGORY_LABEL[value] ?? value}</Tag> : '-',
    },
    { title: '批次号', dataIndex: 'batch_no', width: 140, render: v => v || '-' },
    {
      title: '效期',
      dataIndex: 'expiry_date',
      width: 130,
      render: (value: string | null) => {
        if (!value) return '-'
        const tone = expiryTone(value)
        return (
          <span style={{ color: EXPIRY_TONE_COLOR[tone], fontWeight: tone === 'danger' ? 600 : 500 }}>
            {dayjs(value).format('YYYY-MM-DD')}
            {tone === 'danger' ? ' （临期）' : ''}
          </span>
        )
      },
    },
    { title: '库位', dataIndex: 'location_name', width: 140 },
    {
      title: '库存数量',
      key: 'quantity',
      width: 140,
      align: 'right',
      render: (_, record) => {
        const low =
          record.safety_stock != null &&
          record.safety_stock > 0 &&
          record.quantity < record.safety_stock
        return (
          <span style={{ color: low ? 'var(--ant-color-warning, #dd5b00)' : undefined, fontWeight: 500 }}>
            {record.quantity} {record.unit ?? ''}
            {low ? ' （低于安全库存）' : ''}
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
        scroll={{ x: 950 }}
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
    </div>
  )
}

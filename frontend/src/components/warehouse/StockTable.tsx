'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { App, Input, Select, Space, Table, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import {
  MATERIAL_CATEGORY_LABEL,
  MaterialCategory,
  StockRecord,
} from '@/types/warehouse'
import { fetchLocationsClient, fetchStocksClient } from '@/lib/api/warehouse'

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

  const { data: res, isLoading, isError } = useQuery({
    queryKey: ['warehouse', 'stocks', { page, pageSize, keyword, category, locationId }],
    queryFn: () =>
      fetchStocksClient({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category,
        location_id: locationId,
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
      <Space style={{ marginBottom: 12 }} wrap>
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
      </Space>

      <Table<StockRecord>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={res?.items ?? []}
        loading={isLoading}
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
        scroll={{ x: 820 }}
      />
    </div>
  )
}

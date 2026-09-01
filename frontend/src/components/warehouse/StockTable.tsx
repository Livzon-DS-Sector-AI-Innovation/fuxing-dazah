'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Input, Select, Space, Table, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import {
  MATERIAL_CATEGORY_LABEL,
  MaterialCategory,
  StockRecord,
  LocationRecord,
} from '@/types/warehouse'
import { getLocations, getStocks } from '@/actions/warehouse'

export function StockTable() {
  const { message } = App.useApp()
  const [data, setData] = useState<StockRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState<MaterialCategory | undefined>(undefined)
  const [locationId, setLocationId] = useState<string | undefined>(undefined)
  const [locations, setLocations] = useState<LocationRecord[]>([])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getStocks({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category,
        location_id: locationId,
      })
      setData(res.items)
      setTotal(res.total)
    } catch {
      message.error('获取库存列表失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, keyword, category, locationId])

  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
  }, [fetchData])

  useEffect(() => {
    const load = async () => {
      try {
        setLocations(await getLocations())
      } catch {
        // 库位下拉加载失败不阻断页面
      }
    }
    const t = setTimeout(load, 0)
    return () => clearTimeout(t)
  }, [])

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
          options={locations.map(loc => ({ value: loc.id, label: `${loc.code} ${loc.name}` }))}
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
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
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

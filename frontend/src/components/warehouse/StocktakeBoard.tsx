'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { TableColumnsType } from 'antd'
import {
  Paginated,
  StocktakeCreate,
  StocktakeItemRecord,
  StocktakeItemUpdateInput,
  StocktakeRecord,
} from '@/types/warehouse'
import {
  confirmStocktake,
  createStocktake,
  deleteStocktake,
  getLocations,
  getStocktake,
  getStocktakes,
  updateStocktake,
} from '@/actions/warehouse'
import type { LocationRecord } from '@/types/warehouse'

export function StocktakeBoard() {
  const { message } = App.useApp()
  const [data, setData] = useState<StocktakeRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<string | undefined>(undefined)

  const [createOpen, setCreateOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res: Paginated<StocktakeRecord> = await getStocktakes({
        page,
        page_size: pageSize,
        status,
      })
      setData(res.items)
      setTotal(res.total)
    } catch {
      message.error('获取盘点单列表失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, status])

  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
  }, [fetchData])

  const handleDelete = async (record: StocktakeRecord) => {
    try {
      await deleteStocktake(record.id)
      message.success('盘点单已删除')
      fetchData()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败')
    }
  }

  const columns: TableColumnsType<StocktakeRecord> = [
    { title: '盘点单号', dataIndex: 'stocktake_no', width: 180 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: StocktakeRecord['status']) =>
        value === 'confirmed' ? (
          <Tag color="green">已确认</Tag>
        ) : (
          <Tag color="gold">草稿</Tag>
        ),
    },
    {
      title: '盘点范围',
      width: 160,
      render: (_, record) =>
        record.scope_location_name
          ? `${record.scope_location_code ?? ''} ${record.scope_location_name}`
          : '全库',
    },
    {
      title: '明细数',
      width: 90,
      align: 'right',
      render: (_, record) => record.items.length,
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v ?? '-' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: v => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '确认时间',
      dataIndex: 'confirmed_at',
      width: 150,
      render: v => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="link"
            onClick={() => setDetailId(record.id)}
          >
            {record.status === 'draft' ? '盘点' : '查看'}
          </Button>
          {record.status === 'draft' && (
            <Popconfirm title="确定删除该草稿盘点单？" onConfirm={() => handleDelete(record)}>
              <Button size="small" type="link" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 140 }}
          value={status}
          onChange={value => {
            setStatus(value)
            setPage(1)
          }}
          options={[
            { value: 'draft', label: '草稿' },
            { value: 'confirmed', label: '已确认' },
          ]}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          新建盘点
        </Button>
      </Space>

      <Table<StocktakeRecord>
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
        scroll={{ x: 1000 }}
      />

      {createOpen && (
        <StocktakeCreateModal
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false)
            fetchData()
          }}
        />
      )}

      {detailId && (
        <StocktakeDetailDrawer
          stocktakeId={detailId}
          onChanged={fetchData}
          onClose={() => setDetailId(null)}
        />
      )}
    </div>
  )
}

function StocktakeCreateModal(props: { onClose: () => void; onCreated: () => void }) {
  const { message } = App.useApp()
  const [locations, setLocations] = useState<LocationRecord[]>([])
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<StocktakeCreate>()

  useEffect(() => {
    const load = async () => {
      try {
        setLocations(await getLocations())
      } catch {
        // 下拉加载失败不阻断弹窗
      }
    }
    const t = setTimeout(load, 0)
    return () => clearTimeout(t)
  }, [])

  const handleCreate = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const record = await createStocktake({
        scope_location_id: values.scope_location_id || null,
        remark: values.remark || null,
      })
      message.success(`盘点单 ${record.stocktake_no} 已创建，共 ${record.items.length} 条明细`)
      props.onCreated()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="新建盘点单"
      open
      confirmLoading={saving}
      onOk={handleCreate}
      onCancel={props.onClose}
      destroyOnHidden
    >
      <div style={{ color: 'var(--ant-color-text-secondary, #666)', paddingTop: 8 }}>
        将按当前库存快照生成盘点明细；确认后按实盘结果自动调整库存并生成调整流水。
      </div>
      <Form form={form} layout="vertical" style={{ paddingTop: 8 }}>
        <Form.Item name="scope_location_id" label="盘点范围（默认全库）">
          <Select
            allowClear
            placeholder="全库"
            options={locations.map(loc => ({
              value: loc.id,
              label: `${loc.code} ${loc.name}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function StocktakeDetailDrawer(props: {
  stocktakeId: string
  onChanged: () => void
  onClose: () => void
}) {
  const { message } = App.useApp()
  const [record, setRecord] = useState<StocktakeRecord | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [counted, setCounted] = useState<Record<string, number>>({})

  const fetchDetail = useCallback(async () => {
    setLoading(true)
    try {
      const detail = await getStocktake(props.stocktakeId)
      setRecord(detail)
      // 以服务端数据初始化实盘输入（key={record.id} 重建时自动重置）
      const next: Record<string, number> = {}
      for (const item of detail.items) {
        if (item.counted_quantity != null) next[item.id] = item.counted_quantity
      }
      setCounted(next)
    } catch {
      message.error('获取盘点单详情失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.stocktakeId])

  useEffect(() => {
    const t = setTimeout(fetchDetail, 0)
    return () => clearTimeout(t)
  }, [fetchDetail])

  const isDraft = record?.status === 'draft'

  const handleSave = async () => {
    if (!record) return
    const items: StocktakeItemUpdateInput[] = record.items.map(item => ({
      item_id: item.id,
      counted_quantity: counted[item.id] ?? null,
      remark: item.remark ?? null,
    }))
    setSaving(true)
    try {
      await updateStocktake(record.id, { items })
      message.success('实盘结果已保存')
      await fetchDetail()
      props.onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleConfirm = async () => {
    if (!record) return
    setSaving(true)
    try {
      await confirmStocktake(record.id)
      message.success('盘点单已确认，库存已按实盘调整')
      await fetchDetail()
      props.onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '确认失败')
    } finally {
      setSaving(false)
    }
  }

  const itemColumns: TableColumnsType<StocktakeItemRecord> = [
    { title: '物料编码', dataIndex: 'material_code', width: 130 },
    { title: '物料名称', dataIndex: 'material_name', width: 150 },
    { title: '批次号', dataIndex: 'batch_no', width: 110, render: v => v || '-' },
    { title: '库位', dataIndex: 'location_name', width: 120 },
    { title: '账面', dataIndex: 'book_quantity', width: 90, align: 'right' },
    {
      title: '实盘',
      dataIndex: 'counted_quantity',
      width: 130,
      render: (_, item) =>
        isDraft ? (
          <InputNumber
            size="small"
            min={0}
            style={{ width: '100%' }}
            value={counted[item.id]}
            onChange={value => setCounted(prev => ({ ...prev, [item.id]: value ?? 0 }))}
          />
        ) : (
          item.counted_quantity ?? '-'
        ),
    },
    {
      title: '盘差',
      key: 'difference',
      width: 90,
      align: 'right',
      render: (_, item) => {
        if (item.counted_quantity == null) return '-'
        const diff = item.counted_quantity - item.book_quantity
        if (diff === 0) return <Tag>0</Tag>
        return <Tag color={diff > 0 ? 'green' : 'red'}>{diff > 0 ? `+${diff}` : diff}</Tag>
      },
    },
  ]

  return (
    <Drawer
      title={record ? `盘点单 ${record.stocktake_no}` : '盘点单'}
      open
      width={860}
      onClose={props.onClose}
      destroyOnHidden
      extra={
        record && isDraft ? (
          <Space>
            <Button onClick={handleSave} loading={saving}>
              保存实盘
            </Button>
            <Popconfirm title="确认后库存将按实盘调整，确定？" onConfirm={handleConfirm}>
              <Button type="primary" loading={saving}>
                确认盘点
              </Button>
            </Popconfirm>
          </Space>
        ) : undefined
      }
    >
      {record && (
        <div style={{ marginBottom: 12 }}>
          <Space wrap>
            {record.status === 'confirmed' ? <Tag color="green">已确认</Tag> : <Tag color="gold">草稿</Tag>}
            <span>
              范围：
              {record.scope_location_name
                ? `${record.scope_location_code ?? ''} ${record.scope_location_name}`
                : '全库'}
            </span>
            {record.remark && <span>备注：{record.remark}</span>}
          </Space>
        </div>
      )}
      <Table<StocktakeItemRecord>
        rowKey="id"
        size="small"
        columns={itemColumns}
        dataSource={record?.items ?? []}
        loading={loading}
        pagination={false}
        scroll={{ x: 780, y: 480 }}
      />
    </Drawer>
  )
}

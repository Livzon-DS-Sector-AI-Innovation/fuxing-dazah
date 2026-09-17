'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Table,
} from 'antd'
import { ArrowDownLeft, ArrowUpRight, Plus, RotateCw, Search } from 'lucide-react'
import dayjs, { Dayjs } from 'dayjs'
import type { TableColumnsType } from 'antd'
import {
  MOVEMENT_DIRECTION_LABEL,
  MOVEMENT_SOURCE_LABEL,
  MovementCreate,
  MovementDirection,
  MovementFilter,
  MovementRecord,
  MovementSourceType,
} from '@/types/warehouse'
import {
  fetchLocationsClient,
  fetchMaterialsClient,
  fetchMovementsClient,
} from '@/lib/api/warehouse'
import { createMovement, deleteMovement } from '@/actions/warehouse'
import { PageHeader } from './PageHeader'
import { StatusTag } from './ui/StatusTag'
import type { Tone } from './ui/tokens'

const DIRECTION_TONE: Record<MovementDirection, Tone> = {
  inbound: 'ok',
  outbound: 'danger',
  adjust: 'warn',
}

const DIRECTION_ICON: Record<MovementDirection, React.ReactNode> = {
  inbound: <ArrowDownLeft size={12} />,
  outbound: <ArrowUpRight size={12} />,
  adjust: <RotateCw size={12} />,
}

/** 相对时间：刚刚/x 分钟前/x 小时前/N 天前，超出 7 天回落绝对日期 */
function relativeTime(value: string): string {
  const diffMs = Date.now() - dayjs(value).valueOf()
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days <= 7) return `${days} 天前`
  return dayjs(value).format('YYYY-MM-DD')
}

/** 入库/出库可选的业务来源（盘点调整只能由盘点单生成）。 */
const SOURCE_OPTIONS_BY_DIRECTION: Record<'inbound' | 'outbound', MovementSourceType[]> = {
  inbound: ['purchase', 'production', 'return', 'other'],
  outbound: ['sale', 'production', 'return', 'other'],
}

interface MaterialOption {
  value: string
  label: string
  unit: string
}

export function MovementTable() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [direction, setDirection] = useState<MovementDirection | undefined>(undefined)

  const [modalOpen, setModalOpen] = useState(false)
  const [materialOptions, setMaterialOptions] = useState<MaterialOption[]>([])
  const [materialSearching, setMaterialSearching] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [form] = Form.useForm()

  const { data: res, isLoading, isError } = useQuery({
    queryKey: ['warehouse', 'movements', { page, pageSize, keyword, direction }],
    queryFn: () => {
      const params: MovementFilter = { page, page_size: pageSize }
      if (keyword) params.keyword = keyword
      if (direction) params.direction = direction
      return fetchMovementsClient(params)
    },
    placeholderData: keepPreviousData,
  })

  const { data: locations } = useQuery({
    queryKey: ['warehouse', 'locations'],
    queryFn: () => fetchLocationsClient(),
  })

  useEffect(() => {
    if (isError) message.error('获取出入库记录失败')
  }, [isError, message])

  const invalidateLists = () => {
    queryClient.invalidateQueries({ queryKey: ['warehouse', 'movements'] })
    queryClient.invalidateQueries({ queryKey: ['warehouse', 'stocks'] })
  }

  const createMutation = useMutation({
    mutationFn: (payload: MovementCreate) => createMovement(payload),
    onSuccess: () => {
      setModalOpen(false)
      invalidateLists()
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteMovement(id),
    onSuccess: () => {
      message.success('记录已撤销，库存已冲销')
      invalidateLists()
    },
    onError: (e: unknown) => {
      message.error(e instanceof Error ? e.message : '撤销失败')
    },
  })

  const searchMaterials = async (search: string) => {
    setMaterialSearching(true)
    try {
      const result = await fetchMaterialsClient({
        page: 1,
        page_size: 50,
        keyword: search || undefined,
      })
      setMaterialOptions(
        result.items.map(m => ({ value: m.id, label: `${m.code} ${m.name}`, unit: m.unit })),
      )
    } catch {
      // 搜索失败保持原选项
    } finally {
      setMaterialSearching(false)
    }
  }

  const handleMaterialSearch = (search: string) => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => searchMaterials(search), 300)
  }

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({ direction: 'inbound', source_type: 'purchase', batch_no: '' })
    searchMaterials('')
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    const material = materialOptions.find(m => m.value === values.material_id)
      const payload: MovementCreate = {
        direction: values.direction,
        source_type: values.source_type,
        material_id: values.material_id,
        batch_no: values.batch_no ?? '',
        quantity: values.quantity,
        location_id: values.location_id,
        occurred_at: values.occurred_at ? (values.occurred_at as Dayjs).toISOString() : null,
        expiry_date:
          values.direction === 'inbound' && values.expiry_date
            ? (values.expiry_date as Dayjs).format('YYYY-MM-DD')
            : null,
        remark: values.remark || null,
      }
    createMutation.mutate(payload, {
      onSuccess: () => {
        message.success(
          `${MOVEMENT_DIRECTION_LABEL[payload.direction as MovementDirection]}单已登记${material ? `：${material.label}` : ''}`,
        )
        setModalOpen(false)
      },
    })
  }

  const columns: TableColumnsType<MovementRecord> = [
    { title: '单据编号', dataIndex: 'movement_no', width: 160 },
    {
      title: '方向',
      dataIndex: 'direction',
      width: 96,
      render: (value: MovementDirection) => (
        <StatusTag tone={DIRECTION_TONE[value]} label={MOVEMENT_DIRECTION_LABEL[value] ?? value} icon={DIRECTION_ICON[value]} />
      ),
    },
    {
      title: '业务来源',
      dataIndex: 'source_type',
      width: 110,
      render: (value: MovementSourceType) => MOVEMENT_SOURCE_LABEL[value] ?? value,
    },
    {
      title: '物料 / 批次',
      dataIndex: 'material_name',
      width: 220,
      render: (_, record) => (
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
            {record.material_name}
          </div>
          <div className="truncate text-[12px] leading-4 text-[var(--color-steel)]">
            {record.material_code}
            {record.batch_no ? ` · ${record.batch_no}` : ''}
          </div>
        </div>
      ),
    },
    {
      title: '数量',
      width: 100,
      align: 'right',
      render: (_, record) => (
        <span className="font-medium tabular-nums">
          {record.direction === 'inbound' ? '+' : record.direction === 'outbound' ? '-' : ''}
          {record.quantity} {record.unit}
        </span>
      ),
    },
    { title: '库位', dataIndex: 'location_name', width: 120 },
    {
      title: '发生时间',
      dataIndex: 'occurred_at',
      width: 160,
      render: (v: string) => (
        <div>
          <div className="text-[13px] text-[var(--color-charcoal)]">{relativeTime(v)}</div>
          <div className="text-[12px] leading-4 text-[var(--color-steel)]">{dayjs(v).format('MM-DD HH:mm')}</div>
        </div>
      ),
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v ?? '-' },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_, record) =>
        record.direction === 'adjust' ? (
          <span style={{ color: 'var(--color-stone)' }}>盘点生成</span>
        ) : (
          <Popconfirm
            title="撤销该记录会反向冲销库存，确定？"
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button size="small" type="link" danger>
              撤销
            </Button>
          </Popconfirm>
        ),
    },
  ]

  const watchedDirection = Form.useWatch('direction', form)

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '出入库记录']}
        title="出入库记录"
        description="登记入库/出库，撤销记录自动冲销库存"
        actions={
          <Button type="primary" icon={<Plus size={14} />} onClick={openCreate}>
            登记出入库
          </Button>
        }
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Segmented
          value={direction ?? 'all'}
          onChange={value => {
            setDirection(value === 'all' ? undefined : (value as MovementDirection))
            setPage(1)
          }}
          options={[
            { value: 'all', label: '全部' },
            ...Object.entries(MOVEMENT_DIRECTION_LABEL).map(([value, label]) => ({ value, label })),
          ]}
        />
        <Input
          allowClear
          prefix={<Search size={14} />}
          placeholder="搜索单号/物料/批次"
          style={{ width: 220 }}
          onChange={e => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
      </div>

      <Table<MovementRecord>
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
        scroll={{ x: 1250 }}
      />

      {modalOpen && (
        <Modal
          title="登记出入库"
          open
          confirmLoading={createMutation.isPending}
          onOk={handleSave}
          onCancel={() => setModalOpen(false)}
          destroyOnHidden
          width={520}
        >
          <Form form={form} layout="vertical" style={{ paddingTop: 8 }}>
            <Space.Compact block>
              <Form.Item
                name="direction"
                label="方向"
                rules={[{ required: true }]}
                style={{ width: 160 }}
              >
                <Select
                  onChange={value => {
                    // 方向切换时重置业务来源，避免出现不合法组合
                    const allowed = SOURCE_OPTIONS_BY_DIRECTION[value as 'inbound' | 'outbound']
                    const current = form.getFieldValue('source_type') as MovementSourceType
                    if (!allowed.includes(current)) form.setFieldValue('source_type', allowed[0])
                  }}
                  options={[
                    { value: 'inbound', label: '入库' },
                    { value: 'outbound', label: '出库' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="source_type" label="业务来源" rules={[{ required: true }]} style={{ flex: 1 }}>
                <Select
                  options={(SOURCE_OPTIONS_BY_DIRECTION[(watchedDirection as 'inbound' | 'outbound') ?? 'inbound'] ?? []).map(
                    value => ({ value, label: MOVEMENT_SOURCE_LABEL[value] })
                  )}
                />
              </Form.Item>
            </Space.Compact>
            <Form.Item name="material_id" label="物料" rules={[{ required: true, message: '请选择物料' }]}>
              <Select
                showSearch
                filterOption={false}
                onSearch={handleMaterialSearch}
                loading={materialSearching}
                placeholder="输入编码或名称搜索"
                options={materialOptions}
              />
            </Form.Item>
            <Space.Compact block>
              <Form.Item name="batch_no" label="批次号（可空）" style={{ width: 200 }}>
                <Input placeholder="如 B20260901" />
              </Form.Item>
              <Form.Item
                name="quantity"
                label="数量"
                rules={[{ required: true, message: '请输入数量' }]}
                style={{ flex: 1 }}
              >
                <InputNumber min={0.0001} style={{ width: '100%' }} />
              </Form.Item>
            </Space.Compact>
            <Form.Item name="location_id" label="库位" rules={[{ required: true, message: '请选择库位' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                options={(locations ?? []).map(loc => ({
                  value: loc.id,
                  label: `${loc.code} ${loc.name}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="occurred_at" label="发生时间（默认当前）">
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            {(watchedDirection ?? 'inbound') === 'inbound' && (
              <Form.Item name="expiry_date" label="批次效期（入库）">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            )}
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  )
}

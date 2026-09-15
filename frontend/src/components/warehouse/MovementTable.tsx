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
  Select,
  Space,
  Table,
  Tag,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
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

const DIRECTION_COLOR: Record<MovementDirection, string> = {
  inbound: 'green',
  outbound: 'red',
  adjust: 'orange',
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
    { title: '单据编号', dataIndex: 'movement_no', width: 170 },
    {
      title: '方向',
      dataIndex: 'direction',
      width: 90,
      render: (value: MovementDirection) => (
        <Tag color={DIRECTION_COLOR[value]}>{MOVEMENT_DIRECTION_LABEL[value] ?? value}</Tag>
      ),
    },
    {
      title: '业务来源',
      dataIndex: 'source_type',
      width: 120,
      render: (value: MovementSourceType) => MOVEMENT_SOURCE_LABEL[value] ?? value,
    },
    { title: '物料编码', dataIndex: 'material_code', width: 130 },
    { title: '物料名称', dataIndex: 'material_name', width: 160 },
    { title: '批次号', dataIndex: 'batch_no', width: 120, render: v => v || '-' },
    {
      title: '数量',
      width: 110,
      align: 'right',
      render: (_, record) => `${record.quantity} ${record.unit}`,
    },
    { title: '库位', dataIndex: 'location_name', width: 130 },
    {
      title: '发生时间',
      dataIndex: 'occurred_at',
      width: 150,
      render: v => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v ?? '-' },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_, record) =>
        record.direction === 'adjust' ? (
          <span style={{ color: 'var(--ant-color-text-tertiary, #999)' }}>盘点生成</span>
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
      <Space style={{ marginBottom: 12 }} wrap>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索单号/物料/批次"
          style={{ width: 220 }}
          onChange={e => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
        <Select
          allowClear
          placeholder="全部方向"
          style={{ width: 130 }}
          value={direction}
          onChange={value => {
            setDirection(value)
            setPage(1)
          }}
          options={Object.entries(MOVEMENT_DIRECTION_LABEL).map(([value, label]) => ({
            value,
            label,
          }))}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          登记出入库
        </Button>
      </Space>

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
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  )
}

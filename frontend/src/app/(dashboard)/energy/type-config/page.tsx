'use client'

import { useEffect, useState, useCallback } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, Switch, Popconfirm, App, Space } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { EnergyTypeConfig, CreateTypeConfigInput, UpdateTypeConfigInput, PaginatedResponse } from '@/types/energy'
import { getTypeConfigs, createTypeConfig, updateTypeConfig, deleteTypeConfig } from '@/actions/energy'

export default function TypeConfigPage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<EnergyTypeConfig[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<EnergyTypeConfig | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const result = await getTypeConfigs()
      const paginated = result as unknown as PaginatedResponse<EnergyTypeConfig>
      setData(paginated.items || [])
      setTotal(paginated.total || 0)
    } catch (e: any) {
      message.error('获取能源配置列表失败: ' + (e?.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  function openCreate() {
    setEditingRecord(null)
    setModalOpen(true)
  }

  function openEdit(record: EnergyTypeConfig) {
    setEditingRecord(record)
    setModalOpen(true)
  }

  async function handleDelete(record: EnergyTypeConfig) {
    try {
      await deleteTypeConfig(record.id)
      message.success('删除成功')
      fetchData()
    } catch {
      message.error('删除失败')
    }
  }

  function handleModalClose() {
    setModalOpen(false)
  }

  function handleSaved() {
    setModalOpen(false)
    fetchData()
  }

  const columns = [
    { title: '编码', dataIndex: 'type_code', key: 'type_code', width: 140 },
    { title: '名称', dataIndex: 'display_name', key: 'display_name', width: 140 },
    { title: '单位', dataIndex: 'unit', key: 'unit', width: 80 },
    {
      title: '颜色', dataIndex: 'color', key: 'color', width: 70,
      render: (v: string | null) => v
        ? <span style={{ display: 'inline-block', width: 16, height: 16, borderRadius: 4, background: v, border: '1px solid #e5e7eb' }} />
        : <span style={{ color: '#d4d4d8' }}>—</span>,
    },
    { title: '排序', dataIndex: 'sort_order', key: 'sort_order', width: 60 },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 70,
      render: (v: boolean) => v ? <span style={{ color: '#16a34a' }}>启用</span> : <span style={{ color: '#a4a097' }}>禁用</span>,
    },
    { title: '备注', dataIndex: 'remark', key: 'remark', ellipsis: true },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, record: EnergyTypeConfig) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEdit(record)}
          />
          <Popconfirm
            title="确定删除该能源配置？"
            onConfirm={() => handleDelete(record)}
            okText="删除"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const filledInputStyle = { background: '#f6f5f4', border: 'none', borderRadius: 8, height: 36 }

  return (
    <div style={{ padding: '28px 32px', maxWidth: 1280, minHeight: '100%', background: '#fafaf9' }}>
      {/* 标题 */}
      <h1 style={{ fontSize: 28, fontWeight: 500, color: '#1a1a1a', margin: 0, letterSpacing: '-0.3px' }}>
        能源配置
      </h1>
      <p style={{ fontSize: 13, color: '#a4a097', margin: '4px 0 0', lineHeight: 1.5 }}>
        管理能源类型配置，配置的能源将同步到能源总览和可视化视图
      </p>

      {/* 渐变分割线 */}
      <div style={{ height: 1, marginTop: 18, marginBottom: 20, background: 'linear-gradient(to right, #5645d4 0%, #e6e0f5 40%, transparent 100%)' }} />

      {/* 筛选栏 */}
      <div style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        background: '#ffffff', borderRadius: 12, padding: '12px 18px',
        boxShadow: '0 1px 3px rgba(10, 10, 10, 0.04)', border: '1px solid #ede9e4',
        marginBottom: 20,
      }}>
        <div style={{ flex: 1 }} />
        <Button
          icon={<PlusOutlined />}
          onClick={openCreate}
          style={{ color: '#5645d4', borderColor: '#5645d4', borderRadius: 8, fontWeight: 500, fontSize: 14, height: 36, padding: '0 16px' }}
        >
          新增能源
        </Button>
      </div>

      {/* 表格 */}
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          onChange: (p, ps) => { setPage(p); setPageSize(ps) },
        }}
        style={{ background: '#fff', borderRadius: 12 }}
      />

      {/* 新增/编辑模态框 */}
      {modalOpen && (
        <TypeConfigModal
          record={editingRecord}
          open={modalOpen}
          onClose={handleModalClose}
          onSaved={handleSaved}
          existingColors={data.map(d => d.color).filter(Boolean) as string[]}
        />
      )}
    </div>
  )
}

/** 独立的表单模态框，避免 useForm 未连接警告 */
function TypeConfigModal({
  record,
  open,
  onClose,
  onSaved,
  existingColors,
}: {
  record: EnergyTypeConfig | null
  open: boolean
  onClose: () => void
  onSaved: () => void
  existingColors: string[]
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const isEdit = !!record

  // 预定义的饱和色板（36 色，视觉区分度好）
  const PALETTE = [
    '#0075de', '#1aae39', '#dd5b00', '#722ed1', '#2f54eb', '#fa541c', '#faad14',
    '#13c2c2', '#eb2f96', '#52c41a', '#1890ff', '#f5222d', '#a0d911', '#fadb14',
    '#597ef7', '#9254de', '#36cfc9', '#ff7a45', '#73d13d', '#ff85c0',
    '#237804', '#006d75', '#9c1068', '#d4380d', '#1d39c4', '#531dab',
    '#5b8c00', '#08979c', '#c41d7f', '#d46b08', '#7cb305', '#0958d9',
    '#3f6600', '#00474f', '#780650', '#ad2102',
  ]

  function randomColor(avoid: string[]): string {
    const avoidSet = new Set(avoid.map(c => c.toLowerCase()))
    const available = PALETTE.filter(c => !avoidSet.has(c.toLowerCase()))
    if (available.length === 0) {
      // 所有色板都用完了，随机生成
      const h = Math.floor(Math.random() * 360)
      return `hsl(${h}, 65%, 50%)`
    }
    return available[Math.floor(Math.random() * available.length)]
  }

  useEffect(() => {
    if (open) {
      if (record) {
        form.setFieldsValue({
          type_code: record.type_code,
          display_name: record.display_name,
          unit: record.unit,
          sort_order: record.sort_order,
          is_enabled: record.is_enabled,
          color: record.color || '',
          remark: record.remark || '',
        })
      } else {
        form.resetFields()
        form.setFieldsValue({
          sort_order: 0,
          is_enabled: true,
          color: randomColor(existingColors),
        })
      }
    }
  }, [open, record, form])

  async function handleSubmit() {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (isEdit) {
        const updateData: UpdateTypeConfigInput = {
          display_name: values.display_name,
          unit: values.unit,
          sort_order: values.sort_order,
          is_enabled: values.is_enabled,
          color: values.color || null,
          remark: values.remark || null,
        }
        await updateTypeConfig(record!.id, updateData)
        message.success('修改成功')
      } else {
        const createData: CreateTypeConfigInput = {
          type_code: values.type_code,
          display_name: values.display_name,
          unit: values.unit,
          sort_order: values.sort_order ?? 0,
          is_enabled: values.is_enabled ?? true,
          color: values.color || null,
          remark: values.remark || null,
        }
        await createTypeConfig(createData)
        message.success('新增成功')
      }
      onSaved()
    } catch (e: any) {
      if (e?.errorFields) return // validation error, ignore
      message.error('操作失败: ' + (e?.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  const filledInputStyle = { background: '#f6f5f4', border: 'none', borderRadius: 8, height: 36 }

  return (
    <Modal
      title={isEdit ? '编辑能源配置' : '新增能源配置'}
      open={open}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="type_code"
          label="编码"
          rules={[{ required: true, message: '请输入唯一编码' }, { max: 50 }]}
          extra="唯一标识，如 electricity、water，创建后不可修改"
        >
          <Input placeholder="electricity" disabled={isEdit} style={filledInputStyle} />
        </Form.Item>
        <Form.Item
          name="display_name"
          label="名称"
          rules={[{ required: true, message: '请输入展示名称' }, { max: 100 }]}
        >
          <Input placeholder="电耗数据" style={filledInputStyle} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="unit" label="单位" rules={[{ required: true }, { max: 20 }]} style={{ flex: 1 }}>
            <Input placeholder="kWh" style={filledInputStyle} />
          </Form.Item>
          <Form.Item name="color" label="颜色" rules={[{ max: 20 }]} style={{ flex: 1 }}>
            <Input placeholder="#0075de" style={filledInputStyle} />
          </Form.Item>
          <Form.Item name="sort_order" label="排序" style={{ flex: 1 }}>
            <InputNumber min={0} style={{ width: '100%', ...filledInputStyle }} />
          </Form.Item>
        </div>
        <Form.Item name="is_enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="remark" label="备注" rules={[{ max: 500 }]}>
          <Input.TextArea rows={2} placeholder="备注信息..." style={{ background: '#f6f5f4', border: 'none', borderRadius: 8 }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

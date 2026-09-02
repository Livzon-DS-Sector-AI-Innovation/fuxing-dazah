'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Typography, Table, Button, Modal, Form, Input, Select,
  InputNumber, Space, App, Popconfirm, Tag, Upload,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined, UploadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

const { Title, Paragraph } = Typography

interface ProductStandard {
  id: string
  product_name: string
  item_name: string
  form_id: string | null
  sop_no: string | null
  standard_type: string | null
  operator: string
  limit_value: number | null
  oot_haf: number | null
  oot_haa: number | null
  created_at: string | null
  updated_at: string | null
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export default function StandardsPage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<ProductStandard[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form] = Form.useForm()
  const [filterProduct, setFilterProduct] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = filterProduct ? `?product_name=${encodeURIComponent(filterProduct)}` : ''
      const res = await fetch(`${API_BASE}/api/v1/quality/standards${params}`)
      if (!res.ok) throw new Error('加载失败')
      const json = await res.json()
      setData(json.data || [])
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }, [filterProduct, message])

  useEffect(() => { load() }, [load])

  const handleSave = async () => {
    const values = await form.validateFields()
    try {
      const url = editingId
        ? `${API_BASE}/api/v1/quality/standards/${editingId}`
        : `${API_BASE}/api/v1/quality/standards`
      const res = await fetch(url, {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      })
      if (!res.ok) throw new Error('保存失败')
      message.success(editingId ? '已更新' : '已创建')
      setModalOpen(false)
      setEditingId(null)
      form.resetFields()
      load()
    } catch (err: any) { message.error(err.message || '保存失败') }
  }

  const handleDelete = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/quality/standards/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('删除失败')
      message.success('已删除')
      load()
    } catch { message.error('删除失败') }
  }

  const handleUpload = async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API_BASE}/api/v1/quality/standards/upload`, {
        method: 'POST', body: formData,
      })
      if (!res.ok) throw new Error('导入失败')
      const json = await res.json()
      message.success(`导入完成：新增 ${json.data.created} 条，跳过 ${json.data.skipped} 条`)
      if (json.data.errors?.length) {
        json.data.errors.slice(0, 5).forEach((e: string) => message.warning(e))
      }
      load()
    } catch { message.error('导入失败，请检查文件格式') }
    return false
  }

  const openEdit = (record: ProductStandard) => {
    setEditingId(record.id)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const columns: ColumnsType<ProductStandard> = [
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', width: 150 },
    { title: '代号', dataIndex: 'form_id', key: 'form_id', width: 80,
      render: (v: string | null) => v || '-' },
    { title: '指标名称', dataIndex: 'item_name', key: 'item_name', width: 130 },
    { title: 'SOP号', dataIndex: 'sop_no', key: 'sop_no', width: 90,
      render: (v: string | null) => v || '-' },
    { title: '标准类型', dataIndex: 'standard_type', key: 'standard_type', width: 80,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: '运算符', dataIndex: 'operator', key: 'operator', width: 70 },
    { title: '限度值', dataIndex: 'limit_value', key: 'limit_value', width: 100,
      render: (v: number | null) => v != null ? v : '-' },
    { title: 'OOT(HAF)', dataIndex: 'oot_haf', key: 'oot_haf', width: 100,
      render: (v: number | null) => v != null ? v : '-' },
    { title: 'OOT(HAA)', dataIndex: 'oot_haa', key: 'oot_haa', width: 100,
      render: (v: number | null) => v != null ? v : '-' },
    { title: '操作', key: 'actions', width: 100,
      render: (_: any, r: ProductStandard) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Title level={3}><SettingOutlined /> 产品标准配置</Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        管理各产品的检验标准配置（限度值、OOT 阈值），解析时自动匹配对应标准。
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Input placeholder="筛选产品名称" allowClear value={filterProduct}
          onChange={e => setFilterProduct(e.target.value)}
          onPressEnter={() => load()} style={{ width: 180 }} />
        <Button onClick={load}>筛选</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditingId(null); form.resetFields(); setModalOpen(true)
        }}>
          新增标准
        </Button>
      </Space>

      <Table columns={columns}
        dataSource={data.map(r => ({ ...r, key: r.id }))}
        loading={loading} pagination={false} size="small" />

      <Modal title={editingId ? '编辑标准' : '新增标准'} open={modalOpen}
        onOk={handleSave} onCancel={() => { setModalOpen(false); setEditingId(null) }}
        destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
            <Input placeholder="如 盐酸万古霉素" />
          </Form.Item>
          <Form.Item name="form_id" label="代号/表号">
            <Input placeholder="如 3229（可留空）" />
          </Form.Item>
          <Form.Item name="sop_no" label="SOP号">
            <Input placeholder="项目绑定的 SOP 编号（可留空）" />
          </Form.Item>
          <Form.Item name="item_name" label="指标名称" rules={[{ required: true }]}>
            <Input placeholder="如 万古霉素B、总杂质、RS1" />
          </Form.Item>
          <Form.Item name="standard_type" label="标准类型">
            <Select options={[
              { value: 'USP', label: 'USP' },
              { value: 'EP', label: 'EP' },
              { value: 'CP', label: 'CP' },
            ]} allowClear />
          </Form.Item>
          <Form.Item name="operator" label="运算符" initialValue="≤">
            <Select options={[
              { value: '≤', label: '≤ (不大于)' },
              { value: '≥', label: '≥ (不小于)' },
              { value: '<', label: '< (小于)' },
              { value: '>', label: '> (大于)' },
            ]} />
          </Form.Item>
          <Form.Item name="limit_value" label="限度值">
            <InputNumber style={{ width: '100%' }} placeholder="如 0.95" step={0.01} />
          </Form.Item>
          <Form.Item name="oot_haf" label="OOT 阈值 (HAF)">
            <InputNumber style={{ width: '100%' }} placeholder="HAF 产品线 OOT 阈值" step={0.01} />
          </Form.Item>
          <Form.Item name="oot_haa" label="OOT 阈值 (HAA)">
            <InputNumber style={{ width: '100%' }} placeholder="HAA 产品线 OOT 阈值" step={0.01} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

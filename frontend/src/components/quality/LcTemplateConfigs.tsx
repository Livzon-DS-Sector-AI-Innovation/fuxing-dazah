'use client'

import { useCallback, useEffect, useState } from 'react'
import { usePermission } from '@/hooks/usePermission'
import { Card, Table, Button, Space, App, Modal, Form, Input, Popconfirm, Tag, Typography } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import type { LcTemplateConfig } from '@/types/quality'
import {
  fetchLcTemplateConfigs,
  createLcTemplateConfig,
  updateLcTemplateConfig,
  deleteLcTemplateConfig,
} from '@/actions/quality'

const { Text } = Typography

/** 液相计算表模板配置维护：表号（EX-xx-xxxx-vvv）→ 取值配置 JSON。 */
export default function LcTemplateConfigs() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:standard:manage')
  const [items, setItems] = useState<LcTemplateConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<LcTemplateConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchLcTemplateConfigs()
      setItems(res.data || [])
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ config: '{}' })
    setEditOpen(true)
  }

  const openEdit = (cfg: LcTemplateConfig) => {
    setEditing(cfg)
    form.setFieldsValue({
      table_no: cfg.table_no,
      product_name: cfg.product_name,
      sop_no: cfg.sop_no ?? '',
      description: cfg.description ?? '',
      config: JSON.stringify(cfg.config, null, 2),
    })
    setEditOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    let config: Record<string, unknown>
    try {
      config = JSON.parse(values.config || '{}')
    } catch {
      message.error('配置 JSON 格式错误')
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await updateLcTemplateConfig(editing.id, {
          product_name: values.product_name,
          sop_no: values.sop_no || null,
          description: values.description || null,
          config,
        })
        message.success('配置已更新')
      } else {
        await createLcTemplateConfig({
          table_no: values.table_no.trim(),
          product_name: values.product_name,
          sop_no: values.sop_no || undefined,
          description: values.description || undefined,
          config,
        })
        message.success('配置已创建')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteLcTemplateConfig(id)
      message.success('已删除')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  const columns = [
    { title: '表号', dataIndex: 'table_no', key: 'table_no', width: 150 },
    { title: '产品', dataIndex: 'product_name', key: 'product_name', width: 150 },
    {
      title: 'SOP', dataIndex: 'sop_no', key: 'sop_no', width: 150,
      render: (v: string | null) => v ? <Tag color="green">{v}</Tag> : '-',
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: LcTemplateConfig) => (
        <Space size={4}>
          {canManage && (
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          )}
          {canManage && (
          <Popconfirm
            title={`确认删除配置 ${r.table_no}？`}
            description="删除后该表号的计算表将回落到旧解析器"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(r.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Card
      size="small"
      title="液相计算表模板配置（表号 → 取值位置）"
      extra={canManage ? <Button size="small" icon={<PlusOutlined />} onClick={openCreate}>新增配置</Button> : null}
    >
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        表号来自计算表标题（如 EX-HA-5246-001）；新增产品线时在此登记表号与取值区块。
      </Text>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        size="small"
        scroll={{ x: 720 }}
        pagination={false}
      />

      <Modal
        title={editing ? `编辑配置 ${editing.table_no}` : '新增液相模板配置'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="table_no"
            label="表号（EX-xx-xxxx-vvv）"
            rules={[{ required: true, message: '请输入表号' }]}
          >
            <Input placeholder="EX-HA-5246-001" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请输入产品名称' }]}>
            <Input placeholder="盐酸万古霉素" />
          </Form.Item>
          <Form.Item name="sop_no" label="对应 SOP 号（可选）">
            <Input placeholder="SOP.02.3205.010" />
          </Form.Item>
          <Form.Item name="description" label="描述（可选）">
            <Input placeholder="万古霉素冻干粉-赞比亚" />
          </Form.Item>
          <Form.Item name="config" label="取值配置 JSON" rules={[{ required: true, message: '请输入配置 JSON' }]}>
            <Input.TextArea rows={10} placeholder={'{\n  "batch_label": "批号",\n  "blocks": [...]\n}'} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

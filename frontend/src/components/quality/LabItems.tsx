'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Popconfirm, Typography } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import { LAB_ITEM_TYPE_META } from '@/types/quality'
import type { LabItem, LabItemType } from '@/types/quality'
import { fetchLabItems, createLabItem, updateLabItem, deleteLabItem } from '@/actions/quality'

export default function LabItems() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [data, setData] = useState<LabItem[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [qDraft, setQDraft] = useState('')
  const [qFilter, setQFilter] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<LabItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchLabItems(typeFilter, qFilter)
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取台账失败')
    } finally {
      setLoading(false)
    }
  }, [message, typeFilter, qFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (item: LabItem) => {
    setEditing(item)
    form.setFieldsValue({
      item_type: item.item_type,
      name: item.name,
      batch_no: item.batch_no ?? undefined,
      spec: item.spec ?? undefined,
      opened_at: item.opened_at ? dayjs(item.opened_at) : undefined,
      expiry_date: item.expiry_date ? dayjs(item.expiry_date) : undefined,
      remark: item.remark ?? undefined,
    })
    setEditOpen(true)
  }

  const onSave = async () => {
    const values = await form.validateFields()
    const payload = {
      ...values,
      opened_at: values.opened_at ? values.opened_at.format('YYYY-MM-DD') : undefined,
      expiry_date: values.expiry_date ? values.expiry_date.format('YYYY-MM-DD') : undefined,
    }
    setSaving(true)
    try {
      if (editing) {
        await updateLabItem(editing.id, payload)
        message.success('已更新')
      } else {
        await createLabItem(payload)
        message.success('已新增')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onDelete = async (item: LabItem) => {
    try {
      await deleteLabItem(item.id)
      message.success('已删除')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          placeholder="类型筛选" allowClear style={{ width: 140 }}
          value={typeFilter}
          onChange={setTypeFilter}
          options={Object.entries(LAB_ITEM_TYPE_META).map(([v, label]) => ({ value: v, label }))}
        />
        <Input.Search
          placeholder="名称搜索" allowClear style={{ width: 220 }}
          prefix={<SearchOutlined />}
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
          onSearch={(v) => setQFilter(v || undefined)}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增条目</Button>
        )}
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        scroll={{ x: 900 }}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: '类型', dataIndex: 'item_type', width: 90,
            render: (v: LabItemType) => <Tag>{LAB_ITEM_TYPE_META[v] ?? v}</Tag>,
          },
          { title: '名称', dataIndex: 'name', width: 180 },
          { title: '批号', dataIndex: 'batch_no', width: 120, render: (v: string | null) => v || '-' },
          { title: '规格', dataIndex: 'spec', width: 100, render: (v: string | null) => v || '-' },
          { title: '开封日期', dataIndex: 'opened_at', width: 110, render: (v: string | null) => v || '-' },
          {
            title: '效期/下次校验', dataIndex: 'expiry_date', width: 150,
            render: (v: string | null) => {
              if (!v) return '-'
              const days = dayjs(v).diff(dayjs(), 'day')
              if (days < 0) return <><Typography.Text>{v}</Typography.Text> <Tag color="red">已过期</Tag></>
              if (days <= 30) return <><Typography.Text>{v}</Typography.Text> <Tag color="orange">临期 {days} 天</Tag></>
              return v
            },
          },
          { title: '备注', dataIndex: 'remark', ellipsis: true, render: (v: string | null) => v || '-' },
          {
            title: '操作', key: 'actions', width: 120,
            render: (_: unknown, item: LabItem) => (
              canManage ? (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => openEdit(item)}>编辑</Button>
                  <Popconfirm title="确认删除该条目？" onConfirm={() => onDelete(item)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : '-'
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑台账条目' : '新增台账条目'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        confirmLoading={saving}
        okText="保存"
        width={460}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="item_type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
            <Select options={Object.entries(LAB_ITEM_TYPE_META).map(([v, label]) => ({ value: v, label }))} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 甲醇 / 电子天平" />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="batch_no" label="批号（试剂类）" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="spec" label="规格" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="opened_at" label="开封日期" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="expiry_date" label="效期/下次校验日" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

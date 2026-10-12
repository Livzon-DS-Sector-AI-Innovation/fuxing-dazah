'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Input, Space, Button, App, Drawer, Modal, Form, InputNumber, Select, Popconfirm, Typography } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { MaterialDictItem } from '@/types/quality'
import { fetchMaterialDict, createMaterialDict, updateMaterialDict, deleteMaterialDict } from '@/actions/quality'

const CATEGORY_META: Record<string, string> = {
  原料: 'blue', 辅料: 'green', 包材: 'purple', 溶剂: 'cyan',
}

export default function MaterialDictDrawer({ open, onClose, onChanged }: {
  open: boolean
  onClose: () => void
  onChanged?: () => void
}) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<MaterialDictItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<MaterialDictItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async (p: number, q?: string) => {
    setLoading(true)
    try {
      const res = await fetchMaterialDict(q, p)
      setData(res.data)
      setTotal(res.meta.total)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载物料字典失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { if (open) { (async () => { await load(page, query) })() } }, [open, page, query, load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (item: MaterialDictItem) => {
    setEditing(item)
    form.setFieldsValue({
      code: item.code,
      name: item.name,
      category: item.category ?? undefined,
      vendor_name: item.vendor_name ?? undefined,
      pack_spec: item.pack_spec ?? undefined,
      min_stock: item.min_stock ?? undefined,
      remark: item.remark ?? undefined,
    })
    setEditOpen(true)
  }

  const onSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        // 物料代码是唯一键，编辑时不允许修改——从提交值中剔除
        const rest = { ...values } as Record<string, unknown>
        delete rest.code
        await updateMaterialDict(editing.id, rest)
        message.success('物料已更新')
      } else {
        await createMaterialDict(values)
        message.success('物料已新增')
      }
      setEditOpen(false)
      load(page, query)
      onChanged?.()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onDelete = async (item: MaterialDictItem) => {
    try {
      await deleteMaterialDict(item.id)
      message.success(`已删除 ${item.code}`)
      load(page, query)
      onChanged?.()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '删除失败')
    }
  }

  return (
    <Drawer title="📖 物料字典" open={open} onClose={onClose} width={820}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="搜索物料代码/名称" allowClear style={{ width: 240 }}
          prefix={<SearchOutlined />}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onSearch={(v) => { setQuery(v || undefined); setPage(1) }}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增物料</Button>
        )}
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={data}
        size="small"
        pagination={{ current: page, pageSize: 50, total, showSizeChanger: false, onChange: (p) => setPage(p) }}
        columns={[
          { title: '物料代码', dataIndex: 'code', width: 130, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
          { title: '物料名称', dataIndex: 'name' },
          {
            title: '类别', dataIndex: 'category', width: 80,
            render: (v: string | null) => v ? <Tag color={CATEGORY_META[v] ?? 'default'}>{v}</Tag> : '-',
          },
          { title: '供应商', dataIndex: 'vendor_name', width: 130, render: (v: string | null) => v || '-' },
          { title: '包装规格', dataIndex: 'pack_spec', width: 100, render: (v: string | null) => v || '-' },
          {
            title: '安全库存', dataIndex: 'min_stock', width: 100,
            render: (v: number | null) => v != null ? `${v} 瓶` : <Typography.Text type="secondary">未设置</Typography.Text>,
          },
          { title: '创建时间', dataIndex: 'created_at', width: 100, render: (v: string) => dayjs(v).format('YYYY-MM-DD') },
          {
            title: '操作', key: 'actions', width: 120,
            render: (_: unknown, item: MaterialDictItem) => (
              canManage ? (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => openEdit(item)}>编辑</Button>
                  <Popconfirm title={`确认删除物料 ${item.code}？`} onConfirm={() => onDelete(item)}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : '-'
            ),
          },
        ]}
      />

      <Modal
        title={editing ? `编辑物料 ${editing.code}` : '新增物料'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        confirmLoading={saving}
        okText="保存"
        width={480}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code" label="物料代码"
            tooltip="用于容器号中段（MC-物料代码-日期-流水），不能含空格/斜杠"
            rules={[{ required: true, message: '请输入物料代码' }]}
          >
            <Input disabled={!!editing} placeholder="如 VAN" />
          </Form.Item>
          <Form.Item name="name" label="物料名称" rules={[{ required: true, message: '请输入物料名称' }]}>
            <Input placeholder="如 盐酸万古霉素原料" />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select allowClear placeholder="原料/辅料/包材/溶剂" options={['原料', '辅料', '包材', '溶剂'].map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="vendor_name" label="默认供应商">
            <Input placeholder="供应商名称" />
          </Form.Item>
          <Form.Item name="pack_spec" label="包装规格">
            <Input placeholder="如 5kg/听" />
          </Form.Item>
          <Form.Item
            name="min_stock" label="安全库存阈值（瓶）"
            tooltip="可用库存（在库+合格）低于该值时进入采购建议清单并每日推送提醒"
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="留空表示不参与采购建议" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  )
}

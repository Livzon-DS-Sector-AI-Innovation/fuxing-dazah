'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, DatePicker, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, PlusOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { RetainedSample } from '@/types/quality'
import {
  fetchRetainedSamples,
  createRetainedSample,
  updateRetainedSample,
  destroyRetainedSample,
  deleteRetainedSample,
  exportRetainedSamples,
} from '@/actions/quality'

const TYPE_META: Record<string, { label: string; color: string }> = {
  product: { label: '成品', color: 'blue' },
  material: { label: '物料', color: 'geekblue' },
}

const today = () => dayjs().startOf('day')

export default function RetainedSamples() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [data, setData] = useState<RetainedSample[]>([])
  const [loading, setLoading] = useState(false)
  const [batchDraft, setBatchDraft] = useState('')
  const [batchFilter, setBatchFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<RetainedSample | null>(null)
  const [saving, setSaving] = useState(false)
  const [destroyOpen, setDestroyOpen] = useState<RetainedSample | null>(null)
  const [destroySaving, setDestroySaving] = useState(false)
  const [form] = Form.useForm()
  const [destroyForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchRetainedSamples({ sourceType: typeFilter, batchNo: batchFilter, status: statusFilter })
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取留样台账失败')
    } finally {
      setLoading(false)
    }
  }, [message, typeFilter, batchFilter, statusFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const dueStats = useMemo(() => {
    const actives = data.filter((r) => r.status === 'active' && r.destroy_due_date)
    const expired = actives.filter((r) => dayjs(r.destroy_due_date).startOf('day').isBefore(today()))
    const soon = actives.filter((r) => {
      const d = dayjs(r.destroy_due_date).startOf('day')
      return !d.isBefore(today()) && d.diff(today(), 'day') <= 30
    })
    return { expired: expired.length, soon: soon.length }
  }, [data])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (item: RetainedSample) => {
    setEditing(item)
    form.setFieldsValue({
      source_type: item.source_type,
      batch_no: item.batch_no,
      sample_name: item.sample_name,
      qty: item.qty ?? undefined,
      location: item.location ?? undefined,
      retained_at: item.retained_at ? dayjs(item.retained_at) : undefined,
      destroy_due_date: item.destroy_due_date ? dayjs(item.destroy_due_date) : undefined,
      remark: item.remark ?? undefined,
    })
    setEditOpen(true)
  }

  const onSave = async () => {
    const values = await form.validateFields()
    const payload = {
      ...values,
      retained_at: values.retained_at ? (values.retained_at as Dayjs).format('YYYY-MM-DD') : undefined,
      destroy_due_date: values.destroy_due_date ? (values.destroy_due_date as Dayjs).format('YYYY-MM-DD') : undefined,
    }
    setSaving(true)
    try {
      if (editing) {
        await updateRetainedSample(editing.id, payload)
        message.success('留样登记已更新')
      } else {
        await createRetainedSample(payload)
        message.success('留样登记已保存')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const openDestroy = (item: RetainedSample) => {
    destroyForm.resetFields()
    setDestroyOpen(item)
  }

  const onDestroy = async () => {
    if (!destroyOpen) return
    const values = await destroyForm.validateFields()
    setDestroySaving(true)
    try {
      const res = await destroyRetainedSample(destroyOpen.id, {
        destroyed_at: (values.destroyed_at as Dayjs).format('YYYY-MM-DD'),
        remark: values.remark,
      })
      message.success(res.message)
      setDestroyOpen(null)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '销毁登记失败')
    } finally {
      setDestroySaving(false)
    }
  }

  const onExport = async () => {
    try {
      const blob = await exportRetainedSamples({ sourceType: typeFilter, batchNo: batchFilter, status: statusFilter })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '留样台账.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '导出失败')
    }
  }

  const renderDueDate = (v: string | null, item: RetainedSample) => {
    if (!v || item.status !== 'active') return v || '-'
    const d = dayjs(v).startOf('day')
    const diff = d.diff(today(), 'day')
    if (diff < 0) return <Typography.Text type="danger" strong>{v}（已到期）</Typography.Text>
    if (diff <= 30) return <Typography.Text type="warning" strong>{v}（{diff} 天后）</Typography.Text>
    return v
  }

  return (
    <>
      {(dueStats.expired > 0 || dueStats.soon > 0) && (
        <Alert
          type="warning" showIcon icon={<WarningOutlined />}
          style={{ marginBottom: 12 }}
          message={`销毁到期提醒：${dueStats.expired > 0 ? `${dueStats.expired} 条已到期未销毁` : ''}${dueStats.expired > 0 && dueStats.soon > 0 ? '，' : ''}${dueStats.soon > 0 ? `${dueStats.soon} 条 30 天内到期` : ''}，请安排销毁计划并双人确认登记`}
        />
      )}

      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear placeholder="类型" style={{ width: 110 }}
          value={typeFilter}
          onChange={(v) => setTypeFilter(v)}
          options={[
            { value: 'product', label: '成品' },
            { value: 'material', label: '物料' },
          ]}
        />
        <Input.Search
          placeholder="批号搜索" allowClear style={{ width: 200 }}
          prefix={<SearchOutlined />}
          value={batchDraft}
          onChange={(e) => setBatchDraft(e.target.value)}
          onSearch={(v) => setBatchFilter(v || undefined)}
        />
        <Select
          allowClear placeholder="状态" style={{ width: 110 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
          options={[
            { value: 'active', label: '在留' },
            { value: 'destroyed', label: '已销毁' },
          ]}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>留样登记</Button>
        )}
        <Button icon={<DownloadOutlined />} onClick={onExport}>导出 Excel</Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        scroll={{ x: 1250 }}
        pagination={{ pageSize: 20 }}
        columns={[
          {
            title: '类型', dataIndex: 'source_type', width: 70,
            render: (v: string) => <Tag color={TYPE_META[v]?.color}>{TYPE_META[v]?.label ?? v}</Tag>,
          },
          { title: '品名', dataIndex: 'sample_name', width: 170 },
          { title: '批号', dataIndex: 'batch_no', width: 130 },
          { title: '留样量', dataIndex: 'qty', width: 90, render: (v: string | null) => v || '-' },
          { title: '贮存位置', dataIndex: 'location', width: 100, render: (v: string | null) => v || '-' },
          { title: '留样日期', dataIndex: 'retained_at', width: 105, render: (v: string | null) => v || '-' },
          {
            title: '销毁到期日', dataIndex: 'destroy_due_date', width: 140,
            render: (v: string | null, item: RetainedSample) => renderDueDate(v, item),
          },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v: string, item: RetainedSample) => (
              v === 'destroyed'
                ? <Tag color="default">已销毁</Tag>
                : item.destroyed_by && !item.destroy_confirm_by
                  ? <Tag color="orange">待确认销毁</Tag>
                  : <Tag color="green">在留</Tag>
            ),
          },
          {
            title: '销毁信息', key: 'destroy_info', width: 190,
            render: (_: unknown, item: RetainedSample) => {
              if (item.status === 'destroyed') {
                return (
                  <Typography.Text type="secondary">
                    {item.destroyed_at}｜{item.destroyed_by_name ?? '-'} 登记 / {item.destroy_confirm_by_name ?? '-'} 确认
                  </Typography.Text>
                )
              }
              if (item.destroyed_by) {
                return (
                  <Typography.Text type="warning">
                    待确认（{item.destroyed_by_name ?? '-'} 已登记 {item.destroyed_at ?? ''}）
                  </Typography.Text>
                )
              }
              return '-'
            },
          },
          { title: '备注', dataIndex: 'remark', width: 140, ellipsis: true, render: (v: string | null) => v || '-' },
          {
            title: '操作', key: 'actions', width: 170, fixed: 'right',
            render: (_: unknown, item: RetainedSample) => (
              canManage ? (
                <Space size="small">
                  {item.status === 'active' && (
                    <Button size="small" type="link" onClick={() => openEdit(item)}>编辑</Button>
                  )}
                  {item.status === 'active' && (
                    <Button
                      size="small" type="link"
                      style={{ color: item.destroyed_by ? '#fa8c16' : '#cf1322' }}
                      onClick={() => openDestroy(item)}
                    >
                      {item.destroyed_by ? '销毁确认' : '销毁登记'}
                    </Button>
                  )}
                  <Popconfirm title="确认删除该登记？" onConfirm={async () => {
                    try { await deleteRetainedSample(item.id); message.success('已删除'); load() } catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '删除失败') }
                  }}>
                    <Button size="small" type="link" danger>删除</Button>
                  </Popconfirm>
                </Space>
              ) : '-'
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑留样登记' : '留样登记'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        confirmLoading={saving}
        okText="保存"
        width={520}
      >
        <Form form={form} layout="vertical" initialValues={{ source_type: 'product' }}>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="source_type" label="类型" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={[
                { value: 'product', label: '成品' },
                { value: 'material', label: '物料' },
              ]} />
            </Form.Item>
            <Form.Item name="batch_no" label="批号" rules={[{ required: true, message: '必填' }]} style={{ flex: 1 }}>
              <Input maxLength={100} />
            </Form.Item>
          </Space>
          <Form.Item name="sample_name" label="品名/名称" rules={[{ required: true, message: '必填' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="qty" label="留样量（如 2 瓶）" style={{ flex: 1 }}>
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item name="location" label="贮存位置（柜号）" style={{ flex: 1 }}>
              <Input maxLength={50} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="retained_at" label="留样日期" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="destroy_due_date" label="销毁到期日" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`销毁登记 ${destroyOpen ? `（${destroyOpen.sample_name} 批号 ${destroyOpen.batch_no}）` : ''}`}
        open={!!destroyOpen}
        onCancel={() => setDestroyOpen(null)}
        onOk={onDestroy}
        confirmLoading={destroySaving}
        okText={destroyOpen?.destroyed_by ? '确认销毁' : '提交登记'}
        okButtonProps={{ danger: true }}
        width={480}
      >
        {destroyOpen?.destroyed_by ? (
          <Alert
            type="warning" showIcon style={{ marginBottom: 12 }}
            message={`${destroyOpen.destroyed_by_name ?? '同事'} 已登记销毁（${destroyOpen.destroyed_at ?? ''}），请您作为第二人确认。`}
          />
        ) : (
          <Alert
            type="info" showIcon style={{ marginBottom: 12 }}
            message="登记销毁日期后，需另一位同事再次确认，留样状态才会转为已销毁。"
          />
        )}
        <Form form={destroyForm} layout="vertical">
          <Form.Item name="destroyed_at" label="销毁日期" rules={[{ required: true, message: '必填' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="remark" label="销毁备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

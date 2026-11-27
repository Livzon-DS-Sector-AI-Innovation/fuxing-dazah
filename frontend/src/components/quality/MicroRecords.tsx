'use client'

import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Input, Space, Button, App, Modal, Form, InputNumber, DatePicker, Upload, Popconfirm, Typography, Image } from 'antd'
import { PlusOutlined, DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { MicroRecord } from '@/types/quality'
import { fetchMicroRecords, createMicroRecord, updateMicroRecord, deleteMicroRecord, uploadMicroPhotos, exportMicroRecords, fetchMicroPhotoDataUrl } from '@/actions/quality'

const JUDGE_META: Record<string, { label: string; color: string }> = {
  pass: { label: '合格', color: 'green' },
  alert: { label: '超警戒', color: 'orange' },
  action: { label: '超标准', color: 'red' },
}

export default function MicroRecords() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [data, setData] = useState<MicroRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [batchDraft, setBatchDraft] = useState('')
  const [batchFilter, setBatchFilter] = useState<string | undefined>()
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<MicroRecord | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [photosOpen, setPhotosOpen] = useState<MicroRecord | null>(null)
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchMicroRecords(batchFilter)
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取登记失败')
    } finally {
      setLoading(false)
    }
  }, [message, batchFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setEditOpen(true)
  }

  const openEdit = (item: MicroRecord) => {
    setEditing(item)
    form.setFieldsValue({
      sample_name: item.sample_name,
      batch_number: item.batch_number ?? undefined,
      sample_date: item.sample_date ? dayjs(item.sample_date) : undefined,
      colony_count: item.colony_count ?? undefined,
      ai_count: item.ai_count ?? undefined,
      alert_limit: item.alert_limit ?? undefined,
      action_limit: item.action_limit ?? undefined,
      remark: item.remark ?? undefined,
    })
    setEditOpen(true)
  }

  const onSave = async () => {
    const values = await form.validateFields()
    const payload = {
      ...values,
      sample_date: values.sample_date ? values.sample_date.format('YYYY-MM-DD') : undefined,
    }
    setSaving(true)
    try {
      if (editing) {
        await updateMicroRecord(editing.id, payload)
        message.success('登记已更新')
      } else {
        await createMicroRecord(payload)
        message.success('登记已保存')
      }
      setEditOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onUploadPhotos = async (file: File) => {
    if (!photosOpen) return false
    try {
      const res = await uploadMicroPhotos(photosOpen.id, [file])
      message.success(res.message)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '照片上传失败')
    }
    return false
  }

  const onExport = async () => {
    try {
      const blob = await exportMicroRecords(batchFilter)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '微生物登记表.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '导出失败')
    }
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search
          placeholder="批号搜索" allowClear style={{ width: 200 }}
          prefix={<SearchOutlined />}
          value={batchDraft}
          onChange={(e) => setBatchDraft(e.target.value)}
          onSearch={(v) => setBatchFilter(v || undefined)}
        />
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增登记</Button>
        )}
        <Button icon={<DownloadOutlined />} onClick={onExport}>导出 Excel</Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={data}
        scroll={{ x: 950 }}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '品名', dataIndex: 'sample_name', width: 180 },
          { title: '批号', dataIndex: 'batch_number', width: 130, render: (v: string | null) => v || '-' },
          { title: '检测日期', dataIndex: 'sample_date', width: 110, render: (v: string | null) => v || '-' },
          { title: '菌落计数', dataIndex: 'colony_count', width: 90, render: (v: number | null) => v ?? '-' },
          { title: 'AI预计数', dataIndex: 'ai_count', width: 90, render: (v: number | null) => v != null ? <Typography.Text type="secondary">{v}</Typography.Text> : '-' },
          { title: '警戒线', dataIndex: 'alert_limit', width: 80, render: (v: number | null) => v ?? '-' },
          { title: '标准限', dataIndex: 'action_limit', width: 80, render: (v: number | null) => v ?? '-' },
          {
            title: '判定', dataIndex: 'judge', width: 100,
            render: (v: string | null) => v ? <Tag color={JUDGE_META[v]?.color}>{JUDGE_META[v]?.label ?? v}</Tag> : '-',
          },
          {
            title: '照片', dataIndex: 'photo_keys', width: 100,
            render: (v: string[] | null, item: MicroRecord) => (
              <Button size="small" type="link" onClick={async () => {
                setPhotosOpen(item)
                setPhotoUrls({})
                for (const key of item.photo_keys ?? []) {
                  try {
                    const url = await fetchMicroPhotoDataUrl(item.id, key)
                    setPhotoUrls((m) => ({ ...m, [key]: url }))
                  } catch { /* 单张失败跳过 */ }
                }
              }}>
                {(v ?? []).length} 张
              </Button>
            ),
          },
          {
            title: '操作', key: 'actions', width: 140,
            render: (_: unknown, item: MicroRecord) => (
              canManage ? (
                <Space size="small">
                  <Button size="small" type="link" onClick={() => openEdit(item)}>编辑</Button>
                  <Popconfirm title="确认删除该登记？" onConfirm={async () => {
                    try { await deleteMicroRecord(item.id); message.success('已删除'); load() } catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '删除失败') }
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
        title={editing ? '编辑登记' : '新增微生物登记'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={onSave}
        confirmLoading={saving}
        okText="保存"
        width={480}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="sample_name" label="品名" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如 纯化水" />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="batch_number" label="批号" style={{ flex: 1 }}>
              <Input />
            </Form.Item>
            <Form.Item name="sample_date" label="检测日期" style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="colony_count" label="菌落计数（人工确认）" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="ai_count" label="AI 预计数（预留）" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="alert_limit" label="警戒线" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="action_limit" label="标准限（行动限）" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`平皿照片 ${photosOpen ? `（${photosOpen.sample_name}${photosOpen.batch_number ? ' ' + photosOpen.batch_number : ''}）` : ''}`}
        open={!!photosOpen}
        onCancel={() => setPhotosOpen(null)}
        footer={canManage ? <Upload accept="image/*" showUploadList={false} beforeUpload={onUploadPhotos}>
          <Button icon={<PlusOutlined />}>上传照片</Button>
        </Upload> : null}
        width={620}
      >
        {photosOpen && (photosOpen.photo_keys ?? []).length === 0 && (
          <Typography.Text type="secondary">暂无照片，点击下方「上传照片」归档平皿原始证据。</Typography.Text>
        )}
        <Space wrap size={8}>
          {(photosOpen?.photo_keys ?? []).map((key) => (
            <Image
              key={key}
              alt="平皿照片"
              width={140}
              height={140}
              style={{ objectFit: 'cover', borderRadius: 6 }}
              src={photoUrls[key]}
              placeholder
            />
          ))}
        </Space>
      </Modal>
    </>
  )
}

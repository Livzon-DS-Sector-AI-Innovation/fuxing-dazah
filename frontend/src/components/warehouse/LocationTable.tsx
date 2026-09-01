'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import {
  LOCATION_TYPE_LABEL,
  LocationCreate,
  LocationRecord,
  LocationType,
  LocationUpdate,
} from '@/types/warehouse'
import { createLocation, deleteLocation, getLocations, updateLocation } from '@/actions/warehouse'

const TYPE_OPTIONS = Object.entries(LOCATION_TYPE_LABEL).map(([value, label]) => ({
  value,
  label,
}))

const TYPE_COLOR: Record<LocationType, string> = {
  normal: 'blue',
  cold: 'cyan',
  danger: 'red',
}

export function LocationTable() {
  const { message } = App.useApp()
  const [data, setData] = useState<LocationRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<LocationRecord | null>(null)
  const [initialValues, setInitialValues] = useState<LocationCreate | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<LocationCreate>()

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getLocations())
    } catch {
      message.error('获取库位列表失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
  }, [fetchData])

  const openCreate = () => {
    setEditing(null)
    setInitialValues({ code: '', name: '', location_type: 'normal' })
    setModalOpen(true)
  }

  const openEdit = (record: LocationRecord) => {
    setEditing(record)
    setInitialValues({
      code: record.code,
      name: record.name,
      location_type: record.location_type,
      remark: record.remark ?? undefined,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await updateLocation(editing.id, values as LocationUpdate)
        message.success('库位已更新')
      } else {
        await createLocation(values)
        message.success('库位已创建')
      }
      setModalOpen(false)
      fetchData()
    } catch (e) {
      if (e instanceof Error) message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: LocationRecord) => {
    try {
      await deleteLocation(record.id)
      message.success('库位已删除')
      fetchData()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败')
    }
  }

  const columns: TableColumnsType<LocationRecord> = [
    { title: '库位编码', dataIndex: 'code', width: 150 },
    { title: '库位名称', dataIndex: 'name', width: 220 },
    {
      title: '类型',
      dataIndex: 'location_type',
      width: 100,
      render: (value: LocationType) => (
        <Tag color={TYPE_COLOR[value] ?? 'default'}>{LOCATION_TYPE_LABEL[value] ?? value}</Tag>
      ),
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: v => v ?? '-' },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button size="small" type="link" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该库位？" onConfirm={() => handleDelete(record)}>
            <Button size="small" type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={openCreate}>
          新增库位
        </Button>
      </Space>

      <Table<LocationRecord>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={false}
      />

      {modalOpen && initialValues && (
        <Modal
          title={editing ? `编辑库位：${editing.code}` : '新增库位'}
          open
          confirmLoading={saving}
          onOk={handleSave}
          onCancel={() => setModalOpen(false)}
          destroyOnHidden
        >
          <Form form={form} layout="vertical" initialValues={initialValues} style={{ paddingTop: 8 }}>
            <Form.Item name="code" label="库位编码" rules={[{ required: true, message: '请输入库位编码' }]}>
              <Input placeholder="如 LOC-001" disabled={!!editing} />
            </Form.Item>
            <Form.Item name="name" label="库位名称" rules={[{ required: true, message: '请输入库位名称' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="location_type" label="类型">
              <Select options={TYPE_OPTIONS} />
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

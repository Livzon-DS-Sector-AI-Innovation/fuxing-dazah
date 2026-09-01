'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import {
  MATERIAL_CATEGORY_LABEL,
  MaterialCategory,
  MaterialCreate,
  MaterialRecord,
  MaterialUpdate,
  Paginated,
} from '@/types/warehouse'
import { createMaterial, deleteMaterial, getMaterials, updateMaterial } from '@/actions/warehouse'

const CATEGORY_OPTIONS = Object.entries(MATERIAL_CATEGORY_LABEL).map(([value, label]) => ({
  value,
  label,
}))

export function MaterialTable() {
  const { message } = App.useApp()
  const [data, setData] = useState<MaterialRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState<MaterialCategory | undefined>(undefined)

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<MaterialRecord | null>(null)
  const [initialValues, setInitialValues] = useState<MaterialCreate | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<MaterialCreate>()

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res: Paginated<MaterialRecord> = await getMaterials({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        category,
      })
      setData(res.items)
      setTotal(res.total)
    } catch {
      message.error('获取物料列表失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, keyword, category])

  useEffect(() => {
    const t = setTimeout(fetchData, 0)
    return () => clearTimeout(t)
  }, [fetchData])

  const openCreate = () => {
    setEditing(null)
    setInitialValues({ code: '', name: '', category: 'raw', unit: '', safety_stock: 0 })
    setModalOpen(true)
  }

  const openEdit = (record: MaterialRecord) => {
    setEditing(record)
    setInitialValues({
      code: record.code,
      name: record.name,
      category: record.category,
      spec: record.spec ?? undefined,
      unit: record.unit,
      safety_stock: record.safety_stock,
      remark: record.remark ?? undefined,
    })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await updateMaterial(editing.id, values as MaterialUpdate)
        message.success('物料已更新')
      } else {
        await createMaterial(values)
        message.success('物料已创建')
      }
      setModalOpen(false)
      fetchData()
    } catch (e) {
      if (e instanceof Error) message.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: MaterialRecord) => {
    try {
      await deleteMaterial(record.id)
      message.success('物料已删除')
      fetchData()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败')
    }
  }

  const columns: TableColumnsType<MaterialRecord> = [
    { title: '物料编码', dataIndex: 'code', width: 150 },
    { title: '物料名称', dataIndex: 'name', width: 200 },
    {
      title: '分类',
      dataIndex: 'category',
      width: 100,
      render: (value: MaterialCategory) => (
        <Tag color="blue">{MATERIAL_CATEGORY_LABEL[value] ?? value}</Tag>
      ),
    },
    { title: '规格型号', dataIndex: 'spec', width: 150, render: v => v ?? '-' },
    { title: '单位', dataIndex: 'unit', width: 80 },
    { title: '安全库存', dataIndex: 'safety_stock', width: 110, align: 'right' },
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
          <Popconfirm title="确定删除该物料？" onConfirm={() => handleDelete(record)}>
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
      <Space style={{ marginBottom: 12 }} wrap>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索编码/名称"
          style={{ width: 220 }}
          onChange={e => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
        <Select
          allowClear
          placeholder="全部分类"
          style={{ width: 140 }}
          value={category}
          onChange={value => {
            setCategory(value)
            setPage(1)
          }}
          options={CATEGORY_OPTIONS}
        />
        <Button type="primary" onClick={openCreate}>
          新增物料
        </Button>
      </Space>

      <Table<MaterialRecord>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 900 }}
      />

      {modalOpen && initialValues && (
        <Modal
          title={editing ? `编辑物料：${editing.code}` : '新增物料'}
          open
          confirmLoading={saving}
          onOk={handleSave}
          onCancel={() => setModalOpen(false)}
          destroyOnHidden
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={initialValues}
            style={{ paddingTop: 8 }}
          >
            <Form.Item name="code" label="物料编码" rules={[{ required: true, message: '请输入物料编码' }]}>
              <Input placeholder="如 MAT-0001" disabled={!!editing} />
            </Form.Item>
            <Form.Item name="name" label="物料名称" rules={[{ required: true, message: '请输入物料名称' }]}>
              <Input />
            </Form.Item>
            <Form.Item name="category" label="分类" rules={[{ required: true }]}>
              <Select options={CATEGORY_OPTIONS} />
            </Form.Item>
            <Form.Item name="spec" label="规格型号">
              <Input />
            </Form.Item>
            <Form.Item name="unit" label="计量单位" rules={[{ required: true, message: '请输入计量单位' }]}>
              <Input placeholder="如 kg / L / 桶" />
            </Form.Item>
            <Form.Item name="safety_stock" label="安全库存">
              <InputNumber min={0} style={{ width: '100%' }} />
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

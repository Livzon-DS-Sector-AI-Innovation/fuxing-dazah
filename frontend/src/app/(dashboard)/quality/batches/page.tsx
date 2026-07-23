'use client'

import { useState, useEffect } from 'react'
import { Table, Typography, Button, Input, Space, Tag, message, Card, Popconfirm, Modal, Form, DatePicker, Select } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const BKEY = 'lc_batches'

interface Batch {
  id: string; batchNo: string; product: string; spec: string
  batchSize: string; mfgDate: string; expiry: string; serialPrefix: string
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([])
  const [open, setOpen] = useState(false)
  const [editIdx, setEditIdx] = useState<number>(-1)
  const [form] = Form.useForm()

  useEffect(() => { load() }, [])

  function load() {
    try { setBatches(JSON.parse(localStorage.getItem(BKEY) || '[]')) } catch { setBatches([]) }
  }

  function save(data: any) {
    let list = [...batches]
    const item: Batch = {
      id: data.batchNo || Date.now().toString(),
      batchNo: data.batchNo || '', product: data.product || '', spec: data.spec || '',
      batchSize: data.batchSize || '', mfgDate: data.mfgDate ? dayjs(data.mfgDate).format('YYYY-MM-DD') : '',
      expiry: data.expiry || '', serialPrefix: data.serialPrefix || '',
    }
    if (editIdx >= 0) list[editIdx] = item
    else list.unshift(item)
    localStorage.setItem(BKEY, JSON.stringify(list))
    load(); setOpen(false); message.success('已保存')
  }

  function del(idx: number) {
    const list = batches.filter((_, i) => i !== idx)
    localStorage.setItem(BKEY, JSON.stringify(list)); load()
  }

  function openEdit(idx: number) {
    setEditIdx(idx)
    const b = batches[idx]
    form.setFieldsValue({ ...b, mfgDate: b.mfgDate ? dayjs(b.mfgDate) : null })
    setOpen(true)
  }

  function openNew() {
    setEditIdx(-1); form.resetFields(); setOpen(true)
  }

  const columns = [
    { title: '批号', dataIndex: 'batchNo', width: 130, render: (v: string) => <Text strong>{v}</Text> },
    { title: '产品', dataIndex: 'product', width: 100, render: (v: string) => <Tag color="blue">{v || '-'}</Tag> },
    { title: '规格', dataIndex: 'spec', width: 90 },
    { title: '批量', dataIndex: 'batchSize', width: 80 },
    { title: '生产日期', dataIndex: 'mfgDate', width: 100 },
    { title: '有效期', dataIndex: 'expiry', width: 70 },
    { title: '流水号前缀', dataIndex: 'serialPrefix', width: 100 },
    {
      title: '操作', key: 'act', width: 100,
      render: (_: any, __: any, idx: number) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(idx)} />
          <Popconfirm title="删除？" onConfirm={() => del(idx)}>
            <Button type="link" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <ExperimentOutlined style={{ fontSize: 20, color: '#1a73e8' }} />
          <Title level={4} style={{ margin: 0 }}>批次台账</Title>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>新建批次</Button>
        </Space>
      </div>

      {batches.length ? (
        <Table columns={columns} dataSource={batches.map((b, i) => ({ ...b, key: i }))}
          pagination={{ pageSize: 20 }} size="small" bordered />
      ) : (
        <Card><Text type="secondary">暂无批次记录，点击「新建批次」创建</Text></Card>
      )}

      <Modal title={editIdx >= 0 ? '编辑批次' : '新建批次'} open={open}
        onOk={() => form.submit()} onCancel={() => setOpen(false)} width={500}>
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item label="批号" name="batchNo" rules={[{ required: true }]}><Input placeholder="HAF2606019A" /></Form.Item>
          <Form.Item label="产品" name="product"><Input placeholder="盐酸万古霉素" /></Form.Item>
          <Form.Item label="规格" name="spec"><Input placeholder="5kg/瓶" /></Form.Item>
          <Form.Item label="批量" name="batchSize"><Input placeholder="25.5 kg" /></Form.Item>
          <Form.Item label="生产日期" name="mfgDate"><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item label="有效期(年)" name="expiry"><Input placeholder="3" /></Form.Item>
          <Form.Item label="流水号前缀" name="serialPrefix"><Input placeholder="COA-HAF-3205" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

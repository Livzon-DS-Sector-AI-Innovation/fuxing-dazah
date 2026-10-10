'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Select, Modal, Form, DatePicker, Popconfirm, Typography,
} from 'antd'
import { PlusOutlined, SearchOutlined, DownloadOutlined, ScanOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import { MATERIAL_CONTAINER_STATUS_META } from '@/types/quality'
import type { MaterialContainerItem, MaterialContainerStatus } from '@/types/quality'
import {
  fetchMaterialContainers, generateMaterialContainers, moveMaterialContainer,
  updateMaterialContainerStatus, downloadContainerLabels,
} from '@/actions/quality'

const STATUS_ORDER: MaterialContainerStatus[] = ['labeled', 'in_warehouse', 'qualified', 'issued', 'returned', 'void']

export default function MaterialContainers() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<MaterialContainerItem[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [batchDraft, setBatchDraft] = useState('')
  const [batchFilter, setBatchFilter] = useState<string | undefined>()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [genForm] = Form.useForm()
  const [genLoading, setGenLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [labelLoading, setLabelLoading] = useState(false)

  const load = useCallback(async (p: number, status?: string, batch?: string) => {
    setLoading(true)
    try {
      const res = await fetchMaterialContainers(p, status, batch)
      setData(res.data)
      setTotal(res.meta.total)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { (async () => { await load(1, statusFilter, batchFilter) })() }, [statusFilter, batchFilter, load])

  const onGenerate = async () => {
    const values = await genForm.validateFields()
    setGenLoading(true)
    try {
      const res = await generateMaterialContainers({
        material_code: values.material_code,
        material_name: values.material_name,
        vendor_code: values.vendor_code || undefined,
        inbound_batch_no: values.inbound_batch_no,
        expiry_date: values.expiry_date ? values.expiry_date.format('YYYY-MM-DD') : undefined,
        count: values.count,
      })
      const nos = res.data.map((c) => c.container_no)
      // 生成后直接拉标签 PDF
      const blob = await downloadContainerLabels(nos)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `物料标签-${values.material_code}-${nos.length}张.pdf`
      a.click()
      URL.revokeObjectURL(url)
      message.success(`${res.message}，标签已开始下载`)
      setGenerateOpen(false)
      genForm.resetFields()
      load(page, statusFilter, batchFilter)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '赋码失败')
    } finally {
      setGenLoading(false)
    }
  }

  const onMove = async (row: MaterialContainerItem, op: 'in' | 'out') => {
    try {
      const res = await moveMaterialContainer(row.container_no, op)
      message.success(res.message)
      load(page, statusFilter, batchFilter)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '操作失败')
    }
  }

  const onStatus = async (row: MaterialContainerItem, status: 'in_warehouse' | 'qualified' | 'void') => {
    try {
      const res = await updateMaterialContainerStatus(row.container_no, status)
      message.success(res.message)
      load(page, statusFilter, batchFilter)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '状态变更失败')
    }
  }

  const onDownloadSelected = async () => {
    if (!selectedKeys.length) {
      message.warning('请先勾选容器')
      return
    }
    setLabelLoading(true)
    try {
      const blob = await downloadContainerLabels(selectedKeys)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `物料标签-${selectedKeys.length}张.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '标签生成失败')
    } finally {
      setLabelLoading(false)
    }
  }

  const columns = [
    { title: '容器号', dataIndex: 'container_no', key: 'container_no', width: 220, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: '物料名称', dataIndex: 'material_name', key: 'material_name' },
    { title: '物料代码', dataIndex: 'material_code', key: 'material_code', width: 110 },
    { title: '进厂批号', dataIndex: 'inbound_batch_no', key: 'inbound_batch_no', width: 160 },
    { title: '复验期', dataIndex: 'expiry_date', key: 'expiry_date', width: 110, render: (v: string | null) => v || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: MaterialContainerStatus) => {
        const meta = MATERIAL_CONTAINER_STATUS_META[v]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '操作', key: 'actions', width: 260,
      render: (_: unknown, row: MaterialContainerItem) => (
        <Space size="small">
          {canManage && row.status === 'labeled' && (
            <Popconfirm title="确认入库登记？" onConfirm={() => onMove(row, 'in')}>
              <Button size="small" icon={<ScanOutlined />}>入库</Button>
            </Popconfirm>
          )}
          {canManage && (row.status === 'in_warehouse' || row.status === 'qualified') && (
            <Popconfirm title="确认领料出库？" onConfirm={() => onMove(row, 'out')}>
              <Button size="small" danger>出库</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'in_warehouse' && (
            <Popconfirm title="确认标记合格？（阶段1人工操作，后续放行联动）" onConfirm={() => onStatus(row, 'qualified')}>
              <Button size="small" type="primary" ghost>合格</Button>
            </Popconfirm>
          )}
          {canManage && row.status === 'labeled' && (
            <Popconfirm title="确认作废该容器？" onConfirm={() => onStatus(row, 'void')}>
              <Button size="small" type="link" danger>作废</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space wrap>
        <Input
          placeholder="进厂批号搜索" allowClear style={{ width: 180 }}
          prefix={<SearchOutlined />}
          value={batchDraft}
          onChange={(e) => setBatchDraft(e.target.value)}
          onPressEnter={() => { setBatchFilter(batchDraft || undefined); setPage(1) }}
        />
        <Select
          placeholder="状态筛选" allowClear style={{ width: 140 }}
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v); setPage(1) }}
          options={STATUS_ORDER.map((s) => ({ label: MATERIAL_CONTAINER_STATUS_META[s].label, value: s }))}
        />
        <Button type="primary" onClick={() => { setBatchFilter(batchDraft || undefined); setPage(1) }}>搜索</Button>
        {canManage && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setGenerateOpen(true)}>批量赋码</Button>
        )}
        <Button icon={<DownloadOutlined />} loading={labelLoading} onClick={onDownloadSelected}>下载标签</Button>
      </Space>

      <Table
        rowKey="container_no"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: (p) => setPage(p) }}
        size="small"
        rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys as string[]) }}
      />

      <Modal
        title="批量赋码（生成唯一容器号 + 标签）"
        open={generateOpen}
        onCancel={() => setGenerateOpen(false)}
        onOk={onGenerate}
        confirmLoading={genLoading}
        okText="赋码并下载标签"
      >
        <Form form={genForm} layout="vertical" initialValues={{ count: 1 }}>
          <Form.Item name="material_code" label="物料代码（容器号中段，如 VAN）" rules={[{ required: true, message: '请输入物料代码' }]}>
            <Input placeholder="VAN" />
          </Form.Item>
          <Form.Item name="material_name" label="物料名称" rules={[{ required: true, message: '请输入物料名称' }]}>
            <Input placeholder="盐酸万古霉素原料" />
          </Form.Item>
          <Form.Item name="vendor_code" label="供应商代码（可选）">
            <Input placeholder="SUP-001" />
          </Form.Item>
          <Form.Item name="inbound_batch_no" label="进厂批号" rules={[{ required: true, message: '请输入进厂批号' }]}>
            <Input placeholder="IN-20261010-01" />
          </Form.Item>
          <Form.Item name="expiry_date" label="复验期（可选）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="count" label="本批容器数量" rules={[{ required: true }]}>
            <Input type="number" min={1} max={500} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

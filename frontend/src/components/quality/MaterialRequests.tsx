'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Table, Tag, Input, Space, Button, App, Select, Modal, Form, InputNumber, DatePicker, Typography, Tabs, Popconfirm,
} from 'antd'
import { PlusOutlined, ExperimentOutlined, CheckCircleOutlined, StopOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import { REQUEST_STATUS_META } from '@/types/quality'
import type { MaterialRequestItem, MaterialRequestStatus, MaterialStandardItemRow, MaterialStandardRow } from '@/types/quality'
import {
  fetchMaterialRequests, createMaterialRequest, sampleMaterialRequest,
  createMaterialInspectionTask, releaseMaterialRequest,
  fetchMaterialDict, createMaterialStandard, fetchMaterialStandardItems, createMaterialStandardItem,
} from '@/actions/quality'

export default function MaterialRequests() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:material:manage')
  const canRelease = hasPermission('quality:material:release')
  const canCreateTask = hasPermission('quality:task:create')
  const [data, setData] = useState<MaterialRequestItem[]>([])
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [batchDraft, setBatchDraft] = useState('')
  const [batchFilter, setBatchFilter] = useState<string | undefined>()
  // 新建请验
  const [createOpen, setCreateOpen] = useState(false)
  const [reqForm] = Form.useForm()
  const [dictOptions, setDictOptions] = useState<{ value: string; label: string; name: string; vendor: string | null }[]>([])
  // 取样
  const [sampleTarget, setSampleTarget] = useState<MaterialRequestItem | null>(null)
  const [sampleForm] = Form.useForm()
  // 放行
  const [releaseTarget, setReleaseTarget] = useState<MaterialRequestItem | null>(null)
  const [releaseVerdict, setReleaseVerdict] = useState<'release' | 'reject' | 'concede'>('release')
  const [releaseRemark, setReleaseRemark] = useState('')
  // 物料标准库
  const [stdItems, setStdItems] = useState<MaterialStandardItemRow[]>([])
  const [stdRows, setStdRows] = useState<MaterialStandardRow[]>([])
  const [stdCreateOpen, setStdCreateOpen] = useState(false)
  const [stdForm] = Form.useForm()
  const [stdItemOpen, setStdItemOpen] = useState(false)
  const [stdItemForm] = Form.useForm()
  const [activeStdId, setActiveStdId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetchMaterialRequests(statusFilter, batchFilter)
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '加载请验单失败')
    }
  }, [message, statusFilter, batchFilter])

  const loadDict = useCallback(async () => {
    try {
      const res = await fetchMaterialDict()
      setDictOptions(res.data.map((d) => ({ value: d.code, label: `${d.code} · ${d.name}`, name: d.name, vendor: d.vendor_code })))
    } catch { /* 静默 */ }
  }, [])

  useEffect(() => { (async () => { await load() })() }, [load])
  useEffect(() => { (async () => { await loadDict() })() }, [loadDict])

  const onCreate = async () => {
    const values = await reqForm.validateFields()
    try {
      const res = await createMaterialRequest({
        material_code: values.material_code,
        vendor_code: values.vendor_code || undefined,
        inbound_batch_no: values.inbound_batch_no,
        inbound_qty: values.inbound_qty || 1,
        inbound_date: values.inbound_date ? values.inbound_date.format('YYYY-MM-DD') : undefined,
      })
      message.success(res.message)
      setCreateOpen(false)
      reqForm.resetFields()
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '创建请验单失败')
    }
  }

  const onSample = async () => {
    if (!sampleTarget) return
    const values = await sampleForm.validateFields()
    try {
      const res = await sampleMaterialRequest(sampleTarget.id, {
        sampled_qty: values.sampled_qty,
        sampled_at: values.sampled_at ? values.sampled_at.format('YYYY-MM-DD') : undefined,
      })
      message.success(res.message)
      setSampleTarget(null)
      sampleForm.resetFields()
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '取样登记失败')
    }
  }

  const onCreateTask = async (item: MaterialRequestItem) => {
    try {
      const res = await createMaterialInspectionTask(item.id)
      message.success(res.message)
      load()
      router.push(`/quality/task/${res.data.task_id}`)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '建检验任务失败')
    }
  }

  const onRelease = async () => {
    if (!releaseTarget) return
    if (releaseVerdict !== 'release' && !releaseRemark.trim()) {
      message.warning('拒收/让步需填写原因')
      return
    }
    try {
      const res = await releaseMaterialRequest(releaseTarget.id, releaseVerdict, releaseRemark.trim() || undefined)
      message.success(res.message)
      setReleaseTarget(null)
      setReleaseRemark('')
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '放行操作失败')
    }
  }

  // ── 物料标准库 ──
  const loadStdItems = useCallback(async (sid: string) => {
    try {
      const res = await fetchMaterialStandardItems(sid)
      setStdItems(res.data)
    } catch { /* 静默 */ }
  }, [])

  const onCreateStd = async () => {
    const values = await stdForm.validateFields()
    try {
      const res = await createMaterialStandard({ material_code: values.material_code, vendor_code: values.vendor_code || undefined })
      setStdRows((prev) => [res.data, ...prev])
      message.success(res.message)
      setStdCreateOpen(false)
      stdForm.resetFields()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '创建物料标准失败')
    }
  }

  const onAddStdItem = async () => {
    if (!activeStdId) return
    const values = await stdItemForm.validateFields()
    try {
      await createMaterialStandardItem(activeStdId, values)
      message.success('项目行已添加')
      setStdItemOpen(false)
      stdItemForm.resetFields()
      loadStdItems(activeStdId)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '添加项目行失败')
    }
  }

  const requestColumns = [
    { title: '请验单号', dataIndex: 'request_no', width: 170, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: '物料', dataIndex: 'material_name', width: 160 },
    { title: '供应商', dataIndex: 'vendor_name', width: 130, render: (v: string | null) => v || '-' },
    { title: '进厂批号', dataIndex: 'inbound_batch_no', width: 150 },
    { title: '数量', dataIndex: 'inbound_qty', width: 70 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: MaterialRequestStatus) => <Tag color={REQUEST_STATUS_META[v]?.color}>{REQUEST_STATUS_META[v]?.label ?? v}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 300,
      render: (_: unknown, item: MaterialRequestItem) => (
        <Space size="small">
          {canManage && item.status === 'pending_sample' && (
            <Button size="small" onClick={() => { setSampleTarget(item); sampleForm.resetFields() }}>取样</Button>
          )}
          {canCreateTask && (item.status === 'sampled' || item.status === 'in_test') && (
            <Popconfirm title="按物料标准快照建检验任务？" onConfirm={() => onCreateTask(item)}>
              <Button size="small" type="primary" icon={<ExperimentOutlined />}>
                {item.status === 'in_test' && item.task_id ? '查看检验任务' : '建检验任务'}
              </Button>
            </Popconfirm>
          )}
          {canRelease && (item.status === 'in_test' || item.status === 'sampled') && (
            <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => { setReleaseTarget(item); setReleaseVerdict('release'); setReleaseRemark('') }}>
              放行
            </Button>
          )}
          {canRelease && item.status === 'in_test' && (
            <Button size="small" danger icon={<StopOutlined />} onClick={() => { setReleaseTarget(item); setReleaseVerdict('reject'); setReleaseRemark('') }}>
              拒收
            </Button>
          )}
          {item.verdict && <Tag color={REQUEST_STATUS_META[item.status as MaterialRequestStatus]?.color}>{item.verdict === 'release' ? '放行' : item.verdict === 'reject' ? '拒收' : '让步'}</Tag>}
        </Space>
      ),
    },
  ]

  const stdColumns = [
    { title: '物料代码', dataIndex: 'material_code', width: 120, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
    { title: '物料名称', dataIndex: 'material_name' },
    { title: '供应商代码', dataIndex: 'vendor_code', width: 120, render: (v: string | null) => v || '通用' },
    { title: '版本', dataIndex: 'version', width: 80, render: (v: string | null) => v || '-' },
    {
      title: '操作', key: 'actions', width: 130,
      render: (_: unknown, item: MaterialStandardRow) => (
        <Button size="small" type="link" onClick={() => { setActiveStdId(item.id); loadStdItems(item.id) }}>项目行</Button>
      ),
    },
  ]

  const stdItemColumns = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: '项目名称', dataIndex: 'item_name', width: 160 },
    { title: 'SOP 号', dataIndex: 'sop_no', width: 110, render: (v: string | null) => v || '-' },
    { title: '标准', dataIndex: 'standard_text', render: (v: string | null) => v || '-' },
    { title: '运算符', dataIndex: 'operator', width: 80, render: (v: string | null) => v || '（人工判定）' },
    { title: '下限', dataIndex: 'limit_min', width: 80, render: (v: number | null) => v ?? '-' },
    { title: '上限', dataIndex: 'limit_max', width: 80, render: (v: number | null) => v ?? '-' },
  ]

  return (
    <>
      <Tabs
        items={[
          {
            key: 'requests',
            label: '物料请验',
            children: (
              <>
                <Space wrap style={{ marginBottom: 12 }}>
                  <Input.Search
                    placeholder="进厂批号搜索" allowClear style={{ width: 200 }}
                    value={batchDraft}
                    onChange={(e) => setBatchDraft(e.target.value)}
                    onSearch={(v) => setBatchFilter(v || undefined)}
                  />
                  <Select
                    placeholder="状态筛选" allowClear style={{ width: 140 }}
                    value={statusFilter}
                    onChange={(v) => setStatusFilter(v)}
                    options={Object.keys(REQUEST_STATUS_META).map((s) => ({ label: REQUEST_STATUS_META[s as MaterialRequestStatus].label, value: s }))}
                  />
                  {canManage && (
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => { reqForm.resetFields(); setCreateOpen(true) }}>新建请验单</Button>
                  )}
                </Space>
                <Table rowKey="id" size="small" scroll={{ x: 1150 }} dataSource={data} pagination={{ pageSize: 20 }} columns={requestColumns} />
              </>
            ),
          },
          {
            key: 'standards',
            label: '物料标准库',
            children: (
              <>
                <Space wrap style={{ marginBottom: 12 }}>
                  {canManage && (
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => { stdForm.resetFields(); setStdCreateOpen(true) }}>新建物料标准</Button>
                  )}
                </Space>
                <Table rowKey="id" size="small" scroll={{ x: 700 }} dataSource={stdRows} pagination={false} columns={stdColumns} />
                {activeStdId && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 16 }}>
                      检验项目行
                      {canManage && <Button size="small" type="link" icon={<PlusOutlined />} onClick={() => { stdItemForm.resetFields(); setStdItemOpen(true) }}>添加项目行</Button>}
                    </Typography.Title>
                    <Table rowKey="id" size="small" scroll={{ x: 750 }} dataSource={stdItems} pagination={false} columns={stdItemColumns} />
                  </>
                )}
              </>
            ),
          },
        ]}
      />

      {/* 新建请验弹窗 */}
      <Modal title="新建请验单" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={onCreate} okText="创建" width={480}>
        <Form form={reqForm} layout="vertical">
          <Form.Item name="material_code" label="物料" rules={[{ required: true, message: '请选择物料' }]}>
            <Select showSearch placeholder="选择物料（字典）" options={dictOptions} filterOption={(input, option) => (option?.label as string).toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="vendor_code" label="供应商代码（可选）">
            <Input placeholder="默认取字典供应商" />
          </Form.Item>
          <Form.Item name="inbound_batch_no" label="进厂批号" rules={[{ required: true, message: '请输入进厂批号' }]}>
            <Input placeholder="IN-20261014-01" />
          </Form.Item>
          <Form.Item name="inbound_qty" label="到货数量（瓶/桶）" initialValue={1} rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="inbound_date" label="到货日期（可选）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 取样弹窗 */}
      <Modal title={`取样登记 ${sampleTarget?.request_no ?? ''}`} open={!!sampleTarget} onCancel={() => setSampleTarget(null)} onOk={onSample} okText="登记" width={420}>
        <Form form={sampleForm} layout="vertical">
          <Form.Item name="sampled_qty" label="取样数量" initialValue={1}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="sampled_at" label="取样日期（默认今天）">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 放行弹窗 */}
      <Modal
        title={`放行 ${releaseTarget?.request_no ?? ''}`}
        open={!!releaseTarget}
        onCancel={() => setReleaseTarget(null)}
        onOk={onRelease}
        okText={releaseVerdict === 'release' ? '确认放行' : releaseVerdict === 'reject' ? '确认拒收' : '确认让步接收'}
        okButtonProps={{ danger: releaseVerdict === 'reject' }}
        width={460}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={releaseVerdict}
            onChange={(v) => setReleaseVerdict(v)}
            options={[
              { label: '放行（该批容器全部转合格）', value: 'release' },
              { label: '让步接收（视同合格，需原因）', value: 'concede' },
              { label: '拒收（该批容器全部作废冻结，需原因）', value: 'reject' },
            ]}
          />
          {releaseVerdict !== 'release' && (
            <Input.TextArea rows={2} maxLength={200} value={releaseRemark} onChange={(e) => setReleaseRemark(e.target.value)} placeholder="原因必填" />
          )}
          <Typography.Text type="secondary">放行结论将自动联动该请验单下全部容器状态。</Typography.Text>
        </Space>
      </Modal>

      {/* 新建物料标准弹窗 */}
      <Modal title="新建物料标准" open={stdCreateOpen} onCancel={() => setStdCreateOpen(false)} onOk={onCreateStd} okText="创建" width={440}>
        <Form form={stdForm} layout="vertical">
          <Form.Item name="material_code" label="物料" rules={[{ required: true, message: '请选择物料' }]}>
            <Select showSearch placeholder="选择物料（字典）" options={dictOptions} filterOption={(input, option) => (option?.label as string).toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="vendor_code" label="供应商代码（留空=通用标准）">
            <Input />
          </Form.Item>
          <Form.Item name="version" label="版本号（可选）">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加项目行弹窗 */}
      <Modal title="添加检验项目行" open={stdItemOpen} onCancel={() => setStdItemOpen(false)} onOk={onAddStdItem} okText="添加" width={520}>
        <Form form={stdItemForm} layout="vertical">
          <Form.Item name="item_name" label="项目名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="如 水分" />
          </Form.Item>
          <Form.Item name="sop_no" label="SOP 号（可选）">
            <Input placeholder="如 SOP-M-001" />
          </Form.Item>
          <Form.Item name="standard_text" label="合格标准原文（可选）">
            <Input placeholder="如 ≤3.0%" />
          </Form.Item>
          <Space size={12}>
            <Form.Item name="operator" label="运算符">
              <Select allowClear style={{ width: 100 }} options={['≤', '≥', '<', '>', '范围'].map((o) => ({ value: o, label: o }))} />
            </Form.Item>
            <Form.Item name="limit_min" label="下限">
              <InputNumber style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="limit_max" label="上限">
              <InputNumber style={{ width: 100 }} />
            </Form.Item>
          </Space>
          <Form.Item name="category" label="项目大类（可选）">
            <Input placeholder="如 理化" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

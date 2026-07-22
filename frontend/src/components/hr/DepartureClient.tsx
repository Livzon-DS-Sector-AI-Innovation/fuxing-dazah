'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Input, Tag, Modal, Form, Select, DatePicker, Popconfirm } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  EyeOutlined,
  PlusOutlined,
  DeleteOutlined,
  SendOutlined } from '@ant-design/icons'
import { DepartureRecord } from '@/types/hr'
import { fetchDepartureRecords, fetchDepartments, API_BASE } from '@/lib/api/hr'
import { deleteDepartureRecordAction } from '@/actions/hr'

interface DepartureClientProps {
  initialRecords: DepartureRecord[]
  initialTotal: number
  fetchAction?: typeof fetchDepartureRecords
}

export default function DepartureClient({
  initialRecords,
  initialTotal,
  fetchAction }: DepartureClientProps) {
  const { message } = App.useApp()
  const [records, setRecords] = useState<DepartureRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterOffboardingType, setFilterOffboardingType] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm()
  const [departments, setDepartments] = useState<{value:string,label:string}[]>([])
  const [deptEmployees, setDeptEmployees] = useState<any[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState<DepartureRecord | null>(null)
  const [selectedDept, setSelectedDept] = useState<string>('')
  const [certOpen, setCertOpen] = useState(false)
  const [certRecord, setCertRecord] = useState<DepartureRecord | null>(null)
  const [certEmail, setCertEmail] = useState('')
  const [certSending, setCertSending] = useState(false)

  useEffect(() => {
    fetchDepartments({ page_size: 200 }).then(r => {
      setDepartments((r.data||[]).map((d:any) => ({ value: d.name, label: d.name })))
    })
  }, [])

  const handleDeptChange = async (dept: string) => {
    setSelectedDept(dept)
    createForm.setFieldValue('employee', undefined)
    if (!dept) { setDeptEmployees([]); return }
    try {
      const url = `${API_BASE}/api/v1/hr/employees?department=${encodeURIComponent(dept)}&page=1&page_size=200`
      const res = await fetch(url, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const d = await res.json()
      const list = (d.data||[]).map((e:any) => ({
        value: e.id, label: `${e.employee_number} ${e.name} (${e.position||''})`,
        name: e.name, department: e.department, position: e.position
      }))
      setDeptEmployees(list)
      if (list.length === 0) message.warning(`${dept} 下暂无在职员工`)
    } catch (err: any) { message.error('加载失败: ' + (err.message||'')) }
  }

  const handleCreate = async () => {
    try {
      const vals = await createForm.validateFields()
      setCreateLoading(true)
      const emp = deptEmployees.find((e:any) => e.value === vals.employee)
      const res = await fetch(`${API_BASE}/api/v1/hr/departure-records`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: emp?.name || '', department: selectedDept,
          position: emp?.position || '',
          offboarding_date: vals.offboarding_date?.format('YYYY-MM-DD'),
          offboarding_type: vals.offboarding_type || '辞职',
          reason: vals.reason || '',
        }),
      })
      if (!res.ok) throw new Error('创建失败')
      message.success('离职记录创建成功')
      setCreateOpen(false); createForm.resetFields(); loadData()
    } catch (err: any) { message.error(err.message || '创建失败') }
    finally { setCreateLoading(false) }
  }

  const doFetch = fetchAction || fetchDepartureRecords

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await doFetch({
        department: filterDepartment || undefined,
        offboarding_type: filterOffboardingType || undefined,
        keyword: searchKeyword || undefined,
        page,
        page_size: pageSize })
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [filterDepartment, filterOffboardingType, searchKeyword, page, pageSize, doFetch])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  useEffect(() => {
    loadData()
  }, [filterDepartment, filterOffboardingType, searchKeyword, page, pageSize])

  const handlePreviewCert = async () => {
    if (!certRecord) return
    try {
      const r = await fetch(`${API_BASE}/api/v1/hr/departure-records/${certRecord.id}/preview-certificate`, { method: 'POST', credentials: 'include' })
      if (!r.ok) throw new Error('预览失败')
      const html = await r.text()
      const w = window.open('', '_blank')
      if (w) { w.document.write(html); w.document.close() }
    } catch (err: any) { message.error(err.message || '预览失败') }
  }

  const handleSendCert = async () => {
    if (!certRecord || !certEmail) return
    setCertSending(true)
    try {
      const fd = new FormData()
      fd.append('employee_email', certEmail)
      const res = await fetch(`${API_BASE}/api/v1/hr/departure-records/${certRecord.id}/send-certificate`, { method: 'POST', body: fd, credentials: 'include' })
      if (!res.ok) { const d = await res.json(); throw new Error(d.message || '发送失败') }
      message.success('离职证明已发送')
      setCertOpen(false)
    } catch (err: any) { message.error(err.message || '发送失败') }
    finally { setCertSending(false) }
  }

  const offboardingTypeColorMap: Record<string, string> = {
    '辞职': 'default',
    '辞退': 'error',
    '合同到期': 'warning',
    '退休': 'success',
    '其他': 'processing' }

  const columns: ColumnsType<DepartureRecord> = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100,
      fixed: 'left' },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
      filters: [
        { text: '生产制造部', value: '生产制造部' },
        { text: '质量管理部', value: '质量管理部' },
        { text: '设备动力部', value: '设备动力部' },
        { text: '发酵工程部', value: '发酵工程部' },
        { text: '提炼一部', value: '提炼一部' },
        { text: '提炼二部', value: '提炼二部' },
        { text: '提炼三部', value: '提炼三部' },
        { text: '安全环保部', value: '安全环保部' },
        { text: '采购部', value: '采购部' },
        { text: '人事行政部', value: '人事行政部' },
        { text: '肠激酶车间', value: '肠激酶车间' },
        { text: '财务部', value: '财务部' },
      ],
      onFilter: (value, record: DepartureRecord) => record.department === String(value) },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 120,
      defaultSortOrder: 'descend',
      sorter: (a: DepartureRecord, b: DepartureRecord) =>
        new Date(b.offboarding_date || '').getTime() - new Date(a.offboarding_date || '').getTime() },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 100,
      render: (val: string) => (
        <Tag color={offboardingTypeColorMap[val] || 'default'}>{val || '-'}</Tag>
      ),
      filters: [
        { text: '辞职', value: '辞职' },
        { text: '辞退', value: '辞退' },
        { text: '合同到期', value: '合同到期' },
        { text: '退休', value: '退休' },
        { text: '其他', value: '其他' },
      ],
      onFilter: (value, record: DepartureRecord) => record.offboarding_type === String(value) },
    {
      title: '离职时司龄',
      dataIndex: 'company_tenure_at_leave',
      key: 'company_tenure_at_leave',
      width: 100 },
    {
      title: '入丽珠时间',
      dataIndex: 'livo_entry_date',
      key: 'livo_entry_date',
      width: 120 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 120 },
    {
      title: '离职原因',
      dataIndex: 'offboarding_reason',
      key: 'offboarding_reason',
      width: 160,
      ellipsis: true,
      render: (val: string[]) => val?.join(', ') || '-' },
    {
      title: '操作',
      key: 'action',
      width: 230,
      fixed: 'right',
      render: (_: any, record: DepartureRecord) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => { setDetailRecord(record); setDetailOpen(true) }}
          >
            详情
          </Button>
          <Button type="text" size="small" icon={<SendOutlined />}
            onClick={() => { setCertRecord(record); setCertEmail(''); setCertOpen(true) }}>证明</Button>
          <Popconfirm
            title="确认删除？"
            onConfirm={async () => {
              try {
                await deleteDepartureRecordAction(record.id)
                message.success('已删除')
                loadData()
              } catch (err: any) {
                message.error(err.message || '删除失败')
              }
            }}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          离职台账
        </h1>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); setSelectedDept(''); setDeptEmployees([]); createForm.resetFields() }}>新建离职</Button>
        <Input
          placeholder="搜索姓名/部门/职位"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
        <Input
          placeholder="部门筛选"
          value={filterDepartment}
          onChange={(e) => setFilterDepartment(e.target.value)}
          className="w-40"
          allowClear
        />
        <Input
          placeholder="离职类型筛选"
          value={filterOffboardingType}
          onChange={(e) => setFilterOffboardingType(e.target.value)}
          className="w-40"
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: handlePageChange }}
        scroll={{ x: 1400 }}
        size="small"
      />


      <Modal title="新建离职记录" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)}
        confirmLoading={createLoading} destroyOnHidden width={500}>
        <Form form={createForm} layout="vertical">
          <Form.Item label="选择部门" required>
            <Select placeholder="先选部门" options={departments} value={selectedDept || undefined}
              onChange={(v) => handleDeptChange(v)} allowClear />
          </Form.Item>
          <Form.Item name="employee" label="选择员工" rules={[{ required: true, message: '请选择员工' }]}>
            <Select placeholder="选完部门后选员工" options={deptEmployees} disabled={!selectedDept}
              showSearch filterOption={(input, option) => (option?.label||'').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item name="offboarding_date" label="离职日期" rules={[{ required: true }]}>
            <DatePicker className="w-full" />
          </Form.Item>
          <Form.Item name="offboarding_type" label="离职类型" initialValue="辞职">
            <Select options={[{value:'辞职',label:'辞职'},{value:'辞退',label:'辞退'},{value:'自离',label:'自离'},{value:'其他',label:'其他'}]} />
          </Form.Item>
          <Form.Item name="reason" label="离职原因">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>


      <Modal title="发送离职证明" open={certOpen} onCancel={() => setCertOpen(false)}
        footer={[
          <Button key="preview" onClick={handlePreviewCert}>预览</Button>,
          <Button key="send" type="primary" loading={certSending} onClick={handleSendCert}>发送</Button>,
        ]}
      >
        <div className="space-y-3 py-2">
          <div>收件人：<b>{certRecord?.name}</b>（{certRecord?.department} / {certRecord?.position}）</div>
          <Input placeholder="请输入收件邮箱" value={certEmail}
            onChange={e => setCertEmail(e.target.value)} type="email" />
        </div>
      </Modal>

      <Modal title="离职详情" open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={600}>
        {detailRecord && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {[
                ['姓名', detailRecord.name],
                ['部门', detailRecord.department],
                ['职位', detailRecord.position],
                ['离职日期', detailRecord.offboarding_date],
                ['离职类型', detailRecord.offboarding_type],
                ['离职原因', Array.isArray(detailRecord.offboarding_reason) ? detailRecord.offboarding_reason.join(', ') : (detailRecord.offboarding_reason || '')],
              ].map(([label, val], i) => (
                <tr key={i}>
                  <td style={{ padding: '8px 12px', border: '1px solid #eee', background: '#f5f5f5', fontWeight: 600, width: '30%' }}>{label}</td>
                  <td style={{ padding: '8px 12px', border: '1px solid #eee' }}>{val || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>

    </div>
  )
}

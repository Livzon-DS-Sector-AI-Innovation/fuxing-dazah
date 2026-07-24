'use client'

import { useState, useEffect } from 'react'
import { App, Table, Button, Space, Tag, Input, Select, Modal, Form, DatePicker, Timeline, message } from 'antd'
import { SearchOutlined, EditOutlined, EyeOutlined, SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import { API_BASE } from '@/lib/hr'
import { useHrStore } from '@/stores/hr'

interface EmployeeTableProps {
  employees: Employee[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  onEdit: (employee: Employee) => void
}

const statusColorMap: Record<string, string> = {
  在职: 'success',
  试用期: 'warning',
  离职: 'default',
  待审批: 'processing',
  产假复岗: 'purple' }

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  onEdit }: EmployeeTableProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEmp, setDetailEmp] = useState<Employee | null>(null)
  const { searchKeyword, setSearchKeyword, filterStatus, setFilterStatus } = useHrStore()

  // ─── 异动记录 Modal ───
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferEmp, setTransferEmp] = useState<Employee | null>(null)
  const [transfers, setTransfers] = useState<any[]>([])
  const [transferForm] = Form.useForm()
  const [positionOptions, setPositionOptions] = useState<Record<string, string[]>>({})
  const watchedFromDept = Form.useWatch('from_department', transferForm)
  const watchedToDept = Form.useWatch('to_department', transferForm)

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/positions`, { credentials: 'include' })
      .then(r => r.json()).then(d => {
        const map: Record<string, string[]> = {}
        ;(d.data || []).forEach((p: any) => {
          if (!map[p.department]) map[p.department] = []
          map[p.department].push(p.name)
        })
        setPositionOptions(map)
      }).catch(() => {})
  }, [])

  // 获取某部门下的职位列表
  const getPositions = (dept: string | undefined) => {
    const deptPositions = (dept && positionOptions[dept]) ? positionOptions[dept] : []
    const all = [...deptPositions]
    Object.values(positionOptions).forEach(arr => arr.forEach(p => { if (!all.includes(p)) all.push(p) }))
    return all.map(p => ({ label: p, value: p }))
  }

  const [deptOptions, setDeptOptions] = useState<string[]>([])
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/departments?page_size=200`, { credentials: 'include' })
      .then(r => r.json()).then(d => setDeptOptions((d.data || []).map((x: any) => x.name)))
      .catch(() => {})
  }, [])

  const handleDeptChange = (deptField: string, value: string) => {
    const posField = deptField === 'from_department' ? 'from_position' : 'to_position'
    const currentPos = transferForm.getFieldValue(posField)
    if (currentPos && positionOptions[value] && !positionOptions[value].includes(currentPos)) {
      transferForm.setFieldValue(posField, undefined)
    }
  }

  const loadTransfers = async (employeeId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/transfers?employee_id=${employeeId}&page_size=50`, { credentials: 'include' })
      const d = await res.json()
      setTransfers(d.data || [])
    } catch { setTransfers([]) }
  }

  const handleOpenTransfers = (emp: Employee) => {
    setTransferEmp(emp)
    setTransferOpen(true)
    transferForm.resetFields()
    // 自动填入当前部门和岗位
    transferForm.setFieldsValue({
      from_department: emp.department || undefined,
      from_position: emp.position || undefined,
    })
    loadTransfers(emp.id)
  }

  const handleCreateTransfer = async () => {
    const values = await transferForm.validateFields()
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/transfers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          employee_id: transferEmp!.id,
          transfer_type: values.transfer_type,
          from_department: values.from_department || null,
          to_department: values.to_department || null,
          from_position: values.from_position || null,
          to_position: values.to_position || null,
          effective_date: values.effective_date.format('YYYY-MM-DD'),
          reason: values.reason || null,
        }),
        credentials: 'include',
      })
      if (!res.ok) throw new Error('创建失败')
      message.success('异动记录已添加')
      transferForm.resetFields()
      loadTransfers(transferEmp!.id)
    } catch (err: any) { message.error(err.message || '创建失败') }
  }

  const allColumns: any[] = [
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      width: 110,
      fixed: 'left' as const },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 90,
      fixed: 'left' as const },
    {
      title: '体现部门',
      dataIndex: 'department',
      key: 'department',
      width: 160 },
    {
      title: '实际部门',
      dataIndex: 'actual_department',
      key: 'actual_department',
      width: 140, ellipsis: true,
      render: (v: string) => v || '-' },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '体现岗位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '兼任部门',
      dataIndex: 'concurrent_departments',
      key: 'concurrent_departments',
      width: 130,
      render: (v: string) => v || '-' },
    {
      title: '兼任品种',
      dataIndex: 'variety',
      key: 'variety',
      width: 100,
      render: (v: string) => v || '-' },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 70 },
    {
      title: '年龄',
      dataIndex: 'age',
      key: 'age',
      width: 70 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>{status}</Tag>
      ) },
    {
      title: '入职日期',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 110 },
    {
      title: '籍贯',
      dataIndex: 'native_place',
      key: 'native_place',
      width: 100 },
    {
      title: '政治面貌',
      dataIndex: 'political_status',
      key: 'political_status',
      width: 100 },
    {
      title: '婚姻状况',
      dataIndex: 'marital_status',
      key: 'marital_status',
      width: 100 },
    {
      title: '合同期限',
      dataIndex: 'contract_type',
      key: 'contract_type',
      width: 110 },
    {
      title: '职称类型',
      dataIndex: 'qualification_type',
      key: 'qualification_type',
      width: 100 },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 80 },
    {
      title: '司龄',
      dataIndex: 'company_tenure',
      key: 'company_tenure',
      width: 90 },
    {
      title: '毕业学校',
      dataIndex: 'school',
      key: 'school',
      width: 150 },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120 },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: any, record: Employee) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => { setDetailEmp(record); setDetailOpen(true) }}
          >
            详情
          </Button>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record)}
          >
            编辑
          </Button>
          <Button type="text" size="small" icon={<SwapOutlined />}
            onClick={() => handleOpenTransfers(record)}>
            异动
          </Button>
        </Space>
      ) },
  ]

  // Hide columns where ALL rows have empty values (except key & important columns)
  const alwaysShow = new Set(['action', 'employee_number', 'name', 'department', 'actual_department', 'position', 'concurrent_departments', 'variety'])
  const columns = allColumns.filter(col => {
    if (alwaysShow.has(col.key as string)) return true
    return employees.some((emp: any) => {
      const v = emp[col.dataIndex as string]
      return v !== null && v !== undefined && v !== ''
    })
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <Input.Search
          placeholder="搜索姓名或工号"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          onSearch={(val) => setSearchKeyword(val)}
          className="w-64"
          allowClear
        />
        <Select
          placeholder="状态筛选"
          value={filterStatus || undefined}
          onChange={(value) => setFilterStatus(value || '')}
          allowClear
          className="w-32"
          options={[
            { value: '在职', label: '在职' },
            { value: '试用期', label: '试用期' },
            { value: '离职', label: '离职' },
            { value: '待审批', label: '待审批' },
            { value: '产假复岗', label: '产假复岗' },
          ]}
        />
      </div>

      <Table
        columns={columns}
        dataSource={employees}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: onPageChange }}
        scroll={{ x: 2200 }}
        size="small"
      />

      <Modal title="员工详情" open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={600}>
        {detailEmp && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {[
                ['工号', detailEmp.employee_number], ['姓名', detailEmp.name],
                ['性别', detailEmp.gender], ['体现部门', detailEmp.department],
                ['实际部门', detailEmp.actual_department],
                ['体现岗位', detailEmp.position], ['兼任部门', detailEmp.concurrent_departments],
                ['兼任品种', detailEmp.variety], ['学历', detailEmp.education],
                ['毕业院校', detailEmp.school], ['专业', detailEmp.major],
                ['毕业时间', detailEmp.graduation_date], ['入职日期', detailEmp.hire_date],
                ['职类', detailEmp.job_category], ['级别', detailEmp.level],
                ['域账号', detailEmp.domain_account], ['状态', detailEmp.status],
                ['手机', detailEmp.phone], ['邮箱', detailEmp.email],
                ['身份证号', detailEmp.id_card], ['籍贯', detailEmp.native_place],
                ['政治面貌', detailEmp.political_status], ['婚姻状况', detailEmp.marital_status],
              ].map(([label, val], i) => (
                <tr key={i}>
                  <td style={{ padding: '6px 12px', border: '1px solid #eee', background: '#f5f5f5', fontWeight: 600, width: '30%' }}>{label}</td>
                  <td style={{ padding: '6px 12px', border: '1px solid #eee' }}>{val || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>

      {/* 异动记录 Modal */}
      <Modal
        title={transferEmp ? `${transferEmp.name} — 异动记录` : '异动记录'}
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        footer={null}
        width={700}
      >
        <div className="space-y-4">
          {transfers.length > 0 ? (
            <Timeline
              items={transfers.map((t: any) => ({
                color: t.transfer_type === '晋升' ? 'green' : t.transfer_type === '降职' ? 'red' : 'blue',
                children: (
                  <div>
                    <div className="font-medium">
                      [{t.transfer_type}] {t.from_department || '—'} → {t.to_department || '—'}
                    </div>
                    <div className="text-gray-500 text-sm">
                      {t.from_position || '—'} → {t.to_position || '—'} · {t.effective_date}
                    </div>
                    {t.reason && <div className="text-gray-400 text-xs mt-1">原因：{t.reason}</div>}
                  </div>
                ),
              }))}
            />
          ) : (
            <p className="text-gray-400 text-center py-8">暂无异动记录</p>
          )}

          <div className="border-t pt-4 mt-4">
            <h4 className="font-medium mb-3">新增异动</h4>
            <Form form={transferForm} layout="inline" className="flex flex-wrap gap-2">
              <Form.Item name="transfer_type" label="类型" rules={[{ required: true }]}>
                <Select style={{ width: 110 }} options={[
                  { label: '晋升', value: '晋升' }, { label: '转岗', value: '转岗' },
                  { label: '产假复岗', value: '产假复岗' },
                ]} />
              </Form.Item>
              <Form.Item name="effective_date" label="日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: 130 }} />
              </Form.Item>
              <Form.Item name="from_department" label="原部门">
                <Select showSearch allowClear placeholder="原部门" style={{ width: 120 }}
                  options={deptOptions.map(d => ({ label: d, value: d }))}
                  onChange={(v) => handleDeptChange('from_department', v)} />
              </Form.Item>
              <Form.Item name="to_department" label="新部门">
                <Select showSearch allowClear placeholder="新部门" style={{ width: 120 }}
                  options={deptOptions.map(d => ({ label: d, value: d }))}
                  onChange={(v) => handleDeptChange('to_department', v)} />
              </Form.Item>
              <Form.Item name="from_position" label="原岗位">
                <Select showSearch allowClear placeholder="原岗位" style={{ width: 120 }}
                  options={getPositions(watchedFromDept)} />
              </Form.Item>
              <Form.Item name="to_position" label="新岗位">
                <Select showSearch allowClear placeholder="新岗位" style={{ width: 120 }}
                  options={getPositions(watchedToDept)} />
              </Form.Item>
              <Form.Item name="reason" label="原因"><Input style={{ width: 120 }} /></Form.Item>
              <Form.Item><Button type="primary" onClick={handleCreateTransfer}>添加</Button></Form.Item>
            </Form>
          </div>
        </div>
      </Modal>

    </div>
  )
}

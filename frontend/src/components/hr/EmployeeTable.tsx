'use client'

import { useState, useEffect, useRef } from 'react'
import { App, Table, Button, Space, Tag, Input, Select, Modal, Form, DatePicker, Timeline } from 'antd'
import { AuditOutlined, EditOutlined, EyeOutlined, SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import {
  fetchPositions, fetchDepartmentsAction, fetchTransfers, createTransfer,
  createProbationReview, fetchEmployeesAction,
} from '@/actions/hr'
import { useHrStore } from '@/stores/hr'
import { usePermission } from '@/hooks/usePermission'
import EmployeeInfoModal from './EmployeeInfoModal'

interface EmployeeTableProps {
  employees: Employee[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  onEdit: (employee: Employee) => void
  loading?: boolean
  /** 多维表格同步模式：档案在飞书维护，隐藏会改写档案的编辑/异动入口 */
  syncMode?: boolean
}

const statusColorMap: Record<string, string> = {
  在职: 'success',
  试用期: 'warning',
  离职: 'default',
  待审批: 'processing',
  病假: 'error',
  产假: 'magenta',
  产假复岗: 'purple' }

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  onEdit,
  loading = false,
  syncMode = false }: EmployeeTableProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  // 员工档案基础信息不开放给培训管理员等无档案编辑权限的角色
  const canEditProfile = hasPermission('hr:profile:update')
  const canTransfer = hasPermission('hr:profile:transfer')


  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEmp, setDetailEmp] = useState<Employee | null>(null)
  const { searchKeyword, setSearchKeyword, filterStatus, setFilterStatus } = useHrStore()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ─── 转正评估发起 Modal（行内入口；syncMode 下也开放——写源表不改本地档案） ───
  const [probationOpen, setProbationOpen] = useState(false)
  const [probationEmp, setProbationEmp] = useState<Employee | null>(null)
  const [probationReviewer, setProbationReviewer] = useState<string | undefined>(undefined)
  const [reviewerOptions, setReviewerOptions] = useState<{ value: string; label: string }[]>([])
  const [reviewerSearching, setReviewerSearching] = useState(false)
  const [probationSending, setProbationSending] = useState(false)
  const revSeqRef = useRef(0)

  const searchReviewers = async (keyword: string) => {
    const seq = ++revSeqRef.current
    setReviewerSearching(true)
    try {
      const d = await fetchEmployeesAction({ status: '在职', keyword, page: 1, page_size: 20 })
      if (seq !== revSeqRef.current) return
      const raw = (d as { data?: { items?: unknown[] } | unknown[] })?.data
      const list = (Array.isArray(raw) ? raw : (raw as { items?: unknown[] })?.items || []) as Array<{
        name: string; employee_number?: string; department?: string
      }>
      setReviewerOptions(list.map(e => ({ value: e.name, label: `${e.name}（${e.employee_number || ''} · ${e.department || '-'}）` })))
    } catch { /* 静默 */ }
    finally { if (seq === revSeqRef.current) setReviewerSearching(false) }
  }

  const handleProbationSend = async () => {
    if (!probationEmp || !probationReviewer) { message.warning('请选择评估人'); return }
    setProbationSending(true)
    try {
      const r = await createProbationReview(probationEmp.id, probationReviewer)
      message.success(r.message || '评估卡片已发送')
      setProbationOpen(false); setProbationReviewer(undefined)
    } catch (e) { message.error(e instanceof Error ? e.message : '发起失败') }
    finally { setProbationSending(false) }
  }

  const handleSearchChange = (val: string) => {
    // 防抖：停止输入 300ms 后才触发搜索，避免逐键请求乱序
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchKeyword(val), 300)
  }

  // ─── 异动记录 Modal ───
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferEmp, setTransferEmp] = useState<Employee | null>(null)
  const [transfers, setTransfers] = useState<any[]>([])
  const [transferForm] = Form.useForm()
  const [positionOptions, setPositionOptions] = useState<Record<string, string[]>>({})
  const watchedFromDept = Form.useWatch('from_department', transferForm)
  const watchedToDept = Form.useWatch('to_department', transferForm)

  useEffect(() => {
    fetchPositions()
      .then(list => {
        const map: Record<string, string[]> = {}
        list.forEach((p) => {
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
    fetchDepartmentsAction({ page_size: 200 })
      .then(d => setDeptOptions((d.data || []).map((x: any) => x.name)))
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
      const d = await fetchTransfers({ employee_id: employeeId, page_size: 50 })
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
      await createTransfer({
        employee_id: transferEmp!.id,
        transfer_type: values.transfer_type,
        from_department: values.from_department || null,
        to_department: values.to_department || null,
        from_position: values.from_position || null,
        to_position: values.to_position || null,
        effective_date: values.effective_date.format('YYYY-MM-DD'),
        reason: values.reason || null,
      })
      message.success('异动记录已添加')
      transferForm.resetFields()
      loadTransfers(transferEmp!.id)
    } catch (err: any) { message.error(err.message || '创建失败') }
  }

  // 列集与源数据表（飞书「员工信息表」）保持一致；「状态」为系统按
  // 离职日期/员工性质派生，源表本身无此列。源表没有的字段见详情弹窗「系统附加」。
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
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 160 },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 120 },
    {
      title: '职务',
      dataIndex: 'duty',
      key: 'duty',
      width: 130 },
    {
      title: '职能分类',
      dataIndex: 'job_category',
      key: 'job_category',
      width: 100 },
    {
      title: '职级',
      dataIndex: 'level',
      key: 'level',
      width: 80 },
    {
      title: '岗位职级',
      dataIndex: 'report_grade',
      key: 'report_grade',
      width: 110 },
    {
      title: '员工性质',
      dataIndex: 'status_category',
      key: 'status_category',
      width: 100 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string, record: Employee) => {
        if (status === '试用期' && record.computed_probation_days_left != null) {
          const d = record.computed_probation_days_left
          return (
            <Tag color={d < 0 ? 'error' : statusColorMap[status]}>
              {d < 0 ? `试用期·超${Math.abs(d)}天` : `试用期·剩${d}天`}
            </Tag>
          )
        }
        return <Tag color={statusColorMap[status] || 'default'}>{status}</Tag>
      } },
    {
      title: '域账号',
      dataIndex: 'domain_account',
      key: 'domain_account',
      width: 110 },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 70 },
    {
      title: '年龄',
      dataIndex: 'computed_age',
      key: 'age',
      width: 70,
      render: (_: unknown, record: Employee) => record.computed_age ?? '-',
    },
    {
      title: '出生日期',
      dataIndex: 'birth_year',
      key: 'birth_date',
      width: 110,
      render: (_: unknown, r: Employee) => r.birth_year
        ? `${r.birth_year}-${String(r.birth_month ?? 1).padStart(2, '0')}-${String(r.birth_day ?? 1).padStart(2, '0')}`
        : '-' },
    {
      title: '民族',
      dataIndex: 'ethnicity',
      key: 'ethnicity',
      width: 80 },
    {
      title: '籍贯',
      dataIndex: 'native_place',
      key: 'native_place',
      width: 100 },
    {
      title: '婚姻状况',
      dataIndex: 'marital_status',
      key: 'marital_status',
      width: 90 },
    {
      title: '户口类型',
      dataIndex: 'household_type',
      key: 'household_type',
      width: 90 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '学位类型',
      dataIndex: 'degree_type',
      key: 'degree_type',
      width: 100 },
    {
      title: '学习形式',
      dataIndex: 'classification',
      key: 'classification',
      width: 90 },
    {
      title: '毕业院校',
      dataIndex: 'school',
      key: 'school',
      width: 150 },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120 },
    {
      title: '毕业时间',
      dataIndex: 'graduation_date',
      key: 'graduation_date',
      width: 110 },
    {
      title: '人力资源分析',
      dataIndex: 'hr_analysis',
      key: 'hr_analysis',
      width: 110 },
    {
      title: '联系电话',
      dataIndex: 'phone',
      key: 'phone',
      width: 130 },
    {
      title: '居住地址',
      dataIndex: 'current_address',
      key: 'current_address',
      width: 180, ellipsis: true },
    {
      title: '身份证号',
      dataIndex: 'id_card',
      key: 'id_card',
      width: 170 },
    {
      title: '身份证有效期',
      dataIndex: 'id_card_expiry',
      key: 'id_card_expiry',
      width: 120 },
    {
      title: '紧急联系人-姓名',
      dataIndex: 'emergency_contact_name',
      key: 'emergency_contact_name',
      width: 130 },
    {
      title: '紧急联系人-联系电话',
      dataIndex: 'emergency_contact_phone',
      key: 'emergency_contact_phone',
      width: 150 },
    {
      title: '紧急联系人-关系',
      dataIndex: 'emergency_contact_relation',
      key: 'emergency_contact_relation',
      width: 130 },
    {
      title: '参加工作时间',
      dataIndex: 'work_start_date',
      key: 'work_start_date',
      width: 120 },
    {
      title: '入职日期',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 110 },
    {
      title: '离职日期',
      dataIndex: 'departure_date',
      key: 'departure_date',
      width: 110 },
    {
      title: '离职原因',
      dataIndex: 'departure_reason',
      key: 'departure_reason',
      width: 110 },
    {
      title: '司龄',
      dataIndex: 'computed_tenure',
      key: 'company_tenure',
      width: 100,
      render: (_: unknown, record: Employee) => record.computed_tenure ?? record.company_tenure ?? '-',
    },
    {
      title: '合同开始日期',
      dataIndex: 'contract_start_date',
      key: 'contract_start_date',
      width: 120 },
    {
      title: '合同结束日期',
      dataIndex: 'contract_end_date',
      key: 'contract_end_date',
      width: 120 },
    {
      title: '证书',
      dataIndex: 'certificates',
      key: 'certificates',
      width: 150, ellipsis: true,
      render: (v: string) => v || '-' },
    {
      title: '任命与岗位调动',
      dataIndex: 'transfer_history',
      key: 'transfer_history',
      width: 200, ellipsis: true,
      render: (v: string) => v || '-' },
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
          {canEditProfile && record.status === '试用期' && (
            <Button
              type="text" size="small" icon={<AuditOutlined />}
              onClick={() => { setProbationEmp(record); searchReviewers(''); setProbationOpen(true) }}
            >
              转正
            </Button>
          )}
          {canEditProfile && !syncMode && (
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            >
              编辑
            </Button>
          )}
          {canTransfer && !syncMode && (
            <Button type="text" size="small" icon={<SwapOutlined />}
              onClick={() => handleOpenTransfers(record)}>
              异动
            </Button>
          )}
        </Space>
      ) },
  ]

  // Hide columns where ALL rows have empty values (except key & important columns)
  const alwaysShow = new Set(['action', 'employee_number', 'name', 'department', 'position', 'status'])
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
          onChange={(e) => handleSearchChange(e.target.value)}
          onSearch={(val) => {
            if (debounceRef.current) clearTimeout(debounceRef.current)
            setSearchKeyword(val)
          }}
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
            { value: '病假', label: '病假' },
            { value: '产假', label: '产假' },
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
        scroll={{ x: 4800 }}
        size="small"
      />

      <EmployeeInfoModal employee={detailEmp} open={detailOpen} onClose={() => setDetailOpen(false)} />

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

      {/* 转正评估发起：评估卡片私发部门负责人，结论经 HR 在「转正管理」面板确认生效 */}
      <Modal title={`发起转正评估 — ${probationEmp?.name || ''}`} open={probationOpen}
        onCancel={() => { setProbationOpen(false); setProbationReviewer(undefined) }}
        onOk={handleProbationSend} okText="发送评估卡片" confirmLoading={probationSending}
        okButtonProps={{ disabled: !probationReviewer }}>
        {probationEmp && (
          <div className="text-xs text-gray-500 mb-3">
            {probationEmp.department} · {probationEmp.position} ｜ 入职 {probationEmp.hire_date?.slice(0, 10)}
            {probationEmp.computed_probation_end && ` ｜ 转正到期 ${probationEmp.computed_probation_end.slice(0, 10)}`}
          </div>
        )}
        <Select style={{ width: '100%' }} placeholder="搜索并选择评估人（部门负责人）"
          showSearch filterOption={false} onSearch={searchReviewers}
          notFoundContent={reviewerSearching ? <span style={{ fontSize: 12 }}>搜索中…</span> : null}
          value={probationReviewer} onChange={setProbationReviewer} options={reviewerOptions} />
        <div className="text-xs text-gray-400 mt-3">
          评估表单卡片将私发至负责人飞书（需其登录过系统或在源表有员工账号）；结论提交后由 HR 在档案页「转正管理」确认生效。
        </div>
      </Modal>

    </div>
  )
}

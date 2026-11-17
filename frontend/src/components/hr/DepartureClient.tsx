'use client'

import { useState, useCallback, useEffect } from 'react'
import {
  App, Alert, Button, Table, Space, Input, Tag, Modal, Form, Select,
  DatePicker, Popconfirm, Descriptions, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  EyeOutlined,
  PlusOutlined,
  DeleteOutlined,
  SendOutlined,
  CloudSyncOutlined,
} from '@ant-design/icons'
import { DepartureRecord, DepartureFilterOptions } from '@/types/hr'
import {
  fetchDepartureRecords,
  fetchDepartureFilterOptionsAction,
  fetchDepartmentsAction,
  fetchEmployeesAction,
  createDepartureRecord,
  previewDepartureCertificate,
  sendDepartureCertificate,
  deleteDepartureRecordAction,
  triggerEmployeeSync,
} from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'

const { Text } = Typography

/** 离职台账页的同步状态（服务端注入；绑定离职表后页面转只读展示） */
export interface DepartureSyncInfo {
  departure_table_name: string
  last_sync_at: string | null
}

interface DepartureClientProps {
  initialRecords: DepartureRecord[]
  initialTotal: number
  fetchAction?: typeof fetchDepartureRecords
  /** 绑定飞书离职人员管理表后传入：隐藏本地新建/删除，展示同步横幅 */
  syncInfo?: DepartureSyncInfo
}

function formatSyncTime(iso: string | null): string {
  return iso ? iso.replace('T', ' ') : '从未同步'
}

export default function DepartureClient({
  initialRecords,
  initialTotal,
  fetchAction,
  syncInfo }: DepartureClientProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [records, setRecords] = useState<DepartureRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterOffboardingType, setFilterOffboardingType] = useState('')
  const [filterOptions, setFilterOptions] = useState<DepartureFilterOptions>({})
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
  const [syncing, setSyncing] = useState(false)

  // 同步模式：数据源为飞书离职人员管理表，本地新建/删除无意义（下轮同步会覆盖）
  const syncMode = Boolean(syncInfo)
  const canManage = hasPermission('hr:settings:manage')

  useEffect(() => {
    fetchDepartmentsAction({ page_size: 200 }).then(r => {
      setDepartments((r.data||[]).map((d:any) => ({ value: d.name, label: d.name })))
    })
    // 筛选下拉选项：从台账现有数据聚合（跟随飞书源表，部门与 org 部门表可能不一致）
    fetchDepartureFilterOptionsAction().then(setFilterOptions).catch(() => {})
  }, [])

  const handleDeptChange = async (dept: string) => {
    setSelectedDept(dept)
    createForm.setFieldValue('employee', undefined)
    if (!dept) { setDeptEmployees([]); return }
    try {
      const d = await fetchEmployeesAction({ department: dept, page: 1, page_size: 200 })
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
      await createDepartureRecord({
        name: emp?.name || '', department: selectedDept,
        position: emp?.position || '',
        offboarding_date: vals.offboarding_date?.format('YYYY-MM-DD'),
        offboarding_type: vals.offboarding_type || '辞职',
        reason: vals.reason || '',
      })
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

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await triggerEmployeeSync()
      const dep = res.data?.departures
      if (dep?.error) {
        message.warning(`员工档案已同步，但离职台账拉取失败：${dep.error}`, 10)
      } else if (dep) {
        message.success(`同步完成：离职台账 ${dep.total ?? 0} 行（新增 ${dep.created ?? 0} / 更新 ${dep.updated ?? 0}）`)
      } else {
        message.success('同步完成')
      }
      loadData()
      // 同步可能带来新的部门/离职类型取值，下拉选项一并刷新
      fetchDepartureFilterOptionsAction().then(setFilterOptions).catch(() => {})
    } catch (err: any) {
      message.error(err.message || '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const handlePreviewCert = async () => {
    if (!certRecord) return
    try {
      const html = await previewDepartureCertificate(certRecord.id)
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
      await sendDepartureCertificate(certRecord.id, fd)
      message.success('离职证明已发送')
      setCertOpen(false)
    } catch (err: any) { message.error(err.message || '发送失败') }
    finally { setCertSending(false) }
  }

  const offboardingTypeColorMap: Record<string, string> = {
    '辞职': 'default',
    '辞退': 'error',
    '个人原因': 'default',
    '合同到期': 'warning',
    '退休': 'success',
    '退休返聘到期': 'success',
    '其他': 'processing' }

  // 部门/离职类型筛选已上移到顶部下拉（服务端全量过滤，选项来自 filter-options），
  // 不再用列头筛选（仅过滤当前页，与全量口径冲突）

  const columns: ColumnsType<DepartureRecord> = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 90,
      fixed: 'left' },
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      width: 100,
      render: (v: string) => v ? <Text copyable={Boolean(v)} className="text-xs">{v}</Text> : '-' },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 130 },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      width: 120 },
    {
      title: '职务',
      dataIndex: 'duty',
      key: 'duty',
      width: 100,
      render: (v: string) => v || '-' },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 110,
      defaultSortOrder: 'descend',
      sorter: (a: DepartureRecord, b: DepartureRecord) =>
        new Date(b.offboarding_date || '').getTime() - new Date(a.offboarding_date || '').getTime() },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 110,
      render: (val: string) => (
        <Tag color={offboardingTypeColorMap[val] || 'default'}>{val || '-'}</Tag>
      ) },
    {
      title: '离职时司龄',
      dataIndex: 'company_tenure_at_leave',
      key: 'company_tenure_at_leave',
      width: 100 },
    {
      title: '入丽珠时间',
      dataIndex: 'livo_entry_date',
      key: 'livo_entry_date',
      width: 110 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '统计类别',
      dataIndex: 'status_category',
      key: 'status_category',
      width: 100,
      render: (v: string) => v || '-' },
    {
      title: '操作',
      key: 'action',
      width: 180,
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
          {!syncMode && (
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
          )}
        </Space>
      ) },
  ]

  const detailItem = (label: string, value: unknown) => (
    { key: label, label, children: (value === null || value === undefined || value === '') ? '-' : String(value) }
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          离职台账
        </h1>
      </div>

      {syncMode && (
        <Alert
          type="info"
          showIcon
          icon={<CloudSyncOutlined />}
          title={`数据来源：飞书「${syncInfo!.departure_table_name}」单向同步（员工档案同步顺带拉取，每天 02:00 自动对账）`}
          description={`上次同步：${formatSyncTime(syncInfo!.last_sync_at)}；增删改请在飞书表中操作`}
          action={canManage ? (
            <Button size="small" icon={<CloudSyncOutlined />} loading={syncing} onClick={handleSync}>
              立即同步
            </Button>
          ) : undefined}
        />
      )}

      <div className="flex flex-wrap gap-3 items-center">
        {!syncMode && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); setSelectedDept(''); setDeptEmployees([]); createForm.resetFields() }}>新建离职</Button>
        )}
        <Input
          placeholder="搜索姓名/部门/职位"
          value={searchKeyword}
          onChange={(e) => { setSearchKeyword(e.target.value); setPage(1) }}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
        <Select
          placeholder="部门筛选"
          value={filterDepartment || undefined}
          onChange={(v) => { setFilterDepartment(v || ''); setPage(1) }}
          showSearch
          allowClear
          optionFilterProp="label"
          className="w-44"
          options={filterOptions.departments?.map((d) => ({ value: d, label: d }))}
        />
        <Select
          placeholder="离职类型筛选"
          value={filterOffboardingType || undefined}
          onChange={(v) => { setFilterOffboardingType(v || ''); setPage(1) }}
          allowClear
          className="w-36"
          options={filterOptions.offboarding_types?.map((t) => ({ value: t, label: t }))}
        />
      </div>

      <Table className="table-lg"
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

      <Modal title={`离职详情${detailRecord?.name ? ` — ${detailRecord.name}` : ''}`}
        open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={720}>
        {detailRecord && (
          <div className="space-y-4">
            <Descriptions title="基本信息" size="small" bordered column={2}
              items={[
                detailItem('工号', detailRecord.employee_number),
                detailItem('姓名', detailRecord.name),
                detailItem('部门', detailRecord.department),
                detailItem('岗位', detailRecord.position),
                detailItem('职务', detailRecord.duty),
                detailItem('职级', [detailRecord.rank, detailRecord.rank_category].filter(Boolean).join(' / ')),
                detailItem('性别', detailRecord.gender),
                detailItem('员工性质', detailRecord.employee_category),
                detailItem('统计类别', detailRecord.status_category),
              ]} />
            <Descriptions title="日期与司龄" size="small" bordered column={2}
              items={[
                detailItem('入职日期', detailRecord.livo_entry_date),
                detailItem('离职日期', detailRecord.offboarding_date),
                detailItem('参加工作时间', detailRecord.work_start_date),
                detailItem('离职时司龄', detailRecord.company_tenure_at_leave),
                detailItem('合同期限', detailRecord.contract_type),
                detailItem('合同起止', [
                  detailRecord.contract_start_date, detailRecord.contract_end_date,
                ].filter(Boolean).join(' ~ ')),
              ]} />
            <Descriptions title="离职信息" size="small" bordered column={2}
              items={[
                detailItem('离职类型', detailRecord.offboarding_type),
                detailItem('离职原因', Array.isArray(detailRecord.offboarding_reason) ? detailRecord.offboarding_reason.join('、') : detailRecord.offboarding_reason),
                detailItem('任命与岗位调动', detailRecord.transfer_history),
                detailItem('证书', detailRecord.certificates),
              ]} />
            <Descriptions title="学历" size="small" bordered column={2}
              items={[
                detailItem('学历', detailRecord.education),
                detailItem('学位类型', detailRecord.degree_type),
                detailItem('毕业院校', detailRecord.school),
                detailItem('专业', detailRecord.major),
                detailItem('全日制', detailRecord.classification),
              ]} />
            <Descriptions title="个人与联系（敏感字段按权限脱敏）" size="small" bordered column={2}
              items={[
                detailItem('身份证号', detailRecord.id_card),
                detailItem('身份证有效期', detailRecord.id_card_expiry),
                detailItem('籍贯', detailRecord.native_place),
                detailItem('民族', detailRecord.ethnicity),
                detailItem('户口类型', detailRecord.household_type),
                detailItem('婚姻状况', detailRecord.marital_status),
                detailItem('政治面貌', detailRecord.political_status),
                detailItem('居住地址', detailRecord.residence_address),
                detailItem('联系电话', detailRecord.phone),
                detailItem('银行卡号', detailRecord.bank_account),
                detailItem('紧急联系人', [
                  detailRecord.emergency_contact_name,
                  detailRecord.emergency_contact_relation,
                  detailRecord.emergency_contact_phone,
                ].filter(Boolean).join(' / ')),
              ]} />
          </div>
        )}
      </Modal>

    </div>
  )
}

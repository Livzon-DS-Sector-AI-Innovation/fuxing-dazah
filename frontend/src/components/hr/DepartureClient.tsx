'use client'

import styles from "./lifecycleTable.module.css"
import { useState, useCallback, useEffect, useRef } from 'react'
import {
  App, Button, Table, Space, Input, Tag, Modal, Form, Select, Tooltip,
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
  ImportOutlined,
} from '@ant-design/icons'
import { DepartureRecord, DepartureFilterOptions } from '@/types/hr'
import { DEPARTURE_TYPE_OPTIONS, DEPARTURE_TYPE_TAG_COLORS } from '@/lib/hr'
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
  exportDepartureRecords,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { usePermission } from '@/hooks/usePermission'
import { useDebouncedCallback } from '@/hooks/hr'
import { LedgerImportModal } from '@/components/hr'
import PageHeader from './PageHeader'

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
  /** 绑定飞书离职人员管理表后传入：隐藏本地新建/删除，展示立即同步入口 */
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
  // 输入框即时回显；防抖 300ms 后才写入 searchKeyword 触发查询（此前每敲一个字发一次请求）
  const [keywordInput, setKeywordInput] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterOffboardingType, setFilterOffboardingType] = useState('')
  const [filterOptions, setFilterOptions] = useState<DepartureFilterOptions>({})
  // 服务端排序：分页在服务端，前端 sorter 只会重排当前页 20 条（此前即如此，升降序结果不对）
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend'>('descend')
  const loadSeq = useRef(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const [createForm] = Form.useForm()
  const [departments, setDepartments] = useState<{value:string,label:string}[]>([])
  const [deptEmployees, setDeptEmployees] = useState<any[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState<DepartureRecord | null>(null)
  const [exporting, setExporting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedDept, setSelectedDept] = useState<string>('')
  const [certOpen, setCertOpen] = useState(false)
  const [certRecord, setCertRecord] = useState<DepartureRecord | null>(null)
  const [certEmail, setCertEmail] = useState('')
  const [certSending, setCertSending] = useState(false)
  const [syncing, setSyncing] = useState(false)

  // 同步模式：数据源为飞书离职人员管理表，本地新建/删除无意义（下轮同步会覆盖）
  const syncMode = Boolean(syncInfo)
  const canManage = hasPermission('hr:settings:manage')
  const canImport = hasPermission('hr:departure:manage')

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

  const { run: debouncedSetKeyword, cancel: cancelKeywordDebounce } = useDebouncedCallback((val: string) => {
    setPage(1)
    setSearchKeyword(val)
  }, 300)

  const commitKeyword = (val: string) => {
    cancelKeywordDebounce()
    setPage(1)
    setSearchKeyword(val.trim())
  }

  const loadData = useCallback(async () => {
    // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      const res = await doFetch({
        department: filterDepartment || undefined,
        offboarding_type: filterOffboardingType || undefined,
        keyword: searchKeyword || undefined,
        sort_by: 'offboarding_date',
        sort_order: sortOrder === 'ascend' ? 'asc' : 'desc',
        page,
        page_size: pageSize })
      if (seq !== loadSeq.current) return
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      if (seq === loadSeq.current) message.error(err.message || '加载数据失败')
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [filterDepartment, filterOffboardingType, searchKeyword, sortOrder, page, pageSize, doFetch, message])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  useEffect(() => {
    loadData()
  }, [filterDepartment, filterOffboardingType, searchKeyword, sortOrder, page, pageSize])

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
    // 先同步开窗再取数：await 之后再 window.open 会被浏览器当作非用户手势触发而拦截
    const w = window.open('', '_blank')
    if (!w) { message.warning('浏览器拦截了预览窗口，请允许本站弹出窗口后重试'); return }
    try {
      const html = await previewDepartureCertificate(certRecord.id)
      w.document.write(html); w.document.close()
    } catch (err: any) {
      w.close()
      message.error(err.message || '预览失败')
    }
  }

  const handleSendCert = async () => {
    if (!certRecord || !certEmail) return
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(certEmail.trim())) {
      message.warning('请输入正确的收件邮箱地址')
      return
    }
    setCertSending(true)
    try {
      const fd = new FormData()
      fd.append('employee_email', certEmail.trim())
      await sendDepartureCertificate(certRecord.id, fd)
      message.success('离职证明已发送')
      setCertOpen(false)
    } catch (err: any) { message.error(err.message || '发送失败') }
    finally { setCertSending(false) }
  }

  // 离职类型色：统一口径（此前表单 4 项/颜色 7 项两套，选「自离」曾落到无色 Tag）
  const offboardingTypeColorMap = DEPARTURE_TYPE_TAG_COLORS

  // 导出与列表筛选同口径（部门/离职类型/关键词）
  const handleExport = async () => {
    setExporting(true)
    try {
      const r = await exportDepartureRecords({
        department: filterDepartment || undefined,
        offboarding_type: filterOffboardingType || undefined,
        keyword: searchKeyword || undefined,
      })
      downloadBase64File(r.base64, r.filename)
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setExporting(false) }
  }

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
      // 9 位工号 + 复制图标需要 130px，此前 100px 会让图标折到第二行、行高参差
      width: 130,
      render: (v: string) => v ? <Text copyable={Boolean(v)} className="text-xs">{v}</Text> : '-' },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      // 150px 容纳「质量控制部（QA部）」这类长部门名，避免折行导致行高参差
      width: 150 },
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
      sortOrder,
      sorter: true },
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
      {/* 绑定飞书离职表后把数据来源写进页头描述（与员工档案页同款），不必再把长说明塞在同步按钮的提示里 */}
      <PageHeader
        title="离职台账"
        description={syncMode
          ? `数据来源：飞书「${syncInfo!.departure_table_name}」单向同步 · 只读展示 · 每小时自动对账 · 上次同步：${formatSyncTime(syncInfo!.last_sync_at)}`
          : undefined}
      />

      <div className="flex flex-wrap gap-3 items-center">
        {!syncMode && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); setSelectedDept(''); setDeptEmployees([]); createForm.resetFields() }}>新建离职</Button>
        )}
        {/* 导入是写操作，按离职台账写权限显隐（只读用户点了只会得到 403） */}
        {!syncMode && canImport && (
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入</Button>
        )}
        <Input
          placeholder="搜索姓名/部门/职位"
          value={keywordInput}
          onChange={(e) => { setKeywordInput(e.target.value); debouncedSetKeyword(e.target.value.trim()) }}
          onPressEnter={(e) => commitKeyword((e.target as HTMLInputElement).value)}
          prefix={<SearchOutlined />}
          // antd 输入框自带 width:100%，Tailwind 的 w-64 会被覆盖成整行宽，宽度须走 style
          style={{ width: 240 }}
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
        <Tooltip title="按当前筛选（部门/离职类型/关键词）导出全部匹配记录">
          <Button loading={exporting} onClick={handleExport} className="ml-auto">导出Excel</Button>
        </Tooltip>
        {syncMode && canManage && (
            <Tooltip title="数据来自飞书表的单向同步：增删改请在飞书表中操作，这里只读">
              <Button icon={<CloudSyncOutlined />} loading={syncing} onClick={handleSync}>立即同步</Button>
            </Tooltip>
        )}
      </div>

      <Table className={styles.tableLg}
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        // 排序循环须为「降序→升序→取消」：antd 默认是升→降→取消，从默认的降序点一下会落到「取消」，
        // 被下面的兜底映射回降序后状态就永远推进不到升序
        sortDirections={['descend', 'ascend']}
        onChange={(_pagination, _filters, sorter) => {
          // 离职日期列排序：交给服务端（取消排序时回到默认的倒序）
          const order = (Array.isArray(sorter) ? sorter[0] : sorter)?.order
          setSortOrder(order === 'ascend' ? 'ascend' : 'descend')
          setPage(1)
        }}
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
            <Select options={DEPARTURE_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))} />
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

      <LedgerImportModal
        open={importOpen}
        ledger="departure"
        label="离职台账"
        onClose={() => setImportOpen(false)}
        onSuccess={loadData}
      />

    </div>
  )
}

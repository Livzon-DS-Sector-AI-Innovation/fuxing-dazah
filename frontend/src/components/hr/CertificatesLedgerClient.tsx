'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Select, Spin, Table, Tabs, Tag, Tooltip } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  CERTIFICATE_CATEGORY_LABELS,
  type CertificateAccessLog,
  type CertificateCategory,
  type CertificateRequirement,
  type CertificateUploadInput,
  type EmployeeCertificate,
  type MissingCertificateItem,
} from '@/types/hr'
import {
  addCertificateRequirement,
  deleteCertificateRequirement,
  exportMissingCertificates,
  fetchCertificateAccessLogs,
  fetchCertificateRequirements,
  fetchCertificatesLedger,
  fetchMissingCertificates,
  updateEmployeeCertificate,
} from '@/actions/hr'
import { fetchEmployeeFilterOptionsAction } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { usePermission } from '@/hooks/usePermission'
import PageHeader from './PageHeader'

const CATEGORY_OPTIONS = (Object.entries(CERTIFICATE_CATEGORY_LABELS) as [CertificateCategory, string][])
  .map(([value, label]) => ({ value, label }))

const ACTION_LABELS: Record<string, string> = {
  certificate_view: '预览',
  certificate_download: '下载',
  certificate_upload: '上传',
  certificate_update: '更正',
  certificate_delete: '删除',
  certificate_view_self: '本人预览（机器人）',
}

/** 缺件清单按员工汇总：后端按「员工×类别」逐行返回，页面上一人一行更便于催收 */
interface MissingGroup {
  employee_id: string
  employee_name: string
  employee_number: string
  department: string
  is_key_position: boolean
  missing: MissingCertificateItem[]
}

/** 证件资料库台账：检索 / 缺件清单（HR 催收）/ 调阅记录（审计）/ 应交配置 */
export default function CertificatesLedgerClient() {
  const { message: msg } = App.useApp()
  const router = useRouter()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:certificate:manage')
  const canAudit = hasPermission('hr:certificate:audit')

  const [activeTab, setActiveTab] = useState('ledger')
  // 各列表的请求序号：慢响应回来时若已有更新的查询，丢弃旧结果
  const seqRef = useRef({ ledger: 0, missing: 0, logs: 0 })

  // ── 台账 ──
  const [ledger, setLedger] = useState<EmployeeCertificate[]>([])
  const [ledgerTotal, setLedgerTotal] = useState(0)
  const [ledgerPage, setLedgerPage] = useState(1)
  const [ledgerLoading, setLedgerLoading] = useState(true)
  const [deptOptions, setDeptOptions] = useState<string[]>([])
  const [filters, setFilters] = useState<{ department?: string; category?: string; keyword?: string }>({})

  // ── 缺件 ──
  const [missing, setMissing] = useState<MissingCertificateItem[]>([])
  const [missingLoading, setMissingLoading] = useState(false)
  const [missingLoaded, setMissingLoaded] = useState(false)
  const [missingDept, setMissingDept] = useState<string | undefined>()
  const [missingKeyword, setMissingKeyword] = useState('')
  const [exportingMissing, setExportingMissing] = useState(false)

  // ── 调阅记录 ──
  const [logs, setLogs] = useState<CertificateAccessLog[]>([])
  const [logTotal, setLogTotal] = useState(0)
  const [logPage, setLogPage] = useState(1)
  const [logLoading, setLogLoading] = useState(false)

  // ── 应交配置 ──
  const [reqs, setReqs] = useState<CertificateRequirement[]>([])
  const [reqLoading, setReqLoading] = useState(false)
  const [reqDraft, setReqDraft] = useState<{ category?: CertificateCategory; applies_to?: 'all' | 'key_position' }>({})

  const loadLedger = useCallback(async (page = 1, f = filters) => {
    const seq = ++seqRef.current.ledger
    setLedgerLoading(true)
    try {
      const r = await fetchCertificatesLedger({ ...f, page, page_size: 20 })
      if (seq !== seqRef.current.ledger) return
      setLedger(r.data || [])
      setLedgerTotal(r.meta?.total ?? 0)
      setLedgerPage(page)
    } catch (e) {
      if (seq === seqRef.current.ledger) msg.error(e instanceof Error ? e.message : '加载台账失败')
    } finally { if (seq === seqRef.current.ledger) setLedgerLoading(false) }
  }, [filters, msg])

  const loadMissing = useCallback(async (department?: string) => {
    const seq = ++seqRef.current.missing
    setMissingLoading(true)
    try {
      const r = await fetchMissingCertificates(department)
      if (seq !== seqRef.current.missing) return
      setMissing(r.data || [])
      setMissingLoaded(true)
    } catch (e) {
      if (seq === seqRef.current.missing) msg.error(e instanceof Error ? e.message : '加载缺件清单失败')
    } finally { if (seq === seqRef.current.missing) setMissingLoading(false) }
  }, [msg])

  const loadLogs = useCallback(async (page = 1) => {
    const seq = ++seqRef.current.logs
    setLogLoading(true)
    try {
      const r = await fetchCertificateAccessLogs({ page, page_size: 20 })
      if (seq !== seqRef.current.logs) return
      setLogs(r.data || [])
      setLogTotal(r.meta?.total ?? 0)
      setLogPage(page)
    } catch (e) {
      if (seq === seqRef.current.logs) msg.error(e instanceof Error ? e.message : '加载调阅记录失败')
    } finally { if (seq === seqRef.current.logs) setLogLoading(false) }
  }, [msg])

  const loadReqs = useCallback(async () => {
    setReqLoading(true)
    try {
      const r = await fetchCertificateRequirements()
      setReqs(r.data || [])
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '加载应交配置失败')
    } finally { setReqLoading(false) }
  }, [msg])

  useEffect(() => {
    void loadLedger()
    fetchEmployeeFilterOptionsAction()
      .then(o => setDeptOptions((o.department as string[] | undefined) || []))
      .catch(() => setDeptOptions([]))
  }, [loadLedger])

  const missingGroups = useMemo(() => {
    const map = new Map<string, MissingGroup>()
    for (const m of missing) {
      let g = map.get(m.employee_id)
      if (!g) {
        g = {
          employee_id: m.employee_id,
          employee_name: m.employee_name ?? '',
          employee_number: m.employee_number ?? '',
          department: m.department ?? '',
          is_key_position: !!m.is_key_position,
          missing: [],
        }
        map.set(m.employee_id, g)
      }
      g.missing.push(m)
    }
    return [...map.values()]
  }, [missing])

  // 关键词只过滤已加载的全量清单（纯前端），页签上的人数始终是全量口径
  const visibleGroups = useMemo(() => {
    const kw = missingKeyword.trim()
    if (!kw) return missingGroups
    return missingGroups.filter(g =>
      g.employee_name.includes(kw) || g.employee_number.includes(kw) || g.department.includes(kw))
  }, [missingGroups, missingKeyword])

  const onTabChange = (key: string) => {
    setActiveTab(key)
    if (key === 'missing' && !missingLoaded) void loadMissing(missingDept)
    if (key === 'logs' && logs.length === 0) void loadLogs()
    if (key === 'reqs' && reqs.length === 0) void loadReqs()
  }

  const handleExportMissing = async () => {
    setExportingMissing(true)
    try {
      const r = await exportMissingCertificates(missingDept)
      downloadBase64File(r.base64, r.filename || '证件缺件清单.xlsx')
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '导出失败')
    } finally { setExportingMissing(false) }
  }

  // 更正证件名称/证号：表单弹窗（此前连用两个浏览器原生 prompt，看不到当前值，第二步取消后第一步也已生效）
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<EmployeeCertificate | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editForm] = Form.useForm()

  const openEdit = (cert: EmployeeCertificate) => {
    setEditing(cert)
    editForm.setFieldsValue({ certificate_name: cert.certificate_name ?? '', certificate_no: '' })
    setEditOpen(true)
  }

  const handleEditSave = async () => {
    if (!editing) return
    let v: { certificate_name?: string; certificate_no?: string }
    try { v = await editForm.validateFields() } catch { return }
    setEditSaving(true)
    try {
      await updateEmployeeCertificate(editing.id, {
        certificate_name: v.certificate_name?.trim(),
        // 列表里的证号是脱敏值，不回填；留空=保持不变
        certificate_no: v.certificate_no?.trim() || undefined,
      } as unknown as Partial<CertificateUploadInput>)
      msg.success('已更正')
      setEditOpen(false)
      void loadLedger(ledgerPage)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '更正失败')
    } finally { setEditSaving(false) }
  }

  const deptSelectOptions = deptOptions.map(d => ({ value: d, label: d }))

  return (
    <div className="space-y-4">
      <PageHeader title="证件资料库" description="员工电子证件集中归档：按人建档、版本可溯、缺件催收、调阅留痕" />

      <Tabs activeKey={activeTab} onChange={onTabChange} items={[
        {
          key: 'ledger',
          label: `证件台账（${ledgerTotal}）`,
          children: (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <Select allowClear placeholder="部门" style={{ minWidth: 160 }} showSearch
                  options={deptSelectOptions}
                  onChange={v => { const f = { ...filters, department: v }; setFilters(f); void loadLedger(1, f) }} />
                <Select allowClear placeholder="证件类别" style={{ minWidth: 150 }}
                  options={CATEGORY_OPTIONS}
                  onChange={v => { const f = { ...filters, category: v }; setFilters(f); void loadLedger(1, f) }} />
                <Input.Search allowClear placeholder="姓名 / 工号" style={{ width: 220 }}
                  onSearch={v => { const f = { ...filters, keyword: v.trim() }; setFilters(f); void loadLedger(1, f) }} />
                <Tooltip title="刷新">
                  <Button aria-label="刷新证件台账" icon={<ReloadOutlined />} onClick={() => void loadLedger(ledgerPage)} />
                </Tooltip>
              </div>
              <Table size="small" rowKey="id" loading={ledgerLoading} dataSource={ledger}
                pagination={{ current: ledgerPage, total: ledgerTotal, pageSize: 20, showSizeChanger: false,
                  showTotal: (t) => `共 ${t} 条`, onChange: p => void loadLedger(p) }}
                locale={{ emptyText: <Empty description="暂无证件记录" className="py-6" /> }}
                columns={[
                  { title: '员工', width: 150, render: (_: unknown, r: EmployeeCertificate) => (
                    <Link href={`/hr/profile/${r.employee_id}`} className="text-[var(--color-anchor)] hover:underline">
                      {r.employee_name}
                    </Link>
                  ) },
                  { title: '工号', dataIndex: 'employee_number', width: 100, render: (v: string) => v || '-' },
                  { title: '部门', dataIndex: 'department', width: 120, ellipsis: true },
                  { title: '证件类别', dataIndex: 'category', width: 130,
                    render: (v: CertificateCategory) => CERTIFICATE_CATEGORY_LABELS[v] || v },
                  { title: '证件名称', dataIndex: 'certificate_name', ellipsis: true, render: (v: string | null) => v || '-' },
                  { title: '证号（脱敏）', dataIndex: 'certificate_no', width: 130,
                    render: (v: string | null) => v ? <span className="font-mono text-xs">{v}</span> : '-' },
                  { title: '发证日期', dataIndex: 'issue_date', width: 110, render: (v: string | null) => v || '-' },
                  { title: '有效期', dataIndex: 'expiry_date', width: 150,
                    render: (_: unknown, r: EmployeeCertificate) => r.is_permanent ? <Tag color="green">长期有效</Tag> : (r.expiry_date || '-') },
                  { title: '版本', dataIndex: 'version_no', width: 70, render: (v: number) => `v${v}` },
                  ...(canManage ? [{
                    title: '操作', width: 80, render: (_: unknown, r: EmployeeCertificate) => (
                      <Button size="small" type="link" onClick={() => openEdit(r)}>更正</Button>
                    ),
                  }] : []),
                ]} />
            </div>
          ),
        },
        {
          key: 'missing',
          label: missingLoaded ? `缺件清单（${missingGroups.length} 人）` : '缺件清单',
          children: (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <Select allowClear placeholder="按部门过滤" style={{ minWidth: 180 }} showSearch value={missingDept}
                  options={deptSelectOptions}
                  onChange={v => { setMissingDept(v); void loadMissing(v) }} />
                <Input allowClear placeholder="搜索姓名 / 工号 / 部门" style={{ width: 220 }} value={missingKeyword}
                  onChange={e => setMissingKeyword(e.target.value)} />
                <Tooltip title={missingDept ? '按当前部门筛选导出全部缺件人员' : '导出全部缺件人员'}>
                  <Button icon={<DownloadOutlined />} loading={exportingMissing} onClick={() => void handleExportMissing()}>
                    导出Excel
                  </Button>
                </Tooltip>
                <Tooltip title="刷新">
                  <Button aria-label="刷新缺件清单" icon={<ReloadOutlined />} onClick={() => void loadMissing(missingDept)} />
                </Tooltip>
                <span className="text-xs text-[var(--color-steel)]">按人汇总；应交口径按一般/重点岗位配置计算，供 HR 催收</span>
              </div>
              <Table size="small" rowKey="employee_id" loading={missingLoading} dataSource={visibleGroups}
                pagination={{ pageSize: 50, showSizeChanger: false, showTotal: (t) => `共 ${t} 人缺件` }}
                locale={{ emptyText: <Empty description={missingKeyword.trim() ? '没有匹配的人员' : '应交证件齐全'} className="py-6" /> }}
                columns={[
                  { title: '员工', width: 120, render: (_: unknown, g: MissingGroup) => (
                    <Link href={`/hr/profile/${g.employee_id}`} className="text-[var(--color-anchor)] hover:underline">{g.employee_name}</Link>
                  ) },
                  { title: '工号', dataIndex: 'employee_number', width: 100 },
                  { title: '部门', dataIndex: 'department', width: 150, ellipsis: true },
                  { title: '重点岗位', dataIndex: 'is_key_position', width: 90,
                    render: (v: boolean) => v ? <Tag color="purple">是</Tag> : '否' },
                  { title: '缺件', key: 'missing',
                    render: (_: unknown, g: MissingGroup) => (
                      <>
                        {g.missing.map(m => (
                          <Tag key={m.category} color="orange" className="mr-1">{m.category_label}</Tag>
                        ))}
                      </>
                    ) },
                  { title: '操作', key: 'action', width: 90,
                    render: (_: unknown, g: MissingGroup) => (
                      <Button size="small" type="link" onClick={() => router.push(`/hr/profile/${g.employee_id}`)}>去补交</Button>
                    ) },
                ]} />
            </div>
          ),
        },
        ...(canAudit ? [{
          key: 'logs',
          label: '调阅记录',
          children: (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <Tooltip title="刷新">
                  <Button aria-label="刷新调阅记录" icon={<ReloadOutlined />} onClick={() => void loadLogs(logPage)} />
                </Tooltip>
              </div>
              <Table size="small" rowKey="id" loading={logLoading} dataSource={logs}
                pagination={{ current: logPage, total: logTotal, pageSize: 20, showSizeChanger: false,
                  showTotal: (t) => `共 ${t} 条`, onChange: p => void loadLogs(p) }}
                locale={{ emptyText: <Empty description="暂无调阅记录" className="py-6" /> }}
                columns={[
                  { title: '时间', dataIndex: 'created_at', width: 170,
                    render: (v: string | null) => v?.replace('T', ' ').slice(0, 19) || '-' },
                  { title: '操作', dataIndex: 'action', width: 150,
                    render: (v: string) => ACTION_LABELS[v] || v },
                  { title: '员工', dataIndex: 'employee_name', width: 110 },
                  { title: '证件类别', dataIndex: 'category', width: 130,
                    render: (v: string | null) => v ? (CERTIFICATE_CATEGORY_LABELS[v as CertificateCategory] || v) : '-' },
                  { title: '版本', dataIndex: 'version_no', width: 70, render: (v: number | null) => v != null ? `v${v}` : '-' },
                  { title: '操作人ID', dataIndex: 'user_id', ellipsis: true, render: (v: string | null) => v || '机器人通道' },
                ]} />
            </div>
          ),
        }] : []),
        ...(canManage ? [{
          key: 'reqs',
          label: '应交配置',
          children: (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <Select placeholder="证件类别" style={{ minWidth: 160 }} value={reqDraft.category}
                  options={CATEGORY_OPTIONS} onChange={v => setReqDraft(p => ({ ...p, category: v }))} />
                <Select placeholder="适用范围" style={{ minWidth: 150 }} value={reqDraft.applies_to}
                  options={[
                    { value: 'all', label: '全员必交' },
                    { value: 'key_position', label: '仅重点岗位追加' },
                  ]}
                  onChange={v => setReqDraft(p => ({ ...p, applies_to: v }))} />
                <Button type="primary" size="small" disabled={!reqDraft.category || !reqDraft.applies_to}
                  onClick={async () => {
                    try {
                      await addCertificateRequirement(reqDraft.category!, reqDraft.applies_to!)
                      msg.success('已新增')
                      setReqDraft({})
                      void loadReqs()
                    } catch (e) { msg.error(e instanceof Error ? e.message : '新增失败') }
                  }}>
                  新增
                </Button>
                <Tooltip title="刷新">
                  <Button aria-label="刷新应交配置" icon={<ReloadOutlined />} onClick={() => void loadReqs()} />
                </Tooltip>
              </div>
              <div className="text-xs text-[var(--color-steel)] mb-2">
                缺件口径 =「全员必交」清单 ∪（重点岗位员工追加「仅重点岗位」清单）− 已归档证件。
              </div>
              {reqLoading ? <div className="text-center py-8"><Spin /></div> : (
                <Table size="small" rowKey="id" dataSource={reqs} pagination={false}
                  locale={{ emptyText: <Empty description="暂无配置" className="py-6" /> }}
                  columns={[
                    { title: '证件类别', dataIndex: 'category', width: 160,
                      render: (v: CertificateCategory) => CERTIFICATE_CATEGORY_LABELS[v] || v },
                    { title: '适用范围', dataIndex: 'applies_to', width: 180,
                      render: (v: string) => v === 'all' ? <Tag>全员必交</Tag> : <Tag color="purple">仅重点岗位追加</Tag> },
                    { title: '操作', width: 80, render: (_: unknown, r: CertificateRequirement) => (
                      <Popconfirm title="删除该应交配置？" okText="删除" okButtonProps={{ danger: true }} onConfirm={async () => {
                        try {
                          await deleteCertificateRequirement(r.id)
                          msg.success('已删除')
                          void loadReqs()
                        } catch (e) { msg.error(e instanceof Error ? e.message : '删除失败') }
                      }}>
                        <Button size="small" type="link" danger>删除</Button>
                      </Popconfirm>
                    ) },
                  ]} />
              )}
            </div>
          ),
        }] : []),
      ]} />

      <Modal
        title={`更正证件 — ${editing ? (CERTIFICATE_CATEGORY_LABELS[editing.category] || editing.category) : ''}`}
        open={editOpen}
        onOk={handleEditSave}
        okText="保存"
        confirmLoading={editSaving}
        onCancel={() => setEditOpen(false)}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" className="mt-2">
          <Form.Item name="certificate_name" label="证件名称" rules={[{ required: true, message: '请输入证件名称' }]}>
            <Input maxLength={128} placeholder="如：低压电工证" />
          </Form.Item>
          <Form.Item name="certificate_no" label="证件号码" extra="列表展示的是脱敏值；留空则保持不变">
            <Input maxLength={64} placeholder="留空保持不变" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { App, Button, Empty, Input, Popconfirm, Select, Spin, Table, Tabs, Tag } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
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
  fetchCertificateAccessLogs,
  fetchCertificateRequirements,
  fetchCertificatesLedger,
  fetchMissingCertificates,
  updateEmployeeCertificate,
} from '@/actions/hr'
import { fetchEmployeeFilterOptionsAction } from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'

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

/** 证件资料库台账：检索 / 缺件清单（HR 催收）/ 调阅记录（审计）/ 应交配置 */
export default function CertificatesLedgerClient() {
  const { message: msg } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:certificate:manage')
  const canAudit = hasPermission('hr:certificate:audit')

  const [activeTab, setActiveTab] = useState('ledger')

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
    setLedgerLoading(true)
    try {
      const r = await fetchCertificatesLedger({ ...f, page, page_size: 20 })
      setLedger(r.data || [])
      setLedgerTotal(r.meta?.total ?? 0)
      setLedgerPage(page)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '加载台账失败')
    } finally { setLedgerLoading(false) }
  }, [filters, msg])

  const loadMissing = useCallback(async (department?: string) => {
    setMissingLoading(true)
    try {
      const r = await fetchMissingCertificates(department)
      setMissing(r.data || [])
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '加载缺件清单失败')
    } finally { setMissingLoading(false) }
  }, [msg])

  const loadLogs = useCallback(async (page = 1) => {
    setLogLoading(true)
    try {
      const r = await fetchCertificateAccessLogs({ page, page_size: 20 })
      setLogs(r.data || [])
      setLogTotal(r.meta?.total ?? 0)
      setLogPage(page)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '加载调阅记录失败')
    } finally { setLogLoading(false) }
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
    void fetchEmployeeFilterOptionsAction()
      .then(o => setDeptOptions((o.department as string[] | undefined) || []))
      .catch(() => setDeptOptions([]))
  }, [loadLedger])

  const onTabChange = (key: string) => {
    setActiveTab(key)
    if (key === 'missing' && missing.length === 0) void loadMissing()
    if (key === 'logs' && logs.length === 0) void loadLogs()
    if (key === 'reqs' && reqs.length === 0) void loadReqs()
  }

  const handleEditLedger = async (cert: EmployeeCertificate) => {
    const name = window.prompt('证件名称（留空保持不变）', cert.certificate_name || '')
    if (name === null) return
    const no = window.prompt('证件号码（留空保持不变；当前展示为脱敏值）', '')
    if (no === null) return
    const changes: Partial<CertificateUploadInput> = { certificate_name: name || undefined }
    if (no) changes.certificate_no = no
    try {
      await updateEmployeeCertificate(cert.id, changes)
      msg.success('已更正')
      void loadLedger(ledgerPage)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '更正失败')
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">证件资料库</h1>
        <p className="text-[14px] text-[var(--color-steel)]">员工电子证件集中归档：按人建档、版本可溯、缺件催收、调阅留痕</p>
      </div>

      <Tabs activeKey={activeTab} onChange={onTabChange} items={[
        {
          key: 'ledger',
          label: `证件台账（${ledgerTotal}）`,
          children: (
            <div>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <Select allowClear placeholder="部门" style={{ minWidth: 160 }} showSearch
                  options={deptOptions.map(d => ({ value: d, label: d }))}
                  onChange={v => { const f = { ...filters, department: v }; setFilters(f); void loadLedger(1, f) }} />
                <Select allowClear placeholder="证件类别" style={{ minWidth: 150 }}
                  options={CATEGORY_OPTIONS}
                  onChange={v => { const f = { ...filters, category: v }; setFilters(f); void loadLedger(1, f) }} />
                <Input.Search allowClear placeholder="姓名 / 工号" style={{ width: 220 }}
                  onSearch={v => { const f = { ...filters, keyword: v }; setFilters(f); void loadLedger(1, f) }} />
                <Button icon={<ReloadOutlined />} onClick={() => void loadLedger(ledgerPage)} />
              </div>
              <Table size="small" rowKey="id" loading={ledgerLoading} dataSource={ledger}
                pagination={{ current: ledgerPage, total: ledgerTotal, pageSize: 20, showSizeChanger: false,
                  onChange: p => void loadLedger(p) }}
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
                      <Button size="small" type="link" onClick={() => void handleEditLedger(r)}>更正</Button>
                    ),
                  }] : []),
                ]} />
            </div>
          ),
        },
        {
          key: 'missing',
          label: '缺件清单',
          children: (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Select allowClear placeholder="按部门过滤" style={{ minWidth: 180 }} showSearch
                  options={deptOptions.map(d => ({ value: d, label: d }))}
                  onChange={v => void loadMissing(v)} />
                <Button icon={<ReloadOutlined />} onClick={() => void loadMissing(filters.department)} />
                <span className="text-xs text-gray-400">应交未交清单（应交口径按一般/重点岗位配置计算），供 HR 催收</span>
              </div>
              <Table size="small" rowKey={r => `${r.employee_id}-${r.category}`} loading={missingLoading} dataSource={missing}
                pagination={{ pageSize: 50, showSizeChanger: false }}
                locale={{ emptyText: <Empty description="应交证件齐全" className="py-6" /> }}
                columns={[
                  { title: '员工', dataIndex: 'employee_name', width: 120,
                    render: (v: string, r: MissingCertificateItem) => (
                      <Link href={`/hr/profile/${r.employee_id}`} className="text-[var(--color-anchor)] hover:underline">{v}</Link>
                    ) },
                  { title: '工号', dataIndex: 'employee_number', width: 100 },
                  { title: '部门', dataIndex: 'department', width: 130, ellipsis: true },
                  { title: '重点岗位', dataIndex: 'is_key_position', width: 90,
                    render: (v: boolean) => v ? <Tag color="purple">是</Tag> : '否' },
                  { title: '缺件', dataIndex: 'category_label', render: (v: string) => <Tag color="orange">{v}</Tag> },
                ]} />
            </div>
          ),
        },
        ...(canAudit ? [{
          key: 'logs',
          label: '调阅记录',
          children: (
            <Table size="small" rowKey="id" loading={logLoading} dataSource={logs}
              pagination={{ current: logPage, total: logTotal, pageSize: 20, showSizeChanger: false,
                onChange: p => void loadLogs(p) }}
              locale={{ emptyText: <Empty description="暂无调阅记录" className="py-6" /> }}
              columns={[
                { title: '时间', dataIndex: 'created_at', width: 170,
                  render: (v: string | null) => v?.replace('T', ' ').slice(0, 19) || '-' },
                { title: '操作', dataIndex: 'action', width: 130,
                  render: (v: string) => ACTION_LABELS[v] || v },
                { title: '员工', dataIndex: 'employee_name', width: 110 },
                { title: '证件类别', dataIndex: 'category', width: 130,
                  render: (v: string | null) => v ? (CERTIFICATE_CATEGORY_LABELS[v as CertificateCategory] || v) : '-' },
                { title: '版本', dataIndex: 'version_no', width: 70, render: (v: number | null) => v != null ? `v${v}` : '-' },
                { title: '操作人ID', dataIndex: 'user_id', ellipsis: true, render: (v: string | null) => v || '机器人通道' },
              ]} />
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
                <Button icon={<ReloadOutlined />} onClick={() => void loadReqs()} />
              </div>
              <div className="text-xs text-gray-400 mb-2">
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
                      <Popconfirm title="删除该应交配置？" onConfirm={async () => {
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
    </div>
  )
}

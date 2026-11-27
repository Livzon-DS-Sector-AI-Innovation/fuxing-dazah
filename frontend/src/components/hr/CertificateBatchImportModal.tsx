'use client'

import { useMemo, useRef, useState } from 'react'
import {
  Alert, App, Button, Checkbox, DatePicker, Input, Modal, Select, Table, Tag, Tooltip, Upload,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import type {
  CertificateCategory,
  CertificateImportCommitResult,
  CertificateImportCommitRow,
  CertificateImportEmployeeOption,
  CertificateImportPrecheck,
  CertificateImportRow,
} from '@/types/hr'
import { CERTIFICATE_CATEGORY_LABELS } from '@/types/hr'
import {
  commitCertificateBatchImport,
  fetchBatchImportEmployeeOptions,
  precheckCertificateBatchImport,
} from '@/actions/hr'

const CATEGORY_OPTIONS = (Object.entries(CERTIFICATE_CATEGORY_LABELS) as [CertificateCategory, string][])
  .map(([value, label]) => ({ value, label }))

const STATUS_META: Record<CertificateImportRow['status'], { color: string; text: string }> = {
  ok: { color: 'green', text: '自动匹配' },
  unmatched: { color: 'red', text: '未匹配' },
  ambiguous: { color: 'orange', text: '重名待选' },
  invalid: { color: 'default', text: '无法导入' },
}

/** 可编辑行：预检行 + 确认页补充的员工/要素 */
interface EditRow extends CertificateImportRow {
  employee_id?: string | null
  certificate_no?: string | null
  issue_date?: Dayjs | null
  expiry_date?: Dayjs | null
  is_permanent: boolean
  selected: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  /** 导入成功后回调（刷新台账） */
  onImported: () => void
}

/** 证件批量导入：ZIP 一次性上传 → 确认页修正（选人/改类别/补要素）→ 批量归档 */
export default function CertificateBatchImportModal({ open, onClose, onImported }: Props) {
  const { message: msg } = App.useApp()
  const [stage, setStage] = useState<'upload' | 'review' | 'result'>('upload')
  const [prechecking, setPrechecking] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [rows, setRows] = useState<EditRow[]>([])
  const [summary, setSummary] = useState<CertificateImportPrecheck['summary'] | null>(null)
  const [result, setResult] = useState<CertificateImportCommitResult | null>(null)

  // 补选员工：搜索结果累积进池子，供各行 Select 复用
  const [employeePool, setEmployeePool] = useState<Record<string, CertificateImportEmployeeOption>>({})
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const patchRow = (filename: string, patch: Partial<EditRow>) =>
    setRows(prev => prev.map(r => (r.filename === filename ? { ...r, ...patch } : r)))

  const searchEmployees = (kw: string) => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(async () => {
      try {
        const r = await fetchBatchImportEmployeeOptions(kw.trim() || undefined)
        setEmployeePool(prev => {
          const next = { ...prev }
          for (const o of r.data || []) next[o.id] = o
          return next
        })
      } catch { /* 搜索失败不打断编辑 */ }
    }, 300)
  }

  // 同批同「员工×类别」多个文件：只允许勾选第一个，其余提示合并/改类别
  const dupFiles = useMemo(() => {
    const seen = new Set<string>()
    const dup = new Set<string>()
    for (const r of rows) {
      const empId = r.employee?.id ?? r.employee_id
      if (!empId || r.status === 'invalid') continue
      const pair = `${empId}|${r.category}`
      if (seen.has(pair)) dup.add(r.filename)
      seen.add(pair)
    }
    return dup
  }, [rows])

  const isSelectable = (r: EditRow) =>
    r.status !== 'invalid' && !!r.storage_key && !!(r.employee?.id ?? r.employee_id) && !dupFiles.has(r.filename)

  const selectedRows = rows.filter(r => r.selected && isSelectable(r))

  const optionsFor = (r: EditRow): { value: string; label: string }[] => {
    const pool: CertificateImportEmployeeOption[] = [...r.candidates]
    if (r.employee) pool.push(r.employee)
    const empId = r.employee?.id ?? r.employee_id
    if (empId && employeePool[empId]) pool.push(employeePool[empId])
    const seen = new Set<string>()
    return pool
      .filter(o => (seen.has(o.id) ? false : (seen.add(o.id), true)))
      .map(o => ({ value: o.id, label: `${o.name}（${o.employee_number || '-'} / ${o.department || '-'}）` }))
  }

  const handlePrecheck = async (file: File) => {
    setPrechecking(true)
    try {
      const r = await precheckCertificateBatchImport(file)
      setRows((r.data?.rows || []).map(row => ({
        ...row,
        is_permanent: false,
        // 自动匹配的行默认勾选；重名/未匹配需人工选人后再勾
        selected: row.status === 'ok' && !row.dup_in_batch,
      })))
      setSummary(r.data?.summary ?? null)
      setEmployeePool({})
      setStage('review')
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '预检失败')
    } finally {
      setPrechecking(false)
    }
  }

  const handleCommit = async () => {
    const payload: CertificateImportCommitRow[] = selectedRows.map(r => ({
      storage_key: r.storage_key!,
      filename: r.filename,
      employee_id: (r.employee?.id ?? r.employee_id)!,
      category: r.category,
      certificate_no: r.certificate_no?.trim() || null,
      issue_date: r.issue_date?.format('YYYY-MM-DD') ?? null,
      expiry_date: r.is_permanent ? null : (r.expiry_date?.format('YYYY-MM-DD') ?? null),
      is_permanent: r.is_permanent,
    }))
    if (payload.length === 0) return
    setCommitting(true)
    try {
      const r = await commitCertificateBatchImport(payload)
      setResult(r.data)
      setStage('result')
      onImported()
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '导入失败')
    } finally {
      setCommitting(false)
    }
  }

  const columns = [
    {
      title: '文件名', dataIndex: 'filename', width: 220, ellipsis: true,
      render: (v: string, r: EditRow) => (
        <Tooltip title={r.status === 'invalid' ? `${v}（${r.error}）` : v}>
          <span className={r.status === 'invalid' ? 'text-[var(--color-steel)] line-through' : ''}>{v}</span>
        </Tooltip>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: CertificateImportRow['status'], r: EditRow) => (
        <Tooltip title={r.error || undefined}>
          <Tag color={STATUS_META[v].color}>{STATUS_META[v].text}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '员工', key: 'employee', width: 230,
      render: (_: unknown, r: EditRow) => {
        if (r.status === 'invalid') return '-'
        if (r.status === 'ok' && r.employee) {
          return (
            <span>
              {r.employee.name}
              <span className="text-xs text-[var(--color-steel)]">
                （{r.employee.employee_number || '-'} / {r.employee.department || '-'}）
              </span>
            </span>
          )
        }
        return (
          <Select showSearch allowClear filterOption={false}
            placeholder="搜索姓名/工号选员工" style={{ width: '100%' }}
            value={r.employee?.id ?? r.employee_id ?? undefined}
            onSearch={searchEmployees}
            onChange={v => patchRow(r.filename, { employee_id: v ?? null, selected: v ? r.selected : false })}
            options={optionsFor(r)} />
        )
      },
    },
    {
      title: '类别', dataIndex: 'category', width: 150,
      render: (v: CertificateCategory, r: EditRow) => (
        <Select style={{ width: '100%' }} status={r.category_matched ? undefined : 'warning'}
          value={v} options={CATEGORY_OPTIONS}
          onChange={val => patchRow(r.filename, { category: val })} />
      ),
    },
    {
      title: '证号', key: 'certificate_no', width: 150,
      render: (_: unknown, r: EditRow) => (
        <Input maxLength={64} allowClear placeholder="可空" value={r.certificate_no ?? ''}
          onChange={e => patchRow(r.filename, { certificate_no: e.target.value })} />
      ),
    },
    {
      title: '有效期', key: 'expiry_date', width: 140,
      render: (_: unknown, r: EditRow) => (
        <DatePicker style={{ width: '100%' }} value={r.expiry_date ?? null}
          disabled={r.is_permanent}
          onChange={d => patchRow(r.filename, { expiry_date: d })} />
      ),
    },
    {
      title: '长期', key: 'is_permanent', width: 55, align: 'center' as const,
      render: (_: unknown, r: EditRow) => (
        <Checkbox checked={r.is_permanent}
          onChange={e => patchRow(r.filename, { is_permanent: e.target.checked, expiry_date: null })} />
      ),
    },
    {
      title: '换证', key: 'replaces', width: 90,
      render: (_: unknown, r: EditRow) => r.replaces ? (
        <Tooltip title={`该员工该类别已有 v${r.replaces.version_no}（有效期 ${r.replaces.is_permanent ? '长期' : r.replaces.expiry_date || '-'}），导入后旧版本转历史`}>
          <Tag color="orange">替换 v{r.replaces.version_no}</Tag>
        </Tooltip>
      ) : (dupFiles.has(r.filename)
        ? <Tooltip title="同批内该员工该类别有多个文件，只能导入其一，其余请改类别或删除文件后重新打包"><Tag color="red">同批重复</Tag></Tooltip>
        : '-'),
    },
  ]

  const employeeName = (r: CertificateImportCommitResult['results'][number]) =>
    r.employee_name || '-'

  return (
    <Modal
      title="证件批量导入"
      open={open}
      width={1200}
      destroyOnHidden
      onCancel={onClose}
      footer={stage === 'review'
        ? [
            <Button key="cancel" onClick={onClose}>取消</Button>,
            <Button key="ok" type="primary" loading={committing}
              disabled={selectedRows.length === 0} onClick={() => void handleCommit()}>
              确认导入（{selectedRows.length} 件）
            </Button>,
          ]
        : [
            <Button key="close" type="primary" onClick={onClose}>
              {stage === 'result' ? '完成' : '取消'}
            </Button>,
          ]}
    >
      {stage === 'upload' && (
        <div className="py-2">
          <div className="text-sm text-[var(--color-steel)] mb-3">
            把证件扫描件打包成一个 ZIP 上传，文件名写「<b>姓名_证件类别</b>」即可自动匹配，
            如 <code>张三_身份证.jpg</code>、<code>李四-特种作业操作证.pdf</code>、<code>王五健康证.png</code>；
            支持按员工分文件夹打包。类别识别不出的会归入「其他」，未匹配/重名的在下一步人工处理。
          </div>
          <Upload.Dragger accept=".zip" maxCount={1} showUploadList={false}
            disabled={prechecking}
            beforeUpload={f => { void handlePrecheck(f as unknown as File); return false }}>
            <p className="py-2"><InboxOutlined style={{ fontSize: 40 }} /></p>
            <p className="text-sm">{prechecking ? '正在解析 ZIP…' : '点击或拖拽 ZIP 文件到此处'}</p>
            <p className="text-xs text-[var(--color-steel)]">≤200MB、≤200 个文件，单个扫描件 ≤20MB（图片/PDF）</p>
          </Upload.Dragger>
        </div>
      )}

      {stage === 'review' && summary && (
        <div className="space-y-3">
          <Alert type="info" showIcon message={
            <span>
              共 {summary.total} 个文件：自动匹配 {summary.ok} · 未匹配 {summary.unmatched} ·
              重名待选 {summary.ambiguous} · 无法导入 {summary.invalid}
              {summary.replaces > 0 && ` · 将换证 ${summary.replaces}`}
              ；未识别类别默认「其他」，请在下方核对修正后再导入。
            </span>
          } />
          <Table size="small" rowKey="filename" dataSource={rows} columns={columns}
            scroll={{ x: 1130 }} pagination={false}
            rowSelection={{
              selectedRowKeys: rows.filter(r => r.selected).map(r => r.filename),
              getCheckboxProps: r => ({ disabled: !isSelectable(r as EditRow) }),
              onChange: keys => setRows(prev => prev.map(r => ({ ...r, selected: keys.includes(r.filename) }))),
            }} />
        </div>
      )}

      {stage === 'result' && result && (
        <div className="space-y-3">
          <Alert showIcon
            type={result.summary.failed === 0 ? 'success' : 'warning'}
            message={`已导入 ${result.summary.imported} 件${result.summary.failed > 0 ? `，失败 ${result.summary.failed} 件` : ''}`}
            description={result.summary.failed === 0
              ? '证件已按员工+类别归档；同类别已有证件的自动升版本，旧版本可在员工证件视图查看。'
              : '失败行可修正后在员工档案页单独上传。'} />
          {result.summary.failed > 0 && (
            <Table size="small" rowKey="filename" pagination={false}
              dataSource={result.results.filter(r => !r.ok)}
              columns={[
                { title: '文件名', dataIndex: 'filename', ellipsis: true },
                { title: '员工', dataIndex: 'employee_name', width: 110, render: employeeName },
                { title: '类别', dataIndex: 'category_label', width: 130 },
                { title: '失败原因', dataIndex: 'error', ellipsis: true },
              ]} />
          )}
        </div>
      )}
    </Modal>
  )
}

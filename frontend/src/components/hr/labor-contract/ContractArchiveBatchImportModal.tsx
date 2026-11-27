'use client'

// 合同扫描件批量挂接（P2-5）：存量电子档（如本科以上已有扫描件）一次性挂到对应合同。
// ZIP（扫描件 + 可选 Excel 清单）→ 确认页修正（多份合同待选 / 未识别工号补选）→ 批量归档。
// 版本化规则同单个上传：已有扫描件的合同升为新版本，旧版转历史。

import { useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Input, Modal, Select, Table, Tag, Tooltip, Upload } from 'antd'
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import {
  commitContractImport,
  downloadContractImportTemplate,
  fetchContractImportOptions,
  precheckContractImport,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr/download'
import type {
  ContractImportCommitResult,
  ContractImportContractOption,
  ContractImportOption,
  ContractImportPrecheck,
  ContractImportRow,
} from '@/types/hr'

/** 可编辑行：预检行 + 确认页指定/补选的合同 */
interface EditRow extends ContractImportRow {
  picked_contract_id: string | null
  candidates: ContractImportContractOption[]
  selected: boolean
}

interface Props {
  open: boolean
  onClose: () => void
  /** 挂接成功后回调（刷新档案库） */
  onImported: () => void
}

const contractLabel = (c: ContractImportContractOption) => `${c.seq_label} · ${c.period} · ${c.status_label}`

/** 这一行最终指向的合同（或待建档的离职人员），用于同批去重 */
function targetKey(r: EditRow): string | null {
  if (r.picked_contract_id) return `contract:${r.picked_contract_id}`
  if (r.build_from_departure && r.employee) return `departure:${r.employee.employee_number}`
  return null
}

function statusMeta(r: EditRow): { color: string; text: string } {
  if (r.status === 'invalid') return { color: 'default', text: '无法导入' }
  if (targetKey(r)) return { color: 'green', text: r.status === 'ok' ? '自动匹配' : '已人工指定' }
  if (r.status === 'ambiguous') return { color: 'orange', text: '多份待选' }
  return { color: 'red', text: '未匹配' }
}

export default function ContractArchiveBatchImportModal({ open, onClose, onImported }: Props) {
  const { message } = App.useApp()
  const [stage, setStage] = useState<'upload' | 'review' | 'result'>('upload')
  const [prechecking, setPrechecking] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [rows, setRows] = useState<EditRow[]>([])
  const [summary, setSummary] = useState<ContractImportPrecheck['summary'] | null>(null)
  const [result, setResult] = useState<ContractImportCommitResult | null>(null)
  // 补选员工：搜索结果累积进池子，供各行 Select 复用
  const [optionPool, setOptionPool] = useState<Record<string, ContractImportOption>>({})
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const patchRow = (filename: string, patch: Partial<EditRow>) =>
    setRows((prev) => prev.map((r) => (r.filename === filename ? { ...r, ...patch } : r)))

  // 同批多行指向同一份合同：每份合同一批只能挂一个文件，只让先出现的行可勾选
  const dupFiles = useMemo(() => {
    const seen = new Set<string>()
    const dup = new Set<string>()
    for (const r of rows) {
      const key = targetKey(r)
      if (!key) continue
      if (seen.has(key)) dup.add(r.filename)
      seen.add(key)
    }
    return dup
  }, [rows])

  const isSelectable = (r: EditRow) =>
    r.status !== 'invalid' && !!r.storage_key && !!targetKey(r) && !dupFiles.has(r.filename)

  const selectedRows = rows.filter((r) => r.selected && isSelectable(r))

  const searchOptions = (kw: string) => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(async () => {
      try {
        const r = await fetchContractImportOptions(kw.trim())
        setOptionPool((prev) => {
          const next = { ...prev }
          for (const o of r.data || []) next[o.employee_number] = o
          return next
        })
      } catch { /* 搜索失败不打断编辑 */ }
    }, 300)
  }

  const pickPerson = (r: EditRow, employeeNumber: string) => {
    const option = optionPool[employeeNumber]
    if (!option) return
    patchRow(r.filename, {
      employee: {
        employee_number: option.employee_number,
        name: option.name,
        department: option.department,
        source: option.source,
      },
      candidates: option.contracts,
      // 只有一份合同直接选中；多份留给用户挑签订次数
      picked_contract_id: option.contracts.length === 1 ? option.contracts[0].id : null,
      build_from_departure: option.build_from_departure && option.contracts.length === 0,
    })
  }

  const handlePrecheck = async (file: File) => {
    setPrechecking(true)
    try {
      const r = await precheckContractImport(file)
      setRows((r.data?.rows || []).map((row) => ({
        ...row,
        candidates: row.candidates?.length ? row.candidates : row.contract ? [row.contract] : [],
        picked_contract_id: row.contract?.id ?? null,
        // 自动匹配的行默认勾选；待选/未匹配需人工指定后再勾
        selected: row.status === 'ok' && !row.dup_in_batch,
      })))
      setSummary(r.data?.summary ?? null)
      setOptionPool({})
      setStage('review')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '预检失败')
    } finally {
      setPrechecking(false)
    }
  }

  const handleCommit = async () => {
    const payload = selectedRows.map((r) => ({
      storage_key: r.storage_key!,
      filename: r.filename,
      contract_id: r.picked_contract_id,
      // 离职人员无合同行：传工号，提交时按离职记录合同信息建档
      employee_number:
        !r.picked_contract_id && r.build_from_departure ? (r.employee?.employee_number ?? null) : null,
      remark: r.remark?.trim() || null,
    }))
    if (payload.length === 0) return
    setCommitting(true)
    try {
      const r = await commitContractImport(payload)
      setResult(r.data)
      setStage('result')
      onImported()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '挂接失败')
    } finally {
      setCommitting(false)
    }
  }

  const handleTemplate = async () => {
    try {
      const r = await downloadContractImportTemplate()
      downloadBase64File(r.base64, r.filename || '合同扫描件导入清单模板.xlsx')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '下载模板失败')
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
      title: '状态', width: 110,
      render: (_: unknown, r: EditRow) => {
        const meta = statusMeta(r)
        return (
          <Tooltip title={dupFiles.has(r.filename) ? '与前面某行指向同一份合同，每份合同一批只能挂一个文件' : r.error || undefined}>
            <Tag color={meta.color}>{meta.text}</Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '员工', width: 220,
      render: (_: unknown, r: EditRow) => {
        if (r.status === 'invalid') return '-'
        if (r.employee) {
          return (
            <span>
              {r.employee.name}
              <span className="text-xs text-[var(--color-steel)]">
                （{r.employee.employee_number} / {r.employee.department}）
              </span>
            </span>
          )
        }
        return (
          <Select
            showSearch
            allowClear
            filterOption={false}
            placeholder="搜索姓名/工号选人"
            style={{ width: '100%' }}
            onSearch={searchOptions}
            onChange={(v) => { if (v) pickPerson(r, v) }}
            options={Object.values(optionPool).map((o) => ({
              value: o.employee_number,
              label: `${o.name}（${o.employee_number} / ${o.department}）`,
            }))}
          />
        )
      },
    },
    {
      title: '合同（按签订次数）', width: 250,
      render: (_: unknown, r: EditRow) => {
        if (r.status === 'invalid') return '-'
        if (!r.picked_contract_id && r.build_from_departure && r.employee) {
          return <Tooltip title="该离职人员不在合同表：提交时按离职记录的合同起止日期建一份已终止合同"><Tag color="blue">按离职记录建档</Tag></Tooltip>
        }
        return (
          <Select
            showSearch
            allowClear
            optionFilterProp="label"
            placeholder={r.candidates.length ? '选择签订次数' : '先选员工'}
            disabled={r.candidates.length === 0}
            style={{ width: '100%' }}
            value={r.picked_contract_id ?? undefined}
            onChange={(v) => patchRow(r.filename, { picked_contract_id: v ?? null })}
            options={r.candidates.map((c) => ({ value: c.id, label: contractLabel(c) }))}
          />
        )
      },
    },
    {
      title: '备注', width: 150,
      render: (_: unknown, r: EditRow) => (
        <Input maxLength={128} allowClear placeholder="可空" value={r.remark ?? ''}
          onChange={(e) => patchRow(r.filename, { remark: e.target.value })} />
      ),
    },
    {
      title: '换版', width: 110,
      render: (_: unknown, r: EditRow) => r.replaces ? (
        <Tooltip title={`该合同已有扫描件 v${r.replaces.version_no}，挂接后升为新版本，旧版转历史`}>
          <Tag color="orange">替换 v{r.replaces.version_no}</Tag>
        </Tooltip>
      ) : dupFiles.has(r.filename) ? <Tag color="red">同批重复</Tag> : '-',
    },
  ]

  return (
    <Modal
      title="合同扫描件批量挂接"
      open={open}
      width={1200}
      destroyOnHidden
      onCancel={onClose}
      footer={stage === 'review'
        ? [
            <Button key="cancel" onClick={onClose}>取消</Button>,
            <Button key="ok" type="primary" loading={committing}
              disabled={selectedRows.length === 0} onClick={() => void handleCommit()}>
              确认挂接（{selectedRows.length} 份）
            </Button>,
          ]
        : [
            <Button key="close" type="primary" onClick={onClose}>
              {stage === 'result' ? '完成' : '取消'}
            </Button>,
          ]}
    >
      {stage === 'upload' && (
        <div className="py-2 space-y-3">
          <div className="text-sm text-[var(--color-steel)]">
            把扫描件打包成一个 ZIP 上传。文件名写<b>工号</b>即可自动匹配，如{' '}
            <code>111003118_刘双玲.pdf</code>；员工有多份合同时在文件名里写上「第N次」，
            如 <code>111003118_刘双玲_第2次.pdf</code>。
            也可以在 ZIP 里放一份 Excel 清单（列：工号、签订次数、文件名、备注）逐行指定，
            清单优先于文件名。支持子文件夹；识别不了的在下一步人工处理。
          </div>
          <Button icon={<DownloadOutlined />} onClick={() => void handleTemplate()}>下载 Excel 清单模板</Button>
          <Upload.Dragger accept=".zip" maxCount={1} showUploadList={false}
            disabled={prechecking}
            beforeUpload={(f) => { void handlePrecheck(f as unknown as File); return false }}>
            <p className="py-2"><InboxOutlined style={{ fontSize: 40 }} /></p>
            <p className="text-sm">{prechecking ? '正在解析 ZIP…' : '点击或拖拽 ZIP 文件到此处'}</p>
            <p className="text-xs text-[var(--color-steel)]">≤200MB、≤200 个扫描件，单个 ≤20MB（图片/PDF）</p>
          </Upload.Dragger>
        </div>
      )}

      {stage === 'review' && summary && (
        <div className="space-y-3">
          <Alert type="info" showIcon title={
            <span>
              共 {summary.total} 个文件：自动匹配 {summary.ok} · 多份待选 {summary.ambiguous} ·
              未匹配 {summary.unmatched} · 无法导入 {summary.invalid}
              {summary.replaces > 0 && ` · 将升为新版本 ${summary.replaces}`}
              {summary.builds > 0 && ` · 按离职记录建档 ${summary.builds}`}
              ；请核对后再挂接。
            </span>
          } />
          <Table size="small" rowKey="filename" dataSource={rows} columns={columns}
            scroll={{ x: 1100 }} pagination={false}
            rowSelection={{
              selectedRowKeys: rows.filter((r) => r.selected).map((r) => r.filename),
              getCheckboxProps: (r) => ({ disabled: !isSelectable(r as EditRow) }),
              onChange: (keys) => setRows((prev) => prev.map((r) => ({ ...r, selected: keys.includes(r.filename) }))),
            }} />
        </div>
      )}

      {stage === 'result' && result && (
        <div className="space-y-3">
          <Alert showIcon
            type={result.summary.failed === 0 ? 'success' : 'warning'}
            title={`已挂接 ${result.summary.imported} 份${result.summary.failed > 0 ? `，失败 ${result.summary.failed} 份` : ''}`}
            description={result.summary.failed === 0
              ? '扫描件已挂到对应合同；已有扫描件的合同已升为新版本，旧版在合同详情里可查。'
              : '失败行可在电子档案库里打开合同详情单独上传。'}
          />
          {result.summary.failed > 0 && (
            <Table size="small" rowKey="filename" pagination={false}
              dataSource={result.results.filter((r) => !r.ok)}
              columns={[
                { title: '文件名', dataIndex: 'filename', ellipsis: true },
                { title: '员工', dataIndex: 'employee_name', width: 110, render: (v: string | null) => v || '-' },
                { title: '合同', dataIndex: 'seq_label', width: 120, render: (v: string | null) => v || '-' },
                { title: '失败原因', dataIndex: 'error', ellipsis: true },
              ]} />
          )}
        </div>
      )}
    </Modal>
  )
}

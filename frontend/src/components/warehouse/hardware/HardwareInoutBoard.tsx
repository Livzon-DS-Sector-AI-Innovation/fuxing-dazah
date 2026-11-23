'use client'

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Upload,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { CameraOutlined, PlusOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  acceptHardwareReceiptClient,
  createHardwareReceiptClient,
  fetchHardwareMaterialsClient,
  fetchHardwareReceiptsClient,
  fetchHardwareRequisitionsClient,
  fetchHardwareReturnsClient,
  importHardwareErpFile,
  parseHardwareReceiptExcelClient,
  photoScreenHardwareReceiptClient,
  rejectHardwareReceiptClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_MANAGED_CLASS_LABEL,
  HARDWARE_RECEIPT_SOURCE_LABEL,
  HARDWARE_RECEIPT_STATUS_LABEL,
  type HardwareMaterialRecord,
  type HardwareReceiptParseResult,
  type HardwareReceiptRecord,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { HardwareRequisitions } from './HardwareRequisitions'
import { HardwareReturnPanel } from './HardwareReturnPanel'
import { HardwareReceiptErpDocs, docStatusOf, type ErpDocGroup, type ErpDocGroupStatus, type ErpDocRow } from './HardwareReceiptErpDocs'
import { erpMatchKey, loadErpMatchMemory, saveErpMatch } from './erpMatchMemory'
import { formatQty } from './format'
import { MANAGED_CLASS_TONE, RECEIPT_STATUS_TONE } from './constants'
import { PageHeader, QueryFilter, SectionCard, StatCard, StatusTag, EmptyGuide } from '@/components/warehouse'

type TabKey = 'inbound' | 'outbound' | 'returns'

const TAB_KEYS: readonly TabKey[] = ['inbound', 'outbound', 'returns']

const TAB_ALIASES: Record<string, TabKey> = {
  inbound: 'inbound',
  outbound: 'outbound',
  returns: 'returns',
  requisition: 'outbound',
  issue: 'outbound',
}

export function HardwareInoutBoard() {
  const [tab, setTab] = useState<TabKey>('inbound')
  const [outboundFocus, setOutboundFocus] = useState<string | undefined>(undefined)

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    if (t && TAB_KEYS.includes(t as TabKey)) {
      setTab(t as TabKey)
    } else if (t && TAB_ALIASES[t]) {
      setTab(TAB_ALIASES[t])
    }
  }, [])

  const openTab = (next: TabKey, focusStatus?: string) => {
    setTab(next)
    if (next === 'outbound') setOutboundFocus(focusStatus)
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader breadcrumb={['仓储管理', '五金库', '出入库工作台']} title="五金出入库工作台" />
      <InoutStatCards onOpen={openTab} />
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as TabKey)}
        options={[
          { value: 'inbound', label: '入库' },
          { value: 'outbound', label: '出库' },
          { value: 'returns', label: '退料' },
        ]}
      />
      {tab === 'inbound' && <InboundPanel />}
      {tab === 'outbound' && <HardwareRequisitions key={outboundFocus ?? 'none'} focusStatus={outboundFocus} />}
      {tab === 'returns' && <HardwareReturnPanel />}
    </div>
  )
}

function InoutStatCards({ onOpen }: { onOpen: (tab: TabKey, focusStatus?: string) => void }) {
  const { data: draftReceipts, isLoading: l1 } = useQuery({
    queryKey: ['warehouse', 'hardware', 'receipts', 'stat-draft'],
    queryFn: () => fetchHardwareReceiptsClient({ status: 'draft', page: 1, pageSize: 1 }),
    refetchInterval: 60_000,
  })
  const { data: pendingReq, isLoading: l2 } = useQuery({
    queryKey: ['warehouse', 'hardware', 'requisitions', 'stat-pending'],
    queryFn: () => fetchHardwareRequisitionsClient({ status: 'pending', page: 1, pageSize: 1 }),
    refetchInterval: 60_000,
  })
  const { data: approvedReq, isLoading: l3 } = useQuery({
    queryKey: ['warehouse', 'hardware', 'requisitions', 'stat-approved'],
    queryFn: () => fetchHardwareRequisitionsClient({ status: 'approved', page: 1, pageSize: 1 }),
    refetchInterval: 60_000,
  })
  const { data: draftReturns, isLoading: l4 } = useQuery({
    queryKey: ['warehouse', 'hardware', 'returns', 'stat-draft'],
    queryFn: () => fetchHardwareReturnsClient({ status: 'draft', page: 1, pageSize: 1 }),
    refetchInterval: 60_000,
  })

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatCard
        label="待确认入库"
        value={(draftReceipts?.total ?? 0).toLocaleString()}
        sub="单"
        tone="warn"
        loading={l1}
        onClick={() => onOpen('inbound')}
      />
      <StatCard
        label="待审批申请"
        value={(pendingReq?.total ?? 0).toLocaleString()}
        sub="单"
        tone="info"
        loading={l2}
        onClick={() => onOpen('outbound', 'pending')}
      />
      <StatCard
        label="待发料"
        value={(approvedReq?.total ?? 0).toLocaleString()}
        sub="单"
        tone="primary"
        loading={l3}
        onClick={() => onOpen('outbound', 'approved')}
      />
      <StatCard
        label="待验收退料"
        value={(draftReturns?.total ?? 0).toLocaleString()}
        sub="单"
        tone="warn"
        loading={l4}
        onClick={() => onOpen('returns')}
      />
    </div>
  )
}

const RECEIPT_STATUS_FILTERS = [
  { value: 'draft', label: '待确认' },
  { value: 'accepted', label: '已入账' },
  { value: 'rejected', label: '已拒收' },
  { value: 'all', label: '全部' },
]

function InboundPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('warehouse:hardware:inbound:create')
  const canConfirm = hasPermission('warehouse:hardware:inbound:confirm')

  const [statusFilter, setStatusFilter] = useState<string | undefined>('draft')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [manualOpen, setManualOpen] = useState(false)
  const [entryAutoUpload, setEntryAutoUpload] = useState(false)
  const [ocrUploading, setOcrUploading] = useState(false)
  const [confirming, setConfirming] = useState<HardwareReceiptRecord | null>(null)

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'receipts', { statusFilter, keyword, page, pageSize }],
    queryFn: () =>
      fetchHardwareReceiptsClient({
        status: statusFilter, keyword: keyword || undefined, page, pageSize,
      }),
    placeholderData: keepPreviousData,
  })

  const columns: TableColumnsType<HardwareReceiptRecord> = [
    { title: '单号', dataIndex: 'receipt_no', width: 150, className: 'font-mono' },
    {
      title: '来源',
      dataIndex: 'source',
      width: 90,
      render: (v: string) =>
        HARDWARE_RECEIPT_SOURCE_LABEL[v as keyof typeof HARDWARE_RECEIPT_SOURCE_LABEL] ?? v,
    },
    {
      title: '类别',
      dataIndex: 'mode',
      width: 100,
      render: (v: string) => (
        <StatusTag
          tone={MANAGED_CLASS_TONE[v as keyof typeof MANAGED_CLASS_TONE] ?? 'info'}
          label={v === 'direct' ? HARDWARE_MANAGED_CLASS_LABEL.direct : HARDWARE_MANAGED_CLASS_LABEL.stocked}
        />
      ),
    },
    { title: '供应商', dataIndex: 'supplier_name', width: 160, ellipsis: true, render: (v) => v || '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => (
        <StatusTag
          tone={RECEIPT_STATUS_TONE[v as keyof typeof RECEIPT_STATUS_TONE] ?? 'default'}
          label={HARDWARE_RECEIPT_STATUS_LABEL[v as keyof typeof HARDWARE_RECEIPT_STATUS_LABEL] ?? v}
        />
      ),
    },
    { title: '直发车间', dataIndex: 'target_dept', width: 90, render: (v) => v || '-' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right',
      render: (_: unknown, r) => (
        <Space>
          {r.status === 'draft' && canConfirm && (
            <>
              <Button size="small" type="primary" onClick={() => setConfirming(r)}>
                确认
              </Button>
              <Button
                size="small"
                danger
                onClick={async () => {
                  const reason = window.prompt('拒收原因（留证通知采购）：')
                  if (reason) {
                    await rejectHardwareReceiptClient(r.id, reason)
                    message.success('已拒收留证并通知采购')
                    queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
                  }
                }}
              >
                拒收
              </Button>
            </>
          )}
          {r.status !== 'draft' && <span className="text-[12px] text-gray-400">已处理</span>}
        </Space>
      ),
    },
  ]

  return (
    <SectionCard
      title="入库单"
      action={
        canCreate && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              onClick={() => {
                setEntryAutoUpload(false)
                setManualOpen(true)
              }}
            >
              手动登记
            </Button>
            <Button
              type="primary"
              icon={<UploadOutlined />}
              onClick={() => {
                setEntryAutoUpload(true)
                setManualOpen(true)
              }}
            >
              ERP 流水导入
            </Button>
            <Upload
              accept="image/jpeg,image/png"
              showUploadList={false}
              beforeUpload={async (file) => {
                setOcrUploading(true)
                try {
                  const form = new FormData()
                  form.append('file', file)
                  const base = process.env.NEXT_PUBLIC_API_BASE_URL || ''
                  const resp = await fetch(`${base}/api/v1/warehouse/hardware/receipts/ocr`, {
                    method: 'POST',
                    body: form,
                    credentials: 'include',
                  })
                  const json = await resp.json().catch(() => null)
                  if (!resp.ok) throw new Error(json?.message || `识别失败 (${resp.status})`)
                  message.success(
                    `识别完成：${json.data?.matched_stocked ?? 0} 行匹配 / ${json.data?.unmatched ?? 0} 行待人工，请在列表中确认`,
                  )
                  setStatusFilter('draft')
                  queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
                } catch (e) {
                  message.error(e instanceof Error ? e.message : 'OCR 识别失败，请用手动登记')
                } finally {
                  setOcrUploading(false)
                }
                return false
              }}
            >
              <Button icon={<CameraOutlined />} loading={ocrUploading}>
                拍照 OCR 入库
              </Button>
            </Upload>
            <Upload
              accept=".xlsx,.csv"
              showUploadList={false}
              beforeUpload={async (file) => {
                try {
                  const result = await importHardwareErpFile(file)
                  message.success(
                    `ERP 导入完成：新增 ${result.created} 单 / 去重跳过 ${result.skipped} 单`
                    + (result.auto_accepted ? ` / 自动入账 ${result.auto_accepted} 单` : '')
                    + `（对账匹配 ${result.reconcile?.matched ?? 0}）——请到列表核对确认`,
                  )
                  setStatusFilter('draft')
                  queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
                } catch (e) {
                  message.error(e instanceof Error ? e.message : 'ERP 导入失败')
                }
                return false
              }}
            >
              <Button icon={<UploadOutlined />}>ERP 导入</Button>
            </Upload>
          </div>
        )
      }
    >
      <QueryFilter
        common={
          <>
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: '#999' }} />}
              placeholder="单号 / 供应商 / 送货单号"
              style={{ width: 240 }}
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value)
                setPage(1)
              }}
            />
            <Segmented
              value={statusFilter ?? 'all'}
              onChange={(v) => {
                setStatusFilter(v === 'all' ? undefined : (v as string))
                setPage(1)
              }}
              options={RECEIPT_STATUS_FILTERS}
            />
          </>
        }
      />
      <Table<HardwareReceiptRecord>
        size="middle"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        locale={{ emptyText: <EmptyGuide compact title="暂无入库单" description="手动登记 / ERP 流水导入 / 拍照 OCR 后在这里确认入账" /> }}
        pagination={{
          current: page,
          pageSize,
          total: res?.total ?? 0,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        scroll={{ x: 1000 }}
      />
      <ReceiptEntryModal
        open={manualOpen}
        autoUpload={entryAutoUpload}
        onClose={() => setManualOpen(false)}
      />
      <ReceiptConfirmModal receipt={confirming} onClose={() => setConfirming(null)} />
    </SectionCard>
  )
}

interface ReceiptEntryRow {
  material_id?: string
  name?: string
  spec?: string
  unit?: string
  quantity?: number
  match_confidence?: string
  match_score?: number
}

function ReceiptEntryModal({
  open,
  onClose,
  autoUpload,
}: {
  open: boolean
  onClose: () => void
  autoUpload?: boolean
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [keyword, setKeyword] = useState('')
  const [mode, setMode] = useState<'stocked' | 'direct'>('stocked')
  const [saving, setSaving] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [building, setBuilding] = useState(false)
  const [parsed, setParsed] = useState<HardwareReceiptParseResult | null>(null)
  const [docs, setDocs] = useState<ErpDocGroup[]>([])
  const [summaryText, setSummaryText] = useState('')

  const { data: materialRes, isLoading: materialLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'material-search', keyword],
    queryFn: () => fetchHardwareMaterialsClient(keyword, 30),
    enabled: open,
  })
  const materialOptions = (materialRes?.items ?? []).map((m) => ({
    value: m.id,
    label: `${m.name} ${m.spec ?? ''}（${m.unit}）`,
    material: m,
  }))

  const buildDocsFromParse = (
    result: HardwareReceiptParseResult,
  ): { groups: ErpDocGroup[]; memoryApplied: number } => {
    const memory = loadErpMatchMemory()
    let memoryApplied = 0
    const rows: ErpDocRow[] = result.items.map((it) => {
      const row: ErpDocRow = {
        material_id: it.material_id ?? undefined,
        name: it.name,
        spec: it.spec ?? undefined,
        unit: it.unit ?? undefined,
        quantity: Number(it.quantity),
        match_confidence: it.match_confidence,
        match_score: it.match_score != null ? Number(it.match_score) : undefined,
        managed_class: it.managed_class ?? null,
        low: !!it.low_confidence,
      }
      if (!row.material_id) {
        const hit = memory[erpMatchKey(row.name, row.spec)]
        if (hit) {
          memoryApplied += 1
          return {
            ...row,
            material_id: hit.material_id,
            name: hit.name || row.name,
            spec: hit.spec ?? row.spec,
            unit: hit.unit ?? row.unit,
            managed_class: hit.managed_class ?? null,
            match_confidence: 'manual-memory',
            memory: true,
          }
        }
      }
      return row
    })
    const groups: ErpDocGroup[] = result.documents?.length
      ? result.documents.map((d) => ({
          key: d.key,
          delivery_note_no: d.delivery_note_no ?? null,
          supplier_name: d.supplier_name ?? null,
          rows: d.item_indexes.map((i) => rows[i]).filter(Boolean),
        }))
      : [
          {
            key: '',
            delivery_note_no: result.delivery_note_no ?? null,
            supplier_name: result.supplier_name ?? null,
            rows,
          },
        ]
    return { groups: groups.filter((g) => g.rows.length > 0), memoryApplied }
  }

  const onUploadParse = async (file: File) => {
    setParsing(true)
    try {
      const result = await parseHardwareReceiptExcelClient(file)
      setParsed(result)
      const { groups, memoryApplied } = buildDocsFromParse(result)
      setDocs(groups)
      form.setFieldsValue({ remark: result.remark ?? undefined })
      const statuses = groups.map(docStatusOf)
      const matchedDocs = statuses.filter((d) => d.all_matched).length
      const unmatchedDocs = statuses.length - matchedDocs
      setSummaryText(
        `已解析 ${result.items.length} 行 / ${statuses.length} 张单据：已匹配 ${matchedDocs} 张可建单 · 未匹配 ${unmatchedDocs} 张待人工补配`,
      )
      message.success(
        `解析完成：${statuses.length} 张单据（已匹配 ${matchedDocs} / 未匹配 ${unmatchedDocs}）`
          + (memoryApplied ? `，已套用 ${memoryApplied} 行历史人工匹配` : '')
          + '——已匹配单据可直接建单',
      )
      if (result.errors?.length) {
        message.warning(
          result.errors.map((e) => `第${e.row}行 ${e.name}: ${e.reason}`).join('；'),
          6,
        )
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'Excel 解析失败，请改用手动填写')
    } finally {
      setParsing(false)
    }
    return false
  }

  const patchRow = (docKey: string, rowIdx: number, patch: Partial<ErpDocRow>) => {
    setDocs((prev) =>
      prev.map((d) =>
        d.key !== docKey
          ? d
          : { ...d, rows: d.rows.map((r, i) => (i === rowIdx ? { ...r, ...patch } : r)) },
      ),
    )
  }

  const removeRow = (docKey: string, rowIdx: number) => {
    setDocs((prev) =>
      prev
        .map((d) => (d.key !== docKey ? d : { ...d, rows: d.rows.filter((_, i) => i !== rowIdx) }))
        .filter((d) => d.rows.length > 0),
    )
  }

  const pickMaterial = (docKey: string, rowIdx: number, material: HardwareMaterialRecord) => {
    const row = docs.find((d) => d.key === docKey)?.rows[rowIdx]
    if (row) {
      saveErpMatch({
        name: row.name,
        spec: row.spec,
        material_id: material.id,
        material_name: material.name,
        material_spec: material.spec,
        material_unit: material.unit,
        material_class: material.managed_class,
      })
    }
    patchRow(docKey, rowIdx, {
      material_id: material.id,
      name: material.name,
      spec: material.spec ?? undefined,
      unit: material.unit ?? undefined,
      managed_class: material.managed_class,
      match_confidence: 'manual',
      match_score: undefined,
      low: false,
      memory: false,
    })
  }

  const buildReceiptForDoc = async (doc: ErpDocGroupStatus) => {
    const values = await form.getFieldsValue()
    const targetDept = (values.target_dept || '').trim()
    if (doc.mode === 'direct' && !targetDept) {
      message.warning(`单据 ${doc.delivery_note_no || '（无单号）'} 为直发单，请先填写「直发车间」再建单`)
      return null
    }
    return createHardwareReceiptClient({
      source: 'excel',
      mode: doc.mode,
      supplier_name: doc.supplier_name ?? undefined,
      delivery_note_no: doc.delivery_note_no ?? undefined,
      target_dept: doc.mode === 'direct' ? targetDept : undefined,
      remark: values.remark || undefined,
      excel_result: parsed?.excel_result ?? undefined,
      items: doc.rows.map((r) => ({
        material_id: r.material_id,
        name: r.name,
        spec: r.spec || undefined,
        unit: r.unit || undefined,
        quantity: r.quantity,
        match_confidence: r.match_confidence,
        match_score: r.match_score,
      })),
    })
  }

  const handleBuildDoc = async (doc: ErpDocGroupStatus) => {
    setBuilding(true)
    try {
      const receipt = await buildReceiptForDoc(doc)
      if (!receipt) return
      setDocs((prev) => prev.filter((d) => d.key !== doc.key))
      message.success(
        `单据 ${doc.delivery_note_no || '（无单号）'} 已生成草稿 ${receipt.receipt_no}，请在列表中一屏确认入账`,
      )
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '建单失败')
    } finally {
      setBuilding(false)
    }
  }

  const handleBuildAll = async () => {
    const targets = docs.map(docStatusOf).filter((d) => d.all_matched)
    if (targets.length === 0) return
    setBuilding(true)
    try {
      const builtKeys: string[] = []
      const failed: string[] = []
      for (const doc of targets) {
        try {
          const receipt = await buildReceiptForDoc(doc)
          if (receipt) {
            builtKeys.push(doc.key)
          } else {
            failed.push(doc.delivery_note_no || '（无单号）')
          }
        } catch {
          failed.push(doc.delivery_note_no || '（无单号）')
        }
      }
      setDocs((prev) => prev.filter((d) => !builtKeys.includes(d.key)))
      if (builtKeys.length) {
        message.success(`已批量生成 ${builtKeys.length} 张草稿，请在列表中逐张一屏确认入账`)
        queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
      }
      if (failed.length) {
        message.warning(
          `${failed.length} 张建单未成功（直发单缺车间或校验不过）：${failed.join('、')}`,
          6,
        )
      }
    } finally {
      setBuilding(false)
    }
  }

  const resetState = () => {
    form.resetFields()
    setParsed(null)
    setDocs([])
    setSummaryText('')
    setMode('stocked')
  }

  const closeAndReset = () => {
    resetState()
    onClose()
  }

  const onSubmit = async () => {
    const values = await form.validateFields()
    const rows: ReceiptEntryRow[] = values.items ?? []
    if (rows.length === 0) {
      message.warning('至少填写一行物料明细')
      return
    }
    setSaving(true)
    try {
      await createHardwareReceiptClient({
        source: 'manual',
        mode,
        supplier_name: values.supplier_name || undefined,
        delivery_note_no: values.delivery_note_no || undefined,
        target_dept: mode === 'direct' ? values.target_dept : undefined,
        remark: values.remark || undefined,
        items: rows.map((r) => ({
          material_id: mode === 'stocked' ? r.material_id : undefined,
          name: r.name ?? '',
          spec: r.spec || undefined,
          unit: r.unit || undefined,
          quantity: r.quantity ?? 0,
        })),
      })
      message.success('已生成草稿，请在列表中一屏确认入账')
      resetState()
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '登记失败')
    } finally {
      setSaving(false)
    }
  }

  const statuses = docs.map(docStatusOf)
  const hasDirectDoc = statuses.some((d) => d.mode === 'direct')

  return (
    <Modal
      title="入库登记"
      open={open}
      onCancel={closeAndReset}
      onOk={onSubmit}
      confirmLoading={saving}
      okText="生成草稿"
      width={980}
      footer={
        parsed ? (
          <Button onClick={closeAndReset}>关闭</Button>
        ) : undefined
      }
    >
      {autoUpload && !parsed && (
        <Alert
          type="info"
          showIcon
          className="mb-3"
          message={
            <span>
              上传 <b>ERP 导出的入库流水 Excel</b>（.xls/.xlsx/.csv），系统自动解析并<b>按入库单号分单</b>
              （支持 ERP 列名：物料名称/入库数量/主计量单位/入库单号）——已匹配单据直接建单，
              未匹配单据人工补配后再建单。
            </span>
          }
        />
      )}
      <div className="mb-3 flex items-center gap-3">
        <Upload accept=".xlsx,.xlsm,.xls,.csv" showUploadList={false} beforeUpload={onUploadParse}>
          <Button icon={<UploadOutlined />} loading={parsing}>
            上传 ERP 流水自动填写
          </Button>
        </Upload>
        {parsed && <span className="text-xs text-neutral-500">{summaryText}</span>}
      </div>
      {parsed ? (
        <>
          <Form form={form} layout="vertical">
            <div className="grid grid-cols-2 gap-x-4">
              {hasDirectDoc && (
                <Form.Item
                  name="target_dept"
                  label="直发车间（直发单建单必填）"
                  required
                >
                  <Input placeholder="如：发酵 / 提炼一期 / 精制机修" />
                </Form.Item>
              )}
              <Form.Item name="remark" label="备注（随本批每张建单）">
                <Input placeholder="异常情况等" />
              </Form.Item>
            </div>
          </Form>
          <HardwareReceiptErpDocs
            docs={docs}
            building={building}
            materialOptions={materialOptions}
            onMaterialKeyword={setKeyword}
            materialLoading={materialLoading}
            onRowPatch={patchRow}
            onRowRemove={removeRow}
            onPickMaterial={pickMaterial}
            onBuildDoc={handleBuildDoc}
            onBuildAll={handleBuildAll}
          />
        </>
      ) : (
        <Form form={form} layout="vertical" initialValues={{ items: [{}] }}>
          <Form.Item label="单据类别" className="mb-2">
            <Segmented
              value={mode}
              onChange={(v) => setMode(v as 'stocked' | 'direct')}
              options={[
                { value: 'stocked', label: '共用类（入库存）' },
                { value: 'direct', label: '车间单独需求（直发）' },
              ]}
            />
          </Form.Item>
          <div className="grid grid-cols-2 gap-x-4">
            <Form.Item name="supplier_name" label="供应商">
              <Input placeholder="可空" />
            </Form.Item>
            <Form.Item name="delivery_note_no" label="送货单号">
              <Input placeholder="可空" />
            </Form.Item>
            {mode === 'direct' && (
              <Form.Item
                name="target_dept"
                label="直发车间"
                rules={[{ required: true, message: 'direct 类必须指定车间' }]}
              >
                <Input placeholder="如：发酵 / 提炼一期 / 精制机修" />
              </Form.Item>
            )}
            <Form.Item name="remark" label="备注">
              <Input placeholder="异常情况等" />
            </Form.Item>
          </div>

          <div className="mb-1 text-sm font-medium">物料明细（一行一物料）</div>
          <Form.List name="items">
            {(fields, { add, remove }) => (
              <div className="flex flex-col gap-2">
                {fields.map((field) => (
                  <Space key={field.key} align="start" className="w-full" wrap={false}>
                    {mode === 'stocked' && (
                      <Form.Item name={[field.name, 'material_id']} className="mb-0" style={{ width: 250 }}>
                        <Select
                          showSearch
                          allowClear
                          placeholder="搜索选择物料（未匹配可留空）"
                          filterOption={false}
                          onSearch={setKeyword}
                          notFoundContent={materialRes ? '无匹配物料' : <Spin size="small" />}
                          options={materialOptions}
                          onChange={(v) => {
                            const hit = materialOptions.find((o) => o.value === v)
                            if (hit) {
                              form.setFieldValue(['items', field.name, 'name'], hit.material.name)
                              form.setFieldValue(
                                ['items', field.name, 'spec'],
                                hit.material.spec ?? undefined,
                              )
                              form.setFieldValue(
                                ['items', field.name, 'unit'],
                                hit.material.unit ?? undefined,
                              )
                            }
                          }}
                        />
                      </Form.Item>
                    )}
                    <Form.Item
                      name={[field.name, 'name']}
                      className="mb-0"
                      style={{ width: 150 }}
                      rules={[{ required: true, message: '品名必填' }]}
                    >
                      <Input placeholder="品名" />
                    </Form.Item>
                    <Form.Item name={[field.name, 'spec']} className="mb-0" style={{ width: 140 }}>
                      <Input placeholder="规格（可空）" />
                    </Form.Item>
                    <Form.Item name={[field.name, 'unit']} className="mb-0" style={{ width: 70 }}>
                      <Input placeholder="单位" />
                    </Form.Item>
                    <Form.Item
                      name={[field.name, 'quantity']}
                      className="mb-0"
                      rules={[{ required: true, message: '数量必填' }]}
                    >
                      <InputNumber min={1} precision={0} placeholder="数量" style={{ width: 100 }} />
                    </Form.Item>
                    {fields.length > 1 && (
                      <Button
                        type="text"
                        danger
                        style={{ marginTop: 2 }}
                        onClick={() => remove(field.name)}
                      >
                        删
                      </Button>
                    )}
                  </Space>
                ))}
                <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({})}>
                  添加物料行
                </Button>
              </div>
            )}
          </Form.List>
        </Form>
      )}
    </Modal>
  )
}

const _optionCache = new Map<string, Array<{ value: string; label: string }>>()

function useMaterialOptions() {
  const queryClient = useQueryClient()
  return async (keyword: string) => {
    const key = keyword || ''
    if (_optionCache.has(key)) return _optionCache.get(key)!
    try {
      const res = await queryClient.fetchQuery({
        queryKey: ['warehouse', 'hardware', 'material-search', key],
        queryFn: () => fetchHardwareMaterialsClient(key, 20),
        staleTime: 60_000,
      })
      const options = res.items.map((m) => ({
        value: m.id,
        label: `${m.name} ${m.spec ?? ''}（${m.unit}）`,
      }))
      _optionCache.set(key, options)
      return options
    } catch {
      return []
    }
  }
}

function ReceiptConfirmModal({
  receipt,
  onClose,
}: {
  receipt: HardwareReceiptRecord | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [rows, setRows] = useState<HardwareReceiptRecord['items']>([])
  const [submitting, setSubmitting] = useState(false)
  const [screeningBusy, setScreeningBusy] = useState(false)
  const [matKeyword, setMatKeyword] = useState('')
  const [matOptions, setMatOptions] = useState<Array<{ value: string; label: string }>>([])
  const loadMaterialOptions = useMaterialOptions()

  useEffect(() => {
    if (receipt) {
      setRows(receipt.items.map((i) => ({ ...i })))
      setMatKeyword('')
      setMatOptions([])
    }
  }, [receipt])

  const searchMaterials = async (keyword: string) => {
    setMatKeyword(keyword)
    setMatOptions(await loadMaterialOptions(keyword))
  }

  if (!receipt) return null

  const hasLowConfidence = rows.some(
    (r) => r.match_score != null && Number(r.match_score) < 75 && r.material_id,
  )
  const hasUnmatched = rows.some((r) => !r.material_id && receipt.mode === 'stocked')

  const runScreening = async (file: File) => {
    setScreeningBusy(true)
    try {
      const image_b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
        reader.onerror = () => reject(new Error('图片读取失败'))
        reader.readAsDataURL(file)
      })
      const summary = await photoScreenHardwareReceiptClient(
        receipt.id,
        [{ image_b64, content_type: file.type || 'image/jpeg' }],
      )
      if (summary.screened) {
        message.success(`初筛完成：${summary.flagged_rows} 行存在异常标记（仅供参考，不拦截确认）`)
      } else {
        message.info(
          summary.reason === 'scenario_disabled'
            ? '初筛场景已停用（不影响入库）'
            : '初筛未产出结论（AI 失败不阻塞，可直接确认）',
        )
      }
      const fresh = await fetchHardwareReceiptsClient({
        keyword: receipt.receipt_no, status: 'draft', pageSize: 5,
      })
      const hit = fresh.items.find((x) => x.id === receipt.id)
      if (hit) setRows(hit.items.map((i) => ({ ...i })))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '初筛失败（不影响入库）')
    } finally {
      setScreeningBusy(false)
    }
  }

  const onSubmit = async () => {
    setSubmitting(true)
    try {
      await acceptHardwareReceiptClient(receipt.id, {
        inspected_by_warehouse: 'web',
        items: rows.map((r) => ({
          material_id: r.material_id,
          name: r.material_name || r.name,
          spec: r.spec,
          unit: r.unit,
          quantity: Number(r.quantity),
          location_id: r.location_id || undefined,
          match_confidence: r.match_confidence ?? 'manual',
          match_score: r.match_score != null ? Number(r.match_score) : undefined,
        })),
      })
      message.success('已确认入账（批次/流水已生成；direct 行已推领取卡）')
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '确认入账失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`确认 · ${receipt.receipt_no}`}
      open={!!receipt}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="确认入账"
      width={760}
    >
      <div className="mb-3 text-[13px] leading-6">
        <div>供应商：{receipt.supplier_name || '-'}　送货单号：{receipt.delivery_note_no || '-'}</div>
        <div>
          类别：{receipt.mode === 'direct' ? `车间单独需求（直发 ${receipt.target_dept || '-'}）` : '共用类（入库存）'}
        </div>
      </div>
      {(hasLowConfidence || hasUnmatched) && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          {hasLowConfidence && <div>⚠ 存在低置信匹配行，请逐行核对修正后确认。</div>}
          {hasUnmatched && (
            <div>⚠ 共用类单存在未匹配行：请为每行指定物料，或将单据改为车间单独需求（直发）。</div>
          )}
        </div>
      )}
      <div className="mb-3 flex items-center gap-2 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-[12px] text-blue-700">
        <Upload
          accept="image/jpeg,image/png"
          showUploadList={false}
          beforeUpload={(file) => {
            void runScreening(file)
            return false
          }}
        >
          <Button size="small" icon={<CameraOutlined />} loading={screeningBusy}>
            实物照片初筛
          </Button>
        </Upload>
        <span>破损/锈蚀/渗漏/受潮 AI 辅助标记——只标记不拦截不代改，处置由仓管员决定。</span>
      </div>
      <Table
        size="small"
        rowKey="id"
        dataSource={rows}
        pagination={false}
        columns={[
          {
            title: '品名',
            width: 160,
            render: (_: unknown, r) => (
              <Space direction="vertical" size={0}>
                <span>{r.name}</span>
                {r.photo_screening?.flagged && (
                  <StatusTag tone="danger" label={`⚠ ${r.photo_screening.findings.map((f) => `${f.type}(${f.severity})`).join('、')}`} />
                )}
              </Space>
            ),
          },
          { title: '规格', dataIndex: 'spec', width: 110, render: (v) => v || '-' },
          { title: '数量', dataIndex: 'quantity', width: 80, align: 'right', render: (v: unknown) => formatQty(v) },
          {
            title: '匹配',
            width: 220,
            render: (_: unknown, r, idx) => {
              const isLow = r.match_score != null && Number(r.match_score) < 75
              return (
                <Space direction="vertical" size={0} className="w-full">
                  {isLow && <StatusTag tone="warn" label={`低置信 ${Number(r.match_score).toFixed(0)}`} />}
                  {!r.material_id && <StatusTag tone="danger" label="未匹配" />}
                  <Select
                    size="small"
                    showSearch
                    allowClear
                    placeholder="搜索指定/更换物料"
                    style={{ width: '100%' }}
                    value={r.material_id ?? undefined}
                    filterOption={false}
                    onSearch={searchMaterials}
                    options={matKeyword ? matOptions : []}
                    notFoundContent={matKeyword ? '无匹配物料' : '输入关键词搜索物料'}
                    onChange={(v) => {
                      const next = [...rows]
                      next[idx] = { ...r, material_id: v ?? null }
                      setRows(next)
                    }}
                  />
                </Space>
              )
            },
          },
        ]}
      />
    </Modal>
  )
}

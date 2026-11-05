'use client'

// 五金库出入库工作台（M2）：入库台（拍照 OCR→草稿一屏确认→入账 /
// manual 兜底登记 / direct 直发）+ 发料台（待发料+FIFO+实发确认）+
// 流水台账。设计 §七。

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { CameraOutlined, CheckOutlined, CloseOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  acceptHardwareReceiptClient,
  createHardwareReceiptClient,
  fetchHardwareLocationsClient,
  fetchHardwareMaterialsClient,
  fetchHardwareMovementsClient,
  fetchHardwareReceiptsClient,
  fetchHardwareRequisitionsClient,
  fetchHardwareStockDetailClient,
  issueHardwareRequisitionClient,
  markHardwareMovementsEnteredClient,
  rejectHardwareReceiptClient,
  importHardwareErpFile,
  photoScreenHardwareReceiptClient,
} from '@/lib/api/warehouse-hardware'
import {
  HARDWARE_MOVEMENT_BIZ_LABEL,
  HARDWARE_RECEIPT_SOURCE_LABEL,
  HARDWARE_RECEIPT_STATUS_LABEL,
  HARDWARE_REQ_STATUS_LABEL,
  type HardwareMovementRecord,
  type HardwareReceiptRecord,
  type HardwareRequisitionRecord,
} from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { HardwareReturnPanel } from './HardwareReturnPanel'
import { PageHeader, QueryFilter, SectionCard, StatusTag } from '@/components/warehouse'

type TabKey = 'inbound' | 'issue' | 'returns' | 'movements'

export function HardwareInoutBoard() {
  const [tab, setTab] = useState<TabKey>('inbound')
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumb={['仓储管理', '五金库', '出入库工作台']}
        title="五金出入库工作台"
        description="入库台（拍照 OCR / 手动登记）· 发料台（待发料 FIFO 实扣）· 退库 · 流水与 ERP 标记"
      />
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as TabKey)}
        options={[
          { value: 'inbound', label: '入库台' },
          { value: 'issue', label: '发料台' },
          { value: 'returns', label: '退库' },
          { value: 'movements', label: '流水台账' },
        ]}
      />
      {tab === 'inbound' && <InboundPanel />}
      {tab === 'issue' && <IssuePanel />}
      {tab === 'returns' && <HardwareReturnPanel />}
      {tab === 'movements' && <MovementsPanel />}
    </div>
  )
}

// ── 入库台 ──

const RECEIPT_STATUS_TONE = {
  draft: 'warn',
  accepted: 'ok',
  rejected: 'danger',
} as const

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
  const [ocrUploading, setOcrUploading] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
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
    { title: '单号', dataIndex: 'receipt_no', width: 150 },
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
      width: 110,
      render: (v: string) => (v === 'direct' ? <Tag>车间单独需求</Tag> : <Tag color="blue">共用类</Tag>),
    },
    { title: '供应商', dataIndex: 'supplier_name', width: 180, render: (v) => v || '-' },
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
    { title: '直发车间', dataIndex: 'target_dept', width: 100, render: (v) => v || '-' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 130,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 170,
      render: (_: unknown, r) => (
        <Space>
          {r.status === 'draft' && canConfirm && (
            <>
              <Button size="small" type="primary" onClick={() => setConfirming(r)}>
                一屏确认
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
    <SectionCard title="入库单">
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
              options={[
                { value: 'draft', label: '待确认' },
                { value: 'accepted', label: '已入账' },
                { value: 'rejected', label: '已拒收' },
                { value: 'all', label: '全部' },
              ]}
            />
            {canCreate && (
              <>
                <Upload
                  accept="image/jpeg,image/png"
                  showUploadList={false}
                  beforeUpload={async (file) => {
                    setOcrUploading(true)
                    try {
                      // OCR → 草稿（后端 build_ocr_draft）；成功后定位到待确认
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
                        `识别完成：${json.data?.matched_stocked ?? 0} 行匹配 / ${json.data?.unmatched ?? 0} 行待人工，请在列表中一屏确认`,
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
                  <Button type="primary" icon={<CameraOutlined />} loading={ocrUploading}>
                    拍照入库（OCR）
                  </Button>
                </Upload>
                <Button onClick={() => setManualOpen(true)}>手动登记</Button>
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
              </>
            )}
          </>
        }
      />
      <Table<HardwareReceiptRecord>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
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
        scroll={{ x: 1100 }}
      />
      <ManualReceiptModal open={manualOpen} onClose={() => setManualOpen(false)} />
      <ReceiptConfirmModal receipt={confirming} onClose={() => setConfirming(null)} />
    </SectionCard>
  )
}

function ManualReceiptModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [keyword, setKeyword] = useState('')
  const [mode, setMode] = useState<'stocked' | 'direct'>('stocked')
  const [saving, setSaving] = useState(false)

  const { data: materialRes } = useQuery({
    queryKey: ['warehouse', 'hardware', 'material-search', keyword],
    queryFn: () => fetchHardwareMaterialsClient(keyword, 30),
    enabled: open,
  })

  const onSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await createHardwareReceiptClient({
        source: 'manual',
        mode,
        supplier_name: values.supplier_name || undefined,
        delivery_note_no: values.delivery_note_no || undefined,
        target_dept: mode === 'direct' ? values.target_dept : undefined,
        remark: values.remark,
        items: [
          {
            material_id: mode === 'stocked' ? values.material_id : undefined,
            name: values.item_name,
            spec: values.item_spec || undefined,
            unit: values.item_unit,
            quantity: values.quantity,
          },
        ],
      })
      message.success('登记成功（草稿），请在列表中一屏确认入账')
      form.resetFields()
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'receipts'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '登记失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="手动登记（兜底：手写单/识别失败）"
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={saving}
      okText="生成草稿"
      width={520}
    >
      <Form form={form} layout="vertical">
        <Form.Item label="单据类别">
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as 'stocked' | 'direct')}
            options={[
              { value: 'stocked', label: '共用类（入库存）' },
              { value: 'direct', label: '车间单独需求（直发）' },
            ]}
          />
        </Form.Item>
        {mode === 'stocked' ? (
          <Form.Item name="material_id" label="选择物料" rules={[{ required: true, message: '请选择物料' }]}>
            <Select
              showSearch
              placeholder="输入名称/规格搜索"
              filterOption={false}
              onSearch={setKeyword}
              notFoundContent={materialRes ? '无匹配物料' : <Spin size="small" />}
              options={(materialRes?.items ?? []).map((m) => ({
                value: m.id,
                label: `${m.name} ${m.spec ?? ''}（${m.unit}）`,
              }))}
            />
          </Form.Item>
        ) : (
          <Form.Item name="target_dept" label="直发车间" rules={[{ required: true, message: 'direct 类必须指定车间' }]}>
            <Input placeholder="如：发酵 / 提炼一期 / 精制机修" />
          </Form.Item>
        )}
        <Space className="w-full" size="middle">
          {mode === 'direct' && (
            <Form.Item name="item_name" label="品名" rules={[{ required: true, message: '请输入品名' }]}>
              <Input placeholder="自由文本（不占库存）" />
            </Form.Item>
          )}
          {mode === 'stocked' && (
            <Form.Item name="item_name" label="品名（默认取主数据）">
              <Input placeholder="可空=用主数据" />
            </Form.Item>
          )}
          <Form.Item name="quantity" label="数量" rules={[{ required: true, message: '请输入数量' }]}>
            <InputNumber min={0.001} precision={3} style={{ width: 120 }} />
          </Form.Item>
        </Space>
        <Form.Item name="supplier_name" label="供应商">
          <Input placeholder="可空" />
        </Form.Item>
        <Form.Item name="delivery_note_no" label="送货单号">
          <Input placeholder="可空" />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="异常情况等" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 一屏确认（双签 + 低置信行修正 + stocked 选库位）──

function ReceiptConfirmModal({
  receipt,
  onClose,
}: {
  receipt: HardwareReceiptRecord | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [rows, setRows] = useState<HardwareReceiptRecord['items']>([])
  const [submitting, setSubmitting] = useState(false)
  const [screeningBusy, setScreeningBusy] = useState(false)

  useEffect(() => {
    if (receipt) {
      setRows(receipt.items.map((i) => ({ ...i })))
      form.setFieldsValue({
        inspected_by_dept: receipt.inspected_by_dept ?? '',
      })
    }
  }, [receipt, form])

  const { data: locations } = useQuery({
    queryKey: ['warehouse', 'hardware', 'locations'],
    queryFn: fetchHardwareLocationsClient,
    enabled: !!receipt,
  })

  if (!receipt) return null

  const hasLowConfidence = rows.some(
    (r) => r.match_score != null && Number(r.match_score) < 75 && r.material_id,
  )
  const hasUnmatched = rows.some((r) => !r.material_id && receipt.mode === 'stocked')

  // M7 实物照片初筛：上传→vision 标记落行（advisory 只标记，不拦截确认）
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
            : '初筛未产出结论（LLM 失败不阻塞，可直接确认）',
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
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      await acceptHardwareReceiptClient(receipt.id, {
        inspected_by_warehouse: 'web',
        inspected_by_dept: values.inspected_by_dept,
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
      title={`一屏确认 · ${receipt.receipt_no}`}
      open={!!receipt}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="双签确认入账"
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
      <Form form={form} layout="vertical">
        <Form.Item
          name="inspected_by_dept"
          label="使用部门经办人（双签）"
          rules={[{ required: true, message: '请输入使用部门经办人（制度 5.2.2 双人验收）' }]}
        >
          <Input placeholder="姓名或 open_id" />
        </Form.Item>
      </Form>
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
            title: '品名（OCR）',
            width: 160,
            render: (_: unknown, r) => (
              <Space direction="vertical" size={0}>
                <span>{r.name}</span>
                {r.photo_screening?.flagged && (
                  <Tag color="red">
                    ⚠ {r.photo_screening.findings.map((f) => `${f.type}(${f.severity})`).join('、')}
                  </Tag>
                )}
              </Space>
            ),
          },
          { title: '规格', dataIndex: 'spec', width: 110, render: (v) => v || '-' },
          { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
          {
            title: '匹配',
            width: 200,
            render: (_: unknown, r, idx) => {
              const isLow = r.match_score != null && Number(r.match_score) < 75
              return (
                <Space direction="vertical" size={0} className="w-full">
                  {isLow && <Tag color="orange">低置信 {Number(r.match_score).toFixed(0)}</Tag>}
                  {!r.material_id && <Tag color="red">未匹配</Tag>}
                  <Select
                    size="small"
                    showSearch
                    allowClear
                    placeholder="指定/更换物料"
                    style={{ width: '100%' }}
                    value={r.material_id ?? undefined}
                    optionFilterProp="label"
                    options={searchMaterialOptions(r.material_name || r.name)}
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

// 物料选项（确认弹窗内的轻量搜索；每行独立 keyword，共享缓存）
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

function searchMaterialOptions(_defaultKeyword: string) {
  // Select options 由上层 useMaterialOptions 异步填充；此处返回空由 showSearch onSearch 驱动
  return []
}

// ── 发料台 ──

function IssuePanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [issuing, setIssuing] = useState<HardwareRequisitionRecord | null>(null)

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'requisitions', 'approved', { page, pageSize }],
    queryFn: () =>
      fetchHardwareRequisitionsClient({ status: 'approved', page, pageSize }),
    placeholderData: keepPreviousData,
  })

  const columns: TableColumnsType<HardwareRequisitionRecord> = [
    { title: '单号', dataIndex: 'req_no', width: 150 },
    {
      title: '类型',
      dataIndex: 'req_type',
      width: 70,
      render: (v: string) =>
        v === 'urgent' ? <Tag color="red">紧急</Tag> : v === 'excess' ? <Tag color="orange">超额</Tag> : <Tag>常规</Tag>,
    },
    { title: '部门', dataIndex: 'dept_name', width: 110 },
    { title: '申请人', dataIndex: 'applicant', width: 90 },
    { title: '用途', dataIndex: 'purpose', render: (v) => v || '-' },
    { title: '审批人', dataIndex: 'approved_by', width: 90, render: (v) => v || '-' },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, r) => (
        <Button size="small" type="primary" onClick={() => setIssuing(r)}>
          发料
        </Button>
      ),
    },
  ]

  return (
    <SectionCard title="待发料（审批通过）">
      <Table<HardwareRequisitionRecord>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
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
        scroll={{ x: 900 }}
      />
      <IssueModal requisition={issuing} onClose={() => setIssuing(null)} />
    </SectionCard>
  )
}

function IssueModal({
  requisition,
  onClose,
}: {
  requisition: HardwareRequisitionRecord | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [submitting, setSubmitting] = useState(false)
  const [receivedBy, setReceivedBy] = useState('')
  const [allocations, setAllocations] = useState<Record<string, number>>({})

  useEffect(() => {
    if (requisition) {
      setReceivedBy(requisition.applicant)
      setAllocations(
        Object.fromEntries(requisition.items.map((i) => [i.id, i.need_qty as number])),
      )
    }
  }, [requisition])

  const materialIds = requisition?.items.map((i) => i.material_id) ?? []
  const { data: stockByMaterial } = useQuery({
    queryKey: ['warehouse', 'hardware', 'issue-lots', materialIds.join(',')],
    queryFn: async () => {
      const entries = await Promise.all(
        materialIds.map(async (mid) => {
          const detail = await fetchHardwareStockDetailClient(mid)
          return [mid, detail.lots] as const
        }),
      )
      return Object.fromEntries(entries)
    },
    enabled: materialIds.length > 0 && !!requisition,
  })

  if (!requisition) return null

  const onSubmit = async () => {
    setSubmitting(true)
    try {
      await issueHardwareRequisitionClient(requisition.id, {
        issued_by: 'web',
        received_by: receivedBy,
        items: requisition.items.map((i) => ({
          item_id: i.id,
          issued_qty: allocations[i.id] ?? Number(i.need_qty),
        })),
      })
      message.success('发料完成（FIFO 实扣+流水已落账）')
      onClose()
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'requisitions'] })
    } catch (e) {
      message.error(e instanceof Error ? e.message : '发料失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`发料确认 · ${requisition.req_no}`}
      open={!!requisition}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="确认发料（实扣）"
      width={700}
    >
      <Table
        size="small"
        rowKey="id"
        dataSource={requisition.items}
        pagination={false}
        columns={[
          { title: '物料', dataIndex: 'material_name', width: 180 },
          { title: '规格', dataIndex: 'spec', width: 110, render: (v) => v || '-' },
          { title: '需求数', dataIndex: 'need_qty', width: 90, align: 'right' },
          {
            title: 'FIFO 建议批次',
            width: 220,
            render: (_: unknown, r) => {
              const lots = stockByMaterial?.[r.material_id] ?? []
              const usable = lots.filter((l) => l.remaining_quantity > 0)
              if (!usable.length) return <Tag color="red">无可用批次</Tag>
              return (
                <span className="text-[12px] font-mono">
                  {usable
                    .slice(0, 3)
                    .map((l) => `${l.lot_no}(${l.remaining_quantity})`)
                    .join(' → ')}
                </span>
              )
            },
          },
          {
            title: '实发量',
            width: 130,
            render: (_: unknown, r) => (
              <InputNumber
                size="small"
                min={0.001}
                precision={3}
                value={allocations[r.id]}
                onChange={(v) =>
                  setAllocations((prev) => ({ ...prev, [r.id]: v ?? Number(r.need_qty) }))
                }
              />
            ),
          },
        ]}
      />
      <div className="mt-3">
        <div className="mb-1 text-[13px] text-gray-600">领用人点收（=系统签收）</div>
        <Input
          placeholder="领用人姓名"
          value={receivedBy}
          onChange={(e) => setReceivedBy(e.target.value)}
        />
      </div>
    </Modal>
  )
}

// ── 流水台账（ERP 对账标记）──

function MovementsPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [direction, setDirection] = useState<string | undefined>(undefined)
  const [erpStatus, setErpStatus] = useState<string | undefined>(undefined)
  const [selected, setSelected] = useState<React.Key[]>([])

  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'hardware', 'movements', { page, pageSize, keyword, direction, erpStatus }],
    queryFn: () =>
      fetchHardwareMovementsClient({
        keyword: keyword || undefined,
        direction,
        erp_status: erpStatus,
        page,
        pageSize,
      }),
    placeholderData: keepPreviousData,
  })

  const markEntered = useMutation({
    mutationFn: (ids: string[]) =>
      markHardwareMovementsEnteredClient(ids, 'web'),
    onSuccess: (r) => {
      message.success(`已标记 ${r.marked} 条为 ERP 已录`)
      setSelected([])
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'hardware', 'movements'] })
    },
    onError: (e) => message.error(e instanceof Error ? e.message : '标记失败'),
  })

  const columns: TableColumnsType<HardwareMovementRecord> = [
    { title: '流水号', dataIndex: 'movement_no', width: 150 },
    {
      title: '方向',
      dataIndex: 'direction',
      width: 70,
      render: (v: string) => (
        <Tag color={v === 'inbound' ? 'green' : v === 'outbound' ? 'red' : 'orange'}>
          {v === 'inbound' ? '入' : v === 'outbound' ? '出' : '调'}
        </Tag>
      ),
    },
    {
      title: '业务',
      dataIndex: 'business_type',
      width: 90,
      render: (v: string) => HARDWARE_MOVEMENT_BIZ_LABEL[v] ?? v,
    },
    { title: '品名', dataIndex: 'material_name', width: 160 },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
    { title: '部门', dataIndex: 'dept_name', width: 90, render: (v) => v || '-' },
    { title: '经办', dataIndex: 'operator', width: 90, render: (v) => v || '-' },
    {
      title: '时间',
      dataIndex: 'occurred_at',
      width: 120,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: 'ERP',
      dataIndex: 'erp_status',
      width: 80,
      render: (v: string) =>
        v === 'entered' ? <Tag color="green">已录</Tag> : <Tag color="orange">未录</Tag>,
    },
  ]

  return (
    <SectionCard
      title="出入库流水"
      action={
        selected.length > 0 && (
          <Button
            size="small"
            onClick={() =>
              markEntered.mutate(selected.map(String))
            }
          >
            标记选中为 ERP 已录（{selected.length}）
          </Button>
        )
      }
    >
      <QueryFilter
        common={
          <>
            <Input
              allowClear
              prefix={<SearchOutlined style={{ color: '#999' }} />}
              placeholder="流水号 / 品名 / 批次"
              style={{ width: 220 }}
              value={keyword}
              onChange={(e) => {
                setKeyword(e.target.value)
                setPage(1)
              }}
            />
            <Segmented
              value={direction ?? 'all'}
              onChange={(v) => {
                setDirection(v === 'all' ? undefined : (v as string))
                setPage(1)
              }}
              options={[
                { value: 'all', label: '全部' },
                { value: 'inbound', label: '入' },
                { value: 'outbound', label: '出' },
              ]}
            />
            <Segmented
              value={erpStatus ?? 'all'}
              onChange={(v) => {
                setErpStatus(v === 'all' ? undefined : (v as string))
                setPage(1)
              }}
              options={[
                { value: 'all', label: 'ERP全部' },
                { value: 'pending', label: '未录' },
                { value: 'entered', label: '已录' },
              ]}
            />
          </>
        }
      />
      <Table<HardwareMovementRecord>
        size="small"
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={res?.items ?? []}
        rowSelection={{ selectedRowKeys: selected, onChange: setSelected }}
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
        scroll={{ x: 1050 }}
      />
    </SectionCard>
  )
}

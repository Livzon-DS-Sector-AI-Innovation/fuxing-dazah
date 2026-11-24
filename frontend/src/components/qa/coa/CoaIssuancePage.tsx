'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Spin,
  Table,
  Tooltip,
  Upload,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckCircleFilled,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  FileAddOutlined,
  FileTextOutlined,
  InboxOutlined,
  LeftOutlined,
  LoadingOutlined,
  PlusOutlined,
  RightOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { actionError } from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { createCoaReport, deleteCoaReport, updateCoaReport } from '@/actions/qa'
import {
  fetchCoaMatrix,
  fetchCoaProducts,
  fetchCoaReportDetail,
  fetchCoaStandardDetail,
  fetchCoaStandards,
  importCoaReportPreview,
} from '@/lib/api/qa'
import type {
  CoaProductField,
  CoaReport,
  CoaReportImportPreview,
  CoaReportInput,
  CoaStandard,
  CoaStandardItem,
  CoaValueInput,
} from '@/types/qa'
import {
  CoaResultInput,
  draftToValueInput,
  emptyResultDraft,
  toResultDraft,
} from './CoaResultInput'
import type { CoaResultDraft } from './CoaResultInput'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import { reportColumnKeyOf, stripBuiltinFields } from './CoaBatchFieldsEditor'
import type { CoaReportColumn } from './CoaBatchFieldsEditor'
import styles from './CoaIssuancePage.module.css'

/** 模板单选下拉的展示名。 */
function standardLabel(s: CoaStandard) {
  return `${s.code} ${s.name}${s.customer ? ` · ${s.customer}` : ''}`
}

/** 矩阵值：数值等宽居中；文字单行省略；空值弱化。 */
function MatrixValue({ value }: { value?: { num: number | null; text: string | null } }) {
  if (!value) return <span className={styles.emptyCell}>—</span>
  if (value.num != null) return <span className={styles.numValue}>{value.num}</span>
  if (!value.text) return <span className={styles.emptyCell}>—</span>
  return (
    <span className={styles.cellEllipsis} title={value.text}>
      {value.text}
    </span>
  )
}

function InlineValue(value: number | null | undefined, text: string | null | undefined) {
  if (value != null) return <span className={styles.numValue}>{value}</span>
  if (!text) return <span className={styles.emptyCell}>—</span>
  return <span className={styles.cellEllipsis} title={text}>{text}</span>
}

/** 日期原文 → ISO 文本。与后端 parse_date_text 同一条规则（2026.07.29 / 2026-07-29 /
 *  2026/7/9，可夹在文字里）：这里认不出的原文，提交后后端同样会拒。 */
function toIsoDate(raw: string): string | null {
  const m = raw.match(/(\d{4})[.\-/年](\d{1,2})[.\-/月](\d{1,2})/)
  if (!m) return null
  const parsed = dayjs(`${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`)
  if (!parsed.isValid()) return null
  // dayjs 宽松解析会把 2026.02.30 滚成 3 月 2 日：回读年月日，滚过的按无效处理
  if (
    parsed.year() !== Number(m[1]) ||
    parsed.month() + 1 !== Number(m[2]) ||
    parsed.date() !== Number(m[3])
  ) {
    return null
  }
  return parsed.format('YYYY-MM-DD')
}

/** 报告信息侧栏的横向表单布局：左标签右输入，72px 标签列与上方只读行对齐。 */
const PANEL_FORM_LAYOUT = {
  layout: 'horizontal',
  labelAlign: 'left',
  labelWrap: true,
  labelCol: { flex: '0 0 72px' },
  wrapperCol: { flex: 'auto' },
  className: styles.panelForm,
} as const

/** 检测结果录入单的列：序号 / 检测项目 / 标准要求 / 结果。手工登记与导入登记共用，
 *  两处录入单永远同构。 */
function resultSheetColumns(
  draftOf: (item: CoaStandardItem) => CoaResultDraft,
  onDraftChange: (item: CoaStandardItem, draft: CoaResultDraft) => void,
): ColumnsType<CoaStandardItem> {
  return [
    {
      title: '#',
      key: 'index',
      width: 44,
      render: (_v, _row, index) => <span className={styles.sheetIndex}>{index + 1}</span>,
    },
    {
      title: '检测项目',
      key: 'item',
      render: (_v, row) => <span className={styles.entryName}>{row.name_cn}</span>,
    },
    {
      title: '标准要求',
      key: 'spec',
      render: (_v, row) =>
        row.spec_text ? (
          <span className={styles.entrySpec} title={row.spec_text}>
            {row.spec_text}
          </span>
        ) : (
          <span className={styles.emptyCell}>—</span>
        ),
    },
    {
      title: '结果',
      key: 'value',
      width: 272,
      render: (_v, row) => (
        <CoaResultInput
          itemKey={row.id}
          label={row.name_cn}
          draft={draftOf(row)}
          unit={row.unit ?? null}
          onChange={(next) => onDraftChange(row, next)}
        />
      ),
    },
  ]
}

/** 手工登记 / 编辑报告：左侧检测结果录入单（占满高度、内部滚动、表头吸顶）+
 * 右侧报告信息侧栏（品名/客户标准只读；批号/流水号/模板动态批次字段）。
 * 品名由所选产品带出（只读）；业务键为产品+模板+批号，
 * 模板字段命中报告固定列（生产日期/包装等）由后端镜像落列。 */
function CoaReportFormModal({
  onClose,
  product,
  standard,
  batchFields,
  editing,
  onSaved,
}: {
  onClose: () => void
  product: { id: string; code: string; name: string; name_en?: string | null }
  standard: CoaStandard & { items?: CoaStandardItem[] }
  /** 生效批次字段集（内置 3 键 + 自定义键）。 */
  batchFields: CoaProductField[]
  /** 编辑对象（null=新建）。 */
  editing: CoaReport | null
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  // 结果编辑覆盖层：item_id → 草稿（行内输入直接改这里；基值派生合并，勿镜像进 state）
  const [draftOverrides, setDraftOverrides] = useState<Record<string, CoaResultDraft>>({})

  const detailQuery = useQuery({
    queryKey: ['qa', 'coa', 'report-detail', editing?.id],
    queryFn: () => fetchCoaReportDetail(editing!.id),
    enabled: !!editing,
  })
  const detail = detailQuery.data
  // 详情未就绪时保存会把 values/batch_data 全量替换成空 → 清空历史数据
  const detailPending = !!editing && (detailQuery.isLoading || detailQuery.isError)

  const items = standard.items ?? []
  // 内置 3 字段中批号/流水号走头表单、品名由产品带出，只剩自定义键渲染动态输入
  const customFields = useMemo(() => stripBuiltinFields(batchFields), [batchFields])

  // 结果基值 + 行内覆盖层（派生计算，React Compiler 自动记忆化）。
  // 新建态基值：text 型项目的标准默认值（快捷填写基底层）；编辑态基值：详情原值，
  // 不预填默认值——防保存时给历史报告无声补值。其余项目的空草稿按模板类型定形态
  const baseDraft: Record<string, CoaResultDraft> = {}
  if (editing) {
    for (const v of detail?.values ?? []) baseDraft[v.item_id] = toResultDraft(v)
  } else {
    for (const it of items) {
      if (it.value_type === 'text' && it.default_value) {
        baseDraft[it.id] = { mode: 'text', raw: it.default_value, num: null, text: it.default_value }
      }
    }
  }
  const valueDraft = { ...baseDraft, ...draftOverrides }
  const draftOf = (it: CoaStandardItem): CoaResultDraft =>
    valueDraft[it.id] ?? emptyResultDraft(it.value_type)
  const filledCount = items.filter((it) => draftOf(it).raw.trim() !== '').length

  // 编辑态回填：头字段 + 动态批次字段（batch_info 键=字段键；date 转 dayjs）。
  // setFieldsValue 是 antd 命令式 API 而非 setState，放 effect 不触发渲染期更新
  useEffect(() => {
    if (!detail) return
    const bfValues: Record<string, unknown> = {}
    for (const f of customFields) {
      const raw = detail.batch_info?.[f.key]
      bfValues[`bf_${f.key}`] =
        f.field_type === 'date' ? (raw ? dayjs(raw) : null) : (raw ?? '')
    }
    form.setFieldsValue({
      batch_no: detail.batch_no,
      serial_no: detail.serial_no ?? '',
      ...bfValues,
    })
  }, [detail, form, customFields])

  const handleSave = async () => {
    if (detailPending) return
    const values = await form.validateFields()
    const valueInputs: CoaValueInput[] = []
    for (const item of items) {
      const input = draftToValueInput(item.id, draftOf(item))
      if (input) valueInputs.push(input)
    }
    // 动态批次字段 → batch_data（date 转 ISO；空值不进键，配合后端全量替换=清空）
    const batchData: Record<string, string> = {}
    for (const f of customFields) {
      const raw = values[`bf_${f.key}`]
      if (raw == null || String(raw).trim() === '') continue
      batchData[f.key] =
        f.field_type === 'date' && dayjs.isDayjs(raw)
          ? raw.format('YYYY-MM-DD')
          : String(raw).trim()
    }
    setSaving(true)
    try {
      const head = {
        batch_no: values.batch_no.trim(),
        serial_no: values.serial_no.trim(),
      }
      const result = editing
        ? await updateCoaReport(editing.id, { ...head, batch_data: batchData, values: valueInputs })
        : await createCoaReport({
            product_id: product.id,
            standard_id: standard.id,
            ...head,
            batch_data: batchData,
            values: valueInputs,
          })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(editing ? '报告已更新' : '出具登记完成')
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const reset = () => {
    form.resetFields()
    setDraftOverrides({})
  }

  return (
    <Modal
      title={editing ? '编辑报告' : '手工登记'}
      open
      width={1120}
      centered
      className={styles.entryModal}
      onCancel={() => {
        reset()
        onClose()
      }}
      footer={[
        <Button key="cancel" onClick={() => { reset(); onClose() }}>
          取消
        </Button>,
        <Button
          key="save"
          type="primary"
          loading={saving}
          disabled={detailPending}
          onClick={handleSave}
        >
          {editing ? '保存' : '登记'}
        </Button>,
      ]}
    >
      {editing && detailQuery.isLoading ? (
        <div className={styles.entryState}>
          <Spin size="small" /> 正在加载报告详情…
        </div>
      ) : detailQuery.isError ? (
        <div className={styles.entryState}>
          <span className={styles.detailError}>报告详情加载失败，请关闭后重试。</span>
        </div>
      ) : (
        <div className={styles.entryBody}>
          <section className={styles.entrySheet}>
            <div className={styles.entryHead}>
              <h3 className={styles.entryTitle}>检测结果</h3>
              <span className={styles.sheetMeta}>
                已填 {filledCount} / {items.length}
              </span>
            </div>
            <div className={styles.sheetScroll} data-coa-result-scope>
              <Table<CoaStandardItem>
                rowKey="id"
                size="small"
                className={styles.sheetTable}
                dataSource={items}
                pagination={false}
                tableLayout="fixed"
                locale={{
                  emptyText: <div className={styles.inlineEmpty}>该模板还没有检测项目</div>,
                }}
                columns={resultSheetColumns(draftOf, (item, next) =>
                  setDraftOverrides((prev) => ({ ...prev, [item.id]: next })),
                )}
              />
            </div>
          </section>

          <section className={styles.entryPanel}>
            <h3 className={styles.entryTitle}>报告信息</h3>
            <dl className={styles.panelMeta}>
              <dt>品名</dt>
              <dd
                title={
                  product.name_en ? `${product.code} ${product.name} ${product.name_en}` : undefined
                }
              >
                {product.code} {product.name}
                {product.name_en && <small>{product.name_en}</small>}
              </dd>
              <dt>客户标准</dt>
              <dd title={standard.name}>
                {standard.code}
                {standard.name && <small>{standard.name}</small>}
              </dd>
            </dl>

            <Form form={form} {...PANEL_FORM_LAYOUT}>
              <Form.Item name="batch_no" label="批号" rules={[{ required: true, message: '请输入批号' }]}>
                <Input placeholder="如 TEST001" />
              </Form.Item>
              <Form.Item name="serial_no" label="流水号" rules={[{ required: true, message: '请输入流水号' }]}>
                <Input placeholder="如 001" />
              </Form.Item>
              {customFields.map((f) => (
                <Form.Item key={f.key} name={`bf_${f.key}`} label={f.label_cn}>
                  {f.field_type === 'date' ? (
                    <DatePicker style={{ width: '100%' }} />
                  ) : (
                    <Input />
                  )}
                </Form.Item>
              ))}
            </Form>
          </section>
        </div>
      )}
    </Modal>
  )
}

// ─────────────────────── docx 批量导入 ───────────────────────

/** 同时最多解析的份数：每份都要跑一次 AI 识别，限并发边解析边审
 *  （实测 3 路并发接口全部成功）。 */
const IMPORT_PARSE_CONCURRENCY = 3

/** 每份文件最多尝试解析的次数：OCR 偶发返回空页，自动重试一次再判失败。 */
const IMPORT_PARSE_ATTEMPTS = 2

type ImportEntryStatus = 'parsing' | 'ready' | 'failed' | 'registered'

/** 导入队列里的一份文件及其全部审核状态。每份文件的识别结果、行内修正、校验态
 *  互相隔离，全部放在父组件的条目里——切换文件时离场/入场各渲染一次也不丢编辑。 */
interface CoaImportEntry {
  id: string
  file: File
  status: ImportEntryStatus
  /** 解析失败原因（status=failed）。 */
  error?: string | null
  /** 识别结果。重新解析期间旧预览保留，审核区压暗等待。 */
  preview?: CoaReportImportPreview | null
  /** 用户为这份文件显式选过的客户标准（重新解析时带上）。 */
  pickedStandard?: string | null
  /** 结果编辑覆盖层：item_id → 草稿（识别值可直接修正；基值派生合并）。 */
  valueEdits: Record<string, CoaResultDraft>
  /** 批次字段编辑覆盖层：字段键 → 原文（日期字段存 ISO 文本）。 */
  batchEdits: Record<string, string>
  /** 点过登记后才显示必填错误。 */
  submitted: boolean
  /** 左栏视图：检测结果 / 标准外项目（docx 有、模板没有，不录入）。 */
  view: 'results' | 'unmatched'
  /** 登记成功后的批号与结果数（文件列表与完成态用）。 */
  registeredBatchNo?: string | null
  registeredValues?: number
}

interface ParseJob {
  id: string
  file: File
  standardId: string | null
}

const coaStandardDetailQuery = (standardId: string) => ({
  queryKey: ['qa', 'coa', 'standard-detail', standardId],
  queryFn: () => fetchCoaStandardDetail(standardId),
})

const fileKey = (file: File) => `${file.name}|${file.size}|${file.lastModified}`

/** 识别值基值（有值才建）。没识别到值的项目不建基值 → 按模板类型落空草稿。 */
function importMatchedBase(preview: CoaReportImportPreview): Record<string, CoaResultDraft> {
  return Object.fromEntries(
    preview.matched_items
      .filter((m) => m.value_num != null || !!m.value_text?.trim())
      .map(
        (m) =>
          [m.item_id, toResultDraft({ value_num: m.value_num, value_text: m.value_text })] as const,
      ),
  )
}

/** 批次字段当前值：覆盖层 > 识别值。自定义字段先取 docx 结构化识别（按字段键），
 *  再回落固定列识别值（字段键命中固定列时）。 */
function importBatchValue(entry: CoaImportEntry, key: string): string {
  const edited = entry.batchEdits[key]
  if (edited !== undefined) return edited
  const draft = entry.preview?.report_draft
  if (!draft) return ''
  if (key === 'batch_no') return draft.batch_no ?? ''
  if (key === 'serial_no') return draft.serial_no ?? ''
  const structured = entry.preview?.batch_dynamic.find((d) => d.key === key)?.value
  if (structured) return structured
  const column = reportColumnKeyOf(key)
  return column ? (draft[column] ?? '') : ''
}

/** 这份文件登记前还缺的必填项（批号/流水号，识别或补填都算）。 */
function importMissingHead(entry: CoaImportEntry): Array<'batch_no' | 'serial_no'> {
  return (['batch_no', 'serial_no'] as const).filter((key) => !importBatchValue(entry, key).trim())
}

/** 登记载荷。自定义批次字段 → batch_data（原文照传，日期由后端按字段口径确定性解析）；
 *  模板字段键命中的固定列在顶层传 null 让位给 batch_data 镜像（清空即清零），
 *  模板没定义的固定列保持 docx 识别值。 */
function buildImportPayload(entry: CoaImportEntry, standardDetail: CoaStandard): CoaReportInput {
  const { preview } = entry
  if (!preview?.standard) throw new Error('没有匹配到客户标准，不能构造登记载荷')
  const draft = preview.report_draft
  const valueDraft = { ...importMatchedBase(preview), ...entry.valueEdits }
  const values: CoaValueInput[] = []
  for (const item of standardDetail.items ?? []) {
    const input = draftToValueInput(item.id, valueDraft[item.id] ?? emptyResultDraft(item.value_type))
    if (input) values.push(input)
  }
  const batchData: Record<string, string> = {}
  const covered = new Set<CoaReportColumn>()
  for (const f of stripBuiltinFields(standardDetail.batch_fields ?? [])) {
    const raw = importBatchValue(entry, f.key).trim()
    if (raw) batchData[f.key] = raw
    const column = reportColumnKeyOf(f.key)
    if (column) covered.add(column)
  }
  const fixed: Record<CoaReportColumn, string | null> = {
    mfg_date: draft.mfg_date,
    exp_date: draft.exp_date,
    packaging: draft.packaging,
    batch_size: draft.batch_size,
    storage: draft.storage,
  }
  for (const column of covered) fixed[column] = null
  return {
    product_id: preview.standard.product_id,
    standard_id: preview.standard.id,
    batch_no: importBatchValue(entry, 'batch_no').trim(),
    serial_no: importBatchValue(entry, 'serial_no').trim(),
    ...fixed,
    batch_data: batchData,
    values,
    raw_extract: preview.raw_extract,
  }
}

/** 单份文件的审核区：左侧检测结果（按模板完整列出，识别值预填可修正，未识别的留空
 *  可补）+ 右侧报告信息（识别值预填且可改）。完全受控——状态都在父组件的条目里。 */
function CoaImportFileReview({
  entry,
  standards,
  onPatch,
  onStandardChange,
}: {
  entry: CoaImportEntry & { preview: CoaReportImportPreview }
  standards: CoaStandard[]
  onPatch: (patch: Partial<CoaImportEntry>) => void
  onStandardChange: (standardId: string) => void
}) {
  const preview = entry.preview
  const standard = preview.standard
  // 命中标准的完整项目与生效批次字段集：预览只带识别值，不带模板结构
  const standardDetailQuery = useQuery({
    ...coaStandardDetailQuery(standard?.id ?? ''),
    enabled: !!standard,
  })
  const standardDetail = standardDetailQuery.data
  const items = standardDetail?.items ?? []
  const customFields = stripBuiltinFields(standardDetail?.batch_fields ?? [])
  const parsing = entry.status === 'parsing'
  const fieldId = (key: string) => `coa-import-${entry.id}-${key}`

  const valueDraft = { ...importMatchedBase(preview), ...entry.valueEdits }
  const draftOf = (it: CoaStandardItem): CoaResultDraft =>
    valueDraft[it.id] ?? emptyResultDraft(it.value_type)
  const filledCount = items.filter((it) => draftOf(it).raw.trim() !== '').length
  const unmatchedCount = preview.unmatched_items.length

  const product = preview.product
  const productDraft = preview.product_draft
  const productNameEn = product?.name_en ?? productDraft?.name_en ?? null
  const productLabel = product
    ? `${product.code} ${product.name}`
    : [productDraft?.code, productDraft?.name].filter(Boolean).join(' ') || '—'
  // 自动匹配失败时选项用后端给的候选（docx 认出的产品可能不是当前页的产品）；
  // 匹配成功后候选为空，用当前产品的标准列表，命中的标准不在其中则补进去保证下拉能显示
  const standardOptions = standard
    ? standards.some((s) => s.id === standard.id)
      ? standards
      : [standard, ...standards]
    : preview.standard_candidates.length
      ? preview.standard_candidates
      : standards

  const batchNo = importBatchValue(entry, 'batch_no')
  const serialNo = importBatchValue(entry, 'serial_no')
  const candidateCount = preview.standard_candidates.length
  const setBatch = (key: string, value: string) =>
    onPatch({ batchEdits: { ...entry.batchEdits, [key]: value } })

  return (
    <div className={styles.entryBody}>
      <section className={styles.entrySheet}>
        {!standard ? (
          <div className={styles.entryNotice}>
            <b>未匹配到客户标准</b>
            <span>在右侧选择客户标准后，自动对齐 docx 里的检测项目</span>
          </div>
        ) : standardDetailQuery.isError ? (
          <div className={styles.entryState}>
            <span className={styles.detailError}>模板详情加载失败，请关闭后重试。</span>
          </div>
        ) : !standardDetail ? (
          <div className={styles.entryState}>
            <Spin size="small" /> 正在加载模板…
          </div>
        ) : (
          <>
            <div className={styles.entryHead}>
              <h3 className={styles.entryTitle}>
                {entry.view === 'unmatched' ? '标准外项目' : '检测结果'}
              </h3>
              {entry.view === 'unmatched' ? (
                <Button
                  type="link"
                  size="small"
                  className={styles.backLink}
                  onClick={() => onPatch({ view: 'results' })}
                >
                  返回检测结果
                </Button>
              ) : (
                <span className={styles.sheetMeta}>
                  已填 {filledCount} / {items.length}
                </span>
              )}
            </div>
            <div
              className={styles.sheetScroll}
              data-coa-result-scope={entry.view === 'results' ? '' : undefined}
            >
              {entry.view === 'unmatched' ? (
                <Table
                  rowKey="name_cn"
                  size="small"
                  className={styles.sheetTable}
                  dataSource={preview.unmatched_items}
                  pagination={false}
                  tableLayout="fixed"
                  columns={[
                    {
                      title: '#',
                      key: 'index',
                      width: 44,
                      render: (_v, _row, index) => (
                        <span className={styles.sheetIndex}>{index + 1}</span>
                      ),
                    },
                    {
                      title: '检测项目',
                      key: 'item',
                      // 英文名作副行展示：匹配键=中英拼接，仅中文相同而英文名
                      // 有/无或措辞不同时不命中——差异要肉眼可见才好对因
                      render: (_v, row) => (
                        <div className={styles.itemCell}>
                          <span className={styles.itemName}>{row.name_cn}</span>
                          {row.name_en && (
                            <span className={styles.itemSpec}>{row.name_en}</span>
                          )}
                        </div>
                      ),
                    },
                    {
                      title: '标准要求',
                      key: 'spec',
                      render: (_v, row) =>
                        row.spec_text ? (
                          <span className={styles.entrySpec} title={row.spec_text}>
                            {row.spec_text}
                          </span>
                        ) : (
                          <span className={styles.emptyCell}>—</span>
                        ),
                    },
                    {
                      title: 'docx 结果',
                      key: 'value',
                      width: 272,
                      render: (_v, row) => InlineValue(row.value_num, row.value_text),
                    },
                  ]}
                />
              ) : (
                <Table<CoaStandardItem>
                  rowKey="id"
                  size="small"
                  className={styles.sheetTable}
                  dataSource={items}
                  pagination={false}
                  tableLayout="fixed"
                  locale={{
                    emptyText: (
                      <div className={styles.inlineEmpty}>该模板还没有检测项目</div>
                    ),
                  }}
                  columns={resultSheetColumns(draftOf, (item, next) =>
                    onPatch({ valueEdits: { ...entry.valueEdits, [item.id]: next } }),
                  )}
                />
              )}
            </div>
            {entry.view === 'results' && unmatchedCount > 0 && (
              <div className={styles.sheetFoot}>
                <ExclamationCircleFilled />
                <span>docx 里有 {unmatchedCount} 项不在模板中，登记时不录入</span>
                <Button
                  type="link"
                  size="small"
                  onClick={() => onPatch({ view: 'unmatched' })}
                >
                  查看
                </Button>
              </div>
            )}
          </>
        )}
      </section>

      <section className={styles.entryPanel}>
        <h3 className={styles.entryTitle}>报告信息</h3>
        <dl className={styles.panelMeta}>
          <dt>品名</dt>
          <dd title={productNameEn ? `${productLabel} ${productNameEn}` : productLabel}>
            {productLabel}
            {productNameEn && <small>{productNameEn}</small>}
          </dd>
        </dl>
        {/* 只借 Form 做横向标签布局：字段不带 name，值与校验都由条目的草稿状态驱动
            （识别值预填 + 行内修正），没有 Form 实例，不存在挂载时序问题 */}
        <Form {...PANEL_FORM_LAYOUT}>
          {/* 不加 required：带星号后 72px 标签列放不下「客户标准」会折行，
              必须选这件事由警示态和提示文字表达 */}
          <Form.Item
            label="客户标准"
            htmlFor={fieldId('standard')}
            validateStatus={standard ? undefined : 'warning'}
            help={
              standard ? (
                standard.name && <span className={styles.fieldHint}>{standard.name}</span>
              ) : (
                <>
                  未自动匹配到客户标准，请选择
                  {candidateCount > 0 && `（自动匹配得到 ${candidateCount} 个候选）`}
                </>
              )
            }
          >
            <Select
              id={fieldId('standard')}
              showSearch={{ optionFilterProp: 'label' }}
              placeholder="选择客户标准"
              disabled={parsing}
              value={standard?.id}
              options={standardOptions.map((s) => ({ value: s.id, label: standardLabel(s) }))}
              onChange={onStandardChange}
            />
          </Form.Item>
          <Form.Item
            label="批号"
            required
            htmlFor={fieldId('batch_no')}
            validateStatus={entry.submitted && !batchNo.trim() ? 'error' : undefined}
            help={entry.submitted && !batchNo.trim() ? '请填写批号' : undefined}
          >
            <Input
              id={fieldId('batch_no')}
              data-import-field="batch_no"
              value={batchNo}
              placeholder="未识别，请填写"
              onChange={(e) => setBatch('batch_no', e.target.value)}
            />
          </Form.Item>
          <Form.Item
            label="流水号"
            required
            htmlFor={fieldId('serial_no')}
            validateStatus={entry.submitted && !serialNo.trim() ? 'error' : undefined}
            help={entry.submitted && !serialNo.trim() ? '请填写流水号' : undefined}
          >
            <Input
              id={fieldId('serial_no')}
              data-import-field="serial_no"
              value={serialNo}
              placeholder="未识别，请填写"
              onChange={(e) => setBatch('serial_no', e.target.value)}
            />
          </Form.Item>
          {customFields.map((f) => {
            const raw = importBatchValue(entry, f.key)
            const isDate = f.field_type === 'date'
            // 与后端同一条日期规则：这里认不出的原文，提交后后端同样会拒
            const iso = isDate ? toIsoDate(raw) : null
            const badDate = isDate && !!raw.trim() && iso === null
            return (
              <Form.Item
                key={f.key}
                label={f.label_cn}
                htmlFor={fieldId(f.key)}
                validateStatus={badDate ? 'warning' : undefined}
                help={badDate ? `识别为「${raw}」，不是有效日期，请重新选择` : undefined}
              >
                {isDate ? (
                  <DatePicker
                    id={fieldId(f.key)}
                    style={{ width: '100%' }}
                    value={iso ? dayjs(iso) : null}
                    onChange={(value) =>
                      setBatch(f.key, value ? value.format('YYYY-MM-DD') : '')
                    }
                  />
                ) : (
                  <Input
                    id={fieldId(f.key)}
                    value={raw}
                    onChange={(e) => setBatch(f.key, e.target.value)}
                  />
                )}
              </Form.Item>
            )
          })}
        </Form>
      </section>
    </div>
  )
}

/** 舞台上的一页：按这份文件的状态给出「解析中 / 失败 / 已登记 / 审核区」。 */
function CoaImportSlide({
  entry,
  standards,
  onPatch,
  onStandardChange,
  onRetry,
}: {
  entry: CoaImportEntry
  standards: CoaStandard[]
  onPatch: (patch: Partial<CoaImportEntry>) => void
  onStandardChange: (standardId: string) => void
  onRetry: () => void
}) {
  if (!entry.preview) {
    return entry.status === 'failed' ? (
      <div className={styles.stateBlock}>
        <ExclamationCircleFilled className={`${styles.stateIcon} ${styles.stateIconError}`} />
        <b>这份文件解析失败</b>
        <span>{entry.error}</span>
        {/* OCR 偶发返回空页：自动重试过一次仍失败才到这里，再给一次手动重试的机会 */}
        <Button onClick={onRetry}>重新解析</Button>
        <span>仍然失败就换一份文件，或关闭后用手工登记</span>
      </div>
    ) : (
      <div className={styles.entryState}>
        <Spin size="small" /> 正在解析报告…
      </div>
    )
  }
  if (entry.status === 'registered') {
    return (
      <div className={styles.stateBlock}>
        <CheckCircleFilled className={`${styles.stateIcon} ${styles.stateIconOk}`} />
        <b>已登记批号 {entry.registeredBatchNo}</b>
        <span>{entry.registeredValues ?? 0} 项检测结果已录入</span>
      </div>
    )
  }
  return (
    <>
      <CoaImportFileReview
        entry={{ ...entry, preview: entry.preview }}
        standards={standards}
        onPatch={onPatch}
        onStandardChange={onStandardChange}
      />
      {entry.status === 'parsing' && (
        <div className={styles.reviewBusy} role="status">
          <Spin size="small" /> 正在重新解析…
        </div>
      )}
    </>
  )
}

/** docx 批量导入登记：一次选多份 → 限并发逐份解析 → 左侧文件列表、右侧逐份审核
 * （切换时审核区按方向滑动）→ 登记一份自动到下一份，全部登记完自动关闭。
 * 未命中项（docx 有、标准无）只展示不录入：导入不改标准配置，扩项目走
 * 「客户标准配置」维护。 */
function CoaImportReportModal({
  open,
  onClose,
  standards,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  standards: CoaStandard[]
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [entries, setEntries] = useState<CoaImportEntry[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  // 切换动画：切走的那一份在离场期间留在台上，和新的那一份同台滑动，动画结束即清除
  const [leaving, setLeaving] = useState<{ id: string; forward: boolean } | null>(null)
  const [registeringId, setRegisteringId] = useState<string | null>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const railRef = useRef<HTMLElement>(null)
  // 解析队列（限并发）与条目序号：只在事件回调与异步回调里读写
  const inflight = useRef(0)
  const waiting = useRef<ParseJob[]>([])
  const entrySeq = useRef(0)
  const pendingBatch = useRef<File[]>([])

  const patchEntry = (id: string, patch: Partial<CoaImportEntry>) =>
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)))

  const pump = () => {
    while (inflight.current < IMPORT_PARSE_CONCURRENCY && waiting.current.length) {
      const job = waiting.current.shift()
      if (!job) break
      inflight.current += 1
      void parseJob(job).finally(() => {
        inflight.current -= 1
        pump()
      })
    }
  }

  const parseJob = async (job: ParseJob, attempt = 1): Promise<void> => {
    try {
      const preview = await importCoaReportPreview(job.file, job.standardId)
      // 新预览重置编辑（换标准重跑也走这里）
      patchEntry(job.id, {
        status: 'ready',
        preview,
        error: null,
        valueEdits: {},
        batchEdits: {},
        submitted: false,
        view: 'results',
      })
    } catch (err) {
      if (attempt < IMPORT_PARSE_ATTEMPTS) {
        // 间歇等一下再自动重试（占着并发位，不会因重试把并发顶上去）
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
        return parseJob(job, attempt + 1)
      }
      patchEntry(job.id, {
        status: 'failed',
        preview: null,
        error: err instanceof Error ? err.message : '解析失败',
      })
    }
  }

  /** 手动重试解析失败的文件（沿用它之前显式选过的客户标准）。 */
  const retryEntry = (id: string) => {
    const entry = entries.find((e) => e.id === id)
    if (!entry) return
    patchEntry(id, { status: 'parsing' })
    waiting.current.push({ id, file: entry.file, standardId: entry.pickedStandard ?? null })
    pump()
  }

  const reset = () => {
    waiting.current.length = 0
    setEntries([])
    setCurrentId(null)
    setLeaving(null)
  }

  const addFiles = (picked: File[]) => {
    const seen = new Set(entries.map((e) => fileKey(e.file)))
    const fresh = picked.filter((file) => {
      const key = fileKey(file)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    if (fresh.length < picked.length) {
      message.info(`已跳过 ${picked.length - fresh.length} 个重复文件`)
    }
    if (!fresh.length) return
    const added: CoaImportEntry[] = fresh.map((file) => {
      entrySeq.current += 1
      return {
        id: `e${entrySeq.current}`,
        file,
        status: 'parsing',
        pickedStandard: null,
        valueEdits: {},
        batchEdits: {},
        submitted: false,
        view: 'results',
      }
    })
    setEntries((prev) => [...prev, ...added])
    setCurrentId((prev) => prev ?? added[0].id)
    waiting.current.push(...added.map((e) => ({ id: e.id, file: e.file, standardId: null })))
    pump()
  }

  /** 这份文件换客户标准：带上 standardId 重新解析，期间保留旧预览压暗等待。 */
  const changeStandard = (id: string, standardId: string) => {
    const entry = entries.find((e) => e.id === id)
    if (!entry) return
    patchEntry(id, { status: 'parsing', pickedStandard: standardId })
    waiting.current.push({ id, file: entry.file, standardId })
    pump()
  }

  /** 切到指定文件。forward=向前（从右滑入），backward=向后（从左滑入）。 */
  const goTo = (nextId: string, fromId: string | null = currentId) => {
    if (registeringId || nextId === fromId) return
    const from = entries.findIndex((e) => e.id === fromId)
    const to = entries.findIndex((e) => e.id === nextId)
    // 系统开了「减弱动态效果」就直接切换，不留离场层
    const animate =
      from >= 0 && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    setLeaving(animate ? { id: entries[from].id, forward: to > from } : null)
    setCurrentId(nextId)
    if (animate) {
      // 兜底：动画结束事件没来（页面切到后台等）也要把离场层撤掉
      window.setTimeout(
        () => setLeaving((cur) => (cur?.id === entries[from].id ? null : cur)),
        420,
      )
    }
  }

  /** 登记完一份后去哪：沿顺序找下一份还没登记的，能审的（ready）优先，
   *  都在解析中就去第一份解析中的。 */
  const nextTodo = (list: CoaImportEntry[], fromId: string): CoaImportEntry | null => {
    const index = list.findIndex((e) => e.id === fromId)
    const rest = [...list.slice(index + 1), ...list.slice(0, index)].filter(
      (e) => e.status !== 'registered',
    )
    return rest.find((e) => e.status === 'ready') ?? rest[0] ?? null
  }

  const finish = (list: CoaImportEntry[]) => {
    const registered = list.filter((e) => e.status === 'registered').length
    const failed = list.filter((e) => e.status === 'failed').length
    if (registered > 1 || failed > 0) {
      message.success(
        `本次共登记 ${registered} 份报告${failed ? `，${failed} 份解析失败未登记` : ''}`,
      )
    }
    reset()
    onClose()
  }

  const registerEntry = async () => {
    const entry = entries.find((e) => e.id === currentId)
    const standard = entry?.preview?.standard
    if (!entry || !standard || registeringId) return
    const missing = importMissingHead(entry)
    if (missing.length) {
      // 识别不到批号/流水号是常态（空白模板、表头不规范）：就地补填，不必改走手工登记
      patchEntry(entry.id, { submitted: true })
      const field = missing[0]
      requestAnimationFrame(() => {
        stageRef.current
          ?.querySelector<HTMLElement>(`[data-review-current] [data-import-field="${field}"]`)
          ?.focus()
      })
      return
    }
    setRegisteringId(entry.id)
    try {
      const detail = await queryClient
        .fetchQuery(coaStandardDetailQuery(standard.id))
        .catch(() => null)
      if (!detail) {
        message.error('模板详情加载失败，请重试')
        return
      }
      const payload = buildImportPayload(entry, detail)
      const result = await createCoaReport(payload)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      patchEntry(entry.id, {
        status: 'registered',
        registeredBatchNo: result.data?.batch_no ?? payload.batch_no,
        registeredValues: payload.values?.length ?? 0,
      })
      message.success(
        `已登记批号 ${result.data?.batch_no ?? payload.batch_no}（${payload.values?.length ?? 0} 项结果）`
      )
      onSaved()
      // 去向按「登记后的列表」算：这里拿到的是点击那一刻的闭包，用本地副本
      const nextList = entries.map((e) =>
        e.id === entry.id ? { ...e, status: 'registered' as const } : e,
      )
      const target = nextTodo(nextList, entry.id)
      if (target) goTo(target.id, entry.id)
      else finish(nextList)
    } finally {
      setRegisteringId(null)
    }
  }

  const current = entries.find((e) => e.id === currentId) ?? null
  const currentIndex = entries.findIndex((e) => e.id === current?.id)
  const leavingEntry = leaving ? (entries.find((e) => e.id === leaving.id) ?? null) : null
  const counts = entries.reduce(
    (acc, e) => {
      acc[e.status] += 1
      return acc
    },
    { parsing: 0, ready: 0, failed: 0, registered: 0 } as Record<ImportEntryStatus, number>,
  )
  // 文件列表第二行：这份文件现在卡在哪
  const railSub = (e: CoaImportEntry): string => {
    if (e.status === 'parsing') return e.preview ? '重新解析中…' : '解析中…'
    if (e.status === 'failed') return '解析失败'
    if (e.status === 'registered') return `已登记 · 批号 ${e.registeredBatchNo ?? '—'}`
    if (!e.preview?.standard) return '未匹配客户标准'
    return importMissingHead(e).length ? '待填批号 / 流水号' : e.preview.standard.code
  }
  const railIcon = (e: CoaImportEntry) => {
    if (e.status === 'parsing') return <LoadingOutlined className={styles.railIconSpin} />
    if (e.status === 'failed') {
      return <ExclamationCircleFilled className={styles.railIconError} />
    }
    if (e.status === 'registered') return <CheckCircleFilled className={styles.railIconOk} />
    if (!e.preview?.standard || importMissingHead(e).length) {
      return <ExclamationCircleFilled className={styles.railIconWarn} />
    }
    return null
  }
  const primary = (() => {
    if (!current) return { text: '登记', disabled: true, onClick: () => {} }
    if (current.status === 'registered') {
      const target = nextTodo(entries, current.id)
      return target
        ? { text: '下一份未登记', disabled: false, onClick: () => goTo(target.id) }
        : { text: '已全部登记', disabled: true, onClick: () => {} }
    }
    if (current.status === 'parsing') return { text: '解析中…', disabled: true, onClick: () => {} }
    if (current.status === 'failed') return { text: '无法登记', disabled: true, onClick: () => {} }
    // 未匹配到客户标准时 registerEntry 会直接返回：按钮置灰，避免点了没反应
    return {
      text: entries.length > 1 ? '登记并下一份' : '登记',
      disabled: !current.preview?.standard,
      onClick: () => void registerEntry(),
    }
  })()

  // 当前项变动时把它滚进文件列表的可视区（窄屏横条同理）
  useEffect(() => {
    railRef.current
      ?.querySelector('[aria-current="true"]')
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [currentId])

  const cancel = () => {
    reset()
    onClose()
  }

  return (
    <Modal
      title="批量导入"
      open={open}
      width={1360}
      centered
      className={styles.importModal}
      onCancel={cancel}
      footer={[
        <Button key="cancel" onClick={cancel}>
          取消
        </Button>,
        entries.length > 1 && (
          <Button
            key="prev"
            disabled={registeringId !== null || currentIndex <= 0}
            icon={<LeftOutlined />}
            onClick={() => goTo(entries[currentIndex - 1].id)}
          >
            上一份
          </Button>
        ),
        entries.length > 1 && (
          <Button
            key="next"
            disabled={
              registeringId !== null || currentIndex < 0 || currentIndex >= entries.length - 1
            }
            iconPlacement="end"
            icon={<RightOutlined />}
            onClick={() => goTo(entries[currentIndex + 1].id)}
          >
            下一份
          </Button>
        ),
        <Button
          key="ok"
          type="primary"
          loading={registeringId === current?.id}
          disabled={primary.disabled}
          onClick={primary.onClick}
        >
          {primary.text}
        </Button>,
      ]}
    >
      {/* 整块拖拽区（还没选文件）与添加条（已选文件）是同一个 Dragger：随时可以继续拖入 */}
      <Upload.Dragger
        className={entries.length ? styles.fileBar : styles.dropzone}
        accept=".docx"
        multiple
        showUploadList={false}
        beforeUpload={(picked) => {
          // antd 对这一批里的每个文件各调一次 beforeUpload：先攒着，等这一轮同步调用
          // 结束后一次性入队，不依赖它传参的数组引用
          if (pendingBatch.current.length === 0) {
            queueMicrotask(() => {
              const batch = pendingBatch.current
              pendingBatch.current = []
              addFiles(batch)
            })
          }
          pendingBatch.current.push(picked)
          return false
        }}
      >
        {entries.length > 0 ? (
          <div className={styles.fileRow}>
            <PlusOutlined className={styles.fileIcon} />
            <span className={styles.filePrompt}>点击或拖入继续添加 docx，可多选</span>
            <span className={styles.tally} aria-live="polite">
              <span className={styles.tallyItem}>
                <b>{entries.length}</b> 份
              </span>
              {counts.registered > 0 && (
                <span className={styles.tallyItem}>
                  <b>{counts.registered}</b> 已登记
                </span>
              )}
              {counts.ready > 0 && (
                <span className={styles.tallyItem}>
                  <b>{counts.ready}</b> 待审核
                </span>
              )}
              {counts.parsing > 0 && (
                <span className={styles.tallyItem}>
                  <b>{counts.parsing}</b> 解析中
                </span>
              )}
              {counts.failed > 0 && (
                <span className={styles.tallyItem}>
                  <b>{counts.failed}</b> 失败
                </span>
              )}
            </span>
          </div>
        ) : (
          <>
            <p className={styles.dropIcon}><InboxOutlined /></p>
            <p className={styles.dropTitle}>拖入 COA docx，或点击选择文件</p>
            <p className={styles.dropHint}>
              可一次选择多份；自动识别批号、批次信息与检测结果，并与客户标准匹配
            </p>
          </>
        )}
      </Upload.Dragger>

      {entries.length > 0 && (
        <div className={styles.importLayout}>
          <nav className={styles.fileRail} aria-label="导入文件" ref={railRef}>
            <div className={styles.railHead}>
              <span className={styles.railTitle}>文件</span>
              <span className={styles.railTally}>
                已登记 {counts.registered} / {entries.length}
              </span>
            </div>
            <div className={styles.railList}>
              {entries.map((e, index) => {
                const active = e.id === current?.id
                return (
                  <button
                    key={e.id}
                    type="button"
                    aria-current={active ? 'true' : undefined}
                    disabled={registeringId !== null}
                    className={`${styles.railItem} ${active ? styles.railItemActive : ''} ${
                      e.status === 'registered' ? styles.railItemDone : ''
                    }`}
                    onClick={() => goTo(e.id)}
                  >
                    <span className={styles.railIndex}>{index + 1}</span>
                    <span className={styles.railText}>
                      <span className={styles.railName} title={e.file.name}>
                        {e.file.name}
                      </span>
                      <span className={styles.railSub}>{railSub(e)}</span>
                    </span>
                    <span className={styles.railIcon}>{railIcon(e)}</span>
                  </button>
                )
              })}
            </div>
          </nav>

          <div className={styles.reviewStage} ref={stageRef}>
            {/* 两页的 key 都直接用文件 id：切走的那一页原 DOM 被 React 原样保留（只换类名），
                不必重新挂载——否则一次要挂两份重表格，点击后会卡一下才开始滑动 */}
            {leavingEntry && leaving && (
              <div
                key={leavingEntry.id}
                inert
                className={`${styles.reviewSlide} ${
                  leaving.forward ? styles.slideOutLeft : styles.slideOutRight
                }`}
              >
                <CoaImportSlide
                  entry={leavingEntry}
                  standards={standards}
                  onPatch={(patch) => patchEntry(leavingEntry.id, patch)}
                  onStandardChange={(standardId) => changeStandard(leavingEntry.id, standardId)}
                  onRetry={() => retryEntry(leavingEntry.id)}
                />
              </div>
            )}
            {current && (
              <div
                key={current.id}
                data-review-current
                className={`${styles.reviewSlide} ${
                  leaving ? (leaving.forward ? styles.slideInRight : styles.slideInLeft) : ''
                }`}
                onAnimationEnd={
                  leaving
                    ? (event) => {
                        // 只认舞台自己的动画，嵌套控件的 animationend 冒泡不算
                        if (event.target === event.currentTarget) setLeaving(null)
                      }
                    : undefined
                }
              >
                <CoaImportSlide
                  entry={current}
                  standards={standards}
                  onPatch={(patch) => patchEntry(current.id, patch)}
                  onStandardChange={(standardId) => changeStandard(current.id, standardId)}
                  onRetry={() => retryEntry(current.id)}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

export function CoaIssuancePage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canIssue = hasPermission('qa:coa:issue')
  const router = useRouter()
  // 选择状态同步进 URL（?product=产品代码&standard=模板码），刷新/分享链接恢复现场。
  // APR 录入页同款两层结构：picked* 只存显式切换的 ID，URL 字符在渲染期解析成
  // ID（列表异步加载，effect 镜像 state 被 eslint 禁）；派生回落（第一个）不写回
  // URL，用户显式切换时才同步链接。URL 用直观码不用 UUID：可读、可口头转述。
  const searchParams = useSearchParams()
  const productParam = searchParams.get('product')
  const standardParam = searchParams.get('standard')
  const [pickedProductId, setPickedProductId] = useState<string | null>(null)
  const [pickedStandardId, setPickedStandardId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<CoaReport | null>(null)

  /** 把局部改动合并进当前查询串；空值即删除该参数。 */
  const syncUrl = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [key, value] of Object.entries(patch)) {
      if (value == null || value === '') params.delete(key)
      else params.set(key, value)
    }
    const query = params.toString()
    router.replace(query ? `/qa/coa/issuance?${query}` : '/qa/coa/issuance', { scroll: false })
  }

  const productsQuery = useQuery({
    queryKey: ['qa', 'coa', 'products', 'active'],
    queryFn: () => fetchCoaProducts(true),
  })
  const products = productsQuery.data ?? []
  // 选中优先级：显式切换（ID 须仍存在）> URL 产品代码（停用/不存在视为无效）> 第一个
  const pickedProduct = products.some((p) => p.id === pickedProductId) ? pickedProductId : null
  const urlProductId = productParam
    ? (products.find((p) => p.code === productParam)?.id ?? null)
    : null
  const activeProductId = pickedProduct ?? urlProductId ?? products[0]?.id ?? null
  const activeProduct = products.find((p) => p.id === activeProductId) ?? null

  const standardsQuery = useQuery({
    queryKey: ['qa', 'coa', 'standards', activeProduct?.id, 'active'],
    queryFn: () => fetchCoaStandards(activeProduct!.id, true),
    enabled: !!activeProduct,
  })
  const standards = standardsQuery.data ?? []
  // 模板记忆选择：显式切换 > URL 模板码（仅在本产品的标准列表内解析）> 第一个
  const pickedStandard = standards.some((s) => s.id === pickedStandardId) ? pickedStandardId : null
  const urlStandardId = standardParam
    ? (standards.find((s) => s.code === standardParam)?.id ?? null)
    : null
  const activeStandardId = pickedStandard ?? urlStandardId ?? standards[0]?.id ?? null
  const activeStandard = standards.find((s) => s.id === activeStandardId) ?? null

  // 单模板矩阵：列=该模板项目，行=该模板报告；standards[0] 带项目与生效批次字段集
  const matrixQuery = useQuery({
    queryKey: ['qa', 'coa', 'matrix', activeProduct?.id, activeStandard?.id],
    queryFn: () => fetchCoaMatrix(activeProduct!.id, activeStandard ? [activeStandard.id] : []),
    enabled: !!activeProduct && !!activeStandard,
  })
  const matrix = matrixQuery.data ?? null
  const rows = matrix?.rows ?? []
  const matrixStandard = matrix?.standards.find((s) => s.id === activeStandard?.id) ?? null
  const items = matrixStandard?.items ?? []
  const batchFields = matrixStandard?.batch_fields ?? []
  // 表格/弹窗渲染的自定义批次字段（内置 3 个走固定列/头表单）
  const customFields = stripBuiltinFields(batchFields)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
  }

  const handleVoid = (report: CoaReport) => {
    confirmAsync(modal, {
      title: `作废批号 ${report.batch_no} 的报告？`,
      content: `流水号 ${report.serial_no ?? '—'}；补发请作废后重新登记。`,
      okText: '作废',
      cancelText: '取消',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        const result = await deleteCoaReport(report.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('报告已作废')
        invalidate()
      },
    })
  }

  // 批次字段全部进表格列（一行看全批次信息），列宽由内容自适应
  const batchColumns = customFields.map((f) => ({
    title: (
      <Tooltip title={f.label_en ?? undefined}>
        <span className={styles.headerLabel}>{f.label_cn}</span>
      </Tooltip>
    ),
    key: `bf-${f.key}`,
    align: 'center' as const,
    onHeaderCell: () => ({ className: styles.batchCol }),
    onCell: () => ({ className: styles.batchCol }),
    render: (_v: unknown, record: CoaReport) => {
      const raw = record.batch_info?.[f.key]
      return raw
        ? <span className={styles.cellEllipsis} title={raw}>{raw}</span>
        : <span className={styles.emptyCell}>—</span>
    },
  }))
  // 项目列：单模板下即模板项目原序；列头 tooltip=标准原文
  const itemColumns = (matrix?.columns ?? []).map((col) => {
    const specs = col.spec_texts.join('；')
    const header = (
      <span className={styles.itemHeader}>
        <span className={styles.headerName}>{col.name_cn}</span>
        {specs && (
          <span className={styles.headerSpec}>
            {specs}
          </span>
        )}
      </span>
    )
    return {
      title: (
        <Tooltip
          mouseEnterDelay={0.15}
          title={
            <div>
              <div className={styles.headerTipName}>{col.name_cn}</div>
              {specs && <div className={styles.headerTipSpec}>{specs}</div>}
            </div>
          }
        >
          {header}
        </Tooltip>
      ),
      key: `v-${col.code}`,
      align: 'center' as const,
      onHeaderCell: () => ({ className: styles.itemCol }),
      onCell: () => ({ className: styles.itemCol }),
      render: (_v: unknown, record: CoaReport) => (
        <MatrixValue
          value={col.item_ids
            .map((id) => record.value_map?.[id])
            .find((val) => val !== undefined)}
        />
      ),
    }
  })

  const emptySheet = canIssue ? (
    <div className={styles.emptySheet}>
      <div className={styles.emptyIcon}><FileTextOutlined /></div>
      <div className={styles.emptyTitle}>该模板还没有出具记录</div>
      <p className={styles.emptyHint}>
        点上方「手工登记」填写第一份，或批量导入已有 COA docx 自动识别批次信息与检测结果。
      </p>
      <div className={styles.emptyActions}>
        <Button type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
          批量导入
        </Button>
      </div>
    </div>
  ) : (
    <div className={styles.emptySheet}>
      <div className={styles.emptyIcon}><FileTextOutlined /></div>
      <div className={styles.emptyTitle}>该模板还没有出具记录</div>
      <p className={styles.emptyHint}>当前账号没有出具登记权限，请联系 QA 管理员。</p>
    </div>
  )

  return (
    <div className={styles.page}>
      <PageHeading
        title="COA 出具登记"
        subtitle="选择产品与客户标准，登记或批量导入每批产品的检验报告，按模板逐项记录检测结果。"
        actions={
          canIssue && activeStandard ? (
            <Button type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
              批量导入
            </Button>
          ) : undefined
        }
      />

      {!activeProduct ? (
        <section className={styles.sheet}>
          <div className={styles.emptySheet}>
            <div className={styles.emptyIcon}><FileTextOutlined /></div>
            <div className={styles.emptyTitle}>还没有启用的产品</div>
            <p className={styles.emptyHint}>请先在「客户标准配置」中创建并启用产品。</p>
          </div>
        </section>
      ) : (
        <>
          <section className={styles.scopeBand} aria-label="产品与客户标准">
            <div className={styles.scopeField}>
              <span className={styles.fieldLabel}>产品</span>
              <Select
                className={styles.productSelect}
                placeholder="选择产品"
                value={activeProduct.id}
                showSearch={{ optionFilterProp: 'label' }}
                options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
                onChange={(id) => {
                  setPickedProductId(id)
                  setPickedStandardId(null)
                  // 切产品清模板参数：旧模板码不属于新产品，回落其第一个（派生不写 URL）
                  syncUrl({
                    product: products.find((p) => p.id === id)?.code ?? null,
                    standard: null,
                  })
                }}
              />
              {activeProduct.name_en && (
                <span className={styles.railMeta} title={activeProduct.name_en}>
                  {activeProduct.name_en}
                </span>
              )}
            </div>
            <div className={styles.scopeFieldWide}>
              <div className={styles.standardHead}>
                <span className={styles.fieldLabel}>客户标准</span>
                {standards.length > 0 && (
                  <span className={styles.standardCount}>{standards.length} 个模板</span>
                )}
              </div>
              <Select
                className={styles.standardSelect}
                placeholder={
                  standardsQuery.isLoading
                    ? '正在加载客户标准…'
                    : standards.length
                      ? '搜索模板代码或名称'
                      : '该产品还没有启用的客户标准'
                }
                value={activeStandard?.id}
                loading={standardsQuery.isLoading}
                disabled={!standardsQuery.isLoading && standards.length === 0}
                showSearch={{ optionFilterProp: 'label' }}
                options={standards.map((s) => ({
                  value: s.id,
                  label: `${s.code} ${s.name}${s.customer ? ` · ${s.customer}` : ''}`,
                  code: s.code,
                  name: s.name,
                  customer: s.customer,
                }))}
                optionRender={(option) => (
                  <div className={styles.standardOption}>
                    <span className={styles.optionCode}>{option.data.code}</span>
                    <span className={styles.optionName}>{option.data.name}</span>
                    {option.data.customer && (
                      <span className={styles.optionCustomer}>{option.data.customer}</span>
                    )}
                  </div>
                )}
                onChange={(id) => {
                  setPickedStandardId(id)
                  syncUrl({ standard: standards.find((s) => s.id === id)?.code ?? null })
                }}
              />
            </div>
          </section>

          <section className={styles.sheet}>
            <div className={styles.sheetHead}>
              <div className={styles.sheetHeading}>
                <h2 className={styles.sheetTitle}>出具记录</h2>
                {activeStandard && (
                  <span className={styles.sheetCode} title={activeStandard.name}>
                    {activeStandard.code}
                  </span>
                )}
              </div>
              <div className={styles.sheetTools}>
                {activeStandard && (
                  <div className={styles.sheetStats}>
                    <span className={styles.stat}><b>{rows.length}</b>份报告</span>
                    <span className={styles.stat}><b>{items.length}</b>项检测</span>
                    <span className={styles.stat}><b>{batchFields.length}</b>个批次字段</span>
                  </div>
                )}
                {canIssue && activeStandard && (
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    disabled={!matrixStandard}
                    onClick={() => setCreateOpen(true)}
                  >
                    手工登记
                  </Button>
                )}
              </div>
            </div>

            {!activeStandard || standardsQuery.isLoading ? (
              <div className={styles.loadingBlock}>
                <Spin size="small" /> 正在加载客户标准…
              </div>
            ) : matrixQuery.isError ? (
              <div className={styles.emptySheet}>
                <div className={styles.emptyTitle}>模板数据加载失败</div>
                <p className={styles.emptyHint}>请刷新页面后重试。</p>
              </div>
            ) : !matrix ? (
              <div className={styles.loadingBlock}>
                <Spin size="small" /> 正在加载出具记录…
              </div>
            ) : (
              <Table<CoaReport>
                rowKey="id"
                size="small"
                className={styles.matrix}
                dataSource={rows}
                pagination={false}
                tableLayout="auto"
                scroll={{ x: 'max-content' }}
                locale={{ emptyText: emptySheet }}
                columns={[
                  {
                    title: '批号',
                    dataIndex: 'batch_no',
                    fixed: 'start',
                    align: 'center' as const,
                    render: (v: string) => (
                      <span className={`${styles.cellEllipsis} ${styles.batchNo}`} title={v}>
                        {v}
                      </span>
                    ),
                  },
                  {
                    title: '流水号',
                    dataIndex: 'serial_no',
                    fixed: 'start',
                    align: 'center' as const,
                    render: (v: string | null) => v ?? <span className={styles.emptyCell}>—</span>,
                  },
                  ...batchColumns,
                  ...itemColumns,
                  {
                    title: '操作',
                    key: 'action',
                    fixed: 'end',
                    align: 'center' as const,
                    render: (_v, record) =>
                      canIssue && (
                        <div className={styles.rowActions}>
                          <Tooltip title="编辑">
                            <Button
                              type="text"
                              size="small"
                              icon={<EditOutlined />}
                              aria-label={`编辑批号 ${record.batch_no}`}
                              onClick={() => setEditing(record)}
                            />
                          </Tooltip>
                          <Tooltip title="作废">
                            <Button
                              type="text"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              aria-label={`作废批号 ${record.batch_no}`}
                              onClick={() => handleVoid(record)}
                            />
                          </Tooltip>
                        </div>
                      ),
                  },
                ]}
              />
            )}
          </section>
        </>
      )}

      {activeProduct && activeStandard && (
        <>
          <CoaImportReportModal
            open={importOpen}
            onClose={() => setImportOpen(false)}
            standards={standards}
            onSaved={invalidate}
          />
          {(createOpen || editing) && (
            <CoaReportFormModal
              key={editing?.id ?? 'create'}
              onClose={() => {
                setCreateOpen(false)
                setEditing(null)
              }}
              product={activeProduct}
              standard={matrixStandard ?? activeStandard}
              batchFields={batchFields}
              editing={editing}
              onSaved={invalidate}
            />
          )}
        </>
      )}
    </div>
  )
}

'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  App,
  Button,
  Checkbox,
  DatePicker,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Spin,
  Table,
  Tooltip,
  Upload,
} from 'antd'
import {
  CheckCircleFilled,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  FileAddOutlined,
  FileTextOutlined,
  InboxOutlined,
  PlusOutlined,
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
  fetchCoaStandards,
  importCoaReportPreview,
} from '@/lib/api/qa'
import type {
  CoaNewItemInput,
  CoaProductField,
  CoaReport,
  CoaReportImportPreview,
  CoaStandard,
  CoaStandardItem,
  CoaValueInput,
} from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import { stripBuiltinFields } from './CoaBatchFieldsEditor'
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

/** 手工登记 / 编辑报告：头表单（批号/流水号/出具日期）+ 模板动态批次字段 +
 * 按标准项目逐项填值。品名由所选产品带出（只读）；业务键为产品+模板+批号，
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
  // 值编辑覆盖层：item_id → num/text（行内输入直接改这里；详情基值派生合并，勿镜像进 state）
  const [draftOverrides, setDraftOverrides] = useState<Record<string, { num: number | null; text: string }>>({})

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
  // 模板自带「结论」字段时走动态字段（后端镜像写结论列），不再单独渲染固定结论输入
  const hasConclusionField = customFields.some((f) => f.label_cn.includes('结论'))

  // 新建态预填：text 型项目的标准默认值（快捷填写基底层；编辑态不预填，
  // 防保存时给历史报告无声补值）。优先级：覆盖层 > 编辑基值 > 标准默认值
  const defaultsDraft: Record<string, { num: number | null; text: string }> = {}
  if (!editing) {
    for (const it of items) {
      if (it.value_type === 'text' && it.default_value) {
        defaultsDraft[it.id] = { num: null, text: it.default_value }
      }
    }
  }
  // 编辑态详情基值 + 行内覆盖层（派生计算，React Compiler 自动记忆化）
  const detailDraft = Object.fromEntries(
    (detail?.values ?? []).map(
      (v) => [v.item_id, { num: v.value_num, text: v.value_text ?? '' }] as const,
    ),
  )
  const valueDraft = { ...defaultsDraft, ...detailDraft, ...draftOverrides }

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
      issued_date: detail.issued_date ? dayjs(detail.issued_date) : null,
      ...(hasConclusionField ? {} : { conclusion: detail.conclusion ?? '' }),
      ...bfValues,
    })
  }, [detail, form, customFields, hasConclusionField])

  const handleSave = async () => {
    if (detailPending) return
    const values = await form.validateFields()
    const valueInputs: CoaValueInput[] = []
    for (const item of items) {
      const draft = valueDraft[item.id]
      if (!draft) continue
      if (draft.num == null && !draft.text.trim()) continue
      valueInputs.push({
        item_id: item.id,
        value_num: draft.num,
        value_text: draft.text.trim() || null,
      })
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
        issued_date: values.issued_date ? values.issued_date.format('YYYY-MM-DD') : null,
        ...(hasConclusionField ? {} : { conclusion: values.conclusion || null }),
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
      title={
        <div className={styles.modalHeading}>
          <span>{editing ? '编辑报告' : '手工登记'}</span>
          <span className={styles.modalHeadingCode}>
            {editing ? `批号 ${editing.batch_no}` : standard.code}
          </span>
        </div>
      }
      open
      width={1080}
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
      <div className={styles.modalContext}>
        <span className={styles.contextStandard}>{standard.code}</span>
        <span className={styles.contextName} title={standard.name}>{standard.name}</span>
        <span className={styles.contextProduct}>{product.code} {product.name}</span>
      </div>
      <p className={styles.modalHint}>
        品名由所选产品自动带出；批号与流水号为必填。批次字段按当前模板配置展示。
        {editing && detailQuery.isLoading && (
          <span className={styles.detailError}>正在加载报告详情…</span>
        )}
        {detailQuery.isError && (
          <span className={styles.detailError}>报告详情加载失败，请关闭后重试。</span>
        )}
      </p>

      <section className={styles.modalSection}>
        <div className={styles.sectionHead}>
          <h3 className={styles.sectionTitle}>报告信息</h3>
          <span className={styles.sectionMeta}>
            {editing ? '修改后保存立即生效' : '批号与流水号为必填'}
          </span>
        </div>
        <Form form={form} layout="vertical" className={styles.formGrid}>
          <Form.Item name="batch_no" label="批号" rules={[{ required: true, message: '请输入批号' }]}>
            <Input placeholder="如 TEST001" />
          </Form.Item>
          <Form.Item name="serial_no" label="流水号" rules={[{ required: true, message: '请输入流水号' }]}>
            <Input placeholder="如 001" />
          </Form.Item>
          <Form.Item name="issued_date" label="出具日期">
            <DatePicker style={{ width: '100%' }} />
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
          {!hasConclusionField && (
            <Form.Item name="conclusion" label="结论">
              <Input placeholder="如 符合规定" />
            </Form.Item>
          )}
        </Form>
      </section>

      <section className={styles.modalSection}>
        <div className={styles.sectionHead}>
          <h3 className={styles.sectionTitle}>检测结果</h3>
          <span className={styles.sectionMeta}>{items.length} 项检测项目</span>
        </div>
        <Table
          rowKey="id"
          size="small"
          className={styles.denseTable}
          dataSource={items}
          pagination={false}
          scroll={{ y: 320 }}
          locale={{ emptyText: <div className={styles.inlineEmpty}>该模板还没有检测项目</div> }}
          columns={[
            {
              title: '检测项目',
              key: 'item',
              align: 'center' as const,
              render: (_v, row) => (
                <div className={styles.itemCell}>
                  <span className={styles.itemName}>{row.name_cn}</span>
                  {row.spec_text && <span className={styles.itemSpec}>{row.spec_text}</span>}
                </div>
              ),
            },
            {
              title: '结果',
              key: 'value',
              width: 272,
              align: 'center' as const,
              render: (_v, row) => {
                const draft = valueDraft[row.id]
                return (
                  <div className={styles.resultCell}>
                    <Segmented
                      size="small"
                      value={draft?.num != null ? 'num' : 'text'}
                      options={[
                        { value: 'num', label: '数值' },
                        { value: 'text', label: '文字' },
                      ]}
                      onChange={(mode) =>
                        setDraftOverrides({
                          ...valueDraft,
                          [row.id]:
                            mode === 'num'
                              ? { num: 0, text: '' }
                              : { num: null, text: '' },
                        })
                      }
                    />
                    {draft?.num != null ? (
                      <Input
                        size="small"
                        inputMode="decimal"
                        className={styles.resultInput}
                        value={draft.num}
                        onChange={(e) => {
                          const parsed = Number(e.target.value)
                          setDraftOverrides({
                            ...valueDraft,
                            [row.id]: {
                              num: Number.isFinite(parsed) ? parsed : null,
                              text: e.target.value,
                            },
                          })
                        }}
                      />
                    ) : (
                      <Input
                        size="small"
                        className={styles.resultInput}
                        placeholder="符合规定 / ＜1cfu/g"
                        value={draft?.text ?? ''}
                        onChange={(e) =>
                          setDraftOverrides({
                            ...valueDraft,
                            [row.id]: { num: null, text: e.target.value },
                          })
                        }
                      />
                    )}
                  </div>
                )
              },
            },
          ]}
        />
      </section>
    </Modal>
  )
}

/** docx 导入登记：解析 → 标准匹配（可手选重试）→ 命中/未命中/缺失预览 → 确认。 */
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
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CoaReportImportPreview | null>(null)
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  // 未命中项勾选（默认全勾）：name_cn 为键
  const [mergeKeys, setMergeKeys] = useState<string[]>([])
  const [manualStandard, setManualStandard] = useState<string | null>(null)

  const reset = () => {
    setFile(null)
    setPreview(null)
    setMergeKeys([])
    setManualStandard(null)
  }

  const runPreview = async (picked: File, standardId?: string | null) => {
    setParsing(true)
    try {
      const data = await importCoaReportPreview(picked, standardId)
      setPreview(data)
      setMergeKeys(data.unmatched_items.map((item) => item.name_cn))
    } catch (err) {
      message.error(err instanceof Error ? err.message : '解析失败')
      setFile(null)
    } finally {
      setParsing(false)
    }
  }

  const handleConfirm = async () => {
    if (!preview) return
    const draft = preview.report_draft
    // 批号/流水号为内置必填：name 走产品，批号/流水号必须从 docx 识别
    if (!draft.batch_no || !draft.serial_no) {
      message.warning('批号/流水号未能识别，请改用手工登记')
      return
    }
    if (!preview.standard) {
      message.warning('请先选择客户标准')
      return
    }
    setSaving(true)
    try {
      const newItems: CoaNewItemInput[] = preview.unmatched_items
        .filter((item) => mergeKeys.includes(item.name_cn))
        .map((item) => ({
          group_name: item.group_name ?? null,
          name_cn: item.name_cn,
          name_en: item.name_en ?? null,
          value_type: item.value_type,
          unit: item.unit ?? null,
          spec_text: item.spec_text ?? null,
          spec_min: item.spec_min ?? null,
          spec_max: item.spec_max ?? null,
          value_num: item.value_num,
          value_text: item.value_text,
        }))
      const result = await createCoaReport({
        product_id: preview.standard.product_id,
        standard_id: preview.standard.id,
        batch_no: draft.batch_no,
        serial_no: draft.serial_no,
        mfg_date: draft.mfg_date,
        exp_date: draft.exp_date,
        issued_date: draft.issued_date,
        packaging: draft.packaging,
        batch_size: draft.batch_size,
        storage: draft.storage,
        conclusion: draft.conclusion,
        // 模板动态批次字段（如复验期）：docx 提取值按生效字段键回写
        batch_data: Object.fromEntries(
          preview.batch_dynamic.map((d) => [d.key, d.value])
        ),
        values: preview.matched_items.map((m) => ({
          item_id: m.item_id,
          value_num: m.value_num,
          value_text: m.value_text,
        })),
        new_items: newItems,
        raw_extract: preview.raw_extract,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(
        `已登记批号 ${result.data?.batch_no ?? draft.batch_no}（${preview.matched_items.length + newItems.length} 项结果）`
      )
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
      reset()
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const draft = preview?.report_draft
  const reportMeta = draft
    ? [
        ['批号', draft.batch_no ?? '—'],
        ['流水号', draft.serial_no ?? '—'],
        ['生产日期', draft.mfg_date ?? '—'],
        ['有效期至', draft.exp_date ?? '—'],
        ['出具日期', draft.issued_date ?? '人工补填'],
        // 模板动态字段（复验期等）也给出识别结果，避免用户以为没抽到
        ...(preview?.batch_dynamic ?? []).map((d) => [d.label_cn, d.value]),
      ]
    : []

  return (
    <Modal
      title={<div className={styles.modalHeading}><span>批量导入出具登记</span></div>}
      open={open}
      width={960}
      className={styles.importModal}
      onCancel={() => {
        reset()
        onClose()
      }}
      footer={[
        <Button key="cancel" onClick={() => { reset(); onClose() }}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          loading={saving}
          disabled={!preview?.standard}
          onClick={handleConfirm}
        >
          确认登记
        </Button>,
      ]}
    >
      <Upload.Dragger
        className={styles.dropzone}
        accept=".docx"
        maxCount={1}
        showUploadList={false}
        disabled={parsing}
        beforeUpload={(picked) => {
          setFile(picked)
          void runPreview(picked, manualStandard)
          return false
        }}
      >
        <p className={styles.dropIcon}><InboxOutlined /></p>
        <p className={styles.dropTitle}>
          {parsing ? '正在解析报告…' : '拖入 COA docx，或点击选择文件'}
        </p>
        <p className={styles.dropHint}>
          自动识别批号、批次信息与检测结果，并与所选产品下的客户标准匹配
        </p>
        {file && <p className={styles.dropFile}>{file.name}</p>}
      </Upload.Dragger>

      {preview && !preview.standard && (
        <div className={styles.standardPick}>
          <div className={styles.matchBannerWarn}>
            <ExclamationCircleFilled />
            未匹配到客户标准，请手动选择后重新解析
          </div>
          <Select
            className={styles.importStandardSelect}
            placeholder="选择客户标准"
            value={manualStandard ?? undefined}
            options={standards.map((s) => ({
              value: s.id,
              label: standardLabel(s),
            }))}
            onChange={(id) => {
              setManualStandard(id)
              if (file) void runPreview(file, id)
            }}
          />
          {preview.standard_candidates.length > 0 && (
            <span className={styles.sectionMeta}>
              自动匹配得到 {preview.standard_candidates.length} 个候选模板
            </span>
          )}
        </div>
      )}

      {preview?.standard && (
        <>
          <div
            className={
              preview.unmatched_items.length ? styles.matchBannerWarn : styles.matchBannerOk
            }
          >
            {preview.unmatched_items.length ? <ExclamationCircleFilled /> : <CheckCircleFilled />}
            {preview.unmatched_items.length
              ? `已匹配 ${preview.standard.code}：${preview.matched_items.length} 项命中，${preview.unmatched_items.length} 项不在标准中，勾选后并入`
              : `已匹配 ${preview.standard.code}：${preview.matched_items.length} 项全部命中`}
          </div>

          <div className={styles.previewMeta}>
            {reportMeta.map(([label, value]) => (
              <div key={label} className={styles.metaCell}>
                <span className={styles.metaLabel}>{label}</span>
                <span className={styles.metaValue} title={value}>{value}</span>
              </div>
            ))}
          </div>

          {preview.missing_items.length > 0 && (
            <p className={styles.missingHint}>
              标准中有 {preview.missing_items.length} 个项目未出现在本 docx，登记后将留空（
              {preview.missing_items.slice(0, 5).map((i) => i.name_cn).join('、')}
              {preview.missing_items.length > 5 ? ' 等' : ''}）
            </p>
          )}

          {preview.unmatched_items.length > 0 && (
            <section className={styles.previewSection}>
              <div className={styles.previewSectionHead}>
                <span className={styles.previewSectionTitle}>标准外项目</span>
                <span className={styles.sectionMeta}>
                  {preview.unmatched_items.length} 项 · 勾选后并入
                </span>
              </div>
              <Table
                rowKey="name_cn"
                size="small"
                className={styles.denseTable}
                dataSource={preview.unmatched_items}
                pagination={false}
                columns={[
                  {
                    title: '并入',
                    key: 'merge',
                    width: 64,
                    align: 'center' as const,
                    render: (_v, row) => (
                      <Checkbox
                        checked={mergeKeys.includes(row.name_cn)}
                        onChange={(e) =>
                          setMergeKeys(
                            e.target.checked
                              ? [...mergeKeys, row.name_cn]
                              : mergeKeys.filter((k) => k !== row.name_cn),
                          )
                        }
                        aria-label={`并入 ${row.name_cn}`}
                      />
                    ),
                  },
                  { title: '项目', dataIndex: 'name_cn', align: 'center' as const },
                  {
                    title: '标准要求',
                    dataIndex: 'spec_text',
                    align: 'center' as const,
                    render: (v: string | null) =>
                      v ? <span className={styles.cellEllipsis} title={v}>{v}</span> : <span className={styles.emptyCell}>—</span>,
                  },
                  {
                    title: 'docx 结果',
                    key: 'value',
                    align: 'center' as const,
                    render: (_v, row) => InlineValue(row.value_num, row.value_text),
                  },
                ]}
              />
            </section>
          )}

          <section className={styles.previewSection}>
            <div className={styles.previewSectionHead}>
              <span className={styles.previewSectionTitle}>已匹配项目</span>
              <span className={styles.sectionMeta}>{preview.matched_items.length} 项</span>
            </div>
            <Table
              rowKey="item_id"
              size="small"
              className={styles.denseTable}
              dataSource={preview.matched_items}
              pagination={false}
              scroll={{ y: 260 }}
              columns={[
                { title: '项目', dataIndex: 'name', align: 'center' as const },
                {
                  title: '标准要求',
                  dataIndex: 'spec_text',
                  align: 'center' as const,
                  render: (v: string | null) =>
                    v ? <span className={styles.cellEllipsis} title={v}>{v}</span> : <span className={styles.emptyCell}>—</span>,
                },
                {
                  title: '结果',
                  key: 'value',
                  width: 180,
                  align: 'center' as const,
                  render: (_v, row) => InlineValue(row.value_num, row.value_text),
                },
              ]}
            />
          </section>
        </>
      )}
    </Modal>
  )
}

export function CoaIssuancePage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canIssue = hasPermission('qa:coa:issue:create')
  const [productId, setProductId] = useState<string | null>(null)
  const [standardId, setStandardId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<CoaReport | null>(null)

  const productsQuery = useQuery({
    queryKey: ['qa', 'coa', 'products', 'active'],
    queryFn: () => fetchCoaProducts(true),
  })
  const products = productsQuery.data ?? []
  const activeProduct = products.find((p) => p.id === productId) ?? products[0] ?? null

  const standardsQuery = useQuery({
    queryKey: ['qa', 'coa', 'standards', activeProduct?.id, 'active'],
    queryFn: () => fetchCoaStandards(activeProduct!.id, true),
    enabled: !!activeProduct,
  })
  const standards = standardsQuery.data ?? []
  // 模板记忆选择：产品切换后原 id 不在新列表时回落第一个
  const activeStandard = standards.find((s) => s.id === standardId) ?? standards[0] ?? null

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
                onChange={setProductId}
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
                onChange={setStandardId}
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
                  {
                    title: '出具日期',
                    dataIndex: 'issued_date',
                    align: 'center' as const,
                    render: (v: string | null) =>
                      v ?? <span className={styles.emptyCell}>—</span>,
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

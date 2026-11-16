'use client'

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  DatePicker,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { FileAddOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { actionError, EmptyState, qaPageStyle, subtleText } from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import { createCoaReport, deleteCoaReport, updateCoaReport } from '@/actions/qa'
import {
  fetchCoaMatrix,
  fetchCoaProducts,
  fetchCoaReportDetail,
  importCoaReportPreview,
} from '@/lib/api/qa'
import type {
  CoaNewItemInput,
  CoaReport,
  CoaReportImportPreview,
  CoaStandard,
  CoaValueInput,
} from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS, renderMatrixCell } from './CoaShared'

/** 手工登记 / 编辑报告：头表单 + 按标准项目逐项填值。 */
function CoaReportFormModal({
  onClose,
  product,
  standards,
  editing,
  onSaved,
}: {
  onClose: () => void
  product: { id: string; code: string; name: string }
  standards: CoaStandard[]
  /** 编辑对象（null=新建）。 */
  editing: CoaReport | null
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const [standardId, setStandardId] = useState<string | null>(editing?.standard_id ?? null)
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

  const standard = standards.find((s) => s.id === (standardId ?? editing?.standard_id)) ?? null
  const items = standard?.items ?? []

  // 编辑态详情基值 + 行内覆盖层（派生计算，React Compiler 自动记忆化）
  const detailDraft = Object.fromEntries(
    (detail?.values ?? []).map(
      (v) => [v.item_id, { num: v.value_num, text: v.value_text ?? '' }] as const,
    ),
  )
  const valueDraft = Object.keys(draftOverrides).length ? { ...detailDraft, ...draftOverrides } : detailDraft

  // 表头回填：setFieldsValue 是 antd 命令式 API 而非 setState，放 effect 不触发渲染期更新
  useEffect(() => {
    if (!detail) return
    form.setFieldsValue({
      report_no: detail.report_no,
      batch_no: detail.batch_no,
      serial_no: detail.serial_no ?? '',
      issued_date: detail.issued_date ? dayjs(detail.issued_date) : null,
      packaging: detail.packaging ?? '',
      batch_size: detail.batch_size ?? '',
      storage: detail.storage ?? '',
      conclusion: detail.conclusion ?? '',
    })
  }, [detail, form])

  const handleSave = async () => {
    const values = await form.validateFields()
    if (!standard) {
      message.warning('请选择客户标准')
      return
    }
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
    setSaving(true)
    try {
      const head = {
        report_no: values.report_no.trim(),
        batch_no: values.batch_no.trim(),
        serial_no: values.serial_no || null,
        issued_date: values.issued_date ? values.issued_date.format('YYYY-MM-DD') : null,
        packaging: values.packaging || null,
        batch_size: values.batch_size || null,
        storage: values.storage || null,
        conclusion: values.conclusion || null,
      }
      const result = editing
        ? await updateCoaReport(editing.id, { ...head, values: valueInputs })
        : await createCoaReport({
            product_id: product.id,
            standard_id: standard.id,
            ...head,
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
    if (!editing) setStandardId(null)
  }

  return (
    <Modal
      title={editing ? `编辑 COA 报告 ${editing.report_no}` : '手工出具登记'}
      open
      width={980}
      onCancel={() => {
        reset()
        onClose()
      }}
      footer={[
        <Button key="cancel" onClick={() => { reset(); onClose() }}>
          取消
        </Button>,
        <Button key="save" type="primary" loading={saving} onClick={handleSave}>
          {editing ? '保存' : '登记'}
        </Button>,
      ]}
    >
      {!editing && (
        <Form.Item label="客户标准" style={{ marginBottom: 12 }}>
          <Select
            style={{ width: 420 }}
            placeholder="选择客户标准（决定项目列）"
            value={standardId ?? undefined}
            options={standards.map((s) => ({
              value: s.id,
              label: `${s.code} ${s.name}${s.customer ? ` · ${s.customer}` : ''}`,
            }))}
            onChange={(id) => {
              setStandardId(id)
              setDraftOverrides({})
            }}
          />
        </Form.Item>
      )}
      <Form form={form} layout="inline" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
        <Form.Item name="report_no" label="报告编号" rules={[{ required: true }]}>
          <Input style={{ width: 200 }} placeholder="COA-HAF-3205-006" />
        </Form.Item>
        <Form.Item name="batch_no" label="批号" rules={[{ required: true }]}>
          <Input style={{ width: 160 }} />
        </Form.Item>
        <Form.Item name="serial_no" label="流水号">
          <Input style={{ width: 110 }} />
        </Form.Item>
        <Form.Item name="issued_date" label="出具日期">
          <DatePicker />
        </Form.Item>
        <Form.Item name="packaging" label="包装">
          <Input style={{ width: 110 }} placeholder="5kg/Tin" />
        </Form.Item>
        <Form.Item name="batch_size" label="批量">
          <Input style={{ width: 110 }} />
        </Form.Item>
        <Form.Item name="storage" label="贮存条件">
          <Input style={{ width: 260 }} />
        </Form.Item>
        <Form.Item name="conclusion" label="结论">
          <Input style={{ width: 320 }} />
        </Form.Item>
      </Form>
      {items.length > 0 ? (
        <Table
          rowKey="id"
          size="small"
          dataSource={items}
          pagination={false}
          scroll={{ y: 380 }}
          columns={[
            {
              title: '项目',
              dataIndex: 'name_cn',
              render: (v, row) => (
                <>
                  <div>{v}</div>
                  {row.spec_text && <div style={subtleText}>{row.spec_text}</div>}
                </>
              ),
            },
            {
              title: '结果',
              width: 220,
              render: (_v, row) => {
                const draft = valueDraft[row.id]
                return (
                  <Space.Compact>
                    <Select
                      size="small"
                      style={{ width: 84 }}
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
                        style={{ width: 120 }}
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
                        style={{ width: 120 }}
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
                  </Space.Compact>
                )
              },
            },
          ]}
        />
      ) : (
        <EmptyState title={editing ? '加载中…' : '选择客户标准后填写各项目结果'} />
      )}
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
    if (!draft.report_no || !draft.batch_no) {
      message.warning('报告编号/批号未能识别，请改用手工登记')
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
          spec_text: item.spec_text ?? null,
          spec_min: item.spec_min ?? null,
          spec_max: item.spec_max ?? null,
          value_num: item.value_num,
          value_text: item.value_text,
        }))
      const result = await createCoaReport({
        product_id: preview.standard.product_id,
        standard_id: preview.standard.id,
        report_no: draft.report_no,
        batch_no: draft.batch_no,
        serial_no: draft.serial_no,
        mfg_date: draft.mfg_date,
        exp_date: draft.exp_date,
        issued_date: draft.issued_date,
        packaging: draft.packaging,
        batch_size: draft.batch_size,
        storage: draft.storage,
        conclusion: draft.conclusion,
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
        `已登记 ${result.data?.report_no ?? draft.report_no}（${preview.matched_items.length + newItems.length} 项结果）`
      )
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
      reset()
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="导入 docx 出具登记"
      open={open}
      width={900}
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
      <Space orientation="vertical" style={{ width: '100%' }} size={16}>
        <Space>
          <Upload
            maxCount={1}
            accept=".docx"
            showUploadList={false}
            beforeUpload={(picked) => {
              setFile(picked)
              void runPreview(picked, manualStandard)
              return false
            }}
          >
            <Button icon={<UploadOutlined />} loading={parsing}>
              {file ? `重新选择（当前：${file.name}）` : '选择 COA docx 文件'}
            </Button>
          </Upload>
          {preview && !preview.standard && (
            <>
              <Select
                style={{ width: 320 }}
                placeholder="自动匹配失败，请选择标准"
                value={manualStandard ?? undefined}
                options={standards.map((s) => ({
                  value: s.id,
                  label: `${s.code} ${s.name}${s.customer ? ` · ${s.customer}` : ''}`,
                }))}
                onChange={(id) => {
                  setManualStandard(id)
                  if (file) void runPreview(file, id)
                }}
              />
            </>
          )}
        </Space>

        {preview?.standard && (
          <>
            <Alert
              type={preview.unmatched_items.length ? 'warning' : 'success'}
              showIcon
              title={
                preview.unmatched_items.length
                  ? `标准 ${preview.standard.code}：${preview.matched_items.length} 项命中、${preview.unmatched_items.length} 项不在标准中（勾选后并入）`
                  : `标准 ${preview.standard.code}：${preview.matched_items.length} 项全部命中`
              }
            />
            {preview.missing_items.length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                标准中有 {preview.missing_items.length} 个项目未出现在本 docx，将留空（
                {preview.missing_items.slice(0, 5).map((i) => i.name_cn).join('、')}
                {preview.missing_items.length > 5 ? ' 等' : ''}）
              </Typography.Text>
            )}
            <Descriptions
              size="small"
              column={3}
              bordered
              items={[
                { key: 'report_no', label: '报告编号', children: preview.report_draft.report_no ?? '—' },
                { key: 'batch_no', label: '批号', children: preview.report_draft.batch_no ?? '—' },
                { key: 'serial_no', label: '流水号', children: preview.report_draft.serial_no ?? '—' },
                { key: 'mfg_date', label: '生产日期', children: preview.report_draft.mfg_date ?? '—' },
                { key: 'exp_date', label: '有效期至', children: preview.report_draft.exp_date ?? '—' },
                { key: 'issued_date', label: '出具日期', children: preview.report_draft.issued_date ?? '人工补填' },
              ]}
            />
            {preview.unmatched_items.length > 0 && (
              <Table
                rowKey="name_cn"
                size="small"
                dataSource={preview.unmatched_items}
                pagination={false}
                columns={[
                  {
                    title: '并入',
                    width: 60,
                    render: (_v, row) => (
                      <Tag.CheckableTag
                        checked={mergeKeys.includes(row.name_cn)}
                        onChange={(checked) =>
                          setMergeKeys(
                            checked
                              ? [...mergeKeys, row.name_cn]
                              : mergeKeys.filter((k) => k !== row.name_cn)
                          )
                        }
                      >
                        {mergeKeys.includes(row.name_cn) ? '并入' : '跳过'}
                      </Tag.CheckableTag>
                    ),
                  },
                  { title: '项目', dataIndex: 'name_cn' },
                  { title: '标准', dataIndex: 'spec_text', render: (v) => v ?? '—' },
                  { title: '结果', dataIndex: 'value_text' },
                ]}
              />
            )}
            <Table
              rowKey="item_id"
              size="small"
              dataSource={preview.matched_items}
              pagination={false}
              scroll={{ y: 280 }}
              columns={[
                { title: '项目', dataIndex: 'name' },
                { title: '标准', dataIndex: 'spec_text', render: (v) => v ?? '—' },
                { title: '结果', dataIndex: 'value_text', width: 160 },
              ]}
            />
          </>
        )}
        {preview && !preview.standard && preview.standard_candidates.length > 0 && (
          <Typography.Text type="secondary">
            未按报告编号自动匹配到标准；请在上方选择后重新解析。
          </Typography.Text>
        )}
      </Space>
    </Modal>
  )
}

export function CoaIssuancePage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  const canIssue = hasPermission('qa:coa:issue:create')
  const [productId, setProductId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<CoaReport | null>(null)

  const productsQuery = useQuery({
    queryKey: ['qa', 'coa', 'products', 'active'],
    queryFn: () => fetchCoaProducts(true),
  })
  const products = productsQuery.data ?? []
  const activeProduct = products.find((p) => p.id === productId) ?? products[0] ?? null

  const matrixQuery = useQuery({
    queryKey: ['qa', 'coa', 'matrix', activeProduct?.id],
    queryFn: () => fetchCoaMatrix(activeProduct!.id),
    enabled: !!activeProduct,
  })
  const matrix = matrixQuery.data ?? null

  const standards = matrix?.standards ?? []
  const rows = matrix?.rows ?? []

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
  }

  const handleVoid = (report: CoaReport) => {
    confirmAsync(modal, {
      title: `作废报告 ${report.report_no}？`,
      content: `批次 ${report.batch_no}；补发请作废后重新登记。`,
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

  // 合并列：跨标准同 code 项目共用一列（不同模板的同名检测项目在同一列下比对）；
  // 一份报告只属一个标准，取该列 item_ids 中首个非空值
  const mergedColumns = matrix?.columns ?? []
  const itemColumns = mergedColumns.map((col) => ({
    title: col.name_cn,
    key: `v-${col.code}`,
    width: 110,
    onCell: () => ({
      title: col.spec_texts.length > 0 ? col.spec_texts.join('；') : undefined,
    }),
    render: (_v: unknown, record: CoaReport) =>
      renderMatrixCell(
        col.item_ids
          .map((id) => record.value_map?.[id])
          .find((val) => val !== undefined),
      ),
  }))

  return (
    <div style={qaPageStyle}>
      <PageHeading
        title="COA 出具登记"
        subtitle="按产品汇总所有 COA 的全部项目数据；docx 导入自动对齐"
        actions={
          canIssue && activeProduct ? (
            <>
              <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                手工登记
              </Button>
              <Button type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
                导入 docx 登记
              </Button>
            </>
          ) : null
        }
      />

      <Space style={{ marginBottom: 16 }}>
        <span style={subtleText}>产品</span>
        <Select
          style={{ width: 300 }}
          placeholder="选择产品"
          value={activeProduct?.id}
          showSearch
          optionFilterProp="label"
          options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
          onChange={setProductId}
        />
        {matrix && (
          <span style={subtleText}>
            {standards.length} 个标准 · {rows.length} 份报告 · {mergedColumns.length}{' '}
            个项目列
          </span>
        )}
      </Space>

      {activeProduct ? (
        rows.length > 0 || standards.length > 0 ? (
          <Table<CoaReport>
            rowKey="id"
            size="small"
            dataSource={rows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={[
              { title: '批号', dataIndex: 'batch_no', fixed: 'left', width: 130 },
              { title: '报告编号', dataIndex: 'report_no', fixed: 'left', width: 165 },
              { title: '流水号', dataIndex: 'serial_no', fixed: 'left', width: 95, render: (v) => v ?? '—' },
              { title: '标准', dataIndex: 'standard_code', fixed: 'left', width: 85 },
              { title: '出具日期', dataIndex: 'issued_date', fixed: 'left', width: 105, render: (v) => v ?? '—' },
              ...itemColumns,
              {
                title: '操作',
                fixed: 'right',
                width: 110,
                render: (_v, record) =>
                  canIssue && (
                    <>
                      <Button type="link" size="small" onClick={() => setEditing(record)}>
                        编辑
                      </Button>
                      <Button type="link" size="small" danger onClick={() => handleVoid(record)}>
                        作废
                      </Button>
                    </>
                  ),
              },
            ]}
          />
        ) : (
          <EmptyState
            title="该产品还没有出具记录"
            hint={canIssue ? '导入一份 docx 或手工登记第一份 COA；标准请先在「客户标准配置」准备' : undefined}
          />
        )
      ) : (
        <EmptyState title="暂无启用的产品，请先在客户标准配置中创建" />
      )}

      {activeProduct && (
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
              standards={standards}
              editing={editing}
              onSaved={invalidate}
            />
          )}
        </>
      )}
    </div>
  )
}

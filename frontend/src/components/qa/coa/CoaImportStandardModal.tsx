'use client'

import { useImperativeHandle, useRef, useState, type Ref } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Drawer, Form, Input, Radio, Upload } from 'antd'
import {
  CheckCircleFilled,
  FileWordOutlined,
  LoadingOutlined,
  PlusOutlined,
  UploadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { actionError } from '@/components/qa/deviation/shared'
import {
  createCoaProduct,
  createCoaStandard,
  replaceCoaProductFields,
} from '@/actions/qa'
import { fetchCoaProductFields, importCoaStandardPreview } from '@/lib/api/qa'
import type {
  CoaItemInput,
  CoaProduct,
  CoaProductFieldInput,
  CoaStandardImportPreview,
} from '@/types/qa'
import {
  CoaItemsEditTable,
  rowsToItemPayload,
  toItemRow,
  validateItemRows,
  type CoaItemRow,
} from './CoaItemsEditTable'
import {
  CoaBatchFieldsEditor,
  rowsToFieldPayload,
  stripBuiltinFields,
  toFieldRow,
  validateFieldRows,
  type CoaBatchFieldRow,
} from './CoaBatchFieldsEditor'
import styles from './CoaImportStandardModal.module.css'

export interface DraftPanelHandle {
  save: () => void
}

/** 草稿表单面板：useForm 随本组件挂载即连接（解析完成才渲染，避免悬空实例）。 */
function DraftPanel({
  ref,
  preview,
  products,
  onSave,
}: {
  ref?: Ref<DraftPanelHandle>
  preview: CoaStandardImportPreview
  products: CoaProduct[]
  onSave: (input: {
    productTarget: string
    code: string
    name: string
    customer: string
    items: CoaItemInput[]
    /** 编辑后的批次字段草稿：新产品落产品默认；已有产品由后端与默认对比落覆盖。 */
    fields: CoaProductFieldInput[]
  }) => Promise<void>
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  // 产品去向：已有产品 id，或 'new'（用解析建议建品）
  const [productTarget, setProductTarget] = useState<string | null>(
    preview.product ? preview.product.id : preview.product_draft.code ? 'new' : null
  )
  // 解析结果可编辑：行集本地态，保存时整体提交（增删改/排序都在预览里完成）
  const [rows, setRows] = useState<CoaItemRow[]>(() =>
    preview.standard_draft.items.map(toItemRow)
  )
  // 批次信息字段草稿（结构提取的标签清单，可编辑）
  const [fieldRows, setFieldRows] = useState(() =>
    preview.batch_fields_draft.map(toFieldRow)
  )
  // 最近一次新增的行：挂载时聚焦中文名输入框（聚焦即滚动定位）
  const [focusRowKey, setFocusRowKey] = useState<string | null>(null)

  const handleAddRow = () => {
    const row = toItemRow({ name_cn: '', value_type: 'text' })
    setRows([...rows, row])
    setFocusRowKey(row.key)
  }

  const handleAddFieldRow = () => {
    setFieldRows([...fieldRows, toFieldRow({ key: '', label_cn: '', field_type: 'text' })])
  }

  const handleSave = async () => {
    // 校验失败时 antd 已在字段上标红，这里只中断，不再向外抛 rejection
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    if (!productTarget) {
      message.warning('请选择归属产品')
      return
    }
    const problem = validateItemRows(rows)
    if (problem) {
      message.warning(problem)
      return
    }
    const fieldProblem = validateFieldRows(fieldRows)
    if (fieldProblem) {
      message.warning(fieldProblem)
      return
    }
    await onSave({
      productTarget,
      code: values.code,
      name: values.name,
      customer: values.customer ?? '',
      items: rowsToItemPayload(rows),
      fields: rowsToFieldPayload(fieldRows),
    })
  }

  // 保存动作固定在弹窗底栏，这里只暴露触发入口
  useImperativeHandle(ref, () => ({ save: () => void handleSave() }))

  return (
    <>
      <section className={styles.section}>
        <header className={styles.sectionHead}>
          <div>
            <h3 className={styles.sectionTitle}>归属与标准信息</h3>
            <p className={styles.sectionHint}>保存后仍可在标准编辑器中继续调整项目</p>
          </div>
        </header>
        <Radio.Group
          className={styles.productGroup}
          value={productTarget ?? undefined}
          onChange={(e) => setProductTarget(e.target.value)}
        >
          {products.map((product) => (
            <Radio.Button key={product.id} value={product.id}>
              {product.code} {product.name}
            </Radio.Button>
          ))}
          {preview.product_draft.code && (
            <Radio.Button value="new">
              <PlusOutlined /> 新建 {preview.product_draft.code} {preview.product_draft.name}
            </Radio.Button>
          )}
        </Radio.Group>
        <Form
          form={form}
          layout="vertical"
          className={styles.form}
          initialValues={{
            code: preview.standard_draft.code ?? '',
            name: preview.standard_draft.name,
            customer: preview.standard_draft.customer ?? '',
          }}
        >
          <Form.Item
            name="code"
            label="模板编号"
            rules={[{ required: true, message: '请填写模板编号（报告编号中缀）' }]}
          >
            <Input placeholder="如 3205" />
          </Form.Item>
          <Form.Item name="name" label="标准名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="customer" label="客户">
            <Input placeholder="可选" />
          </Form.Item>
        </Form>
      </section>

      <section className={styles.section}>
        <header className={styles.sectionHead}>
          <div>
            <h3 className={styles.sectionTitle}>
              批次信息字段<span className={styles.count}>{fieldRows.length}</span>
            </h3>
            <p className={styles.sectionHint}>
              品名/批号/流水号为内置必填字段，此处配置其余字段。
              {preview.product
                ? '与产品默认不同时，保存为该模板的自定义字段集'
                : '保存为该产品的默认字段集'}
            </p>
          </div>
          <Button icon={<PlusOutlined />} onClick={handleAddFieldRow}>
            新增字段
          </Button>
        </header>
        {preview.product && <FieldsDiffNote productId={preview.product.id} rows={fieldRows} />}
        <CoaBatchFieldsEditor rows={fieldRows} onChange={setFieldRows} editable />
      </section>

      <section className={styles.section}>
        <header className={styles.sectionHead}>
          <div>
            <h3 className={styles.sectionTitle}>
              检测项目<span className={styles.count}>{rows.length}</span>
            </h3>
            <p className={styles.sectionHint}>可直接编辑、增删、调整顺序，保存时以此为准</p>
          </div>
          <Button icon={<PlusOutlined />} onClick={handleAddRow}>
            新增项目
          </Button>
        </header>
        <CoaItemsEditTable
          rows={rows}
          onChange={setRows}
          editable
          scrollY={false}
          focusRowKey={focusRowKey}
        />
      </section>
    </>
  )
}

/** 已匹配产品：草稿与产品默认的实时对比提示（key/标签/类型，顺序无关；
 * 内置 3 字段两侧恒同，不参与比对）。 */
function FieldsDiffNote({
  productId,
  rows,
}: {
  productId: string
  rows: CoaBatchFieldRow[]
}) {
  const { data } = useQuery({
    queryKey: ['qa', 'coa', 'product-fields', productId],
    queryFn: () => fetchCoaProductFields(productId),
  })
  if (data === undefined) return null
  const sig = (fields: CoaProductFieldInput[]) =>
    fields
      .map((f) => `${f.key}|${f.label_cn}|${f.label_en ?? ''}|${f.field_type}`)
      .sort()
      .join(';')
  const same = sig(rowsToFieldPayload(rows)) === sig(stripBuiltinFields(data))
  return (
    <p className={styles.syncFields}>
      {same
        ? '与产品默认字段集一致（不产生自定义）'
        : '与产品默认字段集不同，将保存为该模板的自定义字段集'}
    </p>
  )
}

/** 来源条：文件 + 解析状态，匹配结果不再是横幅 */
function SourceCard({
  file,
  preview,
  parsing,
  onPick,
}: {
  file: File
  preview: CoaStandardImportPreview | null
  parsing: boolean
  onPick: (file: File) => Promise<void>
}) {
  return (
    <div className={styles.sourceCard}>
      <span className={styles.sourceIcon}>
        <FileWordOutlined />
      </span>
      <div className={styles.sourceBody}>
        <div className={styles.sourceName} title={file.name}>
          {file.name}
        </div>
        <div
          className={`${styles.sourceMeta} ${preview?.product ? styles.sourceMatched : ''}`}
        >
          {parsing ? (
            <>
              <LoadingOutlined spin /> 正在解析检测项目…
            </>
          ) : preview?.product ? (
            <>
              <CheckCircleFilled />
              已匹配产品：{preview.product.code} {preview.product.name}
            </>
          ) : preview ? (
            <>
              <WarningOutlined className={styles.unmatchedIcon} />
              未匹配到产品（建议：{preview.product_draft.code ?? '—'} /{' '}
              {preview.product_draft.name ?? '—'}），请选择已有产品或新建
            </>
          ) : null}
        </div>
      </div>
      <Upload
        maxCount={1}
        accept=".docx"
        showUploadList={false}
        beforeUpload={(picked) => {
          void onPick(picked)
          return false
        }}
      >
        <Button size="small" icon={<UploadOutlined />} loading={parsing}>
          重新选择
        </Button>
      </Upload>
    </div>
  )
}

/**
 * docx → 客户标准草稿导入：上传解析 → 选产品（匹配已有 / 用建议新建）→
 * 编辑标准头 → 预览项目（只读，落库后走主编辑器调整）→ 保存。
 * 提取只产草稿，人工确认后才落库。父组件条件挂载（开才挂）。
 */
export function CoaImportStandardModal({
  onClose,
  products,
  onSaved,
}: {
  onClose: () => void
  products: CoaProduct[]
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<CoaStandardImportPreview | null>(null)
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  // 重新选文件时整块草稿重挂载（表单 initialValues / 行集都按新解析结果重置）
  const [previewSeq, setPreviewSeq] = useState(0)
  const draftRef = useRef<DraftPanelHandle>(null)

  const handleFile = async (picked: File) => {
    setFile(picked)
    setParsing(true)
    try {
      setPreview(await importCoaStandardPreview(picked))
      setPreviewSeq((seq) => seq + 1)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '解析失败')
      setFile(null)
      setPreview(null)
    } finally {
      setParsing(false)
    }
  }

  const handleSave = async (input: {
    productTarget: string
    code: string
    name: string
    customer: string
    items: CoaItemInput[]
    fields: CoaProductFieldInput[]
  }) => {
    if (!preview) return
    setSaving(true)
    try {
      let productId: string
      let batchFields: CoaProductFieldInput[] | null = null
      if (input.productTarget === 'new') {
        const draft = preview.product_draft
        const created = await createCoaProduct({
          code: draft.code ?? input.code,
          name: draft.name ?? `新产品 ${Date.now()}`,
          name_en: draft.name_en,
        })
        if (!created.success || !created.data) {
          message.error(actionError(created))
          return
        }
        productId = created.data.id
        // 新产品的第一份字段集=产品默认（草稿直接落默认，标准不再带覆盖）
        const fieldsResult = await replaceCoaProductFields(productId, input.fields)
        if (!fieldsResult.success) {
          message.error(actionError(fieldsResult))
          return
        }
      } else {
        productId = input.productTarget
        // 已有产品：字段随标准载荷走，后端与产品默认对比，不同才落该模板的覆盖
        batchFields = input.fields
      }
      const result = await createCoaStandard({
        product_id: productId,
        code: input.code,
        name: input.name,
        customer: input.customer || null,
        items: input.items,
        batch_fields: batchFields,
        raw_extract: preview.raw_extract,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(`标准已创建（${input.items.length} 个项目）`)
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title={
        <div>
          <div className={styles.modalTitle}>导入 docx 生成客户标准</div>
          <div className={styles.modalSubtitle}>
            从历史 COA 报告提取检测项目，确认后保存为标准
          </div>
        </div>
      }
      open
      size="min(1280px, 100vw)"
      onClose={onClose}
      // 点遮罩不关闭：正在编辑的草稿会整份丢失
      mask={{ closable: false }}
      styles={{
        header: { padding: '18px 32px', borderBlockEnd: '1px solid var(--color-hairline-soft)' },
        // 内边距交给 .root：滚动条贴抽屉边缘，内容与它留出 32px
        body: { padding: 0 },
        footer: { padding: '16px 32px', borderBlockStart: '1px solid var(--color-hairline-soft)' },
      }}
      footer={
        <div className={styles.footer}>
          <Button onClick={onClose}>取消</Button>
          {preview && (
            <Button
              type="primary"
              loading={saving}
              onClick={() => draftRef.current?.save()}
            >
              保存为标准
            </Button>
          )}
        </div>
      }
    >
      <div className={styles.root}>
        {file ? (
          <SourceCard file={file} preview={preview} parsing={parsing} onPick={handleFile} />
        ) : (
          <Upload.Dragger
            maxCount={1}
            accept=".docx"
            showUploadList={false}
            className={styles.dropzone}
            beforeUpload={(picked) => {
              void handleFile(picked)
              return false
            }}
          >
            <FileWordOutlined className={styles.dropIcon} />
            <span className={styles.dropTitle}>拖入 COA 报告 docx</span>
            <span className={styles.dropHint}>
              或点击选择文件，解析出的检测项目确认后才保存
            </span>
          </Upload.Dragger>
        )}
        {preview && (
          <DraftPanel
            key={previewSeq}
            ref={draftRef}
            preview={preview}
            products={products}
            onSave={handleSave}
          />
        )}
      </div>
    </Drawer>
  )
}

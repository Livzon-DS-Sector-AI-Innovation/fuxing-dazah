'use client'

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Form, Input, Modal, Radio, Upload } from 'antd'
import { FileWordOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { actionError } from '@/components/qa/deviation/shared'
import { createCoaProduct, createCoaStandard } from '@/actions/qa'
import { importCoaStandardPreview } from '@/lib/api/qa'
import type { CoaItemInput, CoaProduct, CoaStandardImportPreview } from '@/types/qa'
import {
  CoaItemsEditTable,
  rowsToItemPayload,
  toItemRow,
  validateItemRows,
  type CoaItemRow,
} from './CoaItemsEditTable'

/** 草稿表单面板：useForm 随本组件挂载即连接（解析完成才渲染，避免悬空实例）。 */
function DraftPanel({
  preview,
  products,
  saving,
  onSave,
}: {
  preview: CoaStandardImportPreview
  products: CoaProduct[]
  saving: boolean
  onSave: (input: {
    productTarget: string
    code: string
    name: string
    customer: string
    items: CoaItemInput[]
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

  const handleSave = async () => {
    const values = await form.validateFields()
    if (!productTarget) {
      message.warning('请选择归属产品')
      return
    }
    const problem = validateItemRows(rows)
    if (problem) {
      message.warning(problem)
      return
    }
    await onSave({
      productTarget,
      code: values.code,
      name: values.name,
      customer: values.customer ?? '',
      items: rowsToItemPayload(rows),
    })
  }

  return (
    <div style={{ marginTop: 16, display: 'grid', gap: 16 }}>
      <Alert
        type={preview.product ? 'success' : 'info'}
        showIcon
        title={
          preview.product
            ? `已匹配产品：${preview.product.code} ${preview.product.name}`
            : `未匹配到产品（建议：${preview.product_draft.code ?? '—'} / ${preview.product_draft.name ?? '—'}），请选择已有产品或新建`
        }
      />
      <Radio.Group
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
            <FileWordOutlined /> 新建 {preview.product_draft.code}{' '}
            {preview.product_draft.name}
          </Radio.Button>
        )}
      </Radio.Group>
      <Form
        form={form}
        layout="vertical"
        style={{ maxWidth: 520 }}
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
      <div>
        <div style={{ marginBottom: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontWeight: 600 }}>
            解析出 {rows.length} 个检测项目（可直接编辑/增删/排序，保存时以此为准）
          </span>
          <Button
            icon={<PlusOutlined />}
            size="small"
            onClick={() => setRows([...rows, toItemRow({ name_cn: '', value_type: 'text' })])}
          >
            新增项目
          </Button>
          {/* 放表格上方：30+ 行时不必滚到底部才能保存 */}
          <Button type="primary" loading={saving} onClick={handleSave}>
            保存为标准
          </Button>
        </div>
        <CoaItemsEditTable rows={rows} onChange={setRows} editable />
      </div>
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

  const handleFile = async (picked: File) => {
    setFile(picked)
    setParsing(true)
    try {
      setPreview(await importCoaStandardPreview(picked))
    } catch (err) {
      message.error(err instanceof Error ? err.message : '解析失败')
      setFile(null)
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
  }) => {
    if (!preview) return
    setSaving(true)
    try {
      let productId: string
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
      } else {
        productId = input.productTarget
      }
      const result = await createCoaStandard({
        product_id: productId,
        code: input.code,
        name: input.name,
        customer: input.customer || null,
        items: input.items,
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
    <Modal
      title="导入 docx 生成客户标准"
      open
      width={1180}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
      ]}
    >
      <Upload
        maxCount={1}
        accept=".docx"
        showUploadList={false}
        beforeUpload={(picked) => {
          void handleFile(picked)
          return false
        }}
      >
        <Button icon={<UploadOutlined />} loading={parsing}>
          {file ? `重新选择（当前：${file.name}）` : '选择 COA docx 文件'}
        </Button>
      </Upload>
      {preview && (
        <DraftPanel preview={preview} products={products} saving={saving} onSave={handleSave} />
      )}
    </Modal>
  )
}

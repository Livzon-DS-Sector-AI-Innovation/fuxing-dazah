'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionError, EmptyState, qaPageStyle, subtleText } from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import {
  copyAprTemplate,
  createAprProduct,
  createAprSection,
  deleteAprProduct,
  deleteAprSection,
  updateAprProduct,
  updateAprSection,
} from '@/actions/qa'
import { fetchAprProducts, fetchAprSections } from '@/lib/api/qa'
import type {
  AprDataKind,
  AprProduct,
  AprSection,
} from '@/types/qa'
import { AprColumnWorkspace } from './AprColumnWorkspace'
import { AprMeta, AprSheet } from './AprChrome'
import { AprConfigTree } from './AprConfigTree'
import { AprCopySectionModal } from './AprCopySectionModal'
import { confirmAsync, DANGER_OK_PROPS, DATA_KIND_OPTIONS } from './AprConfigShared'

const FORM_ITEM = { marginBottom: 12 }

export function AprConfigPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  // 模板配置几乎全部是写操作：无 manage 权限时整页给提示，
  // 不让用户面对一排点了必 403 的按钮
  const canManage = hasPermission('qa:apr:manage')
  const [productId, setProductId] = useState<string | null>(null)
  const [sectionId, setSectionId] = useState<string | null>(null)
  const [productModal, setProductModal] = useState<{ product: AprProduct | null } | null>(null)
  const [sectionModal, setSectionModal] = useState<{ section: AprSection | null } | null>(null)
  const [copyTemplateTarget, setCopyTemplateTarget] = useState<AprProduct | null>(null)
  const [copySectionSource, setCopySectionSource] = useState<AprSection | null>(null)

  const productsQuery = useQuery({
    queryKey: ['qa', 'apr', 'products', 'all'],
    queryFn: () => fetchAprProducts(false),
  })
  const products: AprProduct[] = productsQuery.data ?? []
  // 选中产品可能被删除/被外部改动，按「选中的 → 第一个」回退，避免请求已失效的 id
  const activeProduct =
    products.find((product) => product.id === productId) ?? products[0] ?? null
  const activeProductId = activeProduct?.id ?? null

  const sectionsQuery = useQuery({
    queryKey: ['qa', 'apr', 'sections', activeProductId],
    queryFn: () => fetchAprSections(activeProductId!),
    enabled: !!activeProductId,
  })
  const sections: AprSection[] = sectionsQuery.data ?? []
  // 删除/搜索后选中项可能失效，按「选中的 → 第一个」回退，避免出现空白右栏
  const currentSection = sections.find((section) => section.id === sectionId) ?? sections[0] ?? null

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'apr'] })
  }

  /** 建新资源后先等缓存刷新完成再选中它：否则回退逻辑会先选中 products[0]，右栏闪一下别的产品。 */
  const invalidateAndWait = async () => {
    await queryClient.invalidateQueries({ queryKey: ['qa', 'apr'] })
  }

  const handleSelectProduct = (nextProductId: string) => {
    setProductId(nextProductId)
    setSectionId(null)
  }

  const handleDeleteProduct = (product: AprProduct) => {
    const sectionCount = product.section_count ?? 0
    if (sectionCount > 0) {
      modal.warning({
        title: '无法删除产品',
        content: `「${product.name}」下还有 ${sectionCount} 个模板段，请先删除这些段。`,
        okText: '知道了',
      })
      return
    }
    confirmAsync(modal, {
      title: `删除产品「${product.name}」？`,
      content: '删除后不可恢复；已登记过批次的产品无法删除。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        const result = await deleteAprProduct(product.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('产品已删除')
        if (productId === product.id) {
          setProductId(null)
          setSectionId(null)
        }
        invalidate()
      },
    })
  }

  const handleDeleteSection = (section: AprSection) => {
    confirmAsync(modal, {
      title: `删除模板段「${section.name}」？`,
      content: '段内的列定义会一并删除；已登记过批次的段不能删除，可改为停用列定义。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        const result = await deleteAprSection(section.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('模板段已删除')
        if (sectionId === section.id) setSectionId(null)
        invalidate()
      },
    })
  }

  return (
    <div style={qaPageStyle}>
      <PageHeading
        title="模板配置"
        subtitle="维护回顾表的结构：一个产品下有哪些段，每段有哪些质量属性与标准限度。数据录入按这里的结构生成表单。"
        actions={
          canManage ? (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setProductModal({ product: null })}
            >
              新增产品
            </Button>
          ) : undefined
        }
      />

      {productsQuery.isError && (
        <Alert
          type="error"
          showIcon
          className="mb-4"
          title="产品列表加载失败"
          description={productsQuery.error instanceof Error ? productsQuery.error.message : '请稍后重试'}
          action={
            <Button size="small" onClick={() => void productsQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}

      {!canManage ? (
        <AprSheet title="模板配置" bleed={false} meta={<AprMeta items={['需要配置权限']} />}>
          <EmptyState
            title="需要模板配置权限"
            hint="当前账号没有 qa:apr:manage 权限，无法维护产品模板。如需调整模板或申请新产品，请联系 QA 管理员。"
          />
        </AprSheet>
      ) : (
      <div className="grid grid-cols-1 items-start gap-3.5 xl:grid-cols-[304px_minmax(0,1fr)]">
        <div className="xl:sticky xl:top-2">
          <AprConfigTree
            products={products}
            loading={productsQuery.isLoading}
            selectedProductId={activeProductId}
            sections={sections}
            sectionsLoading={sectionsQuery.isLoading}
            selectedSectionId={currentSection?.id ?? null}
            onSelectProduct={handleSelectProduct}
            onSelectSection={setSectionId}
            onCreateProduct={() => setProductModal({ product: null })}
            onEditProduct={(product) => setProductModal({ product })}
            onCopyTemplate={setCopyTemplateTarget}
            onDeleteProduct={handleDeleteProduct}
            onCreateSection={() => setSectionModal({ section: null })}
            onEditSection={(section) => setSectionModal({ section })}
            onCopySection={setCopySectionSource}
            onDeleteSection={handleDeleteSection}
          />
        </div>

        <AprColumnWorkspace
          key={currentSection?.id ?? 'no-section'}
          product={activeProduct}
          section={currentSection}
          loading={productsQuery.isLoading || (!!activeProductId && sectionsQuery.isLoading)}
          onEditSection={() => currentSection && setSectionModal({ section: currentSection })}
          onCopySection={() => currentSection && setCopySectionSource(currentSection)}
          onDeleteSection={() => currentSection && handleDeleteSection(currentSection)}
          onCreateSection={() => setSectionModal({ section: null })}
          onCopyTemplate={() => activeProduct && setCopyTemplateTarget(activeProduct)}
          onChanged={invalidate}
        />
      </div>
      )}

      {productModal && (
        <ProductFormModal
          product={productModal.product}
          onClose={() => setProductModal(null)}
          onSaved={(created) => {
            if (created) {
              // 等缓存刷新到含新产品的列表后再选中，避免回退逻辑先选中别的产品
              void invalidateAndWait().then(() => {
                setProductId(created.id)
                setSectionId(null)
              })
            } else {
              invalidate()
            }
          }}
        />
      )}

      {sectionModal && activeProduct && (
        <SectionFormModal
          product={activeProduct}
          section={sectionModal.section}
          sectionCount={sections.length}
          onClose={() => setSectionModal(null)}
          onSaved={(created) => {
            if (created) {
              void invalidateAndWait().then(() => setSectionId(created.id))
            } else {
              invalidate()
            }
          }}
        />
      )}

      {copyTemplateTarget && (
        <CopyTemplateModal
          target={copyTemplateTarget}
          products={products}
          onClose={() => setCopyTemplateTarget(null)}
          onCopied={(target) => {
            setProductId(target.id)
            setSectionId(null)
            invalidate()
          }}
        />
      )}

      {copySectionSource && activeProduct && (
        <AprCopySectionModal
          products={products}
          targetProduct={activeProduct}
          defaultSource={copySectionSource}
          onClose={() => setCopySectionSource(null)}
          onCopied={(newSectionId) => {
            void invalidateAndWait().then(() => setSectionId(newSectionId))
          }}
        />
      )}
    </div>
  )
}

// ═════════════════════════ 产品表单 ═════════════════════════

interface ProductFormValues {
  code: string
  name: string
  name_en?: string
  is_active: boolean
  sort_order: number
}

function ProductFormModal({
  product,
  onClose,
  onSaved,
}: {
  product: AprProduct | null
  onClose: () => void
  onSaved: (created: AprProduct | null) => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<ProductFormValues>()
  const [saving, setSaving] = useState(false)

  const initialValues: ProductFormValues = product
    ? {
        code: product.code,
        name: product.name,
        name_en: product.name_en ?? '',
        is_active: product.is_active,
        sort_order: product.sort_order,
      }
    : { code: '', name: '', name_en: '', is_active: true, sort_order: 0 }

  const handleSubmit = async () => {
    let values: ProductFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const input = {
      // 短码统一大写（后端同口径归一），名称唯一由后端校验，撞名回 409 文案
      code: values.code.trim().toUpperCase(),
      name: values.name.trim(),
      name_en: values.name_en?.trim() || null,
      is_active: values.is_active,
      sort_order: values.sort_order ?? 0,
    }
    setSaving(true)
    try {
      const result = product
        ? await updateAprProduct(product.id, input)
        : await createAprProduct(input)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(product ? '产品已更新' : `产品已创建，继续配置「${input.name}」的模板段`)
      onSaved(product ? null : result.data ?? null)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={product ? `编辑产品：${product.code}` : '新增产品'}
      open
      width={520}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      mask={{ closable: false }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues} preserve={false}>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item
            name="code"
            label="产品短码"
            style={FORM_ITEM}
            tooltip="批号前缀与导出识别用，建议 2-4 个字母，自动转大写且不可重复，如 ST"
            normalize={(value: string) => String(value ?? '').toUpperCase()}
            rules={[{ required: true, whitespace: true, message: '请输入产品短码' }]}
          >
            <Input maxLength={32} placeholder="如 ST" />
          </Form.Item>
          <Form.Item
            name="name"
            label="产品名称"
            style={FORM_ITEM}
            tooltip="产品名称不可重复（下拉与导出均按名称辨识）"
            rules={[{ required: true, whitespace: true, message: '请输入产品名称' }]}
          >
            <Input maxLength={100} placeholder="如 硫酸黏菌素" />
          </Form.Item>
        </div>
        <Form.Item name="name_en" label="英文名称" style={FORM_ITEM}>
          <Input maxLength={100} placeholder="如 Colistin Sulfate" />
        </Form.Item>
        <div className="flex items-center gap-8">
          <Form.Item name="is_active" valuePropName="checked" style={FORM_ITEM}>
            <Checkbox>启用（停用后录入页不显示）</Checkbox>
          </Form.Item>
          <Form.Item
            name="sort_order"
            label="排序"
            style={FORM_ITEM}
            tooltip="数字越小越靠前；留 0 按产品短码排序"
          >
            <InputNumber min={0} style={{ width: 110 }} />
          </Form.Item>
        </div>
        <div style={subtleText} className="leading-[1.6]">
          保存后会自动选中该产品，可在左栏继续新建模板段，或从已有产品复制整套模板。
        </div>
      </Form>
    </Modal>
  )
}

// ═════════════════════════ 模板段表单 ═════════════════════════

interface SectionFormValues {
  name: string
  data_kind: AprDataKind
  market?: string
  multi_row: boolean
  stage?: string
  sort_order: number
}

function SectionFormModal({
  product,
  section,
  sectionCount,
  onClose,
  onSaved,
}: {
  product: AprProduct
  section: AprSection | null
  sectionCount: number
  onClose: () => void
  onSaved: (created: AprSection | null) => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<SectionFormValues>()
  const [saving, setSaving] = useState(false)
  // 数据类型决定列在汇总里的分组口径；段内已有列定义后不允许再改（后端同样拦批次）。
  const itemCount = section?.items?.length ?? 0
  const kindLocked = itemCount > 0

  const initialValues: SectionFormValues = section
    ? {
        name: section.name,
        data_kind: section.data_kind,
        market: section.market ?? '',
        multi_row: section.multi_row,
        stage: section.stage ?? '',
        sort_order: section.sort_order,
      }
    : {
        name: '',
        data_kind: 'production',
        market: '',
        multi_row: false,
        stage: '',
        sort_order: (sectionCount + 1) * 10,
      }

  const handleSubmit = async () => {
    let values: SectionFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const base = {
      name: values.name.trim(),
      data_kind: values.data_kind,
      market: values.data_kind === 'inspection' ? values.market?.trim() || null : null,
      stage: values.stage?.trim() || null,
      multi_row: values.multi_row,
      sort_order: values.sort_order ?? 0,
    }
    setSaving(true)
    try {
      const result = section
        ? await updateAprSection(section.id, base)
        : await createAprSection({ ...base, product_id: product.id })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(section ? '模板段已更新' : '模板段已创建，可以开始添加列定义')
      onSaved(section ? null : result.data ?? null)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={
        <div>
          <div className="text-[16px]">{section ? '编辑模板段' : '新建模板段'}</div>
          <div className="mt-0.5 text-[12px] font-normal text-[var(--color-steel)]">
            {product.code} {product.name}
          </div>
        </div>
      }
      open
      width={600}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      mask={{ closable: false }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues} preserve={false}>
        <Form.Item
          name="name"
          label="段名"
          style={FORM_ITEM}
          tooltip="同一产品下段名不可重复；不同产品可同名（各自的药典/工序段）"
          rules={[{ required: true, whitespace: true, message: '请输入模板段名称' }]}
        >
          <Input maxLength={100} placeholder="如 菌种-培养基配制 / 成品检验-USP" />
        </Form.Item>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item
            name="data_kind"
            label="数据类型"
            style={FORM_ITEM}
            tooltip={
              kindLocked
                ? `该段已有 ${itemCount} 个列定义，不能切换数据类型（会改变汇总分组口径）；请新建模板段，或先清空列定义。`
                : undefined
            }
          >
            <Select options={DATA_KIND_OPTIONS} disabled={kindLocked} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.data_kind !== next.data_kind}>
            {({ getFieldValue }) =>
              getFieldValue('data_kind') === 'inspection' ? (
                <Form.Item
                  name="market"
                  label="市场 / 药典"
                  style={FORM_ITEM}
                  tooltip="检验段填写适用药典，如 US / EP / Ch.P；生产段留空"
                >
                  <Input maxLength={16} placeholder="US / EP / Ch.P" />
                </Form.Item>
              ) : (
                <Form.Item label="市场 / 药典" style={FORM_ITEM}>
                  <Input disabled value="" placeholder="生产段不需要填写" />
                </Form.Item>
              )
            }
          </Form.Item>
        </div>
        <Form.Item name="multi_row" valuePropName="checked" style={FORM_ITEM}>
          <Checkbox>一批多行（同一批次可录入多行数据，如多个取样点/多台设备）</Checkbox>
        </Form.Item>
        <div className="grid grid-cols-2 gap-x-4">
          <Form.Item
            name="stage"
            label="工序阶段短码"
            style={FORM_ITEM}
            tooltip="内部标识用，如 seed / fermentation / finished_test；可留空"
          >
            <Input maxLength={32} placeholder="可留空" />
          </Form.Item>
          <Form.Item name="sort_order" label="段顺序" style={FORM_ITEM} tooltip="数字越小越靠前">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </div>
        <div style={subtleText} className="leading-[1.6]">
          模板段对应 Excel 里的一张 sheet 或一个横向块；录入页会按段的顺序分组显示。
        </div>
      </Form>
    </Modal>
  )
}

// ═════════════════════════ 整树复制模板 ═════════════════════════

function CopyTemplateModal({
  target,
  products,
  onClose,
  onCopied,
}: {
  target: AprProduct
  products: AprProduct[]
  onClose: () => void
  onCopied: (target: AprProduct) => void
}) {
  const { message } = App.useApp()
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const candidates = products.filter((product) => product.id !== target.id)
  const source = candidates.find((product) => product.id === sourceId) ?? null

  const handleSubmit = async () => {
    if (!sourceId) return
    setSaving(true)
    try {
      const result = await copyAprTemplate(target.id, sourceId)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(
        `已复制 ${result.data?.sections ?? 0} 个模板段 / ${result.data?.items ?? 0} 个列定义`,
      )
      onCopied(target)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={
        <div>
          <div className="text-[16px]">从已有产品复制整套模板</div>
          <div className="mt-0.5 text-[12px] font-normal text-[var(--color-steel)]">
            复制到「{target.code} {target.name}」
          </div>
        </div>
      }
      open
      width={560}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="复制整套模板"
      cancelText="取消"
      okButtonProps={{ disabled: !sourceId }}
      confirmLoading={saving}
      mask={{ closable: false }}
    >
      <Alert
        type="info"
        showIcon
        className="mb-4"
        title="整树复制，目标产品需没有模板段"
        description="源产品的全部段与列定义都会复制过来，之后可以按产品差异微调。只复制模板，不含批次数据。"
      />
      <Select
        style={{ width: '100%' }}
        placeholder="选择源产品"
        showSearch
        optionFilterProp="label"
        value={sourceId}
        onChange={setSourceId}
        options={candidates.map((product) => ({
          value: product.id,
          label: `${product.code} ${product.name}（${product.section_count ?? 0} 段 / ${product.item_count ?? 0} 列）`,
        }))}
      />
      {source && (
        <div className="mt-3 rounded-md bg-[var(--color-surface)] px-3 py-2 text-[12px] leading-[1.6] text-[var(--color-steel)]">
          将复制「{source.name}」的 {source.section_count ?? 0} 个模板段、
          {source.item_count ?? 0} 个列定义到「{target.name}」。
        </div>
      )}
    </Modal>
  )
}

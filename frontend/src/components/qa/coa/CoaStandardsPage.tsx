'use client'

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Form, Input, Modal, Select, Skeleton, Space, Table, Tag } from 'antd'
import { FileAddOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons'
import { actionError, EmptyState, qaPageStyle } from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import {
  createCoaProduct,
  createCoaStandard,
  deleteCoaStandard,
  replaceCoaProductFields,
  replaceCoaStandardItems,
  updateCoaStandard,
} from '@/actions/qa'
import {
  fetchCoaProductFields,
  fetchCoaProducts,
  fetchCoaStandardDetail,
  fetchCoaStandards,
} from '@/lib/api/qa'
import type { CoaProduct, CoaProductField, CoaStandard } from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import {
  CoaBatchFieldsEditor,
  rowsToFieldPayload,
  stripBuiltinFields,
  toFieldRow,
  validateFieldRows,
  type CoaBatchFieldRow,
} from './CoaBatchFieldsEditor'
import { CoaImportStandardModal } from './CoaImportStandardModal'
import { CoaStandardFieldsSection } from './CoaStandardFieldsSection'
import { CoaStandardItemsEditor } from './CoaStandardItemsEditor'
import styles from './CoaStandardsPage.module.css'

/** 产品管理弹窗：新增 + 启停（产品删除有标准引用守卫，前端不提供入口）。 */
function ProductManageModal({
  onClose,
  products,
  canManage,
}: {
  onClose: () => void
  products: CoaProduct[]
  canManage: boolean
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  // 字段配置编辑目标：独立弹窗（条件挂载，初始行集按已加载配置生成）
  const [fieldsProduct, setFieldsProduct] = useState<CoaProduct | null>(null)

  const handleCreate = async () => {
    // 校验失败由表单行内提示；吞掉 rejection，避免控制台未捕获错误
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSaving(true)
    try {
      const result = await createCoaProduct({
        code: values.code,
        name: values.name,
        name_en: values.name_en || null,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('产品已创建')
      form.resetFields()
      setCreating(false)
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="产品管理" open onCancel={onClose} footer={null} width={600}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <span style={{ color: 'var(--color-steel)', fontSize: 12 }}>共 {products.length} 个产品</span>
        {canManage && !creating && (
          <Button size="small" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            新增产品
          </Button>
        )}
      </div>

      {creating && (
        <Form
          form={form}
          layout="vertical"
          style={{
            marginBottom: 12,
            padding: 12,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-hairline)',
            borderRadius: 10,
          }}
        >
          <div style={{ display: 'grid', gridTemplateColumns: '104px 1fr 1fr', gap: '0 12px' }}>
            <Form.Item name="code" label="短码" rules={[{ required: true, message: '短码必填' }]} style={{ marginBottom: 8 }}>
              <Input placeholder="如 HAF" />
            </Form.Item>
            <Form.Item name="name" label="产品中文名" rules={[{ required: true, message: '品名必填' }]} style={{ marginBottom: 8 }}>
              <Input placeholder="如 盐酸万古霉素" />
            </Form.Item>
            <Form.Item name="name_en" label="英文名（可选）" style={{ marginBottom: 8 }}>
              <Input placeholder="如 Vancomycin HCl" />
            </Form.Item>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button
              size="small"
              onClick={() => {
                setCreating(false)
                form.resetFields()
              }}
            >
              取消
            </Button>
            <Button size="small" type="primary" loading={saving} onClick={handleCreate}>
              创建
            </Button>
          </div>
        </Form>
      )}

      <Table<CoaProduct>
        rowKey="id"
        size="small"
        dataSource={products}
        pagination={false}
        scroll={{ y: 300 }}
        columns={[
          { title: '短码', dataIndex: 'code', width: 80 },
          { title: '品名', dataIndex: 'name' },
          { title: '标准数', dataIndex: 'standard_count', width: 76, align: 'center', render: (v) => v ?? 0 },
          {
            title: '状态',
            dataIndex: 'is_active',
            width: 76,
            render: (v: boolean) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
          },
          ...(canManage
            ? [
                {
                  title: '操作',
                  width: 72,
                  render: (_v: unknown, product: CoaProduct) => (
                    <Button type="text" size="small" onClick={() => setFieldsProduct(product)}>
                      字段
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />

      {fieldsProduct && (
        <ProductFieldsModal product={fieldsProduct} onClose={() => setFieldsProduct(null)} />
      )}
    </Modal>
  )
}

/** 字段配置编辑面板：持有可编辑行集，保存动作由自带底栏触发。 */
function FieldsPanel({
  initialFields,
  productId,
  onDone,
}: {
  initialFields: CoaProductField[]
  productId: string
  onDone: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  // 内置 3 字段（品名/批号/流水号）由编辑器恒定置顶展示，行集只留自定义
  const [rows, setRows] = useState<CoaBatchFieldRow[]>(() =>
    stripBuiltinFields(initialFields).map(toFieldRow)
  )
  const [saving, setSaving] = useState(false)

  const handleAdd = () =>
    setRows([...rows, toFieldRow({ key: '', label_cn: '', field_type: 'text' })])

  const handleSave = async () => {
    const problem = validateFieldRows(rows)
    if (problem) {
      message.warning(problem)
      return
    }
    setSaving(true)
    try {
      const result = await replaceCoaProductFields(productId, rowsToFieldPayload(rows))
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('字段配置已保存')
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
      onDone()
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={handleAdd}>
          新增字段
        </Button>
      </div>
      <CoaBatchFieldsEditor rows={rows} onChange={setRows} editable />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
        <Button onClick={onDone}>关闭</Button>
        <Button type="primary" loading={saving} onClick={() => void handleSave()}>
          保存
        </Button>
      </div>
    </>
  )
}

/** 产品批次信息字段配置弹窗：查看/编辑/全量替换（可脱离 docx 导入独立维护）。 */
function ProductFieldsModal({
  product,
  onClose,
}: {
  product: CoaProduct
  onClose: () => void
}) {
  const { data: fields, isLoading } = useQuery({
    queryKey: ['qa', 'coa', 'product-fields', product.id],
    queryFn: () => fetchCoaProductFields(product.id),
    // 弹窗期短生命周期，关闭即弃；重开时拿最新配置做初始行集
    staleTime: 0,
  })

  return (
    <Modal
      title={`批次信息字段 — ${product.code} ${product.name}`}
      open
      onCancel={onClose}
      footer={null}
      width={760}
    >
      {isLoading || fields === undefined ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : (
        <FieldsPanel key={product.id} initialFields={fields} productId={product.id} onDone={onClose} />
      )}
    </Modal>
  )
}

/** 标准头信息编辑：低频操作收进弹窗，让标准单页保持文档式阅读。 */
function StandardInfoModal({
  standard,
  onClose,
  onSaved,
}: {
  standard: CoaStandard
  onClose: () => void
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const result = await updateCoaStandard(standard.id, {
        code: values.code,
        name: values.name,
        customer: values.customer || null,
        market: values.market || null,
        version: values.version || null,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('标准信息已保存')
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="编辑标准信息"
      open
      width={560}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      onOk={handleSave}
      onCancel={onClose}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          code: standard.code,
          name: standard.name,
          customer: standard.customer ?? '',
          market: standard.market ?? '',
          version: standard.version ?? '',
        }}
      >
        <Form.Item name="code" label="模板编号" rules={[{ required: true, message: '模板编号必填' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="name" label="标准名称" rules={[{ required: true, message: '标准名称必填' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="customer" label="客户">
          <Input placeholder="可选" />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item name="market" label="药典">
            <Input placeholder="USP / EP" />
          </Form.Item>
          <Form.Item name="version" label="版本">
            <Input placeholder="如 2026" />
          </Form.Item>
        </div>
      </Form>
    </Modal>
  )
}

function SourcePill({ source }: { source: CoaStandard['source'] }) {
  return (
    <span className={`${styles.source} ${source === 'import' ? styles.sourceImport : styles.sourceManual}`}>
      {source === 'import' ? '导入' : '手工'}
    </span>
  )
}

function MetaItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.metaItem}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

export function CoaStandardsPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  // 无 manage 权限整页只读提示（配置页几乎全是写操作，apr 同口径）
  const canManage = hasPermission('qa:coa:manage')
  const router = useRouter()
  // 选择状态同步进 URL（?product=产品代码&standard=模板码），刷新/分享链接恢复
  // 现场。APR 录入页同款两层结构：picked* 只存显式切换的 ID，URL 字符在渲染期
  // 解析成 ID（列表异步加载，effect 镜像 state 被 eslint 禁）；派生回落（第一个）
  // 不写回 URL，用户显式切换时才同步链接。
  const searchParams = useSearchParams()
  const productParam = searchParams.get('product')
  const standardParam = searchParams.get('standard')
  const [pickedProductId, setPickedProductId] = useState<string | null>(null)
  const [pickedStandardId, setPickedStandardId] = useState<string | null>(null)
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editingStandard, setEditingStandard] = useState<CoaStandard | null>(null)
  const [savingItems, setSavingItems] = useState(false)
  const [createForm] = Form.useForm()

  /** 把局部改动合并进当前查询串；空值即删除该参数。 */
  const syncUrl = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [key, value] of Object.entries(patch)) {
      if (value == null || value === '') params.delete(key)
      else params.set(key, value)
    }
    const query = params.toString()
    router.replace(query ? `/qa/coa/standards?${query}` : '/qa/coa/standards', { scroll: false })
  }

  const productsQuery = useQuery({
    queryKey: ['qa', 'coa', 'products'],
    queryFn: () => fetchCoaProducts(false),
  })
  const products = productsQuery.data ?? []
  // 选中优先级：显式切换（ID 须仍存在）> URL 产品代码（不存在视为无效）> 第一个
  const pickedProduct = products.some((p) => p.id === pickedProductId) ? pickedProductId : null
  const urlProductId = productParam
    ? (products.find((p) => p.code === productParam)?.id ?? null)
    : null
  const activeProductId = pickedProduct ?? urlProductId ?? products[0]?.id ?? null
  const activeProduct = products.find((p) => p.id === activeProductId) ?? null

  const standardsQuery = useQuery({
    queryKey: ['qa', 'coa', 'standards', activeProduct?.id],
    queryFn: () => fetchCoaStandards(activeProduct!.id),
    enabled: !!activeProduct,
  })
  // 下拉按模板编号自然排序（数字段按数值比较），不依赖后端返回顺序
  const standards = [...(standardsQuery.data ?? [])].sort((a, b) =>
    a.code.localeCompare(b.code, 'en', { numeric: true })
  )
  // 标准选中：显式切换 > URL 模板码（仅在本产品的标准列表内解析）> 第一个
  const pickedStandard = standards.some((s) => s.id === pickedStandardId) ? pickedStandardId : null
  const urlStandardId = standardParam
    ? (standards.find((s) => s.code === standardParam)?.id ?? null)
    : null
  const currentStandardId = pickedStandard ?? urlStandardId ?? standards[0]?.id ?? null
  const currentStandard = standards.find((s) => s.id === currentStandardId) ?? null

  const detailQuery = useQuery({
    queryKey: ['qa', 'coa', 'standard-detail', currentStandard?.id],
    queryFn: () => fetchCoaStandardDetail(currentStandard!.id),
    enabled: !!currentStandard,
  })
  const detail = detailQuery.data ?? null

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
  }

  const handleCreateStandard = async () => {
    const values = await createForm.validateFields()
    const result = await createCoaStandard({
      product_id: activeProduct!.id,
      code: values.code,
      name: values.name,
      customer: values.customer || null,
    })
    if (!result.success) {
      message.error(actionError(result))
      return
    }
    message.success('标准已创建，请继续添加检测项目')
    createForm.resetFields()
    setCreateOpen(false)
    invalidate()
  }

  const handleDeleteStandard = (standard: CoaStandard) => {
    confirmAsync(modal, {
      title: `删除标准「${standard.code} ${standard.name}」？`,
      content: '已有出具登记的标准不能删除（可停用）。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        const result = await deleteCoaStandard(standard.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('标准已删除')
        // 删除后清模板参数：URL 里的码已失效，回落第一个（派生不写 URL）
        if (currentStandardId === standard.id) {
          setPickedStandardId(null)
          syncUrl({ standard: null })
        }
        invalidate()
      },
    })
  }

  const handleOpenCreate = () => {
    if (!activeProduct) return
    setCreateOpen(true)
  }

  return (
    <div style={qaPageStyle} data-coa-standards>
      <PageHeading
        title="COA 客户标准配置"
        subtitle="一个产品多套客户标准；docx 导入生成草稿，人工确认落库"
      />

      {!canManage && (
        <Alert type="info" showIcon title="只读模式：配置客户标准需要 qa:coa:manage 权限" style={{ marginBottom: 16 }} />
      )}

      {productsQuery.isLoading ? (
        <div className={styles.loadingPanel} aria-busy="true">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : products.length === 0 ? (
        <div className={styles.sheet}>
          <div className={styles.sheetEmpty}>
            <EmptyState
              title="还没有产品"
              hint="COA 客户标准挂在产品下。先创建产品，再维护这个产品的客户标准；也可以直接从 docx 导入并建品。"
              action={
                <Space>
                  <Button onClick={() => setProductModalOpen(true)}>打开产品管理</Button>
                  {canManage && (
                    <Button type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
                      导入 docx
                    </Button>
                  )}
                </Space>
              }
            />
          </div>
        </div>
      ) : (
        <div className={styles.workspace}>
          <div className={styles.scopeBar}>
            <div className={styles.scopeFieldProduct}>
              <label className={styles.scopeLabel} htmlFor="coa-standard-product">
                产品
              </label>
              <Select
                id="coa-standard-product"
                className={styles.scopeSelect}
                aria-label="当前产品"
                placeholder="选择产品"
                value={activeProduct?.id}
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
            </div>
            <Button type="text" size="small" icon={<SettingOutlined />} onClick={() => setProductModalOpen(true)}>
              产品管理
            </Button>

            <div className={styles.scopeFieldStandard}>
              <label className={styles.scopeLabel} htmlFor="coa-standard-choice">
                标准
              </label>
              <Select
                id="coa-standard-choice"
                className={styles.scopeSelect}
                aria-label="客户标准"
                placeholder={standards.length === 0 ? '该产品暂无标准' : '选择客户标准'}
                value={currentStandard?.id}
                disabled={standardsQuery.isLoading || standards.length === 0}
                loading={standardsQuery.isLoading}
                showSearch={{ optionFilterProp: 'label' }}
                options={standards.map((s) => ({ value: s.id, label: `${s.code} ${s.name}` }))}
                onChange={(id) => {
                  setPickedStandardId(id)
                  syncUrl({ standard: standards.find((s) => s.id === id)?.code ?? null })
                }}
              />
              <span className={styles.scopeCount}>
                {standardsQuery.isLoading ? '—' : `${standards.length} 套`}
              </span>
            </div>

            {canManage && (
              <div className={styles.scopeActions}>
                <Button size="small" icon={<PlusOutlined />} onClick={handleOpenCreate}>
                  新建标准
                </Button>
                <Button size="small" type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
                  导入 docx
                </Button>
              </div>
            )}
          </div>

          <div className={styles.sheet}>
            {currentStandard ? (
              <>
                <header className={styles.sheetHead}>
                  <div className={styles.sheetIdentity}>
                    <div className={styles.sheetTopline}>
                      <span className={styles.sheetCode}>模板 {currentStandard.code}</span>
                      <SourcePill source={currentStandard.source} />
                    </div>
                    <h2 className={styles.sheetTitle} title={currentStandard.name}>
                      {currentStandard.name}
                    </h2>
                    <dl className={styles.sheetMeta}>
                      <MetaItem label="客户">
                        {currentStandard.customer || <span className={styles.muted}>未指定</span>}
                      </MetaItem>
                      <MetaItem label="药典">
                        {currentStandard.market || <span className={styles.muted}>未指定</span>}
                      </MetaItem>
                      <MetaItem label="版本">
                        {currentStandard.version || <span className={styles.muted}>未指定</span>}
                      </MetaItem>
                      <MetaItem label="已出具 COA">{currentStandard.report_count ?? 0} 份</MetaItem>
                    </dl>
                  </div>
                  {canManage && (
                    <div className={styles.sheetActions}>
                      <Button size="small" onClick={() => setEditingStandard(currentStandard)}>
                        编辑信息
                      </Button>
                      <Button size="small" type="text" danger onClick={() => handleDeleteStandard(currentStandard)}>
                        删除标准
                      </Button>
                    </div>
                  )}
                </header>

                <div className={styles.itemsSection}>
                  <div className={styles.sectionHead}>
                    <h3 className={styles.sectionTitle}>
                      批次信息字段
                      {detail?.batch_fields_custom && (
                        <Tag color="orange" style={{ marginInlineStart: 8 }}>
                          自定义
                        </Tag>
                      )}
                    </h3>
                    <span className={styles.sectionHint}>
                      该模板 COA 要记录的批次信息
                    </span>
                  </div>
                  {detail?.batch_fields ? (
                    <CoaStandardFieldsSection
                      key={detail.id + String(detail.batch_fields_custom) + detail.batch_fields.length}
                      standardId={detail.id}
                      fields={detail.batch_fields}
                      defaults={detail.product_fields ?? []}
                      custom={Boolean(detail.batch_fields_custom)}
                      canManage={canManage}
                      onSaved={invalidate}
                    />
                  ) : (
                    <Skeleton active paragraph={{ rows: 3 }} />
                  )}
                </div>

                <div className={styles.itemsSection}>
                  <div className={styles.sectionHead}>
                    <h3 className={styles.sectionTitle}>检测项目</h3>
                    <span className={styles.sectionHint}>
                      顺序即 COA 报告中的项目顺序，共 {detail?.items?.length ?? currentStandard.item_count ?? 0} 项
                    </span>
                  </div>
                  {detail ? (
                    <CoaStandardItemsEditor
                      key={detail.id + String(detail.item_count)}
                      initialItems={detail.items ?? []}
                      canManage={canManage}
                      saving={savingItems}
                      onSave={async (items) => {
                        setSavingItems(true)
                        try {
                          const result = await replaceCoaStandardItems(detail.id, items)
                          if (!result.success) {
                            message.error(actionError(result))
                            return false
                          }
                          message.success(`已保存 ${items.length} 个项目`)
                          invalidate()
                          return true
                        } finally {
                          setSavingItems(false)
                        }
                      }}
                    />
                  ) : detailQuery.isError ? (
                    <EmptyState
                      title="标准详情加载失败"
                      hint="网络或服务异常，请重新加载。"
                      action={<Button onClick={() => void detailQuery.refetch()}>重新加载</Button>}
                    />
                  ) : (
                    <Skeleton active paragraph={{ rows: 6 }} />
                  )}
                </div>
              </>
            ) : standardsQuery.isLoading ? (
              <div className={styles.sheetLoading}>
                <Skeleton active paragraph={{ rows: 4 }} />
              </div>
            ) : (
              <div className={styles.sheetEmpty}>
                <EmptyState
                  title="这个产品还没有客户标准"
                  hint="用上方「新建标准」手工建，或「导入 docx」从历史 COA 报告生成草稿再确认。"
                />
              </div>
            )}
          </div>
        </div>
      )}

      {productModalOpen && (
        <ProductManageModal
          onClose={() => setProductModalOpen(false)}
          products={products}
          canManage={canManage}
        />
      )}

      {importOpen && (
        <CoaImportStandardModal
          onClose={() => setImportOpen(false)}
          products={products}
          onSaved={invalidate}
        />
      )}

      {editingStandard && (
        <StandardInfoModal
          standard={editingStandard}
          onClose={() => setEditingStandard(null)}
          onSaved={invalidate}
        />
      )}

      {createOpen && activeProduct && (
        <Modal
          title={`新建客户标准（${activeProduct.code} ${activeProduct.name}）`}
          open
          onCancel={() => setCreateOpen(false)}
          onOk={handleCreateStandard}
          okText="创建"
          cancelText="取消"
        >
          <Form form={createForm} layout="vertical">
            <Form.Item name="code" label="模板编号" rules={[{ required: true, message: '模板编号必填（docx 导入登记时按它自动匹配）' }]}>
              <Input placeholder="如 3205" />
            </Form.Item>
            <Form.Item name="name" label="标准名称" rules={[{ required: true }]}>
              <Input placeholder="如 USP 内控版" />
            </Form.Item>
            <Form.Item name="customer" label="客户">
              <Input placeholder="可选" />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  )
}

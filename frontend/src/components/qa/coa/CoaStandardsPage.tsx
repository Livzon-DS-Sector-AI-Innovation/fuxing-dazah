'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import { FileAddOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons'
import { actionError, EmptyState, qaPageStyle, subtleText } from '@/components/qa/deviation/shared'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import {
  createCoaProduct,
  createCoaStandard,
  deleteCoaStandard,
  replaceCoaStandardItems,
  updateCoaStandard,
} from '@/actions/qa'
import { fetchCoaProducts, fetchCoaStandardDetail, fetchCoaStandards } from '@/lib/api/qa'
import type { CoaProduct, CoaStandard } from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import { CoaImportStandardModal } from './CoaImportStandardModal'
import { CoaStandardItemsEditor } from './CoaStandardItemsEditor'

/** 产品管理弹窗：新增 + 启停（产品删除有标准引用守卫，前端不提供入口）。 */
function ProductManageModal({
  onClose,
  products,
}: {
  onClose: () => void
  products: CoaProduct[]
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const handleCreate = async () => {
    const values = await form.validateFields()
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
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa'] })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="产品管理" open onCancel={onClose} footer={null} width={560}>
      <Form form={form} layout="vertical">
        <Space.Compact style={{ display: 'flex', marginBottom: 16 }}>
          <Form.Item name="code" noStyle rules={[{ required: true, message: '短码必填' }]}>
            <Input placeholder="短码（如 HAF）" style={{ width: 130 }} />
          </Form.Item>
          <Form.Item name="name" noStyle rules={[{ required: true, message: '品名必填' }]}>
            <Input placeholder="产品中文名" />
          </Form.Item>
          <Form.Item name="name_en" noStyle>
            <Input placeholder="英文名（可选）" />
          </Form.Item>
          <Button type="primary" loading={saving} onClick={handleCreate}>
            新增
          </Button>
        </Space.Compact>
      </Form>
      <Table<CoaProduct>
        rowKey="id"
        size="small"
        dataSource={products}
        pagination={false}
        scroll={{ y: 300 }}
        columns={[
          { title: '短码', dataIndex: 'code', width: 80 },
          { title: '品名', dataIndex: 'name' },
          { title: '标准数', dataIndex: 'standard_count', width: 80, render: (v) => v ?? 0 },
          {
            title: '状态',
            dataIndex: 'is_active',
            width: 80,
            render: (v: boolean) => (v ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
          },
        ]}
      />
    </Modal>
  )
}

/** 标准头信息编辑（内联表单）。 */
function StandardHeadForm({
  standard,
  onSaved,
}: {
  standard: CoaStandard
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
    } finally {
      setSaving(false)
    }
  }

  return (
    <Form
      form={form}
      layout="inline"
      initialValues={{
        code: standard.code,
        name: standard.name,
        customer: standard.customer ?? '',
        market: standard.market ?? '',
        version: standard.version ?? '',
      }}
      style={{ flexWrap: 'wrap', gap: 8, marginBottom: 12 }}
    >
      <Form.Item name="code" label="模板编号" rules={[{ required: true }]}>
        <Input style={{ width: 120 }} />
      </Form.Item>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input style={{ width: 220 }} />
      </Form.Item>
      <Form.Item name="customer" label="客户">
        <Input style={{ width: 180 }} />
      </Form.Item>
      <Form.Item name="market" label="药典">
        <Input style={{ width: 100 }} placeholder="USP/EP" />
      </Form.Item>
      <Form.Item name="version" label="版本">
        <Input style={{ width: 100 }} placeholder="如 2026" />
      </Form.Item>
      <Button type="primary" loading={saving} onClick={handleSave}>
        保存信息
      </Button>
    </Form>
  )
}

export function CoaStandardsPage() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { hasPermission } = usePermission()
  // 无 manage 权限整页只读提示（配置页几乎全是写操作，apr 同口径）
  const canManage = hasPermission('qa:coa:standard:manage')
  const [productId, setProductId] = useState<string | null>(null)
  const [standardId, setStandardId] = useState<string | null>(null)
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [savingItems, setSavingItems] = useState(false)
  const [createForm] = Form.useForm()

  const productsQuery = useQuery({
    queryKey: ['qa', 'coa', 'products'],
    queryFn: () => fetchCoaProducts(false),
  })
  const products = productsQuery.data ?? []
  const activeProduct = products.find((p) => p.id === productId) ?? products[0] ?? null

  const standardsQuery = useQuery({
    queryKey: ['qa', 'coa', 'standards', activeProduct?.id],
    queryFn: () => fetchCoaStandards(activeProduct!.id),
    enabled: !!activeProduct,
  })
  const standards = standardsQuery.data ?? []
  const currentStandard = standards.find((s) => s.id === standardId) ?? standards[0] ?? null

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
        if (standardId === standard.id) setStandardId(null)
        invalidate()
      },
    })
  }

  return (
    <div style={qaPageStyle}>
      <PageHeading
        title="COA 客户标准配置"
        subtitle="一个产品多套客户标准；docx 导入生成草稿，人工确认落库"
        actions={
          <>
            <Button icon={<SettingOutlined />} onClick={() => setProductModalOpen(true)}>
              产品管理
            </Button>
            {canManage && (
              <>
                <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)} disabled={!activeProduct}>
                  新建标准
                </Button>
                <Button type="primary" icon={<FileAddOutlined />} onClick={() => setImportOpen(true)}>
                  导入 docx 生成标准
                </Button>
              </>
            )}
          </>
        }
      />

      {!canManage && (
        <Alert type="info" showIcon title="只读模式：配置客户标准需要 qa:coa:standard:manage 权限" style={{ marginBottom: 16 }} />
      )}

      <Space style={{ marginBottom: 16 }}>
        <span style={subtleText}>产品</span>
        <Select
          style={{ width: 300 }}
          placeholder="选择产品"
          value={activeProduct?.id}
          showSearch
          optionFilterProp="label"
          options={products.map((p) => ({ value: p.id, label: `${p.code} ${p.name}` }))}
          onChange={(id) => {
            setProductId(id)
            setStandardId(null)
          }}
        />
      </Space>

      {activeProduct ? (
        standards.length > 0 ? (
          <>
            <Table<CoaStandard>
              rowKey="id"
              size="small"
              dataSource={standards}
              pagination={false}
              style={{ marginBottom: 20 }}
              onRow={(record) => ({
                onClick: () => setStandardId(record.id),
                style: { cursor: 'pointer', background: record.id === currentStandard?.id ? 'var(--color-accent-subtle, rgba(0,0,0,0.03))' : undefined },
              })}
              columns={[
                { title: '模板编号', dataIndex: 'code', width: 110 },
                { title: '标准名称', dataIndex: 'name' },
                { title: '客户', dataIndex: 'customer', render: (v) => v ?? '—' },
                { title: '药典', dataIndex: 'market', width: 80, render: (v) => v ?? '—' },
                { title: '项目数', dataIndex: 'item_count', width: 80, render: (v) => v ?? 0 },
                { title: '出具数', dataIndex: 'report_count', width: 80, render: (v) => v ?? 0 },
                {
                  title: '来源',
                  dataIndex: 'source',
                  width: 80,
                  render: (v: string) => (v === 'import' ? <Tag color="blue">导入</Tag> : <Tag>手工</Tag>),
                },
                {
                  title: '操作',
                  width: 80,
                  render: (_v, record) =>
                    canManage && (
                      <Button type="link" size="small" danger onClick={(e) => { e.stopPropagation(); handleDeleteStandard(record) }}>
                        删除
                      </Button>
                    ),
                },
              ]}
            />

            {detail && (
              <div>
                <StandardHeadForm standard={detail} onSaved={invalidate} />
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
                      message.success(`已保存 ${items.length} 个项目（被值引用的移除项已停用保留）`)
                      invalidate()
                      return true
                    } finally {
                      setSavingItems(false)
                    }
                  }}
                />
              </div>
            )}
          </>
        ) : (
          <EmptyState
            title="该产品还没有客户标准"
            hint={canManage ? '点击右上角「新建标准」手工配置，或「导入 docx 生成标准」从一份历史 COA 报告直接提取' : undefined}
          />
        )
      ) : (
        <EmptyState title="请先在产品管理中创建产品" />
      )}

      {productModalOpen && (
        <ProductManageModal onClose={() => setProductModalOpen(false)} products={products} />
      )}

      {importOpen && (
        <CoaImportStandardModal
          onClose={() => setImportOpen(false)}
          products={products}
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

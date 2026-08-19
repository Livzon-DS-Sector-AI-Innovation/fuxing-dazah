'use client'

import { Suspense, useState, useCallback } from 'react'
import {
  App,
  Button,
  ConfigProvider,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { antdTheme } from '@/lib/antd-theme'
import { usePermission } from '@/hooks/usePermission'
import {
  createProduct,
  updateProduct,
  deleteProduct,
  createIntermediateType,
  updateIntermediateType,
  deleteIntermediateType,
} from '@/actions/production'
import {
  fetchProductsClient,
  fetchIntermediateTypesClient,
  fetchRoutesClient,
} from '@/lib/api/production-client'
import type { Product, IntermediateType } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { LinesTab } from './LinesTab'

const { Text } = Typography

// ── 产品表单弹窗 ──

function ProductFormModal({
  open,
  product,
  onClose,
  onSaved,
}: {
  open: boolean
  product: Product | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const result = product
      ? await updateProduct(product.id, values)
      : await createProduct(values)
    if (result.success) {
      message.success(product ? '产品已更新' : '产品已创建')
      onSaved()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={product ? '编辑产品' : '新增产品'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={product ?? { product_code: '', product_name: '', unit: 'kg', remark: '' }}
      >
        <Form.Item name="product_code" label="产品编码">
          <Input maxLength={50} />
        </Form.Item>
        <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="unit" label="单位">
          <Input maxLength={20} />
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 产出物表单弹窗 ──

function IntermediateTypeFormModal({
  open,
  editItem,
  onClose,
  onSaved,
}: {
  open: boolean
  editItem: IntermediateType | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()

  const { data: products } = useQuery({
    queryKey: ['products-select'],
    queryFn: () => fetchProductsClient(),
    enabled: open,
  })

  const isProduct = Form.useWatch('is_product', form)

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const result = editItem
      ? await updateIntermediateType(editItem.id, values)
      : await createIntermediateType(values)
    if (result.success) {
      message.success(editItem ? '产出物已更新' : '产出物已创建')
      onSaved()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={editItem ? '编辑产出物' : '新增产出物'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={editItem ?? {
          code: '', name: '', category: '', default_unit: '', description: '',
          is_product: false, product_id: null,
        }}
      >
        <Form.Item name="code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
          <Input maxLength={50} disabled={!!editItem} />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="category" label="分类">
          <Input maxLength={100} placeholder="如：发酵液、结晶粉、湿品" />
        </Form.Item>
        <Form.Item name="default_unit" label="默认单位">
          <Input maxLength={20} placeholder="如：kg、L" />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="is_product" label="标记为成品" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="product_id" label="关联产品">
          <Select
            allowClear
            placeholder="选择关联的产品"
            disabled={!isProduct}
            options={(products ?? []).map((p) => ({
              value: p.id,
              label: p.product_name,
            }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 产品详情面板 ──

function ProductDetail({ product }: { product: Product }) {
  const { data: routes } = useQuery({
    queryKey: ['production-routes', product.id],
    queryFn: () => fetchRoutesClient(product.id, undefined),
    enabled: !!product.id,
  })

  const routeColumns: ColumnsType<{ id: string; route_name: string; status: string }> = [
    { title: '路线名称', dataIndex: 'route_name', key: 'route_name' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s: string) => {
        const m: Record<string, { label: string; color: string }> = {
          draft: { label: '草稿', color: 'default' },
          published: { label: '已发布', color: 'green' },
          archived: { label: '已归档', color: 'default' },
        }
        const c = m[s] ?? { label: s, color: 'default' }
        return <Tag color={c.color}>{c.label}</Tag>
      },
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24, paddingBottom: 16, borderBottom: '1px solid #e5e3df' }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 600 }}>{product.product_name}</h3>
        <div style={{ display: 'flex', gap: 16, fontSize: 13, color: '#5d5b54' }}>
          {product.product_code && <span>编码: {product.product_code}</span>}
          <span>单位: {product.unit}</span>
        </div>
        {product.remark && (
          <div style={{ fontSize: 13, color: '#787671', marginTop: 8 }}>{product.remark}</div>
        )}
      </div>
      <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 8 }}>关联工艺路线</Text>
      <Table
        dataSource={routes ?? []}
        columns={routeColumns}
        rowKey="id"
        size="small"
        pagination={false}
        locale={{ emptyText: <Empty description="暂无工艺路线" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </div>
  )
}

// ── 产出物卡片 ──

function IntermediateTypeCard({
  item,
  canManage,
  onEdit,
  onDelete,
}: {
  item: IntermediateType
  canManage: boolean
  onEdit: () => void
  onDelete: () => void
}) {
  const props: [string, string | null][] = [
    ['分类', item.category],
    ['默认单位', item.default_unit],
    ...(item.product_name ? [['关联产品', item.product_name] as [string, string]] : []),
  ]
  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 14,
        border: '1px solid #e5e3df',
        padding: '18px 18px 0',
        display: 'flex',
        flexDirection: 'column',
        transition: 'border-color .15s, box-shadow .15s, transform .15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(86,69,212,0.35)'
        e.currentTarget.style.boxShadow = '0 6px 16px rgba(0,0,0,0.06)'
        e.currentTarget.style.transform = 'translateY(-1px)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#e5e3df'
        e.currentTarget.style.boxShadow = 'none'
        e.currentTarget.style.transform = 'none'
      }}
    >
      {/* 头部：编码眉标 + 名称 */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: 11, color: '#a4a097', letterSpacing: 0.4, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.code}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, fontSize: 16, color: '#1a1a1a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.name}
          </span>
          {item.is_product && <Tag color="green" style={{ fontSize: 10, lineHeight: '18px', padding: '0 5px', margin: 0 }}>成品</Tag>}
        </div>
      </div>
      {/* 属性区：标签/值 两列 */}
      <div style={{ display: 'grid', gridTemplateColumns: '64px 1fr', rowGap: 6, fontSize: 12.5, marginBottom: 14 }}>
        {props.map(([label, value]) => (
          <div key={label} style={{ display: 'contents' }}>
            <span style={{ color: '#a4a097' }}>{label}</span>
            <span style={{ color: '#1a1a1a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {value || '—'}
            </span>
          </div>
        ))}
      </div>
      {item.description && (
        <div style={{
          fontSize: 12.5, color: '#787671', lineHeight: 1.6, marginBottom: 14,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {item.description}
        </div>
      )}
      {/* 底部操作区 */}
      {canManage && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 4, borderTop: '1px solid #ede9e4', padding: '8px 0 12px', marginTop: 'auto' }}>
          <Button size="small" type="text" icon={<EditOutlined style={{ fontSize: 13 }} />} onClick={onEdit}>编辑</Button>
          <Button size="small" type="text" danger icon={<DeleteOutlined style={{ fontSize: 13 }} />} onClick={onDelete}>删除</Button>
        </div>
      )}
    </div>
  )
}

// ── 主页面 ──

function MasterDataContent() {
  const { hasPermission } = usePermission()
  const canManage = hasPermission('production:process:manage')
  const queryClient = useQueryClient()
  const { message, modal } = App.useApp()

  // ── 产品状态 ──
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [editProduct, setEditProduct] = useState<Product | null>(null)
  const [productKeyword, setProductKeyword] = useState('')

  const { data: products } = useQuery({
    queryKey: ['production-products', productKeyword],
    queryFn: () => fetchProductsClient(productKeyword || undefined),
  })

  // ── 产出物状态 ──
  const [itModalOpen, setItModalOpen] = useState(false)
  const [editIT, setEditIT] = useState<IntermediateType | null>(null)
  const [itKeyword, setItKeyword] = useState('')

  const { data: itData } = useQuery({
    queryKey: ['intermediate-types', itKeyword],
    queryFn: () => fetchIntermediateTypesClient({ keyword: itKeyword || undefined }),
  })
  const intermediateTypes = itData?.items ?? []

  // ── 产品 CRUD ──
  const handleDeleteProduct = (p: Product) => {
    modal.confirm({
      title: `删除产品「${p.product_name}」?`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteProduct(p.id)
        if (result.success) {
          message.success('已删除')
          if (selectedProduct?.id === p.id) setSelectedProduct(null)
          queryClient.invalidateQueries({ queryKey: ['production-products'] })
        } else {
          message.error(result.error)
        }
      },
    })
  }

  const handleProductSaved = useCallback(() => {
    setProductModalOpen(false)
    setEditProduct(null)
    queryClient.invalidateQueries({ queryKey: ['production-products'] })
  }, [queryClient])

  // ── 产出物 CRUD ──
  const handleDeleteIT = (it: IntermediateType) => {
    modal.confirm({
      title: `删除产出物「${it.name}」?`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteIntermediateType(it.id)
        if (result.success) {
          message.success('已删除')
          queryClient.invalidateQueries({ queryKey: ['intermediate-types'] })
        } else {
          message.error(result.error)
        }
      },
    })
  }

  const handleITSaved = useCallback(() => {
    setItModalOpen(false)
    setEditIT(null)
    queryClient.invalidateQueries({ queryKey: ['intermediate-types'] })
  }, [queryClient])

  const tabItems = [
    {
      key: 'products',
      label: '产品',
      children: (
        <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
          {/* 产品列表 */}
          <div style={{ width: 300, flexShrink: 0, background: '#fff', borderRadius: 12, border: '1px solid #e5e3df', overflow: 'hidden' }}>
            <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid #ede9e4', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text strong style={{ fontSize: 14, flex: 1 }}>产品列表</Text>
              {canManage && (
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => { setEditProduct(null); setProductModalOpen(true) }}>
                  新增
                </Button>
              )}
            </div>
            <div style={{ padding: '8px 14px' }}>
              <Input
                allowClear
                size="small"
                placeholder="搜索产品..."
                value={productKeyword}
                onChange={(e) => setProductKeyword(e.target.value)}
              />
            </div>
            <div style={{ maxHeight: 420, overflowY: 'auto', padding: '0 8px 8px' }}>
              {(products ?? []).map((p) => {
                const isSelected = selectedProduct?.id === p.id
                return (
                  <div
                    key={p.id}
                    onClick={() => setSelectedProduct(p)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '9px 10px', marginBottom: 2, borderRadius: 8, cursor: 'pointer',
                      background: isSelected ? 'rgba(86,69,212,0.05)' : 'transparent',
                      border: isSelected ? '1px solid rgba(86,69,212,0.15)' : '1px solid transparent',
                    }}
                  >
                    <div style={{
                      width: 36, height: 36, borderRadius: 8,
                      background: isSelected ? '#e6e0f5' : '#f6f5f4',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 14, fontWeight: 600,
                      color: isSelected ? '#5645d4' : '#787671',
                      flexShrink: 0,
                    }}>
                      {p.product_name.charAt(0)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: isSelected ? 600 : 500, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {p.product_name}
                      </div>
                      {p.product_code && <div style={{ fontSize: 11, color: '#a4a097' }}>{p.product_code}</div>}
                    </div>
                    {canManage && (
                      <div style={{ display: 'flex', gap: 2, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
                        <Button size="small" type="text" icon={<EditOutlined style={{ fontSize: 13 }} />}
                          onClick={() => { setEditProduct(p); setProductModalOpen(true) }} />
                        <Button size="small" type="text" danger icon={<DeleteOutlined style={{ fontSize: 13 }} />}
                          onClick={() => handleDeleteProduct(p)} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
          {/* 产品详情 */}
          <div style={{ flex: 1, background: '#fff', borderRadius: 12, border: '1px solid #e5e3df', padding: 20, minHeight: 480 }}>
            {selectedProduct ? (
              <ProductDetail product={selectedProduct} />
            ) : (
              <div style={{ textAlign: 'center', padding: '80px 0' }}>
                <Empty description="选择左侧产品查看详情" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'intermediate-types',
      label: '产出物',
      children: (
        <div>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
            <Input
              allowClear
              style={{ maxWidth: 280 }}
              placeholder="搜索产出物..."
              value={itKeyword}
              onChange={(e) => setItKeyword(e.target.value)}
            />
            {canManage && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditIT(null); setItModalOpen(true) }}>
                新增产出物
              </Button>
            )}
          </div>
          {intermediateTypes.length === 0 ? (
            <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e5e3df', padding: '64px 0' }}>
              <Empty description={itKeyword ? '未找到匹配的产出物' : '暂无产出物，点击右上角新增'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
              {intermediateTypes.map((it) => (
                <IntermediateTypeCard
                  key={it.id}
                  item={it}
                  canManage={canManage}
                  onEdit={() => { setEditIT(it); setItModalOpen(true) }}
                  onDelete={() => handleDeleteIT(it)}
                />
              ))}
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'lines',
      label: '产线',
      children: <LinesTab canManage={canManage} />,
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
          主数据管理
        </h2>
        <span style={{ color: '#787671', fontSize: 14 }}>
          管理产品主数据与产出物（中间体）字典
        </span>
      </div>
      <Tabs items={tabItems} />
      <ProductFormModal
        key={editProduct?.id ?? 'product-new'}
        open={productModalOpen || !!editProduct}
        product={editProduct}
        onClose={() => { setProductModalOpen(false); setEditProduct(null) }}
        onSaved={handleProductSaved}
      />
      <IntermediateTypeFormModal
        key={editIT?.id ?? 'it-new'}
        open={itModalOpen || !!editIT}
        editItem={editIT}
        onClose={() => { setItModalOpen(false); setEditIT(null) }}
        onSaved={handleITSaved}
      />
    </div>
  )
}

export function MasterDataPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
            <MasterDataContent />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

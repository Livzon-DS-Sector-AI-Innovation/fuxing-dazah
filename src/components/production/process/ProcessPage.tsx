'use client'

import { Suspense, useMemo, useState } from 'react'
import { App, ConfigProvider, Empty, Skeleton } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { antdTheme } from '@/lib/antd-theme'
import { usePermission } from '@/hooks/usePermission'
import { fetchRouteGraphClient, fetchRoutesClient } from '@/lib/api/production-client'
import { deleteProduct } from '@/actions/production'
import type { Product } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { ProductSidebar, CARD_STYLE } from '../shared/ProductSidebar'
import { ProductFormModal } from './ProductFormModal'
import { RouteVersionBar } from './RouteVersionBar'
import { RouteFlowGraph } from './RouteFlowGraph'
import { RouteGraphEditor } from './RouteGraphEditor'
import { NodeFieldsDrawer } from './NodeFieldsDrawer'

function ProcessPageInner({ initialProducts }: { initialProducts: Product[] }) {
  void initialProducts // 产品列表由 ProductSidebar 经 React Query 拉取；SSR 数据仅用于首屏占位扩展
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('production:process:manage')
  const queryClient = useQueryClient()
  const { modal, message } = App.useApp()

  const selectedProductId = searchParams.get('product')
  const [currentRouteId, setCurrentRouteId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [editProduct, setEditProduct] = useState<Product | null>(null)
  const [fieldsNodeId, setFieldsNodeId] = useState<string | null>(null)

  const { data: routes, refetch: refetchRoutes } = useQuery({
    queryKey: ['production-routes', selectedProductId],
    queryFn: () => fetchRoutesClient(selectedProductId!),
    enabled: !!selectedProductId,
  })

  // 默认选中 published 版本，其次第一个
  const effectiveRouteId = useMemo(() => {
    if (currentRouteId && routes?.some(r => r.id === currentRouteId)) return currentRouteId
    return routes?.find(r => r.status === 'published')?.id ?? routes?.[0]?.id ?? null
  }, [currentRouteId, routes])

  const { data: graph, isLoading: graphLoading, refetch: refetchGraph } = useQuery({
    queryKey: ['production-route-graph', effectiveRouteId],
    queryFn: () => fetchRouteGraphClient(effectiveRouteId!),
    enabled: !!effectiveRouteId,
  })

  const fieldsNode = graph?.nodes.find(n => n.id === fieldsNodeId) ?? null

  const handleDelete = (p: Product) => {
    modal.confirm({
      title: `删除产品「${p.product_name}」?`,
      content: '删除后该产品及其工艺路线将不再展示。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteProduct(p.id)
        if (!result.success) {
          message.error(result.error)
          return
        }
        message.success('删除成功')
        queryClient.invalidateQueries({ queryKey: ['production-products'] })
        if (p.id === selectedProductId) router.replace('/production/process')
      },
    })
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
          产品工艺
        </h2>
        <span style={{ color: '#787671', fontSize: 14 }}>
          管理产品主数据，配置工艺路线与节点流程
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
        <ProductSidebar
          selectedId={selectedProductId}
          onSelect={p => {
            setCurrentRouteId(null)
            setEditing(false)
            router.replace(`/production/process?product=${p.id}`)
          }}
          onCreate={canManage ? () => setProductModalOpen(true) : undefined}
          onEdit={canManage ? setEditProduct : undefined}
          onDelete={canManage ? handleDelete : undefined}
        />
        <div style={{ ...CARD_STYLE, flex: 1, padding: 16, minHeight: 560 }}>
          {!selectedProductId ? (
            <div style={{ textAlign: 'center', padding: '80px 0' }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <span style={{ color: '#787671', fontSize: 14 }}>
                    请在左侧选择一个产品，查看其工艺路线
                  </span>
                }
              />
            </div>
          ) : (
            <>
              <RouteVersionBar
                productId={selectedProductId}
                routes={routes ?? []}
                currentRouteId={effectiveRouteId}
                editing={editing}
                canManage={canManage}
                onSelect={id => {
                  setCurrentRouteId(id)
                  setEditing(false)
                }}
                onChanged={() => {
                  refetchRoutes()
                  refetchGraph()
                }}
                onEdit={() => setEditing(true)}
              />
              <div style={{ marginTop: 12 }}>
                {graphLoading ? (
                  <Skeleton active paragraph={{ rows: 8 }} />
                ) : editing && graph ? (
                  // editing 分支必须在空图检查之前：空 draft 路线也要能进编辑器
                  <RouteGraphEditor
                    routeId={effectiveRouteId!}
                    graph={graph}
                    onCancel={() => setEditing(false)}
                    onSaved={() => {
                      setEditing(false)
                      refetchGraph()
                    }}
                  />
                ) : !graph || !graph.nodes.length ? (
                  <div style={{ textAlign: 'center', padding: '60px 0' }}>
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        <span style={{ color: '#787671', fontSize: 14 }}>
                          {routes?.length
                            ? '该版本还没有工序节点，点击「编辑工艺」开始配置'
                            : '该产品还没有工艺路线，点击「新建路线」创建'}
                        </span>
                      }
                    />
                  </div>
                ) : (
                  <RouteFlowGraph
                    nodes={graph.nodes}
                    edges={graph.edges}
                    onNodeClick={setFieldsNodeId}
                  />
                )}
              </div>
            </>
          )}
        </div>
      </div>
      <ProductFormModal
        open={productModalOpen || !!editProduct}
        product={editProduct}
        onClose={() => { setProductModalOpen(false); setEditProduct(null) }}
      />
      <NodeFieldsDrawer
        open={!!fieldsNodeId}
        node={fieldsNode}
        editable={false}
        onClose={() => setFieldsNodeId(null)}
      />
    </div>
  )
}

export function ProcessPage({ initialProducts }: { initialProducts: Product[] }) {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<Skeleton active />}>
            <ProcessPageInner initialProducts={initialProducts} />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

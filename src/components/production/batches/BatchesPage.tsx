'use client'

import { Suspense, useState } from 'react'
import { App, ConfigProvider, Empty, Skeleton, Tabs } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useRouter, useSearchParams } from 'next/navigation'
import { antdTheme } from '@/lib/antd-theme'
import { usePermission } from '@/hooks/usePermission'
import type { Product, Execution } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'
import { ProductSidebar, CARD_STYLE } from '../shared/ProductSidebar'
import { BatchTable } from './BatchTable'
import { BatchDetailDrawer } from './BatchDetailDrawer'
import { CreateBatchModal } from './CreateBatchModal'
import { StartExecutionModal } from './StartExecutionModal'
import { CompleteExecutionModal } from './CompleteExecutionModal'
import { DeriveModal } from './DeriveModal'
import { MergeModal } from './MergeModal'
import { NodeExecutionsTable } from './NodeExecutionsTable'

function BatchesPageInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasPermission } = usePermission()
  const canSubmit = hasPermission('production:batch:submit')

  const selectedProductId = searchParams.get('product')
  const activeTab = searchParams.get('tab') ?? 'batches'
  const [createOpen, setCreateOpen] = useState(false)
  const [detailBatchId, setDetailBatchId] = useState<string | null>(null)
  const [startBatchId, setStartBatchId] = useState<string | null>(null)
  const [completeExec, setCompleteExec] = useState<{ execution: Execution; routeId: string } | null>(null)
  const [deriveBatchId, setDeriveBatchId] = useState<string | null>(null)
  const [mergeBatchId, setMergeBatchId] = useState<string | null>(null)

  const setParams = (patch: Record<string, string>) => {
    const q = new URLSearchParams(searchParams.toString())
    Object.entries(patch).forEach(([k, v]) => q.set(k, v))
    router.replace(`/production/batches?${q}`)
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
          批次管理
        </h2>
        <span style={{ color: '#787671', fontSize: 14 }}>
          批次执行记录、工序数据提交与全链路溯源
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
        <ProductSidebar
          selectedId={selectedProductId}
          onSelect={p => setParams({ product: p.id })}
        />
        <div style={{ ...CARD_STYLE, flex: 1, padding: 16, minHeight: 560 }}>
          {!selectedProductId ? (
            <div style={{ textAlign: 'center', padding: '80px 0' }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <span style={{ color: '#787671', fontSize: 14 }}>
                    请在左侧选择一个产品，查看其批次数据
                  </span>
                }
              />
            </div>
          ) : (
            <Tabs
              activeKey={activeTab}
              onChange={k => setParams({ tab: k })}
              items={[
                {
                  key: 'batches',
                  label: '批次视角',
                  children: (
                    <BatchTable
                      productId={selectedProductId}
                      canSubmit={canSubmit}
                      onCreate={() => setCreateOpen(true)}
                      onOpenDetail={setDetailBatchId}
                    />
                  ),
                },
                {
                  key: 'nodes',
                  label: '工序视角',
                  children: <NodeExecutionsTable productId={selectedProductId} />,
                },
              ]}
            />
          )}
        </div>
      </div>
      {selectedProductId && (
        <CreateBatchModal
          open={createOpen}
          productId={selectedProductId}
          onClose={() => setCreateOpen(false)}
        />
      )}
      {detailBatchId && (
        <BatchDetailDrawer
          batchId={detailBatchId}
          canSubmit={canSubmit}
          onClose={() => setDetailBatchId(null)}
          onStartExecution={setStartBatchId}
          onCompleteExecution={(e, routeId) => setCompleteExec({ execution: e, routeId })}
          onDerive={setDeriveBatchId}
          onMerge={setMergeBatchId}
        />
      )}
      {startBatchId && (
        <StartExecutionModal batchId={startBatchId} onClose={() => setStartBatchId(null)} />
      )}
      {completeExec && (
        <CompleteExecutionModal
          execution={completeExec.execution}
          routeId={completeExec.routeId}
          onClose={() => setCompleteExec(null)}
        />
      )}
      {deriveBatchId && (
        <DeriveModal batchId={deriveBatchId} onClose={() => setDeriveBatchId(null)} />
      )}
      {mergeBatchId && selectedProductId && (
        <MergeModal
          batchId={mergeBatchId}
          productId={selectedProductId}
          onClose={() => setMergeBatchId(null)}
        />
      )}
    </div>
  )
}

export function BatchesPage({ initialProducts }: { initialProducts: Product[] }) {
  void initialProducts
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <Suspense fallback={<Skeleton active style={{ padding: 24 }} />}>
            <BatchesPageInner />
          </Suspense>
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}

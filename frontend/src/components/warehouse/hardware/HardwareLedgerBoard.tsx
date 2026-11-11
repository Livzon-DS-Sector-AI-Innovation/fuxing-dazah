'use client'

// 五金库「盘点与台账」（2026-11-06 菜单改造）：原「五金盘点」「五金台账报表」
// 两页合并为一段式六段——盘点 | ERP 入库对账 | ERP 出库侧标记 | 报废 | 部门直发 | 流水台账。
// 旧路径 301 进本页（?tab= 深链，挂载后读一次 query）。

import { useEffect, useState } from 'react'
import { Segmented } from 'antd'
import { PageHeader } from '@/components/warehouse'
import { HardwareStocktakeBoard } from './HardwareStocktakeBoard'
import { HardwareScrapPanel } from './HardwareScrapPanel'
import {
  DirectPanel,
  ErpInboundReconcilePanel,
  ErpReconcilePanel,
  LedgerPanel,
} from './HardwareReportsPanels'

export type HardwareLedgerTab =
  | 'stocktake'
  | 'erp_in'
  | 'erp'
  | 'scrap'
  | 'direct'
  | 'ledger'

const TAB_KEYS: readonly HardwareLedgerTab[] = [
  'stocktake',
  'erp_in',
  'erp',
  'scrap',
  'direct',
  'ledger',
]

export function HardwareLedgerBoard() {
  const [tab, setTab] = useState<HardwareLedgerTab>('stocktake')

  // ?tab= 深链（301 跳转目标）：挂载后读一次，非法值回落默认
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    if (t && (TAB_KEYS as readonly string[]).includes(t)) {
      setTab(t as HardwareLedgerTab)
    }
  }, [])

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumb={['仓储管理', '五金库', '盘点与台账']}
        title="盘点与台账"
        description="盘点单生成→实盘→差异入账 · ERP 入库对账 · 出库侧 ERP 标记 · 报废台账 · 部门直发明细 · 流水台账导出"
      />
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as HardwareLedgerTab)}
        options={[
          { value: 'stocktake', label: '盘点' },
          { value: 'erp_in', label: 'ERP 入库对账' },
          { value: 'erp', label: 'ERP 出库侧标记' },
          { value: 'scrap', label: '报废' },
          { value: 'direct', label: '部门直发' },
          { value: 'ledger', label: '流水台账' },
        ]}
      />
      {tab === 'stocktake' && <HardwareStocktakeBoard />}
      {tab === 'erp_in' && <ErpInboundReconcilePanel />}
      {tab === 'erp' && <ErpReconcilePanel />}
      {tab === 'scrap' && <HardwareScrapPanel />}
      {tab === 'direct' && <DirectPanel />}
      {tab === 'ledger' && <LedgerPanel />}
    </div>
  )
}

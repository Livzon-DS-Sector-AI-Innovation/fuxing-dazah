'use client'

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
  | 'erp'
  | 'scrap'
  | 'direct'
  | 'ledger'

const TAB_KEYS: readonly HardwareLedgerTab[] = [
  'stocktake',
  'erp',
  'scrap',
  'direct',
  'ledger',
]

const TAB_ALIASES: Record<string, HardwareLedgerTab> = {
  ...Object.fromEntries(TAB_KEYS.map((k) => [k, k])),
  erp_in: 'erp',
}

export function HardwareLedgerBoard() {
  const [tab, setTab] = useState<HardwareLedgerTab>('stocktake')

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab')
    if (t && TAB_KEYS.includes(t as HardwareLedgerTab)) {
      setTab(t as HardwareLedgerTab)
    } else if (t && TAB_ALIASES[t]) {
      setTab(TAB_ALIASES[t])
    }
  }, [])

  return (
    <div className="flex flex-col gap-4">
      <PageHeader breadcrumb={['仓储管理', '五金库', '五金盘点台账']} title="五金盘点台账" />
      <Segmented
        value={tab}
        onChange={(v) => setTab(v as HardwareLedgerTab)}
        options={[
          { value: 'stocktake', label: '盘点' },
          { value: 'erp', label: 'ERP 对账' },
          { value: 'scrap', label: '报废' },
          { value: 'direct', label: '部门直发' },
          { value: 'ledger', label: '流水台账' },
        ]}
      />
      {tab === 'stocktake' && <HardwareStocktakeBoard />}
      {tab === 'erp' && (
        <div className="flex flex-col gap-4">
          <ErpInboundReconcilePanel />
          <ErpReconcilePanel />
        </div>
      )}
      {tab === 'scrap' && <HardwareScrapPanel />}
      {tab === 'direct' && <DirectPanel />}
      {tab === 'ledger' && <LedgerPanel />}
    </div>
  )
}

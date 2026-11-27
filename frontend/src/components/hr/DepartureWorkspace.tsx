'use client'

// 离职管理页外壳：持有当前页签与跨页签联动。
// - 办理页可以一键切到台账去挑人；办理推进后台账跟着刷新（两页签常驻，各自不会自动重拉）。
// - 网址参数：?case=<id> 直接打开那张办理单（从劳动合同页「转入离职办理」跳过来时带）；
//   ?stage=<状态> 进来就筛在某个环节（人事看板的待办栏用）。

import { useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { DepartureClient } from '@/components/hr'
import DepartureContractLedger from '@/components/hr/labor-contract/DepartureContractLedger'
import DepartureTabs, { type DepartureTabKey } from '@/components/hr/DepartureTabs'
import OffboardingBoardClient from '@/components/hr/OffboardingBoardClient'
import type { DepartureSyncInfo } from '@/components/hr/DepartureClient'

const STAGES = ['draft', 'approving', 'clearing', 'cert_issuing', 'delivering', 'signed', 'closed', 'canceled', 'overdue']

export default function DepartureWorkspace({ syncInfo }: { syncInfo?: DepartureSyncInfo }) {
  const searchParams = useSearchParams()
  const [tab, setTab] = useState<DepartureTabKey>('board')
  const [ledgerRefresh, setLedgerRefresh] = useState(0)

  const stage = searchParams.get('stage')
  return (
    <DepartureTabs
      activeKey={tab}
      onChange={setTab}
      board={
        <OffboardingBoardClient
          initialCaseId={searchParams.get('case')}
          initialStage={stage && STAGES.includes(stage) ? stage : null}
          onChanged={() => setLedgerRefresh((n) => n + 1)}
          onGoLedger={() => setTab('ledger')}
        />
      }
      ledger={
        <DepartureClient
          initialRecords={[]} initialTotal={0} syncInfo={syncInfo} refreshKey={ledgerRefresh}
        />
      }
      contract={<DepartureContractLedger />}
    />
  )
}

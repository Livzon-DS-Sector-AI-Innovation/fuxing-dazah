'use client'

// 劳动合同页的页签外壳（客户端组件：要读网址参数）。
// 两个页签常驻（切回来筛选、页码都还在），用刷新计数互相通知；
// ?todo=<口径> 进来就筛在某个环节（人事看板的待办栏用）。

import { useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Tabs } from 'antd'
import ContractLedgerClient from '@/components/hr/ContractLedgerClient'
import ContractArchiveClient from '@/components/hr/labor-contract/ContractArchiveClient'
import type { ContractTodoKey } from '@/types/hr'

const TODO_KEYS: ContractTodoKey[] = [
  'attention', 'pending_dept_approval', 'to_renew', 'to_stamp', 'to_deliver', 'to_archive',
  'pending_renewal', 'expired_unrenewed',
]

export default function ContractWorkspace() {
  const searchParams = useSearchParams()
  const todo = searchParams.get('todo')
  const [ledgerRefresh, setLedgerRefresh] = useState(0)
  const [archiveRefresh, setArchiveRefresh] = useState(0)

  return (
    // 常驻：在档案库归档后切回台账，「归档」列靠刷新计数更新，不必重新挂载丢掉筛选
    <Tabs
      defaultActiveKey="ledger"
      destroyOnHidden={false}
      items={[
        {
          key: 'ledger',
          label: '在职合同台账',
          children: (
            <ContractLedgerClient
              refreshKey={ledgerRefresh}
              initialTodo={todo && TODO_KEYS.includes(todo as ContractTodoKey) ? (todo as ContractTodoKey) : undefined}
              onChanged={() => setArchiveRefresh((n) => n + 1)}
            />
          ),
        },
        {
          key: 'archive',
          label: '电子档案库',
          children: (
            <ContractArchiveClient
              refreshKey={archiveRefresh}
              onChanged={() => setLedgerRefresh((n) => n + 1)}
            />
          ),
        },
      ]}
    />
  )
}

'use client'

import { Tabs } from 'antd'
import type { ReactNode } from 'react'

/** 离职页 Tab 外壳：台账（结果数据）/ 办理（过程流水线）/ 合同台账（离职人员合同，可选）。 */
export default function DepartureTabs({
  ledger, board, contract }: {
  ledger: ReactNode
  board: ReactNode
  contract?: ReactNode
}) {
  return (
    <Tabs
      defaultActiveKey="ledger"
      destroyOnHidden={false}
      items={[
        { key: 'ledger', label: '离职台账', children: ledger },
        { key: 'board', label: '离职办理', children: board },
        // 离职合同台账（劳动合同管理 P3）：与在职合同台账分开，两本台账不交叉
        ...(contract ? [{ key: 'contract', label: '合同台账', children: contract }] : []),
      ]}
    />
  )
}

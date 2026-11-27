'use client'

import { Tabs } from 'antd'
import type { ReactNode } from 'react'

export type DepartureTabKey = 'board' | 'ledger' | 'contract'

/** 离职管理页 Tab 外壳：办理（过程流水线，日常在这办）/ 台账（结果数据，查与导出）/ 离职合同台账。 */
export default function DepartureTabs({
  ledger,
  board,
  contract,
  activeKey,
  onChange,
}: {
  ledger: ReactNode
  board: ReactNode
  contract?: ReactNode
  activeKey: DepartureTabKey
  onChange: (key: DepartureTabKey) => void
}) {
  return (
    <Tabs
      activeKey={activeKey}
      onChange={(key) => onChange(key as DepartureTabKey)}
      // 常驻：切回台账时筛选条件和滚动位置都还在
      destroyOnHidden={false}
      items={[
        { key: 'board', label: '离职办理', children: board },
        { key: 'ledger', label: '离职台账', children: ledger },
        // 离职人员合同与在职合同台账分开，两本台账不交叉
        ...(contract ? [{ key: 'contract', label: '离职合同台账', children: contract }] : []),
      ]}
    />
  )
}

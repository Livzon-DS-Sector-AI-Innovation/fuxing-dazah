'use client'

// 教育培训与行为管控（S6）——统计+主台账+违章副台账（DomainLedgerPage 配置驱动）
// + 培训生产链三区块（#7：需求草案/课件试卷/签到成绩解析，AI 确认流）

import DomainLedgerPage from '@/components/safety/domain/DomainLedgerPage'
import { TrainingProductionPanel } from '@/components/safety/trainingBehavior/TrainingProductionPanel'

export default function TrainingBehaviorPage() {
  return (
    <div>
      <DomainLedgerPage domain="training-behavior" />
      <TrainingProductionPanel />
    </div>
  )
}

'use client'

// 隐患 AI 识别质量看板 — 独立页（P1-4）。
// 指标与离线 replay 同口径：JSON 合法率 / 闸门分布 / 引用可验证率 / 占位率 /
// 检索维度（P1-1 多路观测）/ 失败分类 / 死信水位 + P0-C 基线对照。

import { PageHeader } from '@/components/ui-kit'
import HazardQualityPanel from '@/components/safety/HazardQualityPanel'

export default function HazardQualityPageClient() {
  return (
    <div>
      <PageHeader
        breadcrumb={['安全管理', 'AI 识别质量']}
        title="AI 识别质量"
        description="隐患 AI 识别链路质量看板（实时聚合，与离线 replay 同口径；覆盖 JSON 合法率、闸门分布、引用可验证性、检索维度与死信水位）"
      />
      <HazardQualityPanel />
    </div>
  )
}

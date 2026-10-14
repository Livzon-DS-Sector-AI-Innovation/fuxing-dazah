'use client'

import { useQuery } from '@tanstack/react-query'
import { Alert } from 'antd'
import { Boxes, Database, FileSearch, Layers } from 'lucide-react'
import { StatCard } from '@/components/ui-kit'
import { fetchKnowledgeRagplusOverview } from '@/lib/api/knowledge'

/**
 * ragplus 知识引擎状态条（参考 ragplus 仪表盘/知识库卡片）：
 * 名单内各库的文档/chunk 实时总量 + 入库映射聚合，30s 自动刷新。
 * 引擎不可用时显式告警（与检索侧故障语义一致，不静默）。
 */
export default function RagplusEngineBar() {
  const { data } = useQuery({
    queryKey: ['knowledge-ragplus-overview'],
    queryFn: fetchKnowledgeRagplusOverview,
    refetchInterval: 30_000,
  })

  if (!data) return null
  if (!data.enabled) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="知识引擎（ragplus-x）未启用"
        description="检索走本地旧链路；打开 SAFETY_RAGPLUS_SEARCH_ENABLED 后切换为条款级语义检索。"
      />
    )
  }
  if (data.error) {
    return (
      <Alert
        type="error"
        showIcon
        style={{ marginBottom: 16 }}
        message="知识引擎（ragplus-x）不可用"
        description={data.error}
      />
    )
  }

  const byName = new Map(data.kbs.map((kb) => [kb.name, kb]))
  const law = byName.get('安全法规标准')
  const msds = byName.get('MSDS')
  const mapCounts = data.map_counts || {}
  const active = mapCounts['active'] || 0
  const failed = mapCounts['failed'] || 0
  const archived = mapCounts['archived'] || 0

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        <StatCard
          label="引擎·法规标准库"
          value={law ? `${law.doc_count} 篇` : '—'}
          sub={law ? `${law.chunk_count} 个知识块` : '库未建立'}
          tone="primary"
          icon={<Database size={16} />}
        />
        <StatCard
          label="引擎·MSDS 库"
          value={msds ? `${msds.doc_count} 篇` : '—'}
          sub={msds ? `${msds.chunk_count} 个知识块` : '库未建立'}
          icon={<Boxes size={16} />}
        />
        <StatCard
          label="已入引擎"
          value={active}
          sub={archived > 0 ? `另归档 ${archived} 篇` : '检索就绪'}
          tone={active > 0 ? 'ok' : 'default'}
          icon={<FileSearch size={16} />}
        />
        <StatCard
          label="入库失败"
          value={failed}
          sub={failed > 0 ? '重跑入库脚本可补齐' : '无失败'}
          tone={failed > 0 ? 'warn' : 'default'}
          icon={<Layers size={16} />}
        />
      </div>
    </div>
  )
}

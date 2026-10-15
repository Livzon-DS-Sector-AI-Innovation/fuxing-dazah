'use client'

/**
 * 采集监控面板（只读，3.0 零业务按钮）。
 *
 * 三态信封渲染：not_connected=未对接引导 / live=正常大盘 /
 * degraded=降级告警（errors 顿号列出，不静默）。
 * T05 骨架：三态 StatusTag + StatCard 六卡 + EmptyGuide 四分支；
 * 内容区（源健康表/法规流/漏斗/运行历史）由 T06 填充。
 */

import { useQuery } from '@tanstack/react-query'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import { fetchRegulationMonitor } from '@/lib/api/safety/regulation-monitor'
import type { RegulationMonitorData, RegulationMonitorStatus } from '@/types/safety'
import { formatMonitorTime } from './format'

const STATUS_TAG: Record<RegulationMonitorStatus, { label: string; tone: 'ok' | 'default' | 'warn' }> = {
  not_connected: { label: '未对接', tone: 'default' },
  live: { label: '采集正常', tone: 'ok' },
  degraded: { label: '采集降级', tone: 'warn' },
}

export default function CrawlMonitorPanel() {
  const query = useQuery({
    queryKey: ['regulation-monitor'],
    queryFn: () => fetchRegulationMonitor(1, 20),
    staleTime: 60_000,
  })

  const data = query.data
  const status = data?.status ?? 'not_connected'
  const tag = STATUS_TAG[status]

  const emptyGuide = (() => {
    if (query.isError) {
      return <EmptyGuide title="数据暂时不可用" description="监控聚合接口请求失败，请稍后重试" />
    }
    if (status === 'not_connected') {
      return (
        <EmptyGuide
          title="采集监控未接入"
          description="法规采集（发现→获取→解析→暂存）由 ragplus-x 知识层承担；未对接时此处显示接入引导。部署 ragplus-x 爬虫模块并配置契约③后自动点亮。"
          extra={
            <span style={{ fontSize: 12, color: 'var(--foreground-muted, #a4a097)' }}>
              蓝本参考：DESIGN-法规采集迁移ragplus-x与监控中心接入-功能改进计划-20261015 §5
            </span>
          }
        />
      )
    }
    if (status === 'degraded') {
      return (
        <EmptyGuide
          title="采集链路降级"
          description={(data?.errors ?? []).join('、') || 'ragplus 状态异常'}
        />
      )
    }
    return undefined
  })()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SectionCard
        title="采集大盘"
        description="数据源健康 · 近7日收录 · 判定与复核概况（一次拉取聚合 ragplus 状态与收录留痕）"
        action={<StatusTag tone={tag.tone} label={tag.label} />}
      >
        <StatCards data={data} loading={query.isLoading} status={status} />
        {emptyGuide}
      </SectionCard>
    </div>
  )
}

function StatCards({
  data,
  loading,
  status,
}: {
  data: RegulationMonitorData | undefined
  loading: boolean
  status: RegulationMonitorStatus
}) {
  const live = status === 'live' || status === 'degraded'
  const s = data?.stats
  const value = (v: number | null | undefined) =>
    live && v != null ? String(v) : '—'
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatCard
        label="监控数据源"
        value={live && s ? `${s.sources_healthy}/${s.sources_total}` : '—'}
        sub={live && s ? `健康 ${s.sources_healthy} · 共 ${s.sources_total}` : '未对接'}
        loading={loading}
      />
      <StatCard
        label="近7日新增"
        value={value(s?.items_7d)}
        sub="判定相关并收录入台账"
        loading={loading}
      />
      <StatCard
        label="AI 判定相关"
        value={value(s?.ai_relevant_7d)}
        sub="近7日 · 场景 regulation_ingest"
        loading={loading}
      />
      <StatCard
        label="待人工复核"
        value={value(s?.pending_review)}
        sub="预算超限/判定失败沉淀"
        loading={loading}
      />
      <StatCard
        label="原文待补"
        value={value(s?.attachment_missing)}
        sub="候选未携带原文附件"
        loading={loading}
      />
      <StatCard
        label="最近运行"
        value={s?.last_run_at ? formatMonitorTime(s.last_run_at) : '—'}
        sub={
          s?.last_run_status
            ? s.last_run_status === 'completed'
              ? '成功'
              : s.last_run_status
            : '暂无运行'
        }
        loading={loading}
      />
    </div>
  )
}

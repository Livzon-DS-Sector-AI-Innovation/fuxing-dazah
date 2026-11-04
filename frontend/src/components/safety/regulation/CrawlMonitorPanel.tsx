'use client'

/**
 * 采集监控面板（只读，3.0 零业务按钮）。
 *
 * 三态信封渲染：not_connected=未对接引导 / live=正常大盘 /
 * degraded=降级告警（errors 顿号列出，不静默）。
 * 布局：StatCard 六卡 → 源健康表+最新法规流（双列）→ 判定漏斗 → 运行历史。
 */

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Col, Row } from 'antd'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import { fetchRegulationMonitor } from '@/lib/api/safety/regulation-monitor'
import type { RegulationMonitorData, RegulationMonitorStatus } from '@/types/safety'
import AiFunnel from './AiFunnel'
import CrawlRunTable from './CrawlRunTable'
import RegulationFeed from './RegulationFeed'
import SourceHealthTable from './SourceHealthTable'
import { formatMonitorTime } from './format'

const STATUS_TAG: Record<RegulationMonitorStatus, { label: string; tone: 'ok' | 'default' | 'warn' }> = {
  not_connected: { label: '未对接', tone: 'default' },
  live: { label: '采集正常', tone: 'ok' },
  degraded: { label: '采集降级', tone: 'warn' },
}

export default function CrawlMonitorPanel() {
  const [page, setPage] = useState(1)
  const healthCardRef = useRef<HTMLDivElement>(null)
  const [feedHeight, setFeedHeight] = useState<number | null>(null)
  const query = useQuery({
    queryKey: ['regulation-monitor', page],
    queryFn: () => fetchRegulationMonitor(page, 20),
    staleTime: 60_000,
  })

  // 让右侧「最新法规流」与左侧「数据源健康度」卡片等高：桌面端实测左卡高度，
  // 右卡按同一高度收起，内部卡片流改为滚轮滚动，避免法规流把整行撑长。
  useEffect(() => {
    const el = healthCardRef.current
    if (el == null) return
    const desktop = window.matchMedia('(min-width: 1200px)')
    const measure = () => {
      if (!desktop.matches) {
        setFeedHeight(null)
        return
      }
      const next = Math.round(el.getBoundingClientRect().height)
      setFeedHeight((prev) => (prev === next ? prev : next))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    desktop.addEventListener('change', measure)
    return () => {
      ro.disconnect()
      desktop.removeEventListener('change', measure)
    }
  }, [])

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

      <Row gutter={16}>
        <Col xs={24} xl={14}>
          <div ref={healthCardRef}>
            <SectionCard title="数据源健康度" description="10 政务源采集状况（ragplus 契约③），行点击查看源详情">
              <SourceHealthTable sources={data?.sources ?? []} />
            </SectionCard>
          </div>
        </Col>
        <Col xs={24} xl={10}>
          <div style={feedHeight != null ? { height: feedHeight, display: 'flex' } : undefined}>
            <SectionCard
              title="最新法规流"
              description="最近收录（点击卡片查看法规详情，修订条目带标记）"
              className={feedHeight != null ? 'flex h-full w-full flex-col' : 'w-full'}
              bodyClassName={feedHeight != null ? 'flex-1 min-h-0 overflow-hidden' : ''}
            >
              <RegulationFeed feed={data?.feed ?? []} scrollable={feedHeight != null} />
            </SectionCard>
          </div>
        </Col>
      </Row>

      <SectionCard title="采集判定漏斗" description="发现→解析→推送→去重→AI 判定→收录（两端留痕拼接）">
        {data ? (
          <AiFunnel funnel={data.funnel} />
        ) : (
          <EmptyGuide compact title="漏斗待数据" description="信封拉取中或暂无运行" />
        )}
      </SectionCard>

      <SectionCard title="运行历史" description="收录批次留痕（行点击查看运行详情：采集段+收录段逐条管线）">
        {data ? (
          <CrawlRunTable
            runs={data.runs.data}
            total={data.runs.meta.total}
            page={data.runs.meta.page}
            pageSize={data.runs.meta.page_size}
            onPageChange={setPage}
          />
        ) : (
          <EmptyGuide compact title="运行历史待数据" description="信封拉取中" />
        )}
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

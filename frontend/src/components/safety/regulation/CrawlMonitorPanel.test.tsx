/**
 * 采集监控面板测试（T05 骨架）：三态渲染 + StatCard 口径 + 只读守卫。
 * 接缝：vi.mock fetchRegulationMonitor（照 DomainLedgerPage.test 手法）。
 */
import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CrawlMonitorPanel from './CrawlMonitorPanel'
import { renderWithQuery } from '@/test/utils'
import type { RegulationMonitorData } from '@/types/safety'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/regulation-monitor', () => ({
  fetchRegulationMonitor: fetchMock,
  fetchRegulationRunDetail: vi.fn(),
}))

const _run = {
  run_log_id: 'r1', source_run_id: 'rag-1', source: 'push', status: 'completed',
  received_count: 3, duplicate_count: 1, pending_count: 0, promoted_count: 1,
  rejected_count: 1, failed_count: 0, ai_tokens_used: 800, items_result: [],
  receipts: null, error_summary: null, created_at: '2026-10-15T06:10:00Z',
  finished_at: null,
}

function envelope(overrides: Partial<RegulationMonitorData>): RegulationMonitorData {
  return {
    status: 'live',
    stats: {
      sources_total: 10, sources_healthy: 8, items_7d: 12, ai_relevant_7d: 11,
      pending_review: 2, attachment_missing: 3, last_run_at: '2026-10-15T06:00:00Z',
      last_run_status: 'completed', last_run_source_id: 'rag-1',
      ragplus_last_run_at: '2026-10-15T06:00:00Z', ragplus_last_run_status: 'success',
    },
    sources: [
      { name: '应急管理部', layer: 'api', status: 'ok' },
      { name: '药监局', layer: 'http_parse', status: 'down' },
    ],
    feed: [
      { candidate_id: 'c1', title: '新法规', url: 'https://a.gov/1', reason: '判定相关',
        is_revision: false, bitable_record_id: 'rec1', article_id: null,
        ingested_at: '2026-10-15T06:10:00Z' },
    ],
    funnel: {
      discovered: 320, parsed: 300, received: 45, deduped: 27, ai_judged: 18,
      promoted: 12, rejected: 6, window_days: 30,
    },
    runs: { data: [_run], meta: { total: 1, page: 1, page_size: 20 } },
    errors: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

// 只读守卫：不允许出现任何业务操作按钮（3.0 铁律）
const BUSINESS_BUTTON_RE = /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发|编辑|保存/

describe('CrawlMonitorPanel（采集监控骨架）', () => {
  it('live：三态标签 + 六卡数值 + 零业务按钮', async () => {
    fetchMock.mockResolvedValue(envelope({}))
    renderWithQuery(<CrawlMonitorPanel />)

    expect(await screen.findByText('采集正常')).toBeInTheDocument()
    expect(screen.getByText('8/10')).toBeInTheDocument()
    // 近7日新增(12) 同时出现在六卡与漏斗收录段——多处出现是预期
    expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1)  // 待人工复核
    const buttons = screen.queryAllByRole('button')
    const biz = buttons.filter((b) => BUSINESS_BUTTON_RE.test(b.textContent ?? ''))
    expect(biz).toHaveLength(0)
  })

  it('not_connected：未对接引导 + StatCard 降级为 —', async () => {
    fetchMock.mockResolvedValue(envelope({
      status: 'not_connected',
      stats: {
        sources_total: 0, sources_healthy: 0, items_7d: 0, ai_relevant_7d: 0,
        pending_review: 0, attachment_missing: 0, last_run_at: null,
        last_run_status: null, last_run_source_id: null,
        ragplus_last_run_at: null, ragplus_last_run_status: null,
      },
      errors: ['ragplus 爬虫模块未部署（404）'],
    }))
    renderWithQuery(<CrawlMonitorPanel />)

    // 等六卡渲染完成（loading 期 StatusTag 已显「未对接」，不能作等待锚点）
    expect(await screen.findByText('监控数据源')).toBeInTheDocument()
    expect(screen.getByText('采集监控未接入')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(5)
  })

  it('degraded：降级标签 + errors 原因可见（不静默）', async () => {
    fetchMock.mockResolvedValue(envelope({
      status: 'degraded',
      errors: ['ragplus 状态查询失败: connect timeout'],
    }))
    renderWithQuery(<CrawlMonitorPanel />)

    expect(await screen.findByText('采集降级')).toBeInTheDocument()
    expect(screen.getByText(/connect timeout/)).toBeInTheDocument()
  })

  it('接口失败：数据暂时不可用引导', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    renderWithQuery(<CrawlMonitorPanel />)

    expect(await screen.findByText('数据暂时不可用')).toBeInTheDocument()
  })
})

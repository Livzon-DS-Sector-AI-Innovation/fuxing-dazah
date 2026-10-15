/**
 * 采集监控内容区测试：源健康表/法规流/漏斗/运行历史 + 双 Drawer 下钻 + 只读守卫。
 * 接缝：vi.mock api client 与 KnowledgeDetailDrawer（复用外部行为由其自身测试覆盖）。
 */
import { screen } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AiFunnel from './AiFunnel'
import CrawlRunTable from './CrawlRunTable'
import RegulationFeed from './RegulationFeed'
import SourceHealthTable from './SourceHealthTable'
import { renderWithQuery } from '@/test/utils'
import type { RegulationAiFunnel, RegulationIngestRunRow } from '@/types/safety'

vi.mock('@/components/safety/KnowledgeDetailDrawer', () => ({
  default: ({ articleId }: { articleId: string | null }) => (
    <div data-testid="knowledge-drawer">{articleId ?? 'closed'}</div>
  ),
}))

const detailMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/regulation-monitor', () => ({
  fetchRegulationMonitor: vi.fn(),
  fetchRegulationRunDetail: detailMock,
}))

beforeEach(() => {
  vi.clearAllMocks()
})

// 只读守卫（3.0 铁律）
const BUSINESS_BUTTON_RE = /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发|编辑|保存/

describe('SourceHealthTable', () => {
  it('渲染源行与状态 Tag，行点击开源详情 Drawer', async () => {
    renderWithQuery(
      <SourceHealthTable
        sources={[
          { name: '应急管理部', layer: 'api', last_success_at: '2026-10-15T06:00:00Z',
            consecutive_failures: 0, items_7d: 5, status: 'ok' },
          { name: '药监局', layer: 'browser', last_success_at: null,
            consecutive_failures: 4, items_7d: 0, status: 'down' },
        ]}
      />,
    )

    expect(screen.getByText('应急管理部')).toBeInTheDocument()
    expect(screen.getByText('正常')).toBeInTheDocument()
    expect(screen.getByText('停摆')).toBeInTheDocument()

    await userEvent.click(screen.getByText('药监局'))
    expect(await screen.findByText(/数据源详情/)).toBeInTheDocument()
  })

  it('空源列表显示引导', () => {
    renderWithQuery(<SourceHealthTable sources={[]} />)
    expect(screen.getByText('暂无数据源')).toBeInTheDocument()
  })
})

describe('RegulationFeed', () => {
  it('渲染卡片流：修订标记+原文链接；有 article_id 时点击开详情 Drawer', async () => {
    renderWithQuery(
      <RegulationFeed
        feed={[
          { candidate_id: 'c1', title: '危化品条例（修订）', url: 'https://a.gov/1',
            reason: '判定相关（score=0.9），修订替代《旧》', is_revision: true,
            bitable_record_id: 'rec1', article_id: 'art-uuid-1', ingested_at: '2026-10-15T06:10:00Z' },
          { candidate_id: 'c2', title: '噪声防治法', url: null, reason: '判定相关',
            is_revision: false, bitable_record_id: 'rec2', article_id: null,
            ingested_at: '2026-10-14T06:10:00Z' },
        ]}
      />,
    )

    expect(screen.getByText('危化品条例（修订）')).toBeInTheDocument()
    expect(screen.getAllByText('修订').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('噪声防治法')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /原文/ })).toBeInTheDocument()

    await userEvent.click(screen.getByText('危化品条例（修订）'))
    expect(await screen.findByText('art-uuid-1')).toBeInTheDocument()
  })
})

describe('AiFunnel', () => {
  const funnel: RegulationAiFunnel = {
    discovered: 320, parsed: 300, received: 45, deduped: 27,
    ai_judged: 18, promoted: 12, rejected: 6, window_days: 30,
  }

  it('渲染两端漏斗数字与口径说明', () => {
    renderWithQuery(<AiFunnel funnel={funnel} />)

    expect(screen.getByText('320')).toBeInTheDocument()
    expect(screen.getByText('300')).toBeInTheDocument()
    expect(screen.getByText('45')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText(/不相关 6 条/)).toBeInTheDocument()
  })

  it('左半缺失时降级显示 —（ragplus 未透出计数）', () => {
    renderWithQuery(<AiFunnel funnel={{ ...funnel, discovered: null, parsed: null }} />)
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })
})

describe('CrawlRunTable', () => {
  const run: RegulationIngestRunRow = {
    run_log_id: 'r1', source_run_id: 'rag-9', source: 'push', status: 'completed',
    received_count: 3, duplicate_count: 1, pending_count: 0, promoted_count: 1,
    rejected_count: 1, failed_count: 0, ai_tokens_used: 800,
    items_result: [
      { candidate_id: 'c1', action_taken: 'promote', reason: '判定相关（score=0.9）',
        bitable_record_id: 'rec1', title: '新法', url: 'https://a.gov/1' },
      { candidate_id: 'c2', action_taken: 'reject', reason: 'AI 判定不相关（score=0.1）' },
    ],
    receipts: null, error_summary: null,
    created_at: '2026-10-15T06:10:00Z', finished_at: null,
  }

  it('渲染运行行，行点击开两段详情 Drawer（逐条管线可看）', async () => {
    detailMock.mockResolvedValue({
      ingest: run,
      ragplus_run: { run_id: 'rag-9', status: 'success', found_count: 12 },
      errors: [],
    })
    renderWithQuery(
      <CrawlRunTable runs={[run]} total={1} page={1} pageSize={20} onPageChange={vi.fn()} />,
    )

    expect(screen.getByText('推送')).toBeInTheDocument()
    expect(screen.getByText('完成')).toBeInTheDocument()

    await userEvent.click(screen.getByText('推送'))
    expect(await screen.findByText(/运行详情/)).toBeInTheDocument()
    expect(await screen.findByText('采集段（ragplus 快照）')).toBeInTheDocument()
    expect(screen.getByText('新法')).toBeInTheDocument()
    expect(screen.getByText('AI 判定不相关（score=0.1）')).toBeInTheDocument()
  })

  it('分页回调触发', async () => {
    const onPageChange = vi.fn()
    renderWithQuery(
      <CrawlRunTable runs={[run]} total={30} page={1} pageSize={20} onPageChange={onPageChange} />,
    )
    const page2 = document.querySelector('.ant-pagination-item-2')
    expect(page2).not.toBeNull()
    fireEvent.click(page2 as HTMLElement)
    expect(onPageChange).toHaveBeenCalledWith(2, 20)
  })

  it('零业务按钮守卫（全内容区）', () => {
    const { container } = renderWithQuery(
      <>
        <SourceHealthTable sources={[{ name: 's1', status: 'ok' }]} />
        <CrawlRunTable runs={[run]} total={1} page={1} pageSize={20} onPageChange={vi.fn()} />
      </>,
    )
    const buttons = [...container.querySelectorAll('button')].filter(
      (b) => !b.closest('.ant-pagination') && !b.closest('.ant-table-filter-trigger'),
    )
    const biz = buttons.filter((b) => BUSINESS_BUTTON_RE.test(b.textContent ?? ''))
    expect(biz).toHaveLength(0)
  })
})

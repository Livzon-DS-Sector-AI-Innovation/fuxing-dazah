/**
 * 知识库页双 Tab 测试：?tab= 直达 / 非法值回默认 / 切换浅同步 / 清单 Tab 回归。
 * 接缝：vi.mock 子组件与 api，只验容器编排与 URL 行为（照 SystemConfigPanel.test 手法）。
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import KnowledgeBasePage from './page'
import { renderWithQuery } from '@/test/utils'

vi.mock('@/components/safety/KnowledgeQueryProvider', () => ({
  KnowledgeQueryProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}))
vi.mock('@/components/safety/KnowledgeDetailDrawer', () => ({
  default: () => <div data-testid="detail-drawer" />,
}))
vi.mock('@/components/safety/knowledge/RagplusEngineBar', () => ({
  default: () => <div data-testid="engine-bar" />,
}))
vi.mock('@/components/safety/knowledge/SemanticResultList', () => ({
  default: () => <div data-testid="semantic-list" />,
}))
vi.mock('@/components/safety/knowledge/ArticleTable', () => ({
  default: () => <div data-testid="article-table" />,
}))
vi.mock('@/components/safety/regulation/CrawlMonitorPanel', () => ({
  default: () => <div data-testid="monitor-panel" />,
}))

const apiMock = vi.hoisted(() => ({
  fetchKnowledgeArticles: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  fetchKnowledgeSemanticSearch: vi.fn(),
  fetchKnowledgeRagplusDocMap: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/lib/api/knowledge', () => ({ ...apiMock }))

const params = vi.hoisted(() => new Map<string, string | null>())
const routerMock = vi.hoisted(() => ({ replace: vi.fn() }))
vi.mock('next/navigation', () => ({
  useSearchParams: () =>
    new URLSearchParams(
      Object.fromEntries(
        [...params.entries()].filter(([, v]) => v != null) as [string, string][],
      ),
    ),
  useRouter: () => routerMock,
  usePathname: () => '/safety/knowledge-base',
}))

const replaceStateSpy = vi.fn()
beforeEach(() => {
  vi.clearAllMocks()
  params.clear()
  window.history.replaceState = replaceStateSpy as unknown as typeof window.history.replaceState
})

describe('knowledge-base 双 Tab（清单检索｜采集监控）', () => {
  it('无 tab 参数默认清单检索', () => {
    renderWithQuery(<KnowledgeBasePage />)

    expect(screen.getByText('清单检索')).toBeInTheDocument()
    expect(screen.getByTestId('article-table')).toBeInTheDocument()
    expect(screen.queryByTestId('monitor-panel')).not.toBeInTheDocument()
  })

  it('?tab=monitor 直达采集监控，清单内容不渲染', () => {
    params.set('tab', 'monitor')
    renderWithQuery(<KnowledgeBasePage />)

    expect(screen.getByTestId('monitor-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('article-table')).not.toBeInTheDocument()
  })

  it('非法 tab 值回默认清单检索', () => {
    params.set('tab', 'hacker')
    renderWithQuery(<KnowledgeBasePage />)

    expect(screen.getByTestId('article-table')).toBeInTheDocument()
    expect(screen.queryByTestId('monitor-panel')).not.toBeInTheDocument()
  })

  it('切到监控 Tab：浅同步 replaceState 带 tab=monitor 且保留检索参数', async () => {
    params.set('q', '动火作业')
    renderWithQuery(<KnowledgeBasePage />)

    await userEvent.click(screen.getByRole('tab', { name: '采集监控' }))

    expect(replaceStateSpy).toHaveBeenCalledTimes(1)
    const url = replaceStateSpy.mock.calls[0][2] as string
    expect(url).toContain('tab=monitor')
    expect(url).toContain('q=')
  })
})

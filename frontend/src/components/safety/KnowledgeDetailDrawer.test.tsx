import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import KnowledgeDetailDrawer from './KnowledgeDetailDrawer'
import { renderWithQuery } from '@/test/utils'
import type { SafetyKnowledgeArticle } from '@/types/safety'

const articleMock = vi.hoisted(() => vi.fn())
const versionsMock = vi.hoisted(() => vi.fn())
vi.mock('@/actions/safety', () => ({
  getKnowledgeArticle: articleMock,
  getArticleVersions: versionsMock,
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/safety/knowledge-base',
}))

function makeArticle(overrides: Partial<SafetyKnowledgeArticle> = {}): SafetyKnowledgeArticle {
  return {
    id: 'a1',
    article_no: 'LAW-001',
    title: '测试法规文档',
    category: 'laws_regulations',
    summary: null,
    content: '正文',
    tags: null,
    source: '法规标准库-安全法规标准',
    author: null,
    publish_date: null,
    version: 1,
    attachment_path: null,
    attachment_original_name: null,
    view_count: 3,
    status: 'published',
    notes: null,
    created_at: '2026-10-15T00:00:00Z',
    updated_at: '2026-10-15T00:00:00Z',
    feishu_record_url: null,
    ragflow_doc_url: null,
    ragflow_dataset_name: null,
    ragplus_doc_status: null,
    ragplus_synced_at: null,
    ...overrides,
  } as SafetyKnowledgeArticle
}

async function openDrawer(article: SafetyKnowledgeArticle) {
  articleMock.mockResolvedValue({ code: 200, data: article })
  versionsMock.mockResolvedValue({ code: 200, data: [] })
  renderWithQuery(
    <KnowledgeDetailDrawer articleId={article.id} open onClose={vi.fn()} />,
  )
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: '基本信息' })).toBeTruthy(),
  )
}

describe('KnowledgeDetailDrawer 源文档外链', () => {
  it('有外链时渲染多维表格与 RagFlow 双链接', async () => {
    await openDrawer(
      makeArticle({
        feishu_record_url:
          'https://bytedance.feishu.cn/base/tokenA?table=tbl1&record=rec1',
        ragflow_doc_url: 'http://192.168.100.7:8086/dataset/files/ds1',
        ragflow_dataset_name: '安全法规标准',
      }),
    )
    const bitable = screen.getByRole('link', { name: /多维表格原文/ })
    expect(bitable).toHaveAttribute(
      'href',
      'https://bytedance.feishu.cn/base/tokenA?table=tbl1&record=rec1',
    )
    const ragflow = screen.getByRole('link', { name: /RagFlow 文档（安全法规标准）/ })
    expect(ragflow).toHaveAttribute(
      'href',
      'http://192.168.100.7:8086/dataset/files/ds1',
    )
  })

  it('无 doc_map 行时只渲染多维表格链接，不渲染 RagFlow', async () => {
    await openDrawer(
      makeArticle({
        feishu_record_url: 'https://bytedance.feishu.cn/base/tokenA?table=tbl1&record=rec1',
      }),
    )
    expect(screen.getByRole('link', { name: /多维表格原文/ })).toBeTruthy()
    expect(screen.queryByRole('link', { name: /RagFlow/ })).toBeNull()
  })

  it('入库失败时渲染失败标记', async () => {
    await openDrawer(
      makeArticle({ ragplus_doc_status: 'failed' }),
    )
    expect(screen.getByText('ragplus 入库失败')).toBeTruthy()
  })
})

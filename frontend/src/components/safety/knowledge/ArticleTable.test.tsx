import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ArticleTable from './ArticleTable'
import { renderWithQuery } from '@/test/utils'

const ARTICLES = [
  {
    id: 'a1',
    title: '危险化学品安全管理条例',
    article_no: 'REG-001',
    category: 'laws_regulations',
    status: 'published',
    knowledge_card: null,
    updated_at: '2026-10-01T00:00:00Z',
  },
]

describe('ArticleTable（3.0 只读口径）', () => {
  it('行操作仅保留查看入口，无编辑/生成类菜单项', () => {
    renderWithQuery(
      <ArticleTable
        articles={ARTICLES as never}
        loading={false}
        docMap={{}}
        onOpenDetail={vi.fn()}
      />,
    )

    expect(screen.getByText('危险化学品安全管理条例')).toBeInTheDocument()
    // eye 查看入口保留（aria 描述来自 Tooltip）
    expect(screen.getByRole('button', { name: /view|eye|查看/i })).toBeInTheDocument()
    // 生成/编辑类入口退役
    for (const label of ['编辑', '生成知识卡片', '生成培训 PPT', '生成摘要']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument()
    }
  })
})

import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { QueryFilter } from './QueryFilter'
import { renderWithQuery } from '@/test/utils'

describe('QueryFilter', () => {
  it('常驻筛选始终可见，高级筛选默认折叠', () => {
    renderWithQuery(
      <QueryFilter
        common={<input aria-label="关键词" />}
        advanced={<input aria-label="批次号" />}
      />,
    )

    expect(screen.getByLabelText('关键词')).toBeInTheDocument()
    expect(screen.queryByLabelText('批次号')).not.toBeInTheDocument()
  })

  it('点击更多筛选展开高级区', async () => {
    const user = userEvent.setup()
    renderWithQuery(
      <QueryFilter
        common={<input aria-label="关键词" />}
        advanced={<input aria-label="批次号" />}
      />,
    )

    await user.click(screen.getByRole('button', { name: /更多筛选/ }))
    expect(screen.getByLabelText('批次号')).toBeInTheDocument()
  })

  it('无高级筛选时不渲染切换按钮', () => {
    renderWithQuery(<QueryFilter common={<input aria-label="关键词" />} />)

    expect(screen.queryByRole('button', { name: /更多筛选/ })).not.toBeInTheDocument()
  })
})

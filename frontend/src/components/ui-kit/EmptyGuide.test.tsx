import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EmptyGuide } from './EmptyGuide'
import { StatusTag } from './StatusTag'

describe('EmptyGuide', () => {
  it('渲染标题/描述与 CTA，点击回调', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn()
    render(
      <EmptyGuide
        title="还没有盘点单"
        description="创建第一张盘点单"
        actionText="新建盘点"
        onAction={onAction}
      />,
    )
    expect(screen.getByText('还没有盘点单')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '新建盘点' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('无 CTA 时不渲染按钮', () => {
    render(<EmptyGuide compact title="暂无数据" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('StatusTag', () => {
  it('渲染语义色 label', () => {
    render(<StatusTag tone="danger" label="冻结" />)
    const tag = screen.getByText('冻结')
    expect(tag.closest('span')?.getAttribute('style')).toContain('--wh-danger-bg')
  })

  it('自定义 icon 取代默认圆点', () => {
    const { container } = render(
      <StatusTag tone="ok" label="正常" icon={<i data-testid="custom-icon" />} />,
    )
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument()
    expect(container.querySelector('span.rounded-full.h-1\\.5')).toBeNull()
  })
})

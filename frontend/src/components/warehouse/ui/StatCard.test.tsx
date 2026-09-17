import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Inbox } from 'lucide-react'
import { StatCard, StatDelta } from './StatCard'

describe('StatCard', () => {
  it('渲染标签/数值/补充说明', () => {
    render(<StatCard label="今日入库" value={123.4} sub="12 笔" />)
    expect(screen.getByText('今日入库')).toBeInTheDocument()
    expect(screen.getByText('123.4')).toBeInTheDocument()
    expect(screen.getByText('12 笔')).toBeInTheDocument()
  })

  it('带图标时渲染图标 chip', () => {
    const { container } = render(<StatCard label="库存" value={1} icon={<Inbox />} tone="ok" />)
    expect(container.querySelector('span[aria-hidden="true"]')).not.toBeNull()
  })

  it('onClick 时可键盘/鼠标触发下钻', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<StatCard label="低库存" value={3} onClick={onClick} />)
    await user.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('loading 时渲染骨架不渲染数值', () => {
    render(<StatCard label="库存总量" value={592} loading />)
    expect(screen.queryByText('592')).not.toBeInTheDocument()
  })
})

describe('StatDelta', () => {
  it('正值绿色、负值红色、零值持平', () => {
    render(
      <div>
        <StatDelta value={5} />
        <StatDelta value={-3} />
        <StatDelta value={0} />
      </div>,
    )
    expect(screen.getByText(/5/).getAttribute('style')).toContain('--wh-ok')
    expect(screen.getByText(/3/).getAttribute('style')).toContain('--wh-danger')
    expect(screen.getByText(/持平/)).toBeInTheDocument()
  })

  it('invert 反转好坏语义（出库场景升=红）', () => {
    render(<StatDelta value={5} invert />)
    expect(screen.getByText(/5/).getAttribute('style')).toContain('--wh-danger')
  })
})

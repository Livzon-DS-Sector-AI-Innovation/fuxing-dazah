import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DonutChart, RankBarChart, TrendAreaChart } from './charts'

describe('charts 空数据态', () => {
  it('趋势全零时渲染空态引导而非坐标轴', () => {
    render(
      <TrendAreaChart
        dates={['09-01', '09-02']}
        inbound={[0, 0]}
        outbound={[0, 0]}
      />,
    )
    expect(screen.getByText('近期暂无出入库')).toBeInTheDocument()
  })

  it('环形图全零时渲染空态', () => {
    render(<DonutChart items={[{ name: '原料', value: 0 }]} />)
    expect(screen.getByText('暂无分布数据')).toBeInTheDocument()
  })

  it('排行全零时渲染空态', () => {
    const onPick = vi.fn()
    render(<RankBarChart names={['A']} values={[0]} onPick={onPick} emptyText="暂无低库存物料" />)
    expect(screen.getByText('暂无低库存物料')).toBeInTheDocument()
  })
})

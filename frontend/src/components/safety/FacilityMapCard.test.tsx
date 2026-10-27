import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FacilityMapCard } from './FacilityMapCard'
import { renderWithQuery } from '@/test/utils'
import asset from '@/data/tiji-risk-districts.json'

// pins 数据走接口替身（vi.mock factory 提升到顶部，样例必须内联）
const PINS = {
  date: '2026-10-26',
  pins: [
    {
      dist_id: '77',
      jobs: { hot: 2, confined: 0, other: 0 },
      alarms: { fire: 1, central: 0 },
      truncated: false,
      refs: [
        {
          kind: 'job',
          ticket_type: 'hot_work',
          ticket_no: 'DH-20261026-004',
          work_site: '消防控制室',
          work_content: '更换桥架',
        },
        {
          kind: 'fire',
          alarm_time: '2026-10-26T08:30:00+08:00',
          alarm_type: '火灾报警',
          location: '消控室一层感烟',
        },
      ],
    },
  ],
  unmapped: [
    { text: '212罐', count: 3, kinds: ['job'] },
    { text: '新罐区', count: 5, kinds: ['central'] },
  ],
  errors: [],
}

vi.mock('@/lib/api/safety/facility-map', () => ({
  fetchFacilityMapPins: vi.fn(async () => PINS),
}))

const RAIL_COUNT = asset.districts.reduce((n, d) => n + d.rails.length, 0)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FacilityMapCard', () => {
  it('渲染资产全部分区轮廓与落点徽标', async () => {
    renderWithQuery(<FacilityMapCard />)
    const groups = await screen.findAllByTestId(/^district-poly-/)
    expect(groups.length).toBe(asset.districts.length)
    // 每条 rail 一个多边形（64 分区 / 84 rail）
    const polys = document.querySelectorAll('[data-testid^="district-poly-"] polygon')
    expect(polys.length).toBe(RAIL_COUNT)
    // 消防控制室(dist 77)：动火 2 徽标 + 报警 1 徽标
    const badge = await screen.findByTestId('district-badge-77')
    expect(badge.textContent).toContain('火2')
    expect(badge.textContent).toContain('警1')
  })

  it('点击分区弹出当日明细 Modal', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findByTestId('district-badge-77')
    await user.click(screen.getByTestId('district-poly-77'))
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('DH-20261026-004')
    expect(modal.textContent).toContain('火灾报警')
  })

  it('底部未映射汇总行可展开清单', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    const summary = await screen.findByText(/未映射 2 处/)
    expect(screen.queryByText('212罐')).not.toBeInTheDocument()
    await user.click(summary)
    expect(await screen.findByText('212罐')).toBeInTheDocument()
    expect(screen.getByText('新罐区')).toBeInTheDocument()
  })

  it('接口失败显示降级空态', async () => {
    const { fetchFacilityMapPins } = await import('@/lib/api/safety/facility-map')
    vi.mocked(fetchFacilityMapPins).mockRejectedValueOnce(new Error('boom'))
    renderWithQuery(<FacilityMapCard />)
    await waitFor(() =>
      expect(screen.getByText(/分区数据暂时不可用/)).toBeInTheDocument(),
    )
  })

  it('缩放按钮调整视图且可重置', async () => {
    const user = userEvent.setup()
    const { container } = renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    const svg = container.querySelector('svg[aria-label="厂区风险分区底图"]') as SVGSVGElement
    const vbW = () => Number(svg.getAttribute('viewBox')!.split(/\s+/)[2])
    expect(vbW()).toBe(1000)
    await user.click(screen.getByRole('button', { name: '放大' }))
    await user.click(screen.getByRole('button', { name: '放大' }))
    expect(vbW()).toBeLessThan(999)
    await user.click(screen.getByRole('button', { name: '重置视图' }))
    expect(vbW()).toBe(1000)
  })

  it('分区名称标注随放大显现', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    await user.click(screen.getByRole('button', { name: '放大' }))
    const labels = await screen.findAllByTestId(/^district-label-/)
    const names = new Set(asset.districts.map(d => d.distName))
    expect(labels.some(l => names.has(l.textContent ?? ''))).toBe(true)
  })
})

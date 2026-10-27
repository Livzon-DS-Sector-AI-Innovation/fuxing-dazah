import { fireEvent, screen, waitFor } from '@testing-library/react'
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
  fetchDistrictSuggestions: vi.fn(async () => SUGGESTIONS),
  scanDistrictSuggestions: vi.fn(async () => ({
    days: 30, unmapped_texts: 2, candidates: 2, batches: 1,
    suggested: 2, no_judgement: 1, batch_id: 'b1',
  })),
  confirmDistrictSuggestion: vi.fn(async () => ({})),
  ignoreDistrictSuggestion: vi.fn(async () => ({})),
  confirmHighDistrictSuggestions: vi.fn(async () => ({ confirmed: 1, map_created: 1 })),
}))

const RAIL_COUNT = asset.districts.reduce((n, d) => n + d.rails.length, 0)

// #2 AI 建议确认页工作集（打开 Modal 才拉取）
const SUGGESTIONS = [
  {
    id: 's1', location_text: '212罐', count: 3, kinds: ['job'],
    dist_id: '27', dist_name: '新罐区', confidence: 'high' as const,
    reason: '位于新罐区', batch_id: 'b1', status: 'pending' as const, created_at: null,
  },
  {
    id: 's2', location_text: '新罐区西门', count: 1, kinds: ['central'],
    dist_id: null, dist_name: null, confidence: 'low' as const,
    reason: '无法判断', batch_id: 'b1', status: 'pending' as const, created_at: null,
  },
]

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

  it('按压带轻微抖动（<4px）仍是点击，弹出明细 Modal', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    const poly = screen.getByTestId('district-poly-77')
    // pointer 事件挂在 svg 上，从 polygon 冒泡；抖动 3px 未过拖动阈值
    fireEvent.pointerDown(poly, { button: 0, pointerId: 1 })
    fireEvent.pointerMove(poly, { pointerId: 1, clientX: 2, clientY: 1 })
    fireEvent.pointerUp(poly, { pointerId: 1 })
    fireEvent.click(poly)
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('DH-20261026-004')
  })

  it('拖动平移后的松手不当作分区点击（不弹 Modal）', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    const poly = screen.getByTestId('district-poly-77')
    fireEvent.pointerDown(poly, { button: 0, pointerId: 1 })
    fireEvent.pointerMove(poly, { pointerId: 1, clientX: 12, clientY: 3 }) // 15px 越过阈值
    fireEvent.pointerUp(poly, { pointerId: 1 })
    fireEvent.click(poly)
    // click 被吞：无分区明细（本测试无其他 dialog 触发源）
    expect(document.querySelector('.ant-modal')).toBeNull()
  })

  it('底部未映射入口打开 AI 建议确认 Modal（#2）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    const entry = await screen.findByText(/未映射 2 处/)
    await user.click(entry)
    // 确认页工作集：建议分区名/置信度/理由 + 触发扫描按钮在 footer
    expect(await screen.findByText(/AI 分区建议确认/)).toBeInTheDocument()
    expect(await screen.findByText('212罐')).toBeInTheDocument()
    expect(screen.getByText('新罐区')).toBeInTheDocument()
    expect(screen.getByText('位于新罐区')).toBeInTheDocument()
    // 触发扫描按钮在 footer
    expect(screen.getByText('扫描近 30 天生成建议')).toBeInTheDocument()
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

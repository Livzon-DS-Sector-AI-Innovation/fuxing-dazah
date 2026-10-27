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
      key_risks: 1,
      over_limits: 1,
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
        {
          kind: 'key_risk',
          report_no: '20261026001',
          apply_status: '已通过',
          area: '消防控制室',
          operation_content: '米尔贝放硅胶',
          start_time: '2026-10-26T06:00:00+00:00',
        },
        {
          kind: 'over_limit',
          material_name: '乙腈',
          department: 'daba',
          storage_location: '消控室试剂柜',
          total_quantity_t: 28.13,
          max_limit: 20,
          unit: 'kg',
        },
      ],
    },
    // 同轮廓组：车间一达托(1)/车间一达巴(11) 共用建筑轮廓——徽标合并、
    // 点击任一多边形弹出整组（两分区）明细
    {
      dist_id: '1',
      jobs: { hot: 0, confined: 0, other: 0 },
      alarms: { fire: 0, central: 1 },
      key_risks: 0,
      over_limits: 0,
      truncated: false,
      refs: [
        {
          kind: 'central',
          alarm_date: '2026-10-26',
          alarm_description: 'P0405A泵温度高',
          workshop: '车间一',
        },
      ],
    },
    {
      dist_id: '11',
      jobs: { hot: 0, confined: 0, other: 0 },
      alarms: { fire: 0, central: 0 },
      key_risks: 0,
      over_limits: 1,
      truncated: false,
      refs: [
        {
          kind: 'over_limit',
          material_name: '乙醇',
          department: 'daba',
          storage_location: '车间一达巴粗提',
          total_quantity_t: 4,
          max_limit: 3,
          unit: 'kg',
        },
      ],
    },
  ],
  unmapped: [
    { text: '212罐', count: 3, kinds: ['job'] },
    { text: '新罐区', count: 5, kinds: ['central'] },
    { text: '车间四二楼合成岗位', count: 1, kinds: ['key_risk'] },
    { text: '四楼危化品储柜', count: 1, kinds: ['over_limit'] },
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
    // 消防控制室(dist 77)：动火 2 + 关键风险 1 + 报警 1 徽标
    const badge = await screen.findByTestId('district-badge-77')
    expect(badge.textContent).toContain('火2')
    expect(badge.textContent).toContain('险1')
    expect(badge.textContent).toContain('储1')
    expect(badge.textContent).toContain('警1')
  })

  it('点击分区弹出当日明细 Modal（含关键风险作业段）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findByTestId('district-badge-77')
    await user.click(screen.getByTestId('district-poly-77'))
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('DH-20261026-004')
    expect(modal.textContent).toContain('火灾报警')
    expect(modal.textContent).toContain('关键风险作业 1 项')
    expect(modal.textContent).toContain('超储物料 1 项')
    expect(modal.textContent).toContain('乙腈')
    expect(modal.textContent).toContain('米尔贝放硅胶')
    expect(modal.textContent).toContain('已通过')
  })

  it('同轮廓分区组合并：点达托/达巴任一多边形都弹出两分区明细与超储', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    // 徽标合并挂组首分区（资产顺序车间一达巴=11 在前）：警1 + 储1
    const badge = await screen.findByTestId('district-badge-11')
    expect(badge.textContent).toContain('警1')
    expect(badge.textContent).toContain('储1')
    // 点击车间一达巴的多边形（与达托共用轮廓）也开整组
    await user.click(screen.getByTestId('district-poly-11'))
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('车间一达巴 / 车间一达托')
    expect(modal.textContent).toContain('车间一达巴粗提')
    expect(modal.textContent).toContain('乙醇')
    expect(modal.textContent).toContain('P0405A泵温度高')
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

  it('右侧未映射栏直出清单，入口按钮打开 AI 建议确认 Modal（#2）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    // 清单随卡片直出（右侧栏），无需展开
    expect(await screen.findByText(/未映射 4 处/)).toBeInTheDocument()
    expect(screen.getAllByText('212罐').length).toBeGreaterThan(0)
    expect(screen.getByText('×5')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /AI 建议映射/ }))
    // 确认页工作集：建议分区名/置信度/理由 + 触发扫描按钮在 footer
    expect(await screen.findByText(/AI 分区建议确认/)).toBeInTheDocument()
    expect(screen.getAllByText('212罐').length).toBeGreaterThan(0)
    expect(screen.getByText('位于新罐区')).toBeInTheDocument()
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

  it('重叠分区名称不相交（米尔贝/提四米贝锚点近邻，贪心避让保证矩形分离）', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^district-poly-/)
    await waitFor(() => {
      const milbei = document.querySelector('[data-testid="district-label-7"]')
      const tiSi = document.querySelector('[data-testid="district-label-20"]')
      expect(milbei).toBeTruthy()
      expect(tiSi).toBeTruthy()
      // 与避让算法同口径的矩形（zoom=1：fs=13，w=len*fs*0.95，h=fs*1.3）：
      // 两标签矩形必须不相交（x 分离或 y 分离）
      const fs = 13
      const rectOf = (el: Element, name: string) => {
        const w = name.length * fs * 0.95
        const x = Number(el.getAttribute('x'))
        const y = Number(el.getAttribute('y'))
        return { x1: x - w / 2, x2: x + w / 2, y1: y - fs * 0.65, y2: y + fs * 0.65 }
      }
      const a = rectOf(milbei!, '米尔贝')
      const b = rectOf(tiSi!, '提四米贝')
      const separated =
        a.x2 <= b.x1 || b.x2 <= a.x1 || a.y2 <= b.y1 || b.y2 <= a.y1
      expect(separated).toBe(true)
    })
  })
})

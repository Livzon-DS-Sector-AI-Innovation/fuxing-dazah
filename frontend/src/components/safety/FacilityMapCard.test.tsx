import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FacilityMapCard } from './FacilityMapCard'
import { renderWithQuery } from '@/test/utils'
import asset from '@/data/tiji-risk-districts.json'
import { BUILDINGS } from '@/data/f2-buildings'

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
      hazard_news: 1,
      hazard_opens: 1,
      fire_ext_dues: 1,
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
        {
          kind: 'hazard_new',
          hazard_no: 'HZ-20261026-008',
          hazard_desc: '消防控制室门口堆放纸箱堵塞通道',
          hazard_level: 'general',
          progress: '',
        },
        {
          kind: 'hazard_open',
          hazard_no: 'HZ-20261010-003',
          hazard_desc: '消防控制室UPS电池鼓包待更换',
          hazard_level: 'major',
          progress: '已联系仪表，待更换',
        },
        {
          kind: 'fire_ext_due',
          location: '消控室入口东侧',
          workshop: '消防控制室',
          ext_type: '手提式干粉灭火器',
          ext_count: 2,
          due_date: '2026-10-20',
          is_overdue: true,
        },
      ],
    },
    // 1 号楼（车间一）：达托(1) 中控报警 + 达巴(11) 超储 + 雷帕(29) 中控
    // 报警——29 的平台几何画在 2 号楼轮廓组，数据按拍板归 1 号楼
    {
      dist_id: '1',
      jobs: { hot: 0, confined: 0, other: 0 },
      alarms: { fire: 0, central: 1 },
      key_risks: 0,
      over_limits: 0,
      hazard_news: 0,
      hazard_opens: 0,
      fire_ext_dues: 0,
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
      hazard_news: 0,
      hazard_opens: 0,
      fire_ext_dues: 0,
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
    {
      dist_id: '29',
      jobs: { hot: 0, confined: 0, other: 0 },
      alarms: { fire: 0, central: 1 },
      key_risks: 0,
      over_limits: 0,
      hazard_news: 0,
      hazard_opens: 0,
      fire_ext_dues: 0,
      truncated: false,
      refs: [
        {
          kind: 'central',
          alarm_date: '2026-10-26',
          alarm_description: '雷帕四楼反应釜温度高',
          workshop: '提四雷帕',
        },
      ],
    },
  ],
  unmapped: [
    { text: '212罐', count: 3, kinds: ['job'] },
    { text: '新罐区', count: 5, kinds: ['central'] },
    { text: '车间四二楼合成岗位', count: 1, kinds: ['key_risk'] },
    { text: '四楼危化品储柜', count: 1, kinds: ['over_limit'] },
    { text: '陶瓷膜旁立柱', count: 1, kinds: ['fire_ext_due'] },
    { text: '质检楼顶灯损坏', count: 2, kinds: ['hazard_new', 'hazard_open'] },
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

// 同轮廓组去重后期望的轮廓数（独立于实现：按原始坐标分组，每组只计
// 首个成员的有效 rail 数）
const EXPECTED_POLYS = (() => {
  const seen = new Map<string, number>()
  for (const d of asset.districts) {
    const key = d.rails
      .map(r => r.polygon.map(p => p.join(',')).join(';'))
      .sort()
      .join('|')
    if (!seen.has(key)) {
      seen.set(key, d.rails.filter(r => r.polygon.length >= 3).length)
    }
  }
  return [...seen.values()].reduce((a, b) => a + b, 0)
})()

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

describe('FacilityMapCard · 建筑级视图', () => {
  it('渲染 33 栋建筑；同轮廓组只画一次（雷帕 29 不单独画轮廓）', async () => {
    renderWithQuery(<FacilityMapCard />)
    const groups = await screen.findAllByTestId(/^building-poly-/)
    expect(groups).toHaveLength(BUILDINGS.length)
    expect(BUILDINGS).toHaveLength(33)
    // 同轮廓组合成：多分区共用轮廓画一次（29 所在组 6 成员仅 1 片轮廓）
    const polys = document.querySelectorAll('[data-testid^="building-poly-"] polygon')
    expect(polys.length).toBe(EXPECTED_POLYS)
    expect(EXPECTED_POLYS).toBeLessThan(RAIL_COUNT)
    // 2 号楼：9/21/22/23/24/29 六分区共用轮廓 → 一片轮廓
    expect(
      document.querySelectorAll('[data-testid="building-poly-2"] polygon').length,
    ).toBe(1)
    // 1 号楼：达托/达巴共用轮廓一片 + 异丙醇回收(27) 一片；29 不贡献轮廓
    expect(
      document.querySelectorAll('[data-testid="building-poly-1"] polygon').length,
    ).toBe(2)
  })

  it('徽标按建筑聚合：1 号楼含 29 的雷帕报警（警2）与达巴超储（储1）', async () => {
    renderWithQuery(<FacilityMapCard />)
    const badge = await screen.findByTestId('building-badge-1')
    expect(badge.textContent).toContain('警2')
    expect(badge.textContent).toContain('储1')
  })

  it('点击 28 号楼弹出建筑信息头与七路明细', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findByTestId('building-badge-28')
    await user.click(screen.getByTestId('building-poly-28'))
    const modal = await screen.findByRole('dialog')
    // 建筑信息头：编号+名称+责任部门+产线明细
    expect(modal.textContent).toContain('28 消防控制室')
    expect(modal.textContent).toContain('责任部门：安全工程中心')
    expect(modal.textContent).toContain('消控室（仅消防')
    // 明细
    expect(modal.textContent).toContain('DH-20261026-004')
    expect(modal.textContent).toContain('火灾报警')
    expect(modal.textContent).toContain('关键风险作业 1 项')
    expect(modal.textContent).toContain('超储物料 1 项')
    expect(modal.textContent).toContain('乙腈')
    expect(modal.textContent).toContain('米尔贝放硅胶')
    expect(modal.textContent).toContain('已通过')
    // 隐患双口径 + 消防到期
    expect(modal.textContent).toContain('今日新增隐患 1 条')
    expect(modal.textContent).toContain('未整改隐患 1 条')
    expect(modal.textContent).toContain('消防设施到期 1 处')
    expect(modal.textContent).toContain('已到期')
    expect(modal.textContent).toContain('收编分区：消防控制室')
  })

  it('点击 1 号楼：达托/达巴/雷帕成员明细聚合展示，子单元与责任部门可见（29 数据归 1 号楼钉子）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findByTestId('building-badge-1')
    await user.click(screen.getByTestId('building-poly-1'))
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('1 车间一')
    expect(modal.textContent).toContain('责任部门：提炼工程五部')
    expect(modal.textContent).toContain('└ 子单元：异丙醇回收（提炼工程四部）')
    expect(modal.textContent).toContain('收编分区：')
    expect(modal.textContent).toContain('提四雷帕')
    expect(modal.textContent).toContain('车间一达托')
    // 三个成员的当日明细都在同一弹窗（29 的雷帕报警落 1 号楼）
    expect(modal.textContent).toContain('P0405A泵温度高')
    expect(modal.textContent).toContain('雷帕四楼反应釜温度高')
    expect(modal.textContent).toContain('车间一达巴粗提')
    expect(modal.textContent).toContain('乙醇')
    expect(modal.textContent).toContain('今日报警 2 条')
  })

  it('点击 3 号楼：子单元「乙腈回收＋丙醇回收」在信息头展示', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^building-poly-/)
    await user.click(screen.getByTestId('building-poly-3'))
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('3 待命名')
    expect(modal.textContent).toContain('└ 子单元：乙腈回收＋丙醇回收（提炼工程四部）')
    expect(modal.textContent).toContain('替考')
  })

  it('色系族图例（11 族）与徽标图例同条展示', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^building-poly-/)
    expect(screen.getByText('提炼一部')).toBeInTheDocument()
    expect(screen.getByText('提炼多部共用')).toBeInTheDocument()
    expect(screen.getByText('公用辅助')).toBeInTheDocument()
    expect(screen.getByText('环保')).toBeInTheDocument()
    expect(screen.getByText('动火')).toBeInTheDocument()
    // 「未整改隐患」同时在图例与未映射栏来源 Tag 出现——多处命中即存在
    expect(screen.getAllByText('未整改隐患').length).toBeGreaterThan(0)
  })

  it('按压带轻微抖动（<4px）仍是点击，弹出明细 Modal', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^building-poly-/)
    const poly = screen.getByTestId('building-poly-28')
    // pointer 事件挂在 svg 上，从 polygon 冒泡；抖动 3px 未过拖动阈值
    fireEvent.pointerDown(poly, { button: 0, pointerId: 1 })
    fireEvent.pointerMove(poly, { pointerId: 1, clientX: 2, clientY: 1 })
    fireEvent.pointerUp(poly, { pointerId: 1 })
    fireEvent.click(poly)
    const modal = await screen.findByRole('dialog')
    expect(modal.textContent).toContain('DH-20261026-004')
  })

  it('拖动平移后的松手不当作建筑点击（不弹 Modal）', async () => {
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^building-poly-/)
    const poly = screen.getByTestId('building-poly-28')
    fireEvent.pointerDown(poly, { button: 0, pointerId: 1 })
    fireEvent.pointerMove(poly, { pointerId: 1, clientX: 12, clientY: 3 }) // 15px 越过阈值
    fireEvent.pointerUp(poly, { pointerId: 1 })
    fireEvent.click(poly)
    // click 被吞：无建筑明细（本测试无其他 dialog 触发源）
    expect(document.querySelector('.ant-modal')).toBeNull()
  })

  it('右侧未映射栏直出清单，入口按钮打开 AI 建议确认 Modal（#2）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    // 清单随卡片直出（右侧栏），无需展开
    expect(await screen.findByText(/未映射 6 处/)).toBeInTheDocument()
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
    await screen.findAllByTestId(/^building-poly-/)
    const svg = container.querySelector('svg[aria-label="厂区建筑底图"]') as SVGSVGElement
    const vbW = () => Number(svg.getAttribute('viewBox')!.split(/\s+/)[2])
    expect(vbW()).toBe(1000)
    await user.click(screen.getByRole('button', { name: '放大' }))
    await user.click(screen.getByRole('button', { name: '放大' }))
    expect(vbW()).toBeLessThan(999)
    await user.click(screen.getByRole('button', { name: '重置视图' }))
    expect(vbW()).toBe(1000)
  })

  it('放大后建筑编号/名称标注显现（编号+名称格式）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<FacilityMapCard />)
    await screen.findAllByTestId(/^building-poly-/)
    await user.click(screen.getByRole('button', { name: '放大' }))
    await user.click(screen.getByRole('button', { name: '放大' }))
    await user.click(screen.getByRole('button', { name: '放大' }))
    const labels = await screen.findAllByTestId(/^building-label-/)
    // 标注文本都是合法建筑标注（编号 或 编号+名称）
    const valid = new Set(
      BUILDINGS.map(b => (b.name ? `${b.id} ${b.name}` : `${b.id}`)),
    )
    for (const l of labels) {
      expect(valid.has(l.textContent ?? '')).toBe(true)
    }
    // 放大三级后多数建筑已有标注
    const distinct = new Set(labels.map(l => l.getAttribute('data-testid')))
    expect(distinct.size).toBeGreaterThanOrEqual(20)
  })
})

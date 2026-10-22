/**
 * 体系标准核查清单页测试（S1 目标责任与绩效）。
 * 接缝：vi.mock fetchStandardCheckPage（照 DomainLedgerPage.test 手法）。
 */
import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import GoalsPageClient from './GoalsPageClient'
import { renderWithQuery } from '@/test/utils'
import type {
  StandardCheckData,
  StandardHistoryData,
} from '@/lib/api/safety/standard-check'

const fetchMock = vi.hoisted(() => vi.fn())
const evidenceMock = vi.hoisted(() => vi.fn())
const historyMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/standard-check', () => ({
  fetchStandardCheckPage: fetchMock,
  fetchStandardEvidence: evidenceMock,
  fetchStandardHistory: historyMock,
}))

const NOT_CONNECTED: StandardCheckData = {
  status: 'not_connected',
  summary: null,
  groups: [],
  departments: [],
  errors: [],
}

const LIVE: StandardCheckData = {
  status: 'live',
  summary: {
    total: 4,
    ok: 2,
    in_progress: 1,
    missed: 1,
    no_data: 0,
    compliance_rate: 67,
  },
  groups: [
    {
      element: '应急管理',
      rows: [
        {
          record_id: 'r1',
          no: 'D6-01',
          clause: '综合或专项应急预案演练每半年≥1次',
          basis: '预案管理办法§33',
          element: '应急管理',
          metric_key: 'drill.count.comprehensive_or_special',
          period: '半年',
          target_display: '≥1次',
          department: ['安环部'],
          owner: '张三',
          auto: true,
          status: 'ok',
          actual_display: '2次',
          residual_days: null,
          note: null,
        },
        {
          record_id: 'r2',
          no: 'D6-02',
          clause: '现场处置方案演练每半年≥1次',
          basis: '预案管理办法§33',
          element: '应急管理',
          metric_key: 'drill.count.site_handling',
          period: '半年',
          target_display: '≥1次',
          department: ['安环部'],
          owner: null,
          auto: true,
          status: 'in_progress',
          actual_display: '0次',
          residual_days: 71,
          note: null,
        },
        {
          record_id: 'r3',
          no: 'D1-03',
          clause: '各级安全责任书按年度签订完成',
          basis: '公司制度',
          element: '应急管理',
          metric_key: null,
          period: '年度',
          target_display: '已完成',
          department: ['安环部'],
          owner: null,
          auto: false,
          status: 'missed',
          actual_display: '未完成',
          residual_days: null,
          note: null,
        },
      ],
    },
    {
      element: '教育培训',
      rows: [
        {
          record_id: 'r4',
          no: 'D3-05',
          clause: '年度培训计划完成率≥95%',
          basis: '公司制度',
          element: '教育培训',
          metric_key: 'training.completion_rate',
          period: '年度',
          target_display: '≥95%',
          department: ['安环部'],
          owner: null,
          auto: true,
          status: 'no_data',
          actual_display: null,
          residual_days: null,
          note: '指标未注册',
        },
      ],
    },
  ],
  departments: [
    { name: '安环部', total: 3, ok: 1, in_progress: 2, missed: 0, no_data: 0 },
    { name: '生产一部', total: 1, ok: 0, in_progress: 0, missed: 1, no_data: 0 },
  ],
  errors: [],
}

const DEGRADED: StandardCheckData = {
  status: 'degraded',
  summary: null,
  groups: [],
  departments: [],
  errors: ['standard_check: 读取失败'],
}

beforeEach(() => {
  vi.clearAllMocks()
})

// 只读守卫：核查页不允许出现任何业务操作按钮（3.0 口径）
const BUSINESS_BUTTON_RE = /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发|编辑|保存/

describe('GoalsPageClient（体系标准核查清单）', () => {
  it('未接入态：三态标签 + 统计行「—」 + EmptyGuide 引导 + 零业务按钮', async () => {
    fetchMock.mockResolvedValue(NOT_CONNECTED)
    renderWithQuery(<GoalsPageClient />)

    expect(await screen.findByText('未接入')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('暂无可核对的体系标准')).toBeInTheDocument()
    expect(screen.getByText(/体系标准核查表/)).toBeInTheDocument()
    const buttons = screen.queryAllByRole('button')
    expect(buttons.filter((b) => BUSINESS_BUTTON_RE.test(b.textContent ?? ''))).toEqual([])
  })

  it('live：统计卡四态计数与符合率 + 分组清单 + 状态标签 + 系统核查小标', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<GoalsPageClient />)

    expect(await screen.findByText('已接入')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument() // 达标统计卡
    expect(screen.getByText('67%')).toBeInTheDocument() // 综合符合率
    // 状态标签在行内断言（统计卡 label 同名，getByText 会撞多处）
    const row_ok = screen.getByRole('row', { name: /D6-01/ })
    expect(within(row_ok).getByText('达标')).toBeInTheDocument()
    expect(within(row_ok).getByText('2次')).toBeInTheDocument()
    const row_prog = screen.getByRole('row', { name: /D6-02/ })
    expect(within(row_prog).getByText('进行中')).toBeInTheDocument()
    expect(row_prog.textContent).toContain('距周期末 71 天')
    const row_missed = screen.getByRole('row', { name: /D1-03/ })
    expect(within(row_missed).getByText('未达标')).toBeInTheDocument()
    expect(within(row_missed).getByText('未完成')).toBeInTheDocument()
    const row_nodata = screen.getByRole('row', { name: /D3-05/ })
    expect(within(row_nodata).getByText('无数据')).toBeInTheDocument()
    // 人工项=人工勾选、自动项=系统核查小标
    expect(screen.getAllByText('系统核查').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('人工勾选')).toBeInTheDocument()
    // 分组标题按要素
    expect(screen.getByText('应急管理')).toBeInTheDocument()
    expect(screen.getByText('教育培训')).toBeInTheDocument()
  })

  it('degraded：降级标签与错误标注', async () => {
    fetchMock.mockResolvedValue(DEGRADED)
    renderWithQuery(<GoalsPageClient />)

    expect(await screen.findByText('数据降级')).toBeInTheDocument()
    expect(screen.getByText(/standard_check: 读取失败/)).toBeInTheDocument()
  })
})

describe('GoalsPageClient 证据下钻 Drawer', () => {
  it('点击自动行「查看」打开凭据抽屉：明细列表', async () => {
    fetchMock.mockResolvedValue(LIVE)
    evidenceMock.mockResolvedValue({
      status: 'live',
      record_id: 'r1',
      no: 'D6-01',
      clause: '综合或专项应急预案演练每半年≥1次',
      window: { start: '2026-07-01', end: '2026-12-31' },
      verdict_status: 'ok',
      evidence: [
        { title: '罐区综合演练', date: '2026-08-15', type: '综合应急演练' },
        { title: '车间专项演练', date: '2026-10-01', type: '专项应急演练' },
      ],
      no_data_reason: null,
    })
    renderWithQuery(<GoalsPageClient />)

    const row = await screen.findByRole('row', { name: /D6-01/ })
    await userClick(within(row).getByText('查看'))

    expect(await screen.findByText('D6-01 凭据')).toBeInTheDocument()
    expect(await screen.findByText('罐区综合演练')).toBeInTheDocument()
    expect(await screen.findByText(/核查窗口 2026-07-01/)).toBeInTheDocument()
  })

  it('无数据行打开抽屉显示原因与接入指引', async () => {
    fetchMock.mockResolvedValue(LIVE)
    evidenceMock.mockResolvedValue({
      status: 'live',
      record_id: 'r4',
      no: 'D3-05',
      clause: '年度培训计划完成率≥95%',
      verdict_status: 'no_data',
      evidence: [],
      no_data_reason: '指标未注册（依赖对应域接入）',
    })
    renderWithQuery(<GoalsPageClient />)

    const row = await screen.findByRole('row', { name: /D3-05/ })
    await userClick(within(row).getByText('查看'))

    expect(await screen.findByText('D3-05 凭据')).toBeInTheDocument()
    expect(screen.getByText(/指标未注册/)).toBeInTheDocument()
  })
})

// 轻量点击 helper（避免引 user-event 依赖差异）
async function userClick(el: Element) {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

const HISTORY_LIVE: StandardHistoryData = {
  status: 'live',
  year: 2099,
  available_years: [2099],
  periods: [
    {
      period_key: '2099-Q3',
      label: '2099 第三季度',
      frozen_at: '2099-10-01T00:20:00Z',
      summary: {
        achieved: 1,
        missed: 1,
        no_data: 1,
        manual_done: 1,
        manual_missed: 0,
        in_progress: 0,
        total: 4,
        compliance_rate: 67,
      },
      rows: [
        {
          standard_no: 'D4-01',
          clause: '特殊作业实行作业许可，作业票审核覆盖率',
          basis: 'GB 30871-2022',
          element: '现场管理',
          metric_key: 'workticket.audit_rate',
          period: '季度',
          target_display: '≥95%',
          actual_display: '95%',
          status: 'achieved',
          department: ['生产一部'],
          owner: null,
          note: null,
          auto: true,
        },
        {
          standard_no: 'D5-04',
          clause: '隐患按期整改完成率',
          basis: '公司年度目标',
          element: '风险管控与隐患治理',
          metric_key: 'hazard.on_time_close_rate',
          period: '季度',
          target_display: '≥95%',
          actual_display: '80%',
          status: 'missed',
          department: ['生产二部'],
          owner: null,
          note: null,
          auto: true,
        },
        {
          standard_no: 'D1-03',
          clause: '各级安全责任书按年度签订完成',
          basis: '公司制度',
          element: '目标职责',
          metric_key: null,
          period: '季度',
          target_display: '已完成',
          actual_display: '已完成',
          status: 'manual_done',
          department: ['安环部'],
          owner: null,
          note: null,
          auto: false,
        },
        {
          standard_no: 'D3-06',
          clause: '外来人员入厂安全培训报备率',
          basis: '公司制度',
          element: '教育培训',
          metric_key: 'visitor.notice_rate',
          period: '月度',
          target_display: '≥100%',
          actual_display: null,
          status: 'no_data',
          department: ['安环部'],
          owner: null,
          note: 'visitor_notice 域未接入',
          auto: true,
        },
      ],
    },
  ],
}

describe('GoalsPageClient 历史定格 Tab（S1 二期）', () => {
  it('live：分期分组 + 六态状态标签 + 定格元信息', async () => {
    fetchMock.mockResolvedValue(LIVE)
    historyMock.mockResolvedValue(HISTORY_LIVE)
    renderWithQuery(<GoalsPageClient />)

    await userClick(screen.getByRole('tab', { name: '历史定格' }))
    expect(await screen.findByText('2099 第三季度')).toBeInTheDocument()
    expect(screen.getByText(/定格于 2099-10-01/)).toBeInTheDocument()
    expect(screen.getByText(/符合率 67%/)).toBeInTheDocument()
    const row_ok = screen.getByRole('row', { name: /D4-01/ })
    expect(within(row_ok).getByText('达标')).toBeInTheDocument()
    const row_missed = screen.getByRole('row', { name: /D5-04/ })
    expect(within(row_missed).getByText('未达标')).toBeInTheDocument()
    const row_manual = screen.getByRole('row', { name: /D1-03/ })
    expect(within(row_manual).getByText('达标·人工')).toBeInTheDocument()
    const row_nodata = screen.getByRole('row', { name: /D3-06/ })
    expect(within(row_nodata).getByText('无数据')).toBeInTheDocument()
  })

  it('empty：无快照年份显示引导', async () => {
    fetchMock.mockResolvedValue(LIVE)
    historyMock.mockResolvedValue({
      status: 'empty',
      year: 2099,
      available_years: [],
      periods: [],
    })
    renderWithQuery(<GoalsPageClient />)

    await userClick(screen.getByRole('tab', { name: '历史定格' }))
    // 面板本地年份=当前年（2099 只是 mock 返回值），标题动态匹配
    expect(await screen.findByText(/\d{4} 年暂无定格记录/)).toBeInTheDocument()
    expect(screen.getByText(/每季度首日 08:20/)).toBeInTheDocument()
  })
})

describe('GoalsPageClient 筛选与部门汇总（T5）', () => {
  it('部门汇总 Tab：部门×四态小表', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<GoalsPageClient />)

    await userClick(screen.getByRole('tab', { name: '责任部门汇总' }))
    expect(await screen.findByText(/联合责任口径/)).toBeInTheDocument()
    const cells = within(screen.getByRole('row', { name: /生产一部/ })).getAllByRole('cell')
    expect(cells[4].textContent).toBe('1') // 未达标列
    const cells2 = within(screen.getByRole('row', { name: /安环部/ })).getAllByRole('cell')
    expect(cells2[2].textContent).toBe('1') // 达标列
  })

  it('筛选栏存在且选择器可展开（年度/要素/状态/部门）', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<GoalsPageClient />)

    expect(await screen.findByText('已接入')).toBeInTheDocument()
    const combos = screen.getAllByRole('combobox')
    expect(combos.length).toBe(4) // 年度/要素/状态/部门
  })
})

/**
 * 四新域通用页面测试（3.0 四期 1-C）：三态渲染 + 只读守卫。
 * 接缝：vi.mock fetchDomainPage（照 SupervisionPage.test 手法）。
 */
import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DomainLedgerPage from './DomainLedgerPage'
import { renderWithQuery } from '@/test/utils'
import type { DomainPageData } from '@/lib/api/safety/domain-pages'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/domain-pages', () => ({
  fetchDomainPage: fetchMock,
}))

const NOT_CONNECTED: DomainPageData = {
  status: 'not_connected',
  stats: null,
  ledger: { data: [], meta: { total: 0, page: 1, page_size: 20 } },
  errors: [],
}

const LIVE: DomainPageData = {
  status: 'live',
  stats: {
    goal_total: 4,
    goal_achieved: 2,
    goal_in_progress: 1,
    goal_missed: 1,
    agreement_rate: 67,
    investment_wan: 75.0,
  },
  ledger: {
    data: [
      {
        record_id: 'r1',
        year: '2026',
        name: '重伤及以上事故为零',
        indicator_type: null,
        target_value: '0',
        level: '公司',
        department: ['EHS部'],
        owner: '张三',
        actual_value: '0',
        status: '已达成',
      },
    ],
    meta: { total: 1, page: 1, page_size: 20 },
  },
  errors: [],
}

const DEGRADED: DomainPageData = {
  status: 'degraded',
  stats: null,
  ledger: { data: [], meta: { total: 0, page: 1, page_size: 20 } },
  errors: ['goal_indicator: BitableQueryError'],
}

beforeEach(() => {
  vi.clearAllMocks()
})

// 只读守卫：不允许出现任何业务操作按钮（3.0 口径）
const BUSINESS_BUTTON_RE = /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发|编辑|保存/

describe('DomainLedgerPage（四新域通用页面）', () => {
  it('goals 未接入态：三态标签 + 统计行「—」 + EmptyGuide 建表引导 + 蓝本列头 + 零业务按钮', async () => {
    fetchMock.mockResolvedValue(NOT_CONNECTED)
    renderWithQuery(<DomainLedgerPage domain="goals" />)

    expect(await screen.findByText('目标责任与绩效')).toBeInTheDocument()
    expect(await screen.findByText('未接入')).toBeInTheDocument()
    // 统计卡全部显示「—」
    expect((await screen.findAllByText('—')).length).toBeGreaterThanOrEqual(6)
    // 未接入引导 + 蓝本引用
    expect(screen.getByText('数据源未接入')).toBeInTheDocument()
    expect(screen.getByText(/目标指标\/责任制清单\/安全投入/)).toBeInTheDocument()
    expect(screen.getByText(/DESIGN-安全模块3.0四期.*§2/)).toBeInTheDocument()
    // 台账列头=蓝本列（空态即设计）
    expect(screen.getByRole('columnheader', { name: '目标名称' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '达成状态' })).toBeInTheDocument()
    // 只读守卫
    const buttons = screen.queryAllByRole('button').filter((b) =>
      BUSINESS_BUTTON_RE.test(b.textContent ?? ''),
    )
    expect(buttons).toHaveLength(0)
  })

  it('live 态：统计卡出数 + 台账行渲染（数组/空值格式化）', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<DomainLedgerPage domain="goals" />)

    expect(await screen.findByText('已接入')).toBeInTheDocument()
    expect(await screen.findByText('4')).toBeInTheDocument() // goal_total
    expect(screen.getByText('67%')).toBeInTheDocument() // agreement_rate
    expect(screen.getByText('75万')).toBeInTheDocument() // investment_wan
    // 台账行：数组顿号连接、空值「—」（在行内断言，避免与统计卡标签重名）
    expect(screen.getByText('重伤及以上事故为零')).toBeInTheDocument()
    expect(screen.getByText('EHS部')).toBeInTheDocument()
    const row = screen.getByRole('row', { name: /重伤及以上事故为零/ })
    expect(within(row).getByText('已达成')).toBeInTheDocument()
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('degraded 态：降级标签 + 错误标注', async () => {
    fetchMock.mockResolvedValue(DEGRADED)
    renderWithQuery(<DomainLedgerPage domain="goals" />)

    expect(await screen.findByText('数据降级')).toBeInTheDocument()
    expect(screen.getByText('数据源读取降级')).toBeInTheDocument()
    expect(screen.getByText(/goal_indicator: BitableQueryError/)).toBeInTheDocument()
  })

  it('四域配置各自生效（标题/列头抽查）', async () => {
    fetchMock.mockResolvedValue(NOT_CONNECTED)
    const { unmount } = renderWithQuery(<DomainLedgerPage domain="training-behavior" />)
    expect(await screen.findByText('教育培训与行为管控')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '下次复训' })).toBeInTheDocument()
    unmount()

    renderWithQuery(<DomainLedgerPage domain="facilities" />)
    expect(await screen.findByText('设备设施管理')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '设备编号' })).toBeInTheDocument()
  })

  it('请求失败（网络错误）：降级空态而非崩溃，仍零业务按钮', async () => {
    fetchMock.mockRejectedValue(new Error('network down'))
    renderWithQuery(<DomainLedgerPage domain="incidents" />)

    expect(await screen.findByText('事故事件管理')).toBeInTheDocument()
    expect(await screen.findByText('数据暂时不可用')).toBeInTheDocument()
    const buttons = screen.queryAllByRole('button').filter((b) =>
      BUSINESS_BUTTON_RE.test(b.textContent ?? ''),
    )
    expect(buttons).toHaveLength(0)
  })
})

/**
 * 承包商在册人员副台账区块测试（3.x 平台关联 F1）：
 * 三态渲染（live 统计+打码行 / degraded 缓存提示 / empty 引导）+
 * 筛选（仅看异常/工种）+ 行点击 Drawer detailFields。
 * 接缝：vi.mock fetchContractorWorkers（照 DomainLedgerPage.test 手法）。
 */
import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ContractorWorkersLedger } from './ContractorWorkersLedger'
import { renderWithQuery } from '@/test/utils'
import type { ContractorWorkersPayload } from '@/lib/api/safety/contractor-workers'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/contractor-workers', () => ({
  fetchContractorWorkers: fetchMock,
}))

function _row(overrides: Partial<ContractorWorkersPayload['workers'][number]>) {
  return {
    id: 'r1',
    name: '施瑞国',
    contractor_name: '福清市一建建筑工程有限公司',
    work_type: '焊工',
    age: 45,
    join_job_date: '2025-12-01',
    card_no_masked: '350***92',
    phone_masked: '139***67',
    insurance_status: 'covered' as const,
    insurance_expire_date: '2027-06-01',
    insurance_days_left: 300,
    insurance_source_company: '福清市一建建筑工程有限公司',
    cert_status: 'hit' as const,
    cert_project: '熔化焊接与热切割作业',
    cert_next_review_date: '2027-03-01',
    age_flag: 'none' as const,
    anomalies: [],
    ...overrides,
  }
}

const LIVE: ContractorWorkersPayload = {
  status: 'live',
  fetched_at: '2026-10-26T10:00:00+08:00',
  message: null,
  stats: {
    total: 3,
    contractors: 3,
    insurance_covered_pct: 67,
    special_total: 2,
    cert_covered_pct: 50,
    overage_count: 1,
    overage_warn_count: 0,
  },
  workers: [
    _row({ id: 'r1' }),
    _row({
      id: 'r2',
      name: '李四',
      contractor_name: '江苏天目建设集团有限公司',
      work_type: '普工',
      age: 61,
      insurance_status: 'uncovered',
      cert_status: 'nonspecial',
      cert_project: null,
      age_flag: 'red',
      anomalies: ['超龄', '保险未覆盖'],
    }),
    _row({
      id: 'r3',
      name: '王五',
      contractor_name: '江苏空间新盛建设工程有限公司',
      work_type: '电工',
      age: 30,
      insurance_status: 'expiring',
      insurance_days_left: 7,
      cert_status: 'missing',
      age_flag: 'none',
      anomalies: ['保险临期', '未见持证记录'],
    }),
  ],
}

beforeEach(() => {
  fetchMock.mockReset()
})

describe('ContractorWorkersLedger', () => {
  it('live：渲染 5 张统计卡与在册行（台账时点标注，无明文）', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<ContractorWorkersLedger />)

    expect(await screen.findByText('施瑞国')).toBeInTheDocument()
    expect(screen.getByText('李四')).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
    // 统计卡
    expect(screen.getByText('在册人数')).toBeInTheDocument()
    expect(screen.getByText('承包商数')).toBeInTheDocument()
    expect(screen.getByText('保险覆盖')).toBeInTheDocument()
    expect(screen.getByText('特种工持证率')).toBeInTheDocument()
    expect(screen.getByText('超龄（≥60）')).toBeInTheDocument()
    // 台账时点标注 + 状态标签
    expect(screen.getByText(/台账时点 2026-10-26 10:00/)).toBeInTheDocument()
    expect(screen.getByText('临期7天')).toBeInTheDocument()
    // 特种列状态标签与异常标签同文案，行内至少出现一次
    expect(screen.getAllByText('未见持证记录').length).toBeGreaterThan(0)
    // 打码明文防线：原始身份证/手机号形态不出现在页面
    expect(document.body.textContent).not.toContain('350100199001016592')
    expect(document.body.textContent).not.toContain('13900001667')
  })

  it('仅看异常：开关后无异常行消失', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<ContractorWorkersLedger />)
    await screen.findByText('施瑞国')

    await userEvent.click(screen.getByRole('switch'))
    expect(screen.getByText('李四')).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
    expect(screen.queryByText('施瑞国')).not.toBeInTheDocument()
  })

  it('工种筛选：选择焊工后只剩焊工行', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<ContractorWorkersLedger />)
    await screen.findByText('施瑞国')

    // antd Select 在 jsdom 的惯用打开手法：mousedown 触发选择器
    const workTypeSelect = screen.getByText('全部工种').closest('.ant-select')
    expect(workTypeSelect).not.toBeNull()
    fireEvent.mouseDown(within(workTypeSelect as HTMLElement).getByRole('combobox'))
    const option = await screen.findByText('焊工', { selector: '.ant-select-item-option-content' })
    await userEvent.click(option)
    expect(screen.getByText('施瑞国')).toBeInTheDocument()
    expect(screen.queryByText('李四')).not.toBeInTheDocument()
    expect(screen.queryByText('王五')).not.toBeInTheDocument()
  })

  it('行点击打开 Drawer：detailFields 配置驱动展示打码身份证与交叉明细', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<ContractorWorkersLedger />)
    await screen.findByText('施瑞国')

    await userEvent.click(screen.getByText('施瑞国'))
    const drawerTitle = await screen.findByText('在册人员详情 - 施瑞国')
    expect(drawerTitle).toBeInTheDocument()
    // Drawer 渲染在传送门里，从标题回溯到 drawer 容器作为断言区域
    const region = (drawerTitle.closest('.ant-drawer') as HTMLElement) ?? document.body
    // detailFields：打码身份证 + 交叉明细（证书项目/来源单位/有效期）
    expect(within(region).getAllByText('350***92').length).toBeGreaterThan(0)
    expect(within(region).getAllByText('熔化焊接与热切割作业').length).toBeGreaterThan(0)
    expect(within(region).getAllByText('2027-06-01').length).toBeGreaterThan(0)
  })

  it('degraded：展示缓存时点与降级提示，行仍可见', async () => {
    fetchMock.mockResolvedValue({
      ...LIVE,
      status: 'degraded',
      message: '数据源拉取失败，当前展示缓存数据（缓存时点 2026-10-26T10:00:00+08:00）',
    })
    renderWithQuery(<ContractorWorkersLedger />)
    await screen.findByText('施瑞国')
    expect(screen.getByText(/缓存时点 2026-10-26 10:00/)).toBeInTheDocument()
    expect(screen.getByText(/数据源拉取失败/)).toBeInTheDocument()
  })

  it('empty：EmptyGuide 展示平台不可用说明', async () => {
    fetchMock.mockResolvedValue({
      status: 'empty',
      fetched_at: null,
      message: '承包商在册人员数据拉取失败且无缓存：3.x 平台接口或飞书数据源暂不可用，请稍后重试',
      stats: null,
      workers: [],
    })
    renderWithQuery(<ContractorWorkersLedger />)
    expect(await screen.findByText('平台数据暂不可用')).toBeInTheDocument()
    expect(screen.getByText(/3.x 平台接口或飞书数据源暂不可用/)).toBeInTheDocument()
    expect(screen.queryByText('在册人数')).not.toBeInTheDocument()
  })
})

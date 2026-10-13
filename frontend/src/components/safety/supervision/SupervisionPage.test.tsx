import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SupervisionPage from './SupervisionPage'
import { renderWithQuery } from '@/test/utils'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/workticket-review', () => ({
  fetchWorkTicketReview: fetchMock,
}))

const REVIEW_DATA = {
  date: '2026-10-12',
  total: 14,
  reviewed: 11,
  violation_count: 2,
  compliant_count: 9,
  data_insufficient: 3,
  status: 'success',
  report_markdown: '## 作业票审核速递\n\n**类型分布**：动火 5；受限空间 3\n\n违规 2 起。',
  pushed: true,
  push_message_id: 'om_x',
  error: null,
  finished_at: '2026-10-12T09:00:00+00:00',
  violations: [
    {
      id: 'v1',
      review_id: 'r1',
      ticket_no: 'WT-2026-001',
      ticket_type: 'hot_work',
      rule_no: 'TIME_ORDER',
      rule_name: '时间顺序违规',
      detail: '气体分析晚于作业开始',
      key_times: { 开始时间: '08:00', 气体分析: '09:30' },
      not_applicable: false,
    },
    {
      id: 'v2',
      review_id: 'r1',
      ticket_no: 'WT-2026-002',
      ticket_type: 'confined_space',
      rule_no: 'GAS_VALIDITY',
      rule_name: '气体分析有效期',
      detail: '该票无气体分析要求',
      key_times: null,
      not_applicable: true,
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SupervisionPage（全流程监督 v1）', () => {
  it('按日期渲染审核摘要、违规明细与速递原文；默认查今天', async () => {
    fetchMock.mockResolvedValue(REVIEW_DATA)
    renderWithQuery(<SupervisionPage />)

    // 摘要 5 指标
    expect(await screen.findByText('14')).toBeInTheDocument()
    expect(screen.getByText('11')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()

    // 默认查今天（YYYY-MM-DD 格式参数）
    const today = new Date().toLocaleDateString('sv-SE')
    expect(fetchMock).toHaveBeenCalledWith(today)

    // 违规明细表：票号/票型中文/判定
    expect(screen.getByText('WT-2026-001')).toBeInTheDocument()
    expect(screen.getByText('动火作业')).toBeInTheDocument()
    expect(screen.getByText('受限空间作业')).toBeInTheDocument()
    expect(screen.getAllByText('违规').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('不适用')).toBeInTheDocument()

    // 速递原文渲染（markdown 标题与内容）
    expect(screen.getByText('作业票审核速递', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByText(/类型分布/)).toBeInTheDocument()
    expect(screen.getByText(/已推送飞书/)).toBeInTheDocument()
  })

  it('无记录日期显示空态引导而非报错', async () => {
    fetchMock.mockResolvedValue(null)
    renderWithQuery(<SupervisionPage />)

    expect(await screen.findByText(/尚无作业票审核记录/)).toBeInTheDocument()
    expect(screen.getByText(/每日 17:00 定时任务生成/)).toBeInTheDocument()
  })

  it('查询失败显示错误与重试', async () => {
    fetchMock.mockRejectedValue(new Error('连接失败'))
    renderWithQuery(<SupervisionPage />)

    expect(await screen.findByText('作业票审核记录加载失败')).toBeInTheDocument()
    expect(screen.getByText('连接失败')).toBeInTheDocument()
    // antd 按钮双字间渲染空格（「重 试」）
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
  })

  it('刷新按钮按当前日期重查', async () => {
    fetchMock.mockResolvedValue(REVIEW_DATA)
    const user = userEvent.setup()
    renderWithQuery(<SupervisionPage />)

    await screen.findByText('14')
    fetchMock.mockClear()
    await user.click(screen.getByRole('button', { name: /刷\s*新/ }))
    const today = new Date().toLocaleDateString('sv-SE')
    expect(fetchMock).toHaveBeenCalledWith(today)
  })

  it('页面无业务操作按钮（只读；刷新/日期/重试除外）', async () => {
    fetchMock.mockResolvedValue(REVIEW_DATA)
    renderWithQuery(<SupervisionPage />)

    await screen.findByText('14')
    const businessButtons = screen
      .queryAllByRole('button')
      .filter((btn) =>
        /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发/.test(btn.textContent ?? ''),
      )
    expect(businessButtons).toHaveLength(0)
  })
})

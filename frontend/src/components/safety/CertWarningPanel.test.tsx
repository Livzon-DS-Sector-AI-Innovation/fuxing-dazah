import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CertWarningPanel from './CertWarningPanel'
import { renderWithQuery } from '@/test/utils'

// 回填抽屉走 server actions，桩掉（交互由后端既有行为覆盖，不属本测试范围）
vi.mock('./CertRenewDrawer', () => ({
  default: () => <div data-testid="renew-drawer-stub" />,
}))

const listMock = vi.hoisted(() => vi.fn())
const summaryMock = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api/safety/cert-warning', () => ({
  fetchCertWarnings: listMock,
  fetchCertWarningSummary: summaryMock,
}))

const SUMMARY = {
  overdue_count: 2,
  urgent_count: 1, // 0-7
  key_warning_count: 3, // 8-30
  to_schedule_count: 4, // 31-60
  early_notice_count: 5, // 61-90
  normal_count: 90,
  total: 105,
  by_category: {},
  by_event: {},
}

const ROWS = [
  {
    id: 'c1',
    person_name: '张三',
    department: 'EHS部',
    cert_category: 'special_op',
    project: '-',
    current_node: '复审',
    deadline: '2026-10-20',
    remaining_days: 5,
    status_level: 'urgent',
    suggestion: '尽快安排复审',
  },
  {
    id: 'c2',
    person_name: '李四',
    department: '生产部',
    cert_category: 'guardian_a',
    project: '-',
    current_node: '正常',
    deadline: '2027-03-01',
    remaining_days: 140,
    status_level: 'normal',
    suggestion: '',
  },
  {
    id: 'c3',
    person_name: '王五',
    department: 'EHS部',
    cert_category: 'special_op',
    project: '-',
    current_node: '换证',
    deadline: '2026-09-01',
    remaining_days: -30,
    status_level: 'overdue',
    suggestion: '立即换证',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  summaryMock.mockResolvedValue(SUMMARY)
  listMock.mockResolvedValue({
    items: ROWS,
    total: 3,
    page: 1,
    page_size: 20,
  })
})

describe('CertWarningPanel（证书台账 + 预警一体，三期强化）', () => {
  it('统计行由 summary 六档推导 30/60/90 分层与已过期', async () => {
    renderWithQuery(<CertWarningPanel />)

    // 总持证 = total；30 内 = urgent(1) + key_warning(3)；31-60 = 4；61-90 = 5；已过期 = 2
    expect(await screen.findByText('105')).toBeInTheDocument()
    expect(screen.getAllByText('4').length).toBe(2) // 30 天内 与 31-60 天（同值 4）
    expect(screen.getByText(/31-60/)).toBeInTheDocument()
    expect(screen.getByText(/61-90/)).toBeInTheDocument()
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1) // 已过期（卡片与行内标签可能同现）
    // 卡片标签齐全
    expect(screen.getByText('总持证数')).toBeInTheDocument()
    expect(screen.getByText('30 天内到期')).toBeInTheDocument()
    expect(screen.getByText('已过期')).toBeInTheDocument()
  })

  it('台账默认全量：姓名/状态列渲染、预警状态用 StatusTag、回填入口保留', async () => {
    renderWithQuery(<CertWarningPanel />)

    expect(await screen.findByText('张三')).toBeInTheDocument()
    expect(screen.getByText('李四')).toBeInTheDocument()
    expect(screen.getByText('王五')).toBeInTheDocument()
    // 台账描述（全量口径）
    expect(screen.getByText(/全量证书台账（共 3 条）/)).toBeInTheDocument()
    // 状态与类型标签
    expect(screen.getByText('紧急预警')).toBeInTheDocument()
    expect(screen.getAllByText('已逾期').length).toBe(1) // 行内标签（统计卡标签为「已过期」）
    expect(screen.getAllByText('特种作业证').length).toBe(2) // 两行特种作业证
    // 既有回填交互保留（闭环类既有操作）
    expect(screen.getAllByText('回填').length).toBe(3)
  })

  it('姓名筛选：本页检索口径，拉 200 条客户端过滤并停用分页', async () => {
    const user = userEvent.setup()
    renderWithQuery(<CertWarningPanel />)

    await screen.findByText('张三')
    listMock.mockClear()
    // data-testid 由 antd Input 落在 input 元素本身
    const input = screen.getByTestId('cert-name-input')
    await user.type(input, '张')
    await user.keyboard('{Enter}')

    // 应用后按 200 上限拉取、无姓名参数下发（后端无该参数）
    expect(listMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 200 }),
    )
    // 命中 1 条（张三）
    expect(await screen.findByText(/命中 1 条/)).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.queryByText('李四')).not.toBeInTheDocument()
  })
})

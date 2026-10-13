import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SafetyOverviewDashboard } from './SafetyOverviewDashboard'
import { renderWithQuery } from '@/test/utils'

// echarts 依赖 canvas，happy-dom 下以占位元素代替
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echart" />,
}))

const pushMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn(), back: vi.fn() }),
}))

// vi.mock factory 会被提升到文件顶部，样例数据必须内联在 factory 里
vi.mock('@/lib/api/safety/overview', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/api/safety/overview')>()
  const OVERVIEW = {
    date: '2026-10-12',
    generated_at: '2026-10-12T09:30:00+00:00',
    hazards: {
      unclosed: 12,
      delta: -3,
      overdue: 2,
      trend: {
        dates: ['2026-10-11', '2026-10-12'],
        created: [4, 2],
        closed: [7, 3],
      },
    },
    special_ops: { today_total: 8, high: 2 },
    alarms: {
      today_total: 15,
      fire_today: 9,
      central_today: 6,
      fire_real_today: 1,
      analysis: {
        dates: ['2026-10-11', '2026-10-12'],
        fire_daily: [9, 6],
        central_daily: [4, 2],
        top_fire_types: [{ name: '手动报警', count: 5 }],
      },
    },
    certs: {
      within_30d: 9,
      urgent_or_overdue: 1,
      items: [
        {
          person_name: '张三',
          department: 'EHS部',
          cert_category: 'special_op',
          deadline: '2026-10-20',
          remaining_days: 5,
        },
      ],
    },
    chemicals: {
      over_limit: 3,
      materials: [
        {
          material_name: '甲醇',
          department: '一车间',
          storage_location: '库1',
          total_quantity_t: 12.5,
          max_limit: 10,
          unit: 't',
        },
      ],
    },
    key_risk_ops: {
      today_approved: 3,
      in_progress: 1,
      items: [
        {
          start_time: '2026-10-12T02:00:00+00:00',
          department: '二车间',
          operation_content: '受限空间作业',
          apply_status: '已通过',
        },
      ],
    },
    digest: {
      count: 1,
      cells: [
        {
          key: 'special_op',
          tag_color: 'blue',
          tag_text: '特殊作业',
          title: '特殊作业晨报',
          stats: '今日计划 **14** 项',
          zone: '高风险集中在发酵工程部',
          detail: '作业明细全文内容',
          sent_at: '2026-10-12T00:00:00+00:00',
        },
      ],
    },
    module_health: [
      { key: 'knowledge-base', status: 'ok', metric: '运行中' },
      { key: 'goals', status: 'inactive', metric: '未开展' },
      { key: 'risk-grading', status: 'ok', metric: '运行中' },
      { key: 'hazard-ledger', status: 'warn', metric: '未闭环 12 · 逾期 2' },
      { key: 'cert-warnings', status: 'warn', metric: '30 天内到期 9' },
      { key: 'training-behavior', status: 'inactive', metric: '未开展' },
      { key: 'occupational-health', status: 'ok', metric: '运行中' },
      { key: 'facilities', status: 'inactive', metric: '未开展' },
      { key: 'chemicals', status: 'warn', metric: '超储 3 项' },
      { key: 'special-ops', status: 'warn', metric: '今日 8 项 · 高险 2' },
      { key: 'risk-reporting', status: 'ok', metric: '今日通过 3 / 审批中 1' },
      { key: 'alarms', status: 'warn', metric: '今日 15 起 · 真报 1' },
      { key: 'ehs-change', status: 'ok', metric: '进行中 4 项' },
      { key: 'contractor-admission', status: 'ok', metric: '运行中' },
      { key: 'emergency-drill', status: 'ok', metric: '运行中' },
      { key: 'supervision', status: 'ok', metric: '最近审核 2026-10-12 · 违规 2' },
      { key: 'incidents', status: 'inactive', metric: '未开展' },
    ],
    errors: [],
  } satisfies import('@/lib/api/safety/overview').SafetyOverview
  return {
    ...actual,
    fetchSafetyOverview: vi.fn().mockResolvedValue(OVERVIEW),
  }
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SafetyOverviewDashboard（3.0 只读驾驶舱）', () => {
  it('渲染 6 项 KPI（含隐患较昨日 delta 与高险/真报副文本）', async () => {
    renderWithQuery(<SafetyOverviewDashboard />)

    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.getByText(/较昨日/)).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('高风险 2 项')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('真报 1 起（消防口径）')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    // 「今日安全速递」同时是 KPI 标签与速递区块标题
    expect(screen.getAllByText('今日安全速递')).toHaveLength(2)
    expect(screen.getByText('机器人已推送日报条数')).toBeInTheDocument()
  })

  it('速递流渲染条目，点击弹层看全文', async () => {
    const user = userEvent.setup()
    renderWithQuery(<SafetyOverviewDashboard />)

    const row = await screen.findByText('特殊作业晨报')
    await user.click(row)
    expect(await screen.findByText('作业明细全文内容')).toBeInTheDocument()
  })

  it('健康度墙 17 个模块全展示且与菜单对齐；灰卡可点占位页、监督卡可点监督页', async () => {
    const user = userEvent.setup()
    renderWithQuery(<SafetyOverviewDashboard />)

    await screen.findByText('体系模块健康度')
    expect(screen.getAllByTestId('module-card')).toHaveLength(17)
    // 分组与一期菜单一致（8 个体系要素分组标题全渲染）
    for (const g of [
      '体系治理', '风险管控', '隐患治理', '人员管理',
      '现场管理', '应急处置', '检查监督', '持续改进',
    ]) {
      expect(screen.getByText(g)).toBeInTheDocument()
    }
    // 与一期菜单同名（纯文字短名）
    for (const label of [
      '目标责任与绩效', '法规标准与规程', '风险分级管控', '隐患排查与治理',
      '人员准入与资质', '教育培训与行为管控', '职业健康管理', '设备设施管理',
      '危化品与 MSDS 管理', '特殊作业管理', '风险作业报备', '监测报警与预警',
      'EHS 变更管理', '相关方管理', '应急管理', '全流程监督', '事故事件管理',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // 灰卡（未开展）可点击达占位页
    await user.click(screen.getByText('教育培训与行为管控'))
    expect(pushMock).toHaveBeenCalledWith('/safety/training-behavior')
    pushMock.mockClear()
    // 全流程监督（三期已上线）卡片可点直达监督页
    await user.click(screen.getByText('全流程监督'))
    expect(pushMock).toHaveBeenCalledWith('/safety/supervision')
  })

  it('页面无业务操作按钮（只读态势；刷新/导航/弹层除外）', async () => {
    renderWithQuery(<SafetyOverviewDashboard />)

    await screen.findByText('体系模块健康度')
    const businessButtons = screen
      .queryAllByRole('button')
      .filter(btn => /登记|整改|复核|同步|生成|提交|新增|删除|审核|关闭隐患/.test(
        btn.textContent ?? '',
      ))
    expect(businessButtons).toHaveLength(0)
  })

  it('下钻三列渲染表格数据', async () => {
    renderWithQuery(<SafetyOverviewDashboard />)

    expect(await screen.findByText('受限空间作业')).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    expect(screen.getByText('甲醇')).toBeInTheDocument()
    // 图表：隐患趋势 + 报警分析 + Top 类型 = 3 个 echart 占位
    expect(screen.getAllByTestId('echart')).toHaveLength(3)
  })
})

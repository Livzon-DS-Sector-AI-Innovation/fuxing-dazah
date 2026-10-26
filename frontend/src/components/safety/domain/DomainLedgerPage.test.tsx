/**
 * 四新域通用页面测试（3.0 四期 1-C）：三态渲染 + 只读守卫。
 * 接缝：vi.mock fetchDomainPage（照 SupervisionPage.test 手法）。
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    training_total: 4,
    completion_rate: 67,
    pass_rate: 88,
    retraining_due_30d: 1,
    violation_total: 2,
    violation_open: 1,
  },
  ledger: {
    data: [
      {
        record_id: 'r1',
        name: '入厂三级教育',
        category: '入厂三级教育',
        planned_at: '2026-10-01T00:00:00',
        held_at: null,
        lecturer: '张三',
        actual_count: '10',
        assessment: '考试',
        status: '已完成',
        next_retraining_at: null,
      },
    ],
    meta: { total: 1, page: 1, page_size: 20 },
  },
  errors: [],
}

const LIVE_WITH_VIOLATIONS: DomainPageData = {
  ...LIVE,
  secondary_ledger: {
    data: [
      {
        record_id: 'v1',
        occurred_at: '2026-10-20T16:00:00+00:00',
        person_name: '李四',
        department: ['生产一部'],
        category: '操作违章',
        level: '严重',
        description: '未佩戴安全帽登高作业',
        handling: '停工培训',
        status: '纠正中',
        related_hazard_no: 'HJ-2026-001',
        corrective_action: '停工当日完成安全帽佩戴复训',
        retraining_note: '已生成待推送（2026-10-22）\n- 进入生产区必须正确佩戴安全帽',
        evidence_files: ['现场照片1.jpg', '现场照片2.jpg'],
        ai_level_suggestion: '建议定级：严重（高处作业未防护）',
        note: null,
      },
      {
        record_id: 'v2',
        occurred_at: null,
        person_name: null,
        department: [],
        category: null,
        level: null,
        description: '往年存量违章',
        handling: null,
        status: '已纠正',
        related_hazard_no: null,
      },
    ],
  },
}

const DEGRADED: DomainPageData = {
  status: 'degraded',
  stats: null,
  ledger: { data: [], meta: { total: 0, page: 1, page_size: 20 } },
  errors: ['training: BitableQueryError'],
}

beforeEach(() => {
  vi.clearAllMocks()
})

// 只读守卫：不允许出现任何业务操作按钮（3.0 口径）
const BUSINESS_BUTTON_RE = /登记|整改|复核|同步|生成|提交|新增|删除|审核通过|触发|编辑|保存/

describe('DomainLedgerPage（四新域通用页面；goals 已改走标准核查引擎）', () => {
  it('training-behavior 未接入态：三态标签 + 统计行「—」 + EmptyGuide 建表引导 + 蓝本列头 + 零业务按钮', async () => {
    fetchMock.mockResolvedValue(NOT_CONNECTED)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    expect(await screen.findByText('教育培训与行为管控')).toBeInTheDocument()
    expect(await screen.findByText('未接入')).toBeInTheDocument()
    // 统计卡全部显示「—」
    expect((await screen.findAllByText('—')).length).toBeGreaterThanOrEqual(6)
    // 未接入引导 + 蓝本引用
    expect(screen.getByText('数据源未接入')).toBeInTheDocument()
    expect(screen.getByText(/培训计划与实施\/违章行为档案/)).toBeInTheDocument()
    expect(screen.getByText(/DESIGN-安全模块3.0四期.*§3/)).toBeInTheDocument()
    // 台账列头=蓝本列（空态即设计）
    expect(screen.getByRole('columnheader', { name: '培训名称' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '状态' })).toBeInTheDocument()
    // 只读守卫
    const buttons = screen.queryAllByRole('button').filter((b) =>
      BUSINESS_BUTTON_RE.test(b.textContent ?? ''),
    )
    expect(buttons).toHaveLength(0)
  })

  it('live 态：统计卡出数 + 台账行渲染（ISO 时间格式化/空值「—」）', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    expect(await screen.findByText('已接入')).toBeInTheDocument()
    expect(await screen.findByText('4')).toBeInTheDocument() // training_total
    expect(screen.getByText('67%')).toBeInTheDocument() // completion_rate
    // 台账行：ISO 时间本地化、空值「—」（在行内断言，避免与统计卡/类别重名）
    expect(screen.getByText('张三')).toBeInTheDocument()
    const row = screen.getByRole('row', { name: /入厂三级教育/ })
    expect(within(row).getByText('已完成')).toBeInTheDocument()
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('degraded 态：降级标签 + 错误标注', async () => {
    fetchMock.mockResolvedValue(DEGRADED)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    expect(await screen.findByText('数据降级')).toBeInTheDocument()
    expect(screen.getByText('数据源读取降级')).toBeInTheDocument()
    expect(screen.getByText(/training: BitableQueryError/)).toBeInTheDocument()
  })

  it('live 且违章档案有数据：主台账下方渲染「违章行为档案」区块（行/列头/空值「—」）', async () => {
    fetchMock.mockResolvedValue(LIVE_WITH_VIOLATIONS)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    expect(await screen.findByText('违章行为档案')).toBeInTheDocument()
    // 副台账列头（违章专属列，主台账没有）
    expect(screen.getByRole('columnheader', { name: '违章等级' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '关联隐患编号' })).toBeInTheDocument()
    // 行内容 + 空值「—」（在违章行内断言）
    const row = screen.getByRole('row', { name: /未佩戴安全帽登高作业/ })
    expect(within(row).getByText('操作违章')).toBeInTheDocument()
    expect(within(row).getByText('纠正中')).toBeInTheDocument()
    expect(within(row).getByText('HJ-2026-001')).toBeInTheDocument()
    const sparseRow = screen.getByRole('row', { name: /往年存量违章/ })
    expect(within(sparseRow).getAllByText('—').length).toBeGreaterThanOrEqual(5)
    // 主台账仍在（两表同屏）
    expect(screen.getByRole('row', { name: /入厂三级教育/ })).toBeInTheDocument()
    // 副台账共 2 条（客户端分页 showTotal）
    expect(screen.getByText('共 2 条')).toBeInTheDocument()
  })

  it('live 但违章副表未接入（secondary_ledger=null）：区块整体隐藏，主台账照常', async () => {
    fetchMock.mockResolvedValue(LIVE)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    expect(await screen.findByText('已接入')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /入厂三级教育/ })).toBeInTheDocument()
    expect(screen.queryByText('违章行为档案')).not.toBeInTheDocument()
  })

  it('点击违章行打开详情 Drawer：要点卡/证据附件/AI判级建议（表格外字段）', async () => {
    fetchMock.mockResolvedValue(LIVE_WITH_VIOLATIONS)
    renderWithQuery(<DomainLedgerPage domain="training-behavior" />)

    const row = await screen.findByRole('row', { name: /未佩戴安全帽登高作业/ })
    await userEvent.click(row)

    expect(await screen.findByText('违章行为档案详情')).toBeInTheDocument()
    expect(screen.getByText('定向培训要点卡')).toBeInTheDocument()
    expect(
      screen.getByText(/已生成待推送（2026-10-22）\s*- 进入生产区必须正确佩戴安全帽/),
    ).toBeInTheDocument()
    expect(screen.getByText('证据附件')).toBeInTheDocument()
    expect(screen.getByText('现场照片1.jpg、现场照片2.jpg')).toBeInTheDocument()
    expect(screen.getByText('建议定级：严重（高处作业未防护）')).toBeInTheDocument()

    // 关闭后可再次点击另一行（空字段行 Drawer 里显示「—」）
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    const sparseRow = screen.getByRole('row', { name: /往年存量违章/ })
    await userEvent.click(sparseRow)
    expect(screen.getByText('违章行为档案详情')).toBeInTheDocument()
    expect(screen.getByText('定向培训要点卡')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('facilities 副台账：检验记录区块通用渲染（配置驱动）', async () => {
    fetchMock.mockResolvedValue({
      status: 'live',
      stats: {
        equipment_total: 1, special_equipment: 0, inspection_overdue: 0,
        inspection_due_30d: 1, inspection_pass_rate: 100, inactive_equipment: 0,
      },
      ledger: {
        data: [{ record_id: 'e1', equipment_no: 'EQ-01', name: '叉车', status: '在用' }],
        meta: { total: 1, page: 1, page_size: 20 },
      },
      secondary_ledger: {
        data: [
          {
            record_id: 'i1',
            equipment_no: 'EQ-01',
            equipment_name: '叉车',
            category: '定期检验',
            next_inspected_at: '2026-11-01T00:00:00',
            result: '合格',
            report_file: ['检验报告.pdf'],
          },
        ],
      },
      errors: [],
    } as DomainPageData)
    renderWithQuery(<DomainLedgerPage domain="facilities" />)

    expect(await screen.findByText('检验校验记录')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '下次检验日期' })).toBeInTheDocument()
    const row = screen.getByRole('row', { name: /定期检验/ })
    expect(within(row).getByText('合格')).toBeInTheDocument()
    // 主台账与检验记录是同设备的两行（设备台账 e1 + 检验记录 i1）→ 两表齐渲染
    expect(screen.getAllByRole('row', { name: /EQ-01/ })).toHaveLength(2)
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

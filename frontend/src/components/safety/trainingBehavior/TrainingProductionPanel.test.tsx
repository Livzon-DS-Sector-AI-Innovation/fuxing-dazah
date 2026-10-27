/**
 * TrainingProductionPanel（#7 S6 培训生产链前端接入）三区块交互测试。
 *
 * 替身口径：仓库惯例=vi.mock API 模块（msw 未安装，见 .scratch/3x-ai-suggest/spec.md
 * 摸底偏差）。覆盖：草案生成 confirm 门/采纳写台账 toast/驳回灰显、
 * 产物清单兜底展示、解析 confidence 分级展示与 mid/low 人工核对提示。
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TrainingProductionPanel } from './TrainingProductionPanel'
import { renderWithQuery } from '@/test/utils'

const DRAFTS = [
  {
    id: 'd1', year: 2027, position: '新员工',
    topic: '危化品单位新员工岗前三级教育', suggested_hours: 72,
    form: '线下', audience: '本年度新入职员工', basis: '输入显示未安排岗前三级教育',
    is_statutory_gap: true, status: 'draft' as const, status_label: '待处理',
    adopted_record_id: null, created_at: '2026-10-26T10:00:00',
  },
  {
    id: 'd2', year: 2027, position: '电工、焊工',
    topic: '特种作业复审培训', suggested_hours: 4, form: '实操',
    audience: '电工与焊工持证人员', basis: '违章档案', is_statutory_gap: false,
    status: 'adopted' as const, status_label: '已采纳',
    adopted_record_id: 'rec88', created_at: '2026-10-26T10:00:00',
  },
]

const LEDGER_ROWS = {
  status: 'live',
  stats: {},
  ledger: {
    data: [
      { record_id: 'r1', name: 'GMP 基础培训', status: '未开始' },
      { record_id: 'r2', name: '消防演练', status: '已完成' },
    ],
    meta: { total: 2, page: 1, page_size: 500 },
  },
  secondary_ledger: null,
  errors: [],
}

const MATERIALS = {
  record_id: 'r1',
  topic: 'GMP 基础培训',
  attachments: [
    { name: 'GMP 基础培训-讲义要点卡-2026-10-26.docx', file_token: 't1', material_type: 'lecture' },
    { name: 'GMP 基础培训-考核试卷-2026-10-26.docx', file_token: 't2', material_type: 'exam' },
    { name: '签到表.jpg', file_token: 't3', material_type: null },
  ],
  generations: [
    { material_type: 'lecture' as const, generated_at: '2026-10-26' },
    { material_type: 'exam' as const, generated_at: '2026-10-26' },
  ],
}

const PARSE_RESULT = {
  record_id: 'r1',
  parse: {
    doc_type: '签到表',
    attendance_count: 18,
    names: ['张三', '李四'],
    passed_count: null,
    scores: [{ name: '王五', score: '92' }],
    confidence: 'medium' as const,
    notes: '两处签名辨认不清',
    unrecognized: ['赵六'],
  },
  writeback_keys: ['备注'],
}

vi.mock('@/lib/api/safety/training-production', () => ({
  generateTrainingDemand: vi.fn(async () => ({
    year: 2027, summary: 'ok', count: 2, replaced: 0,
    statutory_notes: [], sources: { disconnected: 0 },
  })),
  fetchTrainingDemandDrafts: vi.fn(async () => DRAFTS),
  adoptTrainingDemandDraft: vi.fn(async () => ({
    draft_id: 'd1', adopted_record_id: 'rec99', fields: {},
  })),
  rejectTrainingDemandDraft: vi.fn(async () => ({
    draft_id: 'd1', status: 'rejected', status_label: '已驳回',
  })),
  generateTrainingMaterial: vi.fn(async () => ({
    record_id: 'r1', material_type: 'both',
    materials: [
      { material_type: 'lecture' as const, file_name: '讲义.docx', file_token: 'x', generated_at: '2026-10-27' },
    ],
  })),
  fetchTrainingMaterials: vi.fn(async () => MATERIALS),
  parseTrainingRecord: vi.fn(async () => PARSE_RESULT),
}))

vi.mock('@/lib/api/safety/domain-pages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/safety/domain-pages')>()),
  fetchDomainPage: vi.fn(async () => LEDGER_ROWS),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TrainingProductionPanel', () => {
  it('区块1：草案表渲染+已处理行灰显+采纳走 confirm 并 toast 台账行号', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TrainingProductionPanel />)
    expect(await screen.findByText('危化品单位新员工岗前三级教育')).toBeInTheDocument()
    // 已采纳行操作禁用（灰显）
    const adoptedRow = screen.getByText('特种作业复审培训').closest('tr')!
    expect(adoptedRow.querySelectorAll('button:disabled').length).toBe(2)

    // 采纳 d1：confirm 弹窗 → 确认（antd 两字按钮自动插空格：采 纳；
    // 精确文本避开区块描述段里的「采纳」字样）
    await user.click(screen.getAllByText('采 纳')[0].closest('button')!)
    expect(
      await screen.findByText('将写入培训台账计划行（状态=未开始），生成记录回填到草案行。'),
    ).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: '采 纳' }).at(-1)!)
    await waitFor(() =>
      expect(screen.getByText(/已采纳并写入培训台账（行 rec99）/)).toBeInTheDocument(),
    )
  })

  it('区块1：生成草案走 confirm 门（同年重跑替换提示）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TrainingProductionPanel />)
    await screen.findByText('危化品单位新员工岗前三级教育')
    await user.click(screen.getByRole('button', { name: '生成草案' }))
    // 弹窗独有文案（描述段亦有「同年重跑」字样，勿用）
    expect(await screen.findByText(/AI\+五源取数约 10-30 秒/)).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: '生 成' }).at(-1)!)
    await waitFor(() =>
      expect(screen.getByText(/生成完成：2 条草案/)).toBeInTheDocument(),
    )
  })

  it('区块2：选培训行出产物清单（附件名+类型+生成日期兜底展示）', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TrainingProductionPanel />)
    await screen.findByText('课件与试卷生成')
    // 默认只列未开始/进行中 → r1 可选（jsdom 惯用 mousedown 打开下拉）
    const selectBox = screen.getByTestId('material-row-select').querySelector('.ant-select')
    fireEvent.mouseDown(within(selectBox as HTMLElement).getByRole('combobox'))
    const option = await screen.findByText('GMP 基础培训（未开始）', {
      selector: '.ant-select-item-option-content',
    })
    await user.click(option)
    expect(await screen.findByText(/讲义要点卡-2026-10-26/)).toBeInTheDocument()
    expect(screen.getByText(/考核试卷-2026-10-26/)).toBeInTheDocument()
    expect(screen.getByText('签到表.jpg')).toBeInTheDocument()
    expect(screen.getByText(/附件已挂培训台账「课件与试卷」列/)).toBeInTheDocument()
  })

  it('区块3：解析结果 medium 分级展示+人工核对提示+分数明细', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TrainingProductionPanel />)
    await screen.findByText('签到成绩解析')
    const selectBox = screen.getByTestId('parse-row-select').querySelector('.ant-select')
    fireEvent.mouseDown(within(selectBox as HTMLElement).getByRole('combobox'))
    await user.click(
      await screen.findByText('GMP 基础培训（未开始）', {
        selector: '.ant-select-item-option-content',
      }),
    )
    await user.click(screen.getByRole('button', { name: /解\s*析/ }))
    const result = await screen.findByTestId('parse-result')
    expect(result.textContent).toContain('签到表')
    expect(result.textContent).toContain('实到 18 人')
    expect(result.textContent).toContain('仅备注（未回填数字列）')
    expect(result.textContent).toContain('张三')
    expect(result.textContent).toContain('王五：92')
    expect(screen.getByText(/medium\/low 置信度未回填数字列/)).toBeInTheDocument()
  })
})

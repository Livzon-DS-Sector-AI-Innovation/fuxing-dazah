/**
 * 隐患台账三列口径测试（P0-B / B6 接缝 S8）：
 * 三列统一 effective_*（人工优先 + AI fallback）展示、AI建议徽标、mismatch 提示、
 * 筛选请求参数保持旧契约、客户端排序按 effective 值。
 * 接缝：mock `@/lib/api/safety/hazard`（照 SafetyOverviewDashboard.test 手法）。
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HazardLedgerPage from './HazardLedgerPage'
import { renderWithQuery } from '@/test/utils'
import {
  HazardCategory,
  HazardLevel,
  HazardType,
  type HazardReport,
} from '@/types/safety'

const fetchHazardsMock = vi.hoisted(() => vi.fn())
const fetchHazardStatsMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/safety/hazard', () => ({
  fetchHazards: fetchHazardsMock,
  fetchHazardStats: fetchHazardStatsMock,
}))

const STATS = {
  total: 0,
  pending_review: 0,
  pending: 0,
  in_progress: 0,
  replied: 0,
  verifying: 0,
  rejected: 0,
  closed: 0,
  overdue: 0,
}

/** 构造一条 HazardReport（只贡献测试关心的字段，其余补最小占位）。 */
function makeHazard(
  overrides: Partial<HazardReport> & { id: string; hazard_no: string },
): HazardReport {
  return {
    hazard_type: HazardType.UNSAFE_CONDITION,
    hazard_level: HazardLevel.GENERAL,
    hazard_category: HazardCategory.EQUIPMENT,
    description: '测试隐患描述',
    discovered_at: '2026-11-01T02:00:00+00:00',
    rectification_status: 'pending',
    verify_level_1_status: 'pending',
    verify_level_2_status: 'pending',
    verify_level_3_status: 'pending',
    status: 'open',
    ai_node_progress: '',
    overall_status: '',
    ai_generated: false,
    script1_review_status: 'pending',
    script2_review_status: 'pending',
    ai_review_status: 'pending',
    created_at: '2026-11-01T02:00:00+00:00',
    updated_at: '2026-11-01T02:00:00+00:00',
    ...overrides,
  } as HazardReport
}

function mockList(items: HazardReport[], total = items.length) {
  fetchHazardsMock.mockResolvedValue({ items, total, page: 1, page_size: 20 })
}

/** 表格当前行序（按隐患编号提取，用于排序断言）。 */
function hazardNoOrder(): string[] {
  return screen
    .getAllByRole('row')
    .map((row) => row.textContent?.match(/HZ-[A-Za-z0-9-]*[A-Za-z0-9]/)?.[0])
    .filter((v): v is string => Boolean(v))
}

/** 打开「筛选」Popover（antd 渲染到 body portal）。 */
async function openFilterPopover() {
  const user = userEvent.setup()
  // 工具栏筛选按钮文案恰好为「筛选」（统计卡按钮名称含「点击按状态筛选」，图标 aria-label 会加入名称）
  const filterButton = screen
    .getAllByRole('button')
    .find((btn) => btn.textContent?.trim() === '筛选')
  if (!filterButton) throw new Error('未找到工具栏「筛选」按钮')
  await user.click(filterButton)
  return waitFor(() => {
    const el = document.querySelector('.ant-popover')
    expect(el).not.toBeNull()
    return el as HTMLElement
  })
}

/** 点击可排序表头（点击目标为 th 内的标题 span，其 onClick 才绑定排序）。 */
async function clickSortHeader(label: RegExp, user: ReturnType<typeof userEvent.setup>) {
  const th = screen.getByRole('columnheader', { name: label })
  await user.click(within(th).getByText(label))
}

beforeEach(() => {
  vi.clearAllMocks()
  fetchHazardStatsMock.mockResolvedValue({ ...STATS })
})

describe('HazardLedgerPage 三列字段口径（P0-B / B6）', () => {
  it('三列按 effective_* 展示：人工值优先于 AI 原始值，且不标 AI建议', async () => {
    mockList([
      makeHazard({
        id: 'h1',
        hazard_no: 'HJ-001',
        // AI 原始值（不应成为展示权威）
        hazard_level: HazardLevel.GENERAL,
        hazard_type: HazardType.UNSAFE_CONDITION,
        hazard_category: HazardCategory.EQUIPMENT,
        // effective_*（人工优先）
        effective_level: HazardLevel.SERIOUS,
        effective_level_source: 'human',
        effective_level_mismatch: false,
        effective_type: HazardType.MANAGEMENT_DEFECT,
        effective_type_source: 'human',
        effective_type_mismatch: false,
        effective_category: HazardCategory.SIX_S,
        effective_category_source: 'human',
        effective_category_mismatch: false,
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)

    const row = await screen.findByRole(
      'row',
      { name: /HJ-001/ },
      { timeout: 5000 },
    )
    expect(within(row).getByText('较大隐患')).toBeInTheDocument()
    expect(within(row).queryByText('一般隐患')).not.toBeInTheDocument()
    expect(within(row).getByText('管理的缺陷')).toBeInTheDocument()
    expect(within(row).queryByText('物的不安全状态')).not.toBeInTheDocument()
    expect(within(row).getByText('6S')).toBeInTheDocument()
    expect(within(row).queryByText('设备设施')).not.toBeInTheDocument()
    // source=human：无 AI建议徽标、无 mismatch 提示
    expect(within(row).queryByText('AI建议')).not.toBeInTheDocument()
    expect(within(row).queryByText(/与人工不一致/)).not.toBeInTheDocument()
  })

  it('source=ai（人工为空回退 AI）时值旁显示「AI建议」徽标', async () => {
    mockList([
      makeHazard({
        id: 'h1',
        hazard_no: 'HJ-002',
        hazard_level: HazardLevel.MAJOR,
        effective_level: HazardLevel.MAJOR,
        effective_level_source: 'ai',
        hazard_type: HazardType.ENVIRONMENTAL,
        effective_type: HazardType.ENVIRONMENTAL,
        effective_type_source: 'ai',
        hazard_category: HazardCategory.OCCUPATIONAL_HEALTH,
        effective_category: HazardCategory.OCCUPATIONAL_HEALTH,
        effective_category_source: 'ai',
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)

    const row = await screen.findByRole(
      'row',
      { name: /HJ-002/ },
      { timeout: 5000 },
    )
    expect(within(row).getByText('重大隐患')).toBeInTheDocument()
    expect(within(row).getByText('环境的不安全因素')).toBeInTheDocument()
    expect(within(row).getByText('职业健康+劳保防护')).toBeInTheDocument()
    // 三列各一个「AI建议」徽标
    expect(within(row).getAllByText('AI建议')).toHaveLength(3)
    expect(within(row).getByTestId('effective-cell-hazard_level')).toHaveTextContent(
      '重大隐患',
    )
  })

  it('mismatch 时 hover Tooltip 展示「AI建议：{AI 值标签}（与人工不一致）」', async () => {
    mockList([
      makeHazard({
        id: 'h1',
        hazard_no: 'HJ-003',
        // 人工权威值 serious，AI 原始建议 major → 不一致
        hazard_level: HazardLevel.MAJOR,
        effective_level: HazardLevel.SERIOUS,
        effective_level_source: 'human',
        effective_level_mismatch: true,
        hazard_type: HazardType.UNSAFE_CONDITION,
        effective_type: HazardType.UNSAFE_CONDITION,
        effective_type_source: 'human',
        effective_type_mismatch: false,
        hazard_category: HazardCategory.EQUIPMENT,
        effective_category: HazardCategory.EQUIPMENT,
        effective_category_source: 'human',
        effective_category_mismatch: false,
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)

    const row = await screen.findByRole(
      'row',
      { name: /HJ-003/ },
      { timeout: 5000 },
    )
    expect(within(row).getByText('较大隐患')).toBeInTheDocument()
    // 不一致列不显示 fallback 徽标（仅 hover 提示）
    expect(within(row).queryByText('AI建议')).not.toBeInTheDocument()
    // mismatch 标记 + hover 后 antd Tooltip 弹出 AI 原始值（中文 label）
    const cell = within(row).getByTestId('effective-cell-hazard_level')
    expect(cell).toHaveAttribute('data-mismatch', 'true')
    const user = userEvent.setup()
    await user.hover(cell)
    expect(await screen.findByRole('tooltip', {}, { timeout: 5000 })).toHaveTextContent(
      'AI建议：重大隐患（与人工不一致）',
    )
  })

  it('source=human 且枚举无法归一（effective 为空）→ 不回退 AI 值', async () => {
    mockList([
      makeHazard({
        id: 'h1',
        hazard_no: 'HJ-007',
        hazard_type: HazardType.UNSAFE_ACTION,
        hazard_category: HazardCategory.LABEL_SIGNAGE,
        effective_type: null,
        effective_type_source: 'human',
        effective_type_mismatch: false,
        effective_category: null,
        effective_category_source: 'human',
        effective_category_mismatch: false,
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)

    const row = await screen.findByRole('row', { name: /HJ-007/ }, { timeout: 5000 })
    // 人工权威但无法归一：两列显示 "-"，绝不显示 AI 原始值
    expect(within(row).queryByText('人的不安全行为')).not.toBeInTheDocument()
    expect(within(row).queryByText('标签标识')).not.toBeInTheDocument()
    // 空值单元格渲染 "-"（无 effective 值时不挂来源/差异提示）
    expect(within(row).getAllByText('-').length).toBeGreaterThanOrEqual(2)
  })

  it('mirror 模式（effective_* 全 null）回退旧口径：人工等级/原字段类型类别', async () => {
    mockList([
      makeHazard({
        id: 'h1',
        hazard_no: 'HJ-004',
        // 旧口径：等级 = hazard_level_manual || hazard_level（中文人工值需归一）
        hazard_level_manual: '较大隐患',
        hazard_level: HazardLevel.GENERAL,
        hazard_type: HazardType.UNSAFE_ACTION,
        hazard_category: HazardCategory.LABEL_SIGNAGE,
        // effective_* 缺省 = mirror 模式
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)

    const row = await screen.findByRole(
      'row',
      { name: /HJ-004/ },
      { timeout: 5000 },
    )
    expect(within(row).getByText('较大隐患')).toBeInTheDocument()
    expect(within(row).queryByText('一般隐患')).not.toBeInTheDocument()
    expect(within(row).getByText('人的不安全行为')).toBeInTheDocument()
    expect(within(row).getByText('标签标识')).toBeInTheDocument()
    // mirror 模式无来源信息：不标 AI建议、无 mismatch 提示
    expect(within(row).queryByText('AI建议')).not.toBeInTheDocument()
    expect(within(row).queryByText(/与人工不一致/)).not.toBeInTheDocument()
  })

  it('筛选点击后请求参数名保持 hazard_level/hazard_type/hazard_category 不变', async () => {
    mockList([makeHazard({ id: 'h1', hazard_no: 'HJ-005' })])
    renderWithQuery(<HazardLedgerPage />)
    await screen.findByRole('row', { name: /HJ-005/ }, { timeout: 5000 })

    const user = userEvent.setup()

    // 等级筛选
    let popover = await openFilterPopover()
    await user.click(within(popover).getByText('隐患等级'))
    await user.click(await within(popover).findByText('较大隐患'))
    await waitFor(() => {
      expect(fetchHazardsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ hazard_level: 'serious', page: 1, page_size: 20 }),
      )
    })

    // 类型筛选（叠加）
    popover = await openFilterPopover()
    await user.click(within(popover).getByText('隐患类型'))
    await user.click(await within(popover).findByText('人的不安全行为'))
    await waitFor(() => {
      expect(fetchHazardsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          hazard_level: 'serious',
          hazard_type: 'unsafe_action',
        }),
      )
    })

    // 类别筛选（叠加）
    popover = await openFilterPopover()
    await user.click(within(popover).getByText('隐患类别'))
    await user.click(await within(popover).findByText('危化储存'))
    await waitFor(() => {
      expect(fetchHazardsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          hazard_level: 'serious',
          hazard_type: 'unsafe_action',
          hazard_category: 'hazardous_storage',
        }),
      )
    })
    // 不得把前端新口径（effective_*）泄漏为请求参数
    const lastParams = fetchHazardsMock.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(lastParams).not.toHaveProperty('effective_level')
    expect(lastParams).not.toHaveProperty('effective_type')
    expect(lastParams).not.toHaveProperty('effective_category')
  })

  it('客户端排序按 effective 值（而非 AI 原始值），asc/desc 行为不变', async () => {
    mockList([
      // A：effective=serious（人工），AI 原始=general → 按旧 AI 值排序会排在前面
      makeHazard({
        id: 'a',
        hazard_no: 'HZ-A',
        hazard_level: HazardLevel.GENERAL,
        effective_level: HazardLevel.SERIOUS,
        effective_level_source: 'human',
      }),
      // B：effective=general（人工），AI 原始=major
      makeHazard({
        id: 'b',
        hazard_no: 'HZ-B',
        hazard_level: HazardLevel.MAJOR,
        effective_level: HazardLevel.GENERAL,
        effective_level_source: 'human',
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)
    await screen.findByRole('row', { name: /HZ-A/ }, { timeout: 5000 })

    // 默认 = API 返回顺序
    expect(hazardNoOrder()).toEqual(['HZ-A', 'HZ-B'])

    const user = userEvent.setup()
    // 升序：general < serious → B 在前（若按 AI 原始值则是 A(general) 在前）
    await clickSortHeader(/隐患等级/, user)
    await waitFor(() => expect(hazardNoOrder()).toEqual(['HZ-B', 'HZ-A']))

    // 降序：恢复 A 在前
    await clickSortHeader(/隐患等级/, user)
    await waitFor(() => expect(hazardNoOrder()).toEqual(['HZ-A', 'HZ-B']))
  })
})

// ═══════════════════════════════════════════════════════════════
// P1-2/D3：行点击差异详情 Drawer（三维 diff + 以人工为准 + AI/人工对照）
// ═══════════════════════════════════════════════════════════════

describe('HazardLedgerPage 差异详情 Drawer（P1-2 / D3）', () => {
  it('行点击打开 Drawer：以人工为准标注 + 三维 diff（不一致/一致/AI建议）', async () => {
    mockList([
      makeHazard({
        id: 'recD3',
        hazard_no: 'HZ-D3-1',
        hazard_level_manual: '较大隐患',
        hazard_type_manual: '管理的缺陷',
        description: '人工描述原文-D3',
        key_defect: 'AI 关键缺陷-D3',
        major_hazard_basis: '《某法规》第1条：原文-D3',
        corrective_preventive_measures: 'AI 整改建议-D3',
        rectification_reply: '人工纠正措施-D3',
        effective_level: HazardLevel.SERIOUS,
        effective_level_source: 'human',
        effective_level_mismatch: true,
        effective_type: HazardType.MANAGEMENT_DEFECT,
        effective_type_source: 'human',
        effective_type_mismatch: false,
        effective_category: HazardCategory.EQUIPMENT,
        effective_category_source: 'ai',
        effective_category_mismatch: false,
        ai_vs_manual: {
          level: {
            manual_raw: '较大隐患',
            ai_raw: '一般隐患',
            effective: 'serious',
            source: 'human',
            mismatch: true,
          },
          type: {
            manual_raw: '管理的缺陷',
            ai_raw: '管理的缺陷',
            effective: 'management_defect',
            source: 'human',
            mismatch: false,
          },
          category: {
            manual_raw: null,
            ai_raw: '设备设施',
            effective: 'equipment',
            source: 'ai',
            mismatch: false,
          },
        },
      }),
    ])
    renderWithQuery(<HazardLedgerPage />)
    await screen.findByText('HZ-D3-1')
    await userEvent.click(screen.getByText('HZ-D3-1'))

    // 固定标注 + Drawer 标题
    expect(await screen.findByText('以人工为准')).toBeTruthy()
    expect(screen.getByText(/AI 识别结果仅为候选证据/)).toBeTruthy()

    // 三维 diff 行：等级不一致 / 分类一致 / 类别 AI 建议（人工未填）
    const levelRow = screen.getByTestId('diff-row-hazard_level')
    expect(levelRow.textContent).toContain('较大隐患')
    expect(levelRow.textContent).toContain('一般隐患')
    expect(screen.getByTestId('diff-mismatch-hazard_level').textContent).toContain('不一致')
    expect(screen.getByTestId('diff-row-hazard_type').textContent).toContain('一致')
    const catRow = screen.getByTestId('diff-row-hazard_category')
    expect(catRow.textContent).toContain('未填')
    expect(catRow.textContent).toContain('设备设施')

    // AI / 人工对照区（Drawer 独有文案）
    expect(screen.getByText(/AI 关键缺陷-D3/)).toBeTruthy()
    expect(screen.getByText(/《某法规》第1条：原文-D3/)).toBeTruthy()
    expect(screen.getByText(/AI 整改建议-D3/)).toBeTruthy()
    // 描述同时出现在表格列与 Drawer → 多命中取全部
    expect(screen.getAllByText(/人工描述原文-D3/).length).toBeGreaterThan(0)
    expect(screen.getByText(/人工纠正措施-D3/)).toBeTruthy()
  })

  it('无 ai_vs_manual（mirror 回退）时 Drawer 仍可打开并显示对照区，不显示 diff 区', async () => {
    mockList([
      makeHazard({ id: 'recD4', hazard_no: 'HZ-D4-1', description: '镜像描述-D4' }),
    ])
    renderWithQuery(<HazardLedgerPage />)
    await screen.findByText('HZ-D4-1')
    await userEvent.click(screen.getByText('HZ-D4-1'))
    // Drawer 独有锚点（区分表格内同文本）：对照区标题
    expect(await screen.findByText('人工结论（权威）')).toBeTruthy()
    expect(screen.queryByTestId('diff-row-hazard_level')).toBeNull()
  })
})

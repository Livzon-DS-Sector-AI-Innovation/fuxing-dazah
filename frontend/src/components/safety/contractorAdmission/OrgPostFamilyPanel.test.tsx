/**
 * OrgPostFamilyPanel（#4 岗位族归类）交互测试。
 *
 * 替身口径=仓库惯例 vi.mock API 模块。覆盖：族聚合 chips 渲染、确认清单
 * Modal（ai 工作集+九族 Select）、未改族确认走 confirm API、改族后确认走
 * 修正 API（manual）。
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OrgPostFamilyPanel, POST_FAMILIES } from './OrgPostFamilyPanel'
import { renderWithQuery } from '@/test/utils'

const DICT = {
  status: 'live',
  fetched_at: '2026-10-27T10:00:00',
  message: null,
  posts: [
    { post_name: '1#冻干线冻干出料操作工', dept_names: ['精制工程一部'], headcount: 6 },
    { post_name: 'QC化验员', dept_names: ['质量管理部'], headcount: 4 },
    { post_name: '新岗', dept_names: ['其他'], headcount: 2 },
  ],
  families: [
    { family: '危化工艺操作', headcount: 6 },
    { family: '质检与实验', headcount: 4 },
    { family: '未归类', headcount: 2 },
  ],
}

const AI_ROWS = [
  {
    id: 'f1', post_name: '1#冻干线冻干出料操作工', family: '危化工艺操作',
    confidence: 'high' as const, note: '冻干出料为工艺操作',
    source: 'ai' as const, updated_at: null,
  },
  {
    id: 'f2', post_name: '机修电工', family: '特种作业相关',
    confidence: 'mid' as const, note: '电工持特种证',
    source: 'ai' as const, updated_at: null,
  },
]

vi.mock('@/lib/api/safety/contractor-workers', () => ({
  fetchOrgPostsFamilies: vi.fn(async () => DICT),
  fetchOrgPostFamilies: vi.fn(async () => AI_ROWS),
  classifyOrgPosts: vi.fn(async () => ({
    posts_total: 300, candidates: 300, batches: 10, classified: 300,
    inserted: 300, updated: 0, manual_kept: 0,
    by_family: { 危化工艺操作: 120, 质检与实验: 40 },
  })),
  confirmOrgPostFamily: vi.fn(async () => ({ ...AI_ROWS[0], source: 'manual' as const })),
  updateOrgPostFamily: vi.fn(async () => ({
    ...AI_ROWS[1], source: 'manual' as const, family: '设备维护',
  })),
}))

const confirmMock = vi.fn()
const updateMock = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
})

describe('OrgPostFamilyPanel', () => {
  it('族聚合 chips 渲染（含未归类）', async () => {
    renderWithQuery(<OrgPostFamilyPanel />)
    const agg = await screen.findByTestId('family-aggregation')
    expect(agg.textContent).toContain('危化工艺操作 6')
    expect(agg.textContent).toContain('未归类 2')
  })

  it('确认清单：未改族→confirm；改族后→修正 API（manual）', async () => {
    const user = userEvent.setup()
    const api = await import('@/lib/api/safety/contractor-workers')
    const confirmFn = vi.mocked(api.confirmOrgPostFamily)
    const updateFn = vi.mocked(api.updateOrgPostFamily)
    renderWithQuery(<OrgPostFamilyPanel />)
    await screen.findByTestId('family-aggregation')
    await user.click(screen.getByRole('button', { name: /确认清单/ }))

    // 工作集渲染 + 判断依据
    expect(await screen.findByText('1#冻干线冻干出料操作工')).toBeInTheDocument()
    expect(screen.getByText('冻干出料为工艺操作')).toBeInTheDocument()

    // ① 未改族：确认第一条（操作列按钮；带 icon 时 antd 不自动插空格，用正则兼容）
    const rowConfirm = screen.getAllByRole('button', { name: /确\s*认/ })
    await user.click(rowConfirm.find(b => b.closest('tr') !== null)!)
    await waitFor(() => expect(confirmFn).toHaveBeenCalledWith('f1'))
    expect(updateFn).not.toHaveBeenCalled()

    // ② 改族后确认：机修电工 行内 Select 改「设备维护」→确认
    const rows = screen.getAllByText('机修电工')
    const row = rows[0].closest('tr')!
    const familySelect = within(row).getByText('特种作业相关').closest('.ant-select')
    fireEvent.mouseDown(within(familySelect as HTMLElement).getByRole('combobox'))
    await user.click(
      await screen.findByText('设备维护', { selector: '.ant-select-item-option-content' }),
    )
    await user.click(
      within(row).getAllByRole('button', { name: /确\s*认/ })[0],
    )
    await waitFor(() => expect(updateFn).toHaveBeenCalledWith('f2', '设备维护'))
    expect(POST_FAMILIES).toHaveLength(9)
  })
})

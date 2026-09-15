import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TodayBoard } from './TodayBoard'
import { renderWithQuery } from '@/test/utils'
import type { MovementPlanRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/api/warehouse')>()
  return {
    ...actual,
    fetchPlansClient: vi.fn(),
    fetchLocationsClient: vi.fn().mockResolvedValue([]),
    fetchMaterialsClient: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 }),
  }
})
vi.mock('@/actions/warehouse', () => ({
  createMovementPlan: vi.fn(),
  startMovementPlan: vi.fn(),
  cancelMovementPlan: vi.fn(),
  generatePlanMovementAction: vi.fn(),
}))

import { generatePlanMovementAction } from '@/actions/warehouse'

const mockedGenerate = vi.mocked(generatePlanMovementAction)

import { fetchPlansClient } from '@/lib/api/warehouse'

const mockedPlans = vi.mocked(fetchPlansClient)

const plan = (over: Partial<MovementPlanRecord>): MovementPlanRecord => ({
  id: over.id ?? 'p1',
  plan_no: over.plan_no ?? 'IP-20260915-001',
  direction: over.direction ?? 'inbound',
  source_type: over.source_type ?? 'purchase',
  material_id: 'm1',
  material_code: 'MAT-001',
  material_name: over.material_name ?? '甲醇',
  batch_no: 'B1',
  quantity: over.quantity ?? 12,
  location_id: 'l1',
  location_code: 'L-A',
  location_name: 'A 库位',
  planned_date: '2026-09-15',
  status: over.status ?? 'planned',
  cancel_reason: null,
  movement_id: null,
  remark: null,
})

beforeEach(() => {
  vi.clearAllMocks()
  mockedGenerate.mockResolvedValue({
    plan: plan({ id: 'p2', status: 'completed', plan_no: 'OP-001', movement_id: 'mv1' }),
    movement: { id: 'mv1', movement_no: 'MV-GEN-001' } as never,
  })
  mockedPlans.mockImplementation((params: { status?: string } = {}) => {
    if (params.status === 'planned') {
      return Promise.resolve({
        items: [plan({ id: 'p1', status: 'planned', direction: 'inbound', plan_no: 'IP-001' })],
        total: 1,
        page: 1,
        page_size: 200,
      })
    }
    if (params.status === 'in_progress') {
      return Promise.resolve({
        items: [plan({ id: 'p2', status: 'in_progress', direction: 'outbound', plan_no: 'OP-001' })],
        total: 1,
        page: 1,
        page_size: 50,
      })
    }
    if (params.status === 'completed') {
      return Promise.resolve({
        items: [plan({ id: 'p3', status: 'completed', direction: 'inbound', plan_no: 'IP-000', movement_id: 'mv9' })],
        total: 1,
        page: 1,
        page_size: 20,
      })
    }
    return Promise.resolve({ items: [], total: 0, page: 1, page_size: 20 })
  })
})

describe('TodayBoard', () => {
  it('三列看板按状态与方向正确分组', async () => {
    renderWithQuery(<TodayBoard />)

    expect(await screen.findByText('今日待收（1）')).toBeInTheDocument()
    expect(await screen.findByText('今日待发（1）')).toBeInTheDocument()
    // plan_no 与来源拼接在同一文本节点，用包含匹配
    expect((await screen.findAllByText(/IP-001/)).length).toBeGreaterThan(0)
    expect(screen.getByText(/OP-001/)).toBeInTheDocument()
    expect(screen.getByText(/IP-000/)).toBeInTheDocument()
  })

  it('按状态渲染操作按钮', async () => {
    renderWithQuery(<TodayBoard />)

    expect(await screen.findByText('开始执行')).toBeInTheDocument()
    expect(screen.getByText('生成登记')).toBeInTheDocument()
    // antd Button 对两个汉字自动插空格（“取 消”），用宽容匹配
    expect(screen.getAllByText(/取\s*消/).length).toBeGreaterThanOrEqual(2)
  })

  it('生成登记弹窗预填数量并提交', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TodayBoard />)

    await user.click(await screen.findByText('生成登记'))
    await user.click(await screen.findByText(/生成登记：OP-001/))
    // 预填计划数量，可直接确认（测试环境 Modal 底部按钮为默认英文 OK）
    await user.click(screen.getByRole('button', { name: 'OK' }))
    const { generatePlanMovementAction } = await import('@/actions/warehouse')
    await waitFor(() =>
      expect(generatePlanMovementAction).toHaveBeenCalledWith('p2', {
        quantity: 12,
        remark: null,
      }),
    )
  })

  it('新建计划单弹窗可打开', async () => {
    const user = userEvent.setup()
    renderWithQuery(<TodayBoard />)

    await user.click(await screen.findByRole('button', { name: /新建计划单/ }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})

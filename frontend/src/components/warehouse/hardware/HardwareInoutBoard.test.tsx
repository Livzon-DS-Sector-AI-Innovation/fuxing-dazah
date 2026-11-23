import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HardwareInoutBoard } from './HardwareInoutBoard'
import { renderWithQuery } from '@/test/utils'

const receiptsMock = vi.hoisted(() => vi.fn())
const requisitionsMock = vi.hoisted(() => vi.fn())
const returnsMock = vi.hoisted(() => vi.fn())
const stockMock = vi.hoisted(() => vi.fn())
const summaryMock = vi.hoisted(() => vi.fn())
const currentUserMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/warehouse-hardware', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchHardwareReceiptsClient: receiptsMock,
  fetchHardwareRequisitionsClient: requisitionsMock,
  fetchHardwareReturnsClient: returnsMock,
  fetchHardwareStockClient: stockMock,
  fetchHardwareStockSummaryClient: summaryMock,
}))
vi.mock('@/actions/auth', () => ({
  getCurrentUser: currentUserMock,
}))

beforeEach(() => {
  vi.clearAllMocks()
  currentUserMock.mockResolvedValue(null)
  receiptsMock.mockResolvedValue({
    items: [
      {
        id: 'rc1',
        receipt_no: 'RK-20261120-001',
        source: 'manual',
        mode: 'stocked',
        supplier_name: '供应商A',
        status: 'draft',
        target_dept: null,
        created_at: '2026-11-20T09:00:00',
        items: [],
      },
    ],
    total: 3,
    page: 1,
    page_size: 20,
  })
  requisitionsMock.mockResolvedValue({ items: [], total: 7, page: 1, page_size: 20 })
  returnsMock.mockResolvedValue({ items: [], total: 1, page: 1, page_size: 20 })
  stockMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  summaryMock.mockResolvedValue({
    total_materials: 10,
    stocked_materials: 8,
    low_count: 0,
    on_hand_total: 100,
    reserved_total: 0,
    low_materials: [],
  })
})

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

describe('五金出入库工作台三段化', () => {
  it('渲染入库/出库/退料三段与统计卡，默认展示入库单列表', async () => {
    renderWithQuery(<HardwareInoutBoard />)

    expect(screen.getByText('入库')).toBeInTheDocument()
    expect(screen.getByText('出库')).toBeInTheDocument()
    expect(screen.getByText('退料')).toBeInTheDocument()
    expect(await screen.findByText('待确认入库')).toBeInTheDocument()
    expect(await screen.findByText('RK-20261120-001')).toBeInTheDocument()
    expect(await screen.findByText('待验收退料')).toBeInTheDocument()
    expect(await screen.findByText('待审批申请')).toBeInTheDocument()
  })

  it('点击「待发料」统计卡切换到出库段的申请单据视图', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareInoutBoard />)

    await user.click(await screen.findByText('待发料'))
    expect(await screen.findByText('领用申请单')).toBeInTheDocument()
    expect(screen.queryByText('RK-20261120-001')).not.toBeInTheDocument()
  })

  it('旧深链 ?tab=requisition 兜底到出库段', async () => {
    window.history.replaceState({}, '', '/warehouse/hardware/inout?tab=requisition')
    renderWithQuery(<HardwareInoutBoard />)

    expect(await screen.findByText('申领库存')).toBeInTheDocument()
    expect(screen.queryByText('RK-20261120-001')).not.toBeInTheDocument()
  })
})

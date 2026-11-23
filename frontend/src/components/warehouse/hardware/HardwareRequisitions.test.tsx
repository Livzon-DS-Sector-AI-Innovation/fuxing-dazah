import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HardwareRequisitions } from './HardwareRequisitions'
import { renderWithQuery } from '@/test/utils'
import type { HardwareRequisitionRecord } from '@/types/warehouse-hardware'

const requisitionsMock = vi.hoisted(() => vi.fn())
const stockMock = vi.hoisted(() => vi.fn())
const summaryMock = vi.hoisted(() => vi.fn())
const stockDetailMock = vi.hoisted(() => vi.fn())
const issueMock = vi.hoisted(() => vi.fn())
const approversMock = vi.hoisted(() => vi.fn())
const movementsMock = vi.hoisted(() => vi.fn())
const currentUserMock = vi.hoisted(() => vi.fn())
const hasPermissionMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/warehouse-hardware', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchHardwareRequisitionsClient: requisitionsMock,
  fetchHardwareStockClient: stockMock,
  fetchHardwareStockSummaryClient: summaryMock,
  fetchHardwareStockDetailClient: stockDetailMock,
  issueHardwareRequisitionClient: issueMock,
  fetchRequisitionApproversClient: approversMock,
  fetchHardwareMovementsClient: movementsMock,
}))
vi.mock('@/actions/auth', () => ({
  getCurrentUser: currentUserMock,
}))
vi.mock('@/hooks/usePermission', () => ({
  usePermission: () => ({ hasPermission: hasPermissionMock }),
}))

const approvedRow: HardwareRequisitionRecord = {
  id: 'r1',
  req_no: 'LL-20261120-001',
  dept_name: '发酵',
  applicant: '张三',
  purpose: '设备检修',
  req_type: 'normal',
  status: 'approved',
  created_at: '2026-11-20T09:00:00',
  items: [
    {
      id: 'i1',
      material_id: 'm1',
      material_name: '球阀 DN25',
      material_code: null,
      spec: 'DN25',
      unit: '个',
      need_qty: 2,
      issued_qty: null,
      fifo_lot_allocations: null,
    },
  ],
}

const urgentPendingRow: HardwareRequisitionRecord = {
  ...approvedRow,
  id: 'r2',
  req_no: 'LL-20261120-002',
  req_type: 'urgent',
  status: 'pending',
}

const normalPendingRow: HardwareRequisitionRecord = {
  ...approvedRow,
  id: 'r3',
  req_no: 'LL-20261120-003',
  req_type: 'normal',
  status: 'pending',
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUserMock.mockResolvedValue(null)
  hasPermissionMock.mockReturnValue(true)
  requisitionsMock.mockResolvedValue({
    items: [approvedRow, urgentPendingRow, normalPendingRow],
    total: 3,
    page: 1,
    page_size: 20,
  })
  stockMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  summaryMock.mockResolvedValue({
    total_materials: 10,
    stocked_materials: 8,
    low_count: 0,
    on_hand_total: 100,
    reserved_total: 0,
    low_materials: [],
  })
  stockDetailMock.mockResolvedValue({
    stock: { available: 10, on_hand: 10, reserved: 0, is_low: false, low_gap: 0, material: { id: 'm1', name: '球阀 DN25', unit: '个' } },
    lots: [
      {
        lot_id: 'l1',
        lot_no: 'LOT-A',
        receipt_no: 'RK-001',
        arrived_at: '2026-11-01',
        expiry_date: null,
        location_code: 'A-01',
        remaining_quantity: 10,
        quantity: 10,
      },
    ],
    recent_movements: [],
  })
  issueMock.mockResolvedValue({ ...approvedRow, status: 'issued' })
  approversMock.mockResolvedValue([])
  movementsMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
})

describe('五金出库段（领用申请 + 行内发料）', () => {
  it('默认落在申领库存子段，可切换到申请单据', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareRequisitions />)

    expect(screen.getByText('申领库存')).toBeInTheDocument()
    expect(screen.getByText('申请单据')).toBeInTheDocument()
    expect(screen.getByText('部门统计')).toBeInTheDocument()

    await user.click(screen.getByText('申请单据'))
    expect(await screen.findByText('LL-20261120-001')).toBeInTheDocument()
    expect(screen.getByText('LL-20261120-002')).toBeInTheDocument()
  })

  it('有发料权限时，审批通过与紧急待发单显示发料按钮，待审批常规单不显示', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareRequisitions />)
    await user.click(screen.getByText('申请单据'))

    expect(await screen.findByText('LL-20261120-001')).toBeInTheDocument()
    expect(screen.getAllByText(/^发\s*料$/)).toHaveLength(2)
  })

  it('无发料权限时不显示发料按钮', async () => {
    hasPermissionMock.mockImplementation((p: string) => p !== 'warehouse:hardware:requisition:issue')
    const user = userEvent.setup()
    renderWithQuery(<HardwareRequisitions />)
    await user.click(screen.getByText('申请单据'))

    expect(await screen.findByText('LL-20261120-001')).toBeInTheDocument()
    expect(screen.queryByText(/^发\s*料$/)).not.toBeInTheDocument()
  })

  it('发料弹窗确认后调用发料接口', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareRequisitions />)
    await user.click(screen.getByText('申请单据'))

    const issueButtons = await screen.findAllByText(/^发\s*料$/)
    await user.click(issueButtons[0])
    expect(screen.getByText('发料确认 · LL-20261120-001')).toBeInTheDocument()

    await user.click(screen.getByText(/^确认发料（实扣）$/))
    expect(issueMock).toHaveBeenCalledTimes(1)
    expect(issueMock.mock.calls[0][0]).toBe('r1')
  })

  it('focusStatus 指定时直接落在申请单据段并按状态筛选', async () => {
    renderWithQuery(<HardwareRequisitions focusStatus="approved" />)

    expect(await screen.findByText('领用申请单')).toBeInTheDocument()
    expect(await screen.findByText('LL-20261120-001')).toBeInTheDocument()
  })
})

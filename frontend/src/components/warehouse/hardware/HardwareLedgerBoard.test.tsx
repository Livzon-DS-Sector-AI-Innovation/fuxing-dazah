import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HardwareLedgerBoard } from './HardwareLedgerBoard'
import { renderWithQuery } from '@/test/utils'

const stocktakesMock = vi.hoisted(() => vi.fn())
const movementsMock = vi.hoisted(() => vi.fn())
const erpReceiptsMock = vi.hoisted(() => vi.fn())
const diffsMock = vi.hoisted(() => vi.fn())
const scrapsMock = vi.hoisted(() => vi.fn())
const approveScrapMock = vi.hoisted(() => vi.fn())
const hasPermissionMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/warehouse-hardware', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchHardwareStocktakesClient: stocktakesMock,
  fetchHardwareMovementsClient: movementsMock,
  fetchHardwareErpReceiptsClient: erpReceiptsMock,
  fetchHardwareReconcileDiffsClient: diffsMock,
  fetchHardwareScrapsClient: scrapsMock,
  approveHardwareScrapClient: approveScrapMock,
}))
vi.mock('@/hooks/usePermission', () => ({
  usePermission: () => ({ hasPermission: hasPermissionMock }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  stocktakesMock.mockResolvedValue({
    items: [
      {
        id: 'st1',
        take_no: 'PD-202611-001',
        take_type: 'monthly',
        status: 'draft',
        snapshot_at: null,
        summary_note: null,
        diff_surplus_items: null,
        diff_deficit_items: null,
        diff_total_amount: null,
        explained_by: null,
        explained_at: null,
        confirmed_by: null,
        confirmed_at: null,
        remark: null,
        created_at: '2026-11-20T08:00:00',
        items: [],
      },
    ],
    total: 1,
    page: 1,
    page_size: 20,
  })
  movementsMock.mockResolvedValue({
    items: [
      {
        id: 'mv1',
        movement_no: 'LS-20261120-001',
        direction: 'outbound',
        business_type: 'req_issue',
        material_name: '球阀 DN25',
        quantity: 2,
        unit: '个',
        dept_name: '发酵',
        operator: '仓管员',
        occurred_at: '2026-11-20T10:00:00',
        erp_status: 'pending',
      },
    ],
    total: 1,
    page: 1,
    page_size: 50,
  })
  erpReceiptsMock.mockResolvedValue({
    items: [
      {
        id: 'rc1',
        receipt_no: 'RK-20261120-001',
        erp_doc_no: 'ERP-9001',
        supplier_name: '供应商A',
        status: 'accepted',
        reconcile_status: 'matched',
        auto_accepted: false,
        created_at: '2026-11-20T09:00:00',
      },
    ],
    total: 1,
  })
  diffsMock.mockResolvedValue({ erp_only: [], ocr_only: [] })
  hasPermissionMock.mockReturnValue(true)
  approveScrapMock.mockResolvedValue({})
  scrapsMock.mockResolvedValue({
    items: [
      {
        id: 's1',
        scrap_no: 'WJK-BF-261125-001',
        dept_name: 'AI创新部',
        requested_by: '叶海斌',
        scrap_reason: 'damaged',
        reason_note: null,
        attachments: null,
        approver_user_id: 'xukangfu',
        approver_name: '许康福',
        approval_channel: 'manual',
        approval_instance_code: null,
        approval_status: 'pending',
        approved_by: null,
        approved_at: null,
        executed_by: null,
        rejected_by: null,
        rejected_reason: null,
        status: 'pending',
        scrapped_at: null,
        lot_allocations: null,
        remark: null,
        created_at: '2026-11-25T10:20:00',
        can_approve: true,
      },
    ],
    total: 1,
    page: 1,
    page_size: 50,
  })
})

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

describe('五金盘点台账五段', () => {
  it('渲染五段切换，默认展示盘点列表', async () => {
    renderWithQuery(<HardwareLedgerBoard />)

    expect(screen.getByText('盘点')).toBeInTheDocument()
    expect(screen.getByText('ERP 对账')).toBeInTheDocument()
    expect(screen.getByText('报废')).toBeInTheDocument()
    expect(screen.getByText('部门直发')).toBeInTheDocument()
    expect(screen.getByText('流水台账')).toBeInTheDocument()
    expect(await screen.findByText('PD-202611-001')).toBeInTheDocument()
  })

  it('点击「流水台账」渲染全量流水与批量标记入口', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareLedgerBoard />)

    await user.click(screen.getByText('流水台账'))
    expect(await screen.findByText('出入库流水台账')).toBeInTheDocument()
    expect(screen.getByText('LS-20261120-001')).toBeInTheDocument()
  })

  it('点击「ERP 对账」合并段同时渲染入库对账与出库侧标记', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareLedgerBoard />)

    await user.click(screen.getByText('ERP 对账'))
    expect(await screen.findByText('差异清单 · ERP 有 / 系统无')).toBeInTheDocument()
    expect(screen.getByText('差异清单 · 系统有 / ERP 无')).toBeInTheDocument()
    expect(screen.getByText('出库侧 ERP 标记')).toBeInTheDocument()
    expect(screen.getByText('RK-20261120-001')).toBeInTheDocument()
  })

  it('旧深链 ?tab=erp_in 兜底到合并的 ERP 对账段', async () => {
    window.history.replaceState({}, '', '/warehouse/hardware/ledger?tab=erp_in')
    renderWithQuery(<HardwareLedgerBoard />)

    expect(await screen.findByText('差异清单 · ERP 有 / 系统无')).toBeInTheDocument()
    expect(screen.queryByText('PD-202611-001')).not.toBeInTheDocument()
  })

  it('点击「报废」展示报废单：待审批单有审批资格时可在台账页直接点通过', async () => {
    const user = userEvent.setup()
    renderWithQuery(<HardwareLedgerBoard />)

    await user.click(screen.getByText('报废'))
    const row = (await screen.findByText('WJK-BF-261125-001')).closest('tr') as HTMLElement
    expect(screen.getByText('待审批')).toBeInTheDocument()

    // antd 会在两个汉字的按钮中间插空格（如「通 过」）
    await user.click(within(row).getByText(/^通\s*过$/))
    expect(approveScrapMock).toHaveBeenCalledTimes(1)
    expect(approveScrapMock.mock.calls[0][0]).toBe('s1')
  })
})

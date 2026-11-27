import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HardwareRequisitions } from './HardwareRequisitions'
import { renderWithQuery } from '@/test/utils'
import type {
  HardwareOutboundDocRow,
  HardwareRequisitionRecord,
  HardwareScrapRecord,
  HardwareStockRow,
} from '@/types/warehouse-hardware'

const docsMock = vi.hoisted(() => vi.fn())
const stockMock = vi.hoisted(() => vi.fn())
const summaryMock = vi.hoisted(() => vi.fn())
const stockDetailMock = vi.hoisted(() => vi.fn())
const issueMock = vi.hoisted(() => vi.fn())
const approversMock = vi.hoisted(() => vi.fn())
const scrapApproversMock = vi.hoisted(() => vi.fn())
const createScrapMock = vi.hoisted(() => vi.fn())
const submitScrapMock = vi.hoisted(() => vi.fn())
const approveScrapMock = vi.hoisted(() => vi.fn())
const executeScrapMock = vi.hoisted(() => vi.fn())
const scrapDetailMock = vi.hoisted(() => vi.fn())
const movementsMock = vi.hoisted(() => vi.fn())
const returnableMock = vi.hoisted(() => vi.fn())
const returnApproversMock = vi.hoisted(() => vi.fn())
const createReturnMock = vi.hoisted(() => vi.fn())
const currentUserMock = vi.hoisted(() => vi.fn())
const hasPermissionMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/warehouse-hardware', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchHardwareOutboundDocsClient: docsMock,
  fetchHardwareStockClient: stockMock,
  fetchHardwareStockSummaryClient: summaryMock,
  fetchHardwareStockDetailClient: stockDetailMock,
  issueHardwareRequisitionClient: issueMock,
  fetchRequisitionApproversClient: approversMock,
  fetchScrapApproversClient: scrapApproversMock,
  createHardwareScrapClient: createScrapMock,
  submitHardwareScrapClient: submitScrapMock,
  approveHardwareScrapClient: approveScrapMock,
  executeHardwareScrapClient: executeScrapMock,
  fetchHardwareScrapClient: scrapDetailMock,
  fetchHardwareMovementsClient: movementsMock,
  fetchReturnableQtyClient: returnableMock,
  fetchReturnApproversClient: returnApproversMock,
  createReturnFromRequisitionClient: createReturnMock,
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

const reqRow = (r: HardwareRequisitionRecord): HardwareOutboundDocRow => ({
  doc_kind: 'requisition',
  id: r.id,
  requisition: r,
  scrap: null,
})

const pendingScrap: HardwareScrapRecord = {
  id: 's1',
  scrap_no: 'WJK-BF-261125-001',
  dept_name: 'AI创新部',
  requested_by: '叶海斌',
  scrap_reason: 'damaged',
  reason_note: '外壳破裂',
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
  items: [
    {
      id: 'si1',
      material_id: 'm1',
      quantity: 1,
      preferred_lot_id: null,
      name: 'ABS三通',
      spec: null,
      unit: '个',
      unit_price: null,
    },
  ],
  can_approve: true,
}

const approvedScrap: HardwareScrapRecord = {
  ...pendingScrap,
  status: 'approved',
  approval_status: 'approved',
  approved_by: '许康福',
}

const scrapRow = (s: HardwareScrapRecord): HardwareOutboundDocRow => ({
  doc_kind: 'scrap',
  id: s.id,
  requisition: null,
  scrap: s,
})

// antd 会在两个汉字的按钮中间插空格（如「通 过」），按正则匹配
const twoChar = (s: string) => new RegExp(`^${s[0]}\\s*${s[1]}$`)
const paged = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 20 })

beforeEach(() => {
  vi.clearAllMocks()
  currentUserMock.mockResolvedValue(null)
  hasPermissionMock.mockReturnValue(true)
  docsMock.mockResolvedValue(paged([reqRow(approvedRow), reqRow(urgentPendingRow), reqRow(normalPendingRow)]))
  stockMock.mockResolvedValue(paged([]))
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
  scrapApproversMock.mockResolvedValue([])
  createScrapMock.mockResolvedValue({ ...pendingScrap, id: 's-new', status: 'draft' })
  submitScrapMock.mockResolvedValue({ ...pendingScrap, status: 'pending' })
  approveScrapMock.mockResolvedValue({ ...approvedScrap })
  executeScrapMock.mockResolvedValue({ ...approvedScrap, status: 'issued' })
  scrapDetailMock.mockResolvedValue(approvedScrap)
  movementsMock.mockResolvedValue(paged([]))
  returnableMock.mockResolvedValue({
    requisition_status: 'issued',
    items: [
      {
        material_id: 'm1',
        name: '球阀 DN25',
        spec: 'DN25',
        unit: '个',
        issued: 2,
        returned: 0,
        returnable: 2,
      },
    ],
  })
  returnApproversMock.mockResolvedValue([
    { user_id: 'xukangfu', name: '许康福', department: 'AI创新部', position: '安全主管', supervisor: true },
  ])
  createReturnMock.mockResolvedValue({ id: 'rt1', return_no: 'WJK-TK-1', status: 'pending' })
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

    // 页签名与卡片标题都是「申请单据」
    expect((await screen.findAllByText('申请单据')).length).toBeGreaterThanOrEqual(2)
    expect(await screen.findByText('LL-20261120-001')).toBeInTheDocument()
  })
})

describe('申请单据里的报废单（同申领出库路径）', () => {
  it('待审批的报废单与领料单同列表，有审批资格时显示通过/驳回，点通过调用报废审批接口', async () => {
    const user = userEvent.setup()
    docsMock.mockResolvedValue(paged([reqRow(approvedRow), scrapRow(pendingScrap)]))
    renderWithQuery(<HardwareRequisitions focusStatus="pending" />)

    const row = (await screen.findByText('WJK-BF-261125-001')).closest('tr') as HTMLElement
    expect(screen.getByText('LL-20261120-001')).toBeInTheDocument()
    expect(within(row).getByText('报废')).toBeInTheDocument()
    expect(within(row).getByText('待审批')).toBeInTheDocument()
    expect(within(row).getByText('许康福')).toBeInTheDocument()

    await user.click(within(row).getByText(twoChar('通过')))
    expect(approveScrapMock).toHaveBeenCalledTimes(1)
    expect(approveScrapMock.mock.calls[0][0]).toBe('s1')
  })

  it('无审批资格的待审批报废单不显示通过/驳回', async () => {
    hasPermissionMock.mockReturnValue(false)
    docsMock.mockResolvedValue(
      paged([scrapRow({ ...pendingScrap, can_approve: false })]),
    )
    renderWithQuery(<HardwareRequisitions focusStatus="pending" />)

    const row = (await screen.findByText('WJK-BF-261125-001')).closest('tr') as HTMLElement
    expect(within(row).queryByText(twoChar('通过'))).toBeNull()
    expect(within(row).queryByText(twoChar('驳回'))).toBeNull()
  })

  it('待发料页签里的待出库报废单显示「出库」，确认后调用出库接口', async () => {
    const user = userEvent.setup()
    docsMock.mockResolvedValue(paged([scrapRow(approvedScrap)]))
    renderWithQuery(<HardwareRequisitions focusStatus="approved" />)

    const row = (await screen.findByText('WJK-BF-261125-001')).closest('tr') as HTMLElement
    expect(within(row).getByText('待出库')).toBeInTheDocument()
    await user.click(within(row).getByText(twoChar('出库')))

    expect(await screen.findByText('出库确认 · WJK-BF-261125-001')).toBeInTheDocument()
    expect(await screen.findByText('ABS三通')).toBeInTheDocument()
    await user.click(screen.getByText(/^确认出库（实扣）$/))
    expect(executeScrapMock).toHaveBeenCalledTimes(1)
    expect(executeScrapMock.mock.calls[0][0]).toBe('s1')
  })

  it('报废出库弹窗确定后创建并立即提交（同申领），带上所选审批人', async () => {
    const user = userEvent.setup()
    currentUserMock.mockResolvedValue({ name: '叶海斌', department: 'AI创新部' })
    stockMock.mockResolvedValue(
      paged([
        {
          material: { id: 'm1', name: 'ABS三通', managed_class: 'stocked', category: '耗材' },
          name: 'ABS三通',
          category: '耗材',
          spec: null,
          unit: '个',
          available: 5,
          on_hand: 5,
          reserved: 0,
          is_low: false,
          low_gap: 0,
        } as unknown as HardwareStockRow,
      ]),
    )
    scrapApproversMock.mockResolvedValue([
      {
        user_id: 'xukangfu',
        name: '许康福',
        department: 'AI创新部',
        position: '安全主管',
        supervisor: true,
      },
    ])
    renderWithQuery(<HardwareRequisitions />)

    await user.click(await screen.findByText('报废出库'))
    expect(await screen.findByText('报废出库 · ABS三通')).toBeInTheDocument()

    // 选审批人
    const select = screen
      .getByText('搜索姓名 / 部门 / 职位选择审批人')
      .closest('.ant-select') as HTMLElement
    fireEvent.mouseDown(within(select).getByRole('combobox'))
    const option = await screen.findByText(/许康福/, { selector: '.ant-select-item-option-content' })
    await user.click(option)

    await user.click(screen.getByText('发起报废'))
    await user.click(await screen.findByText('确认发起'))

    expect(createScrapMock).toHaveBeenCalledTimes(1)
    expect(createScrapMock.mock.calls[0][0]).toMatchObject({
      dept_name: 'AI创新部',
      requested_by: '叶海斌',
      approver_user_id: 'xukangfu',
      approver_name: '许康福',
      scrap_reason: 'damaged',
      items: [{ material_id: 'm1', quantity: 1 }],
    })
    // 确定即提交：预扣生效的关键一步
    expect(submitScrapMock).toHaveBeenCalledWith('s-new')
  })
})

describe('已发料领料单的退料入口', () => {
  it('已发料行显示「退料」，弹窗预填额度与审批人，确认后创建并提交', async () => {
    const user = userEvent.setup()
    const issuedRow: HardwareRequisitionRecord = {
      ...approvedRow,
      id: 'r9',
      req_no: 'LL-20261126-001',
      status: 'issued',
      items: [
        {
          id: 'i9',
          material_id: 'm1',
          material_name: '球阀 DN25',
          material_code: null,
          spec: 'DN25',
          unit: '个',
          need_qty: 2,
          issued_qty: 2,
          fifo_lot_allocations: [{ lot_id: 'l1', lot_no: 'LOT-A', location_id: null, qty: 2 }],
        },
      ],
    }
    docsMock.mockResolvedValue(paged([reqRow(issuedRow)]))
    renderWithQuery(<HardwareRequisitions focusStatus="issued" />)

    const row = (await screen.findByText('LL-20261126-001')).closest('tr') as HTMLElement
    await user.click(within(row).getByText(/^退\s*料$/))
    expect(await screen.findByText('发起退料 · LL-20261126-001')).toBeInTheDocument()
    // 额度行：实发 2 / 可退 2，退料量默认取满
    expect(await screen.findByText('球阀 DN25')).toBeInTheDocument()
    const inputs = document.querySelectorAll('.ant-input-number-input')
    expect(inputs.length).toBeGreaterThan(0)
    expect(Number((inputs[0] as HTMLInputElement).value)).toBe(2)

    // 选审批人
    const select = screen
      .getByText('搜索姓名 / 部门 / 职位选择审批人')
      .closest('.ant-select') as HTMLElement
    fireEvent.mouseDown(within(select).getByRole('combobox'))
    const option = await screen.findByText(/许康福/, { selector: '.ant-select-item-option-content' })
    await user.click(option)

    await user.click(screen.getByText('提交退料'))
    await user.click(await screen.findByText('确认提交'))

    expect(createReturnMock).toHaveBeenCalledTimes(1)
    expect(createReturnMock.mock.calls[0][0]).toMatchObject({
      requisition_id: 'r9',
      approver_user_id: 'xukangfu',
      approver_name: '许康福',
      items: [{ material_id: 'm1', quantity: 2, preferred_lot_id: 'l1' }],
    })
  })
})

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StockTable } from './StockTable'
import { renderWithQuery } from '@/test/utils'
import type { LocationRecord, StockRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', () => ({
  fetchStocksClient: vi.fn(),
  fetchLocationsClient: vi.fn(),
  fetchMovementsClient: vi.fn(),
}))

import { fetchLocationsClient, fetchMovementsClient, fetchStocksClient } from '@/lib/api/warehouse'

const mockedStocks = vi.mocked(fetchStocksClient)
const mockedLocations = vi.mocked(fetchLocationsClient)
const mockedMovements = vi.mocked(fetchMovementsClient)

const stock: StockRecord = {
  id: 's1',
  material_id: 'm1',
  material_code: 'MAT-001',
  material_name: '甲醇',
  category: 'raw',
  unit: 'kg',
  safety_stock: 100,
  batch_no: 'B1',
  location_id: 'l1',
  location_code: 'L-A',
  location_name: 'A 库位',
  expiry_date: new Date(Date.now() + 5 * 86_400_000).toISOString().slice(0, 10),
  quantity: 30,
}

const location: LocationRecord = {
  id: 'l1',
  code: 'L-A',
  name: 'A 库位',
  location_type: 'normal',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedStocks.mockResolvedValue({ items: [stock], total: 1, page: 1, page_size: 20 })
  mockedLocations.mockResolvedValue([location])
  mockedMovements.mockResolvedValue({
    items: [
      {
        id: 'mv1',
        movement_no: 'MV-1',
        direction: 'inbound',
        source_type: 'purchase',
        material_id: 'm1',
        material_code: 'MAT-001',
        material_name: '甲醇',
        batch_no: 'B1',
        quantity: 40,
        unit: 'kg',
        location_id: 'l1',
        location_code: 'L-A',
        location_name: 'A 库位',
        occurred_at: '2026-09-15T10:00:00+08:00',
        remark: null,
      },
    ],
    total: 1,
    page: 1,
    page_size: 200,
  })
})

describe('StockTable', () => {
  it('加载后渲染库存行并标注低于安全库存', async () => {
    renderWithQuery(<StockTable />)

    expect(await screen.findByText('MAT-001')).toBeInTheDocument()
    expect(screen.getByText('A 库位')).toBeInTheDocument()
    expect(await screen.findByText(/低于安全库存/)).toBeInTheDocument()
  })

  it('临期效期以红色标注', async () => {
    renderWithQuery(<StockTable />)

    // expiry_date = 今天+5 天 → danger 档
    expect(await screen.findByText(/（临期）/)).toBeInTheDocument()
  })

  it('加载失败显示错误 Alert 且可重试', async () => {
    const user = userEvent.setup()
    mockedStocks.mockRejectedValueOnce(new Error('network down'))

    renderWithQuery(<StockTable />)

    // toast 与 Alert 都有提示文案，取其一断言
    expect((await screen.findAllByText('获取库存列表失败')).length).toBeGreaterThan(0)
    await user.click(screen.getByRole('button', { name: /重试/ }))
    await waitFor(() => expect(mockedStocks).toHaveBeenCalledTimes(2))
    // 重试成功后错误条消失
    expect(await screen.findByText('MAT-001')).toBeInTheDocument()
  })

  it('库位下拉数据已加载', async () => {
    renderWithQuery(<StockTable />)

    // Select 下拉选项仅在展开时渲染，这里断言库位查询已发出
    await screen.findByText('MAT-001')
    expect(mockedLocations).toHaveBeenCalled()
  })

  it('点击行打开物料流水抽屉', async () => {
    const user = userEvent.setup()
    renderWithQuery(<StockTable />)

    const cells = await screen.findAllByText('MAT-001')
    await user.click(cells[0])

    expect(await screen.findByText(/物料流水：MAT-001 甲醇/)).toBeInTheDocument()
    expect(await screen.findByText(/MV-1/)).toBeInTheDocument()
  })
})

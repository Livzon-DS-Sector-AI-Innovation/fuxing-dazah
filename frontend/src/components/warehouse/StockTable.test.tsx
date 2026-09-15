import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StockTable } from './StockTable'
import { renderWithQuery } from '@/test/utils'
import type { LocationRecord, StockRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', () => ({
  fetchStocksClient: vi.fn(),
  fetchLocationsClient: vi.fn(),
}))

import { fetchLocationsClient, fetchStocksClient } from '@/lib/api/warehouse'

const mockedStocks = vi.mocked(fetchStocksClient)
const mockedLocations = vi.mocked(fetchLocationsClient)

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
})

describe('StockTable', () => {
  it('加载后渲染库存行并标注低于安全库存', async () => {
    renderWithQuery(<StockTable />)

    expect(await screen.findByText('MAT-001')).toBeInTheDocument()
    expect(screen.getByText('A 库位')).toBeInTheDocument()
    expect(await screen.findByText(/低于安全库存/)).toBeInTheDocument()
  })

  it('库位下拉数据已加载', async () => {
    renderWithQuery(<StockTable />)

    // Select 下拉选项仅在展开时渲染，这里断言库位查询已发出
    await screen.findByText('MAT-001')
    expect(mockedLocations).toHaveBeenCalled()
  })
})

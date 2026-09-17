import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { StocktakeBoard } from './StocktakeBoard'
import { renderWithQuery } from '@/test/utils'
import type { StocktakeRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', () => ({
  fetchStocktakesClient: vi.fn(),
  fetchStocktakeClient: vi.fn(),
  fetchLocationsClient: vi.fn(),
}))
vi.mock('@/actions/warehouse', () => ({
  confirmStocktake: vi.fn(),
  createStocktake: vi.fn(),
  deleteStocktake: vi.fn(),
  updateStocktake: vi.fn(),
}))

import { fetchStocktakesClient } from '@/lib/api/warehouse'

const mockedStocktakes = vi.mocked(fetchStocktakesClient)

const record: StocktakeRecord = {
  id: 'st1',
  stocktake_no: 'ST-20260915-001',
  status: 'draft',
  remark: '月度盘点',
  items: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedStocktakes.mockResolvedValue({ items: [record], total: 1, page: 1, page_size: 20 })
})

describe('StocktakeBoard', () => {
  it('加载后渲染盘点单列表', async () => {
    renderWithQuery(<StocktakeBoard />)

    expect(await screen.findByText('ST-20260915-001')).toBeInTheDocument()
    expect(screen.getAllByText('草稿').length).toBeGreaterThan(0)
    expect(screen.getByText('月度盘点')).toBeInTheDocument()
  })
})

import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InventoryPanels } from './InventoryPanels'
import { renderWithQuery } from '@/test/utils'

// 表格组件挂载即取数：mock 数据层（client 读 + actions 写），避免真实请求
vi.mock('@/lib/api/warehouse', () => ({
  fetchStocksClient: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
  fetchMaterialsClient: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
  fetchLocationsClient: vi.fn().mockResolvedValue([]),
}))
vi.mock('@/actions/warehouse', () => ({
  createMaterial: vi.fn(),
  updateMaterial: vi.fn(),
  deleteMaterial: vi.fn(),
  createLocation: vi.fn(),
  updateLocation: vi.fn(),
  deleteLocation: vi.fn(),
}))

describe('InventoryPanels', () => {
  it('渲染库存管理三个页签', () => {
    renderWithQuery(<InventoryPanels />)

    expect(screen.getByText('现有库存')).toBeInTheDocument()
    expect(screen.getByText('物料主数据')).toBeInTheDocument()
    expect(screen.getByText('库位管理')).toBeInTheDocument()
  })
})

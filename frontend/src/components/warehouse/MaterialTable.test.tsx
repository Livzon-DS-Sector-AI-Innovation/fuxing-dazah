import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MaterialTable } from './MaterialTable'
import { renderWithQuery } from '@/test/utils'
import type { MaterialRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', () => ({
  fetchMaterialsClient: vi.fn(),
}))
vi.mock('@/actions/warehouse', () => ({
  createMaterial: vi.fn(),
  updateMaterial: vi.fn(),
  deleteMaterial: vi.fn(),
}))

import { fetchMaterialsClient } from '@/lib/api/warehouse'
import { deleteMaterial } from '@/actions/warehouse'

const mockedFetch = vi.mocked(fetchMaterialsClient)
const mockedDelete = vi.mocked(deleteMaterial)

const sample: MaterialRecord = {
  id: 'm1',
  code: 'MAT-001',
  name: '甲醇',
  category: 'raw',
  unit: 'kg',
  safety_stock: 5,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetch.mockResolvedValue({ items: [sample], total: 1, page: 1, page_size: 20 })
})

describe('MaterialTable', () => {
  it('加载后渲染物料行', async () => {
    renderWithQuery(<MaterialTable />)

    expect(await screen.findByText('MAT-001')).toBeInTheDocument()
    expect(screen.getByText('共 1 条')).toBeInTheDocument()
  })

  it('加载失败提示错误信息', async () => {
    mockedFetch.mockRejectedValueOnce(new Error('network down'))

    renderWithQuery(<MaterialTable />)

    expect(await screen.findByText('获取物料列表失败')).toBeInTheDocument()
  })

  it('删除确认后调用删除并刷新列表', async () => {
    const user = userEvent.setup()
    mockedDelete.mockResolvedValueOnce(undefined)

    renderWithQuery(<MaterialTable />)
    await screen.findByText('MAT-001')

    await user.click(screen.getByText('删除'))
    await user.click(await screen.findByRole('button', { name: 'OK' }))

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('m1'))
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('物料已删除')).toBeInTheDocument()
  })
})

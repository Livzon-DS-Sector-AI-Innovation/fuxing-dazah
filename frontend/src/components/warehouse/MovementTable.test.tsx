import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MovementTable } from './MovementTable'
import { renderWithQuery } from '@/test/utils'
import type { MovementRecord } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse', () => ({
  fetchMovementsClient: vi.fn(),
  fetchLocationsClient: vi.fn(),
  fetchMaterialsClient: vi.fn(),
}))
vi.mock('@/actions/warehouse', () => ({
  createMovement: vi.fn(),
  deleteMovement: vi.fn(),
}))

import { fetchLocationsClient, fetchMovementsClient } from '@/lib/api/warehouse'
import { deleteMovement } from '@/actions/warehouse'

const mockedMovements = vi.mocked(fetchMovementsClient)
const mockedLocations = vi.mocked(fetchLocationsClient)
const mockedDelete = vi.mocked(deleteMovement)

const movement: MovementRecord = {
  id: 'mv1',
  movement_no: 'MV-20260915-001',
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
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedMovements.mockResolvedValue({ items: [movement], total: 1, page: 1, page_size: 20 })
  mockedLocations.mockResolvedValue([
    { id: 'l1', code: 'L-A', name: 'A 库位', location_type: 'normal' },
  ])
})

describe('MovementTable', () => {
  it('加载后渲染出入库记录', async () => {
    renderWithQuery(<MovementTable />)

    expect(await screen.findByText('MV-20260915-001')).toBeInTheDocument()
    expect(screen.getByText('甲醇')).toBeInTheDocument()
  })

  it('撤销确认后调用删除并刷新列表', async () => {
    const user = userEvent.setup()
    mockedDelete.mockResolvedValueOnce(undefined)

    renderWithQuery(<MovementTable />)
    await screen.findByText('MV-20260915-001')

    await user.click(screen.getByText('撤销'))
    await user.click(await screen.findByRole('button', { name: 'OK' }))

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('mv1'))
    await waitFor(() => expect(mockedMovements).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('记录已撤销，库存已冲销')).toBeInTheDocument()
  })
})

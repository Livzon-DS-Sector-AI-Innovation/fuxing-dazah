import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WarehouseDashboard } from './WarehouseDashboard'
import { renderWithQuery } from '@/test/utils'

// echarts 依赖 canvas，happy-dom 下以占位元素代替
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echart" />,
}))

// 组件内使用 useRouter 做下钻跳转，测试环境桩掉
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

vi.mock('@/lib/api/warehouse', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/api/warehouse')>()
  return {
    ...actual,
    fetchDashboardSummaryClient: vi.fn().mockResolvedValue({
      total_quantity: 618,
      total_quantity_change: null,
      material_count: 3,
      stock_sku_count: 3,
      today_inbound_quantity: 40,
      today_inbound_count: 1,
      today_outbound_quantity: 5,
      today_outbound_count: 1,
      yesterday_inbound_quantity: 20,
      yesterday_outbound_quantity: 0,
      low_stock_count: 1,
      draft_stocktake_count: 1,
      summary_text: '今日入库 1 笔共 40，出库 1 笔共 5；低库存 1 项；进行中盘点 1 张。',
    }),
    fetchMovementTrendClient: vi.fn().mockResolvedValue([]),
    fetchStockDistributionClient: vi.fn().mockResolvedValue({
      by_category: [{ category: 'raw', total_quantity: 118 }],
      by_location_type: [{ location_type: 'normal', total_quantity: 618 }],
    }),
    fetchLowStockTopClient: vi.fn().mockResolvedValue({
      low_stock: [
        { material_code: 'MAT-LOW', material_name: '低库存物料', total_quantity: 30, safety_stock: 100 },
      ],
      idle: [],
    }),
    fetchDashboardTodosClient: vi.fn().mockResolvedValue({
      low_stock_count: 1,
      low_stock_items: [
        { material_code: 'MAT-LOW', material_name: '低库存物料', total_quantity: 30, safety_stock: 100 },
      ],
      draft_stocktakes: [{ stocktake_no: 'ST-1', remark: null, created_at: null }],
      recent_movements: [
        {
          movement_no: 'MV-1',
          direction: 'inbound',
          material_name: '甲醇',
          quantity: 40,
          unit: 'kg',
          occurred_at: '2026-09-15T10:00:00+08:00',
        },
      ],
    }),
  }
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('WarehouseDashboard', () => {
  it('渲染 KPI、摘要与快照积累提示', async () => {
    renderWithQuery(<WarehouseDashboard />)

    expect(await screen.findByText('618')).toBeInTheDocument()
    expect(await screen.findByText(/今日入库 1 笔共 40/)).toBeInTheDocument()
    expect(screen.getByText('快照积累中')).toBeInTheDocument()
  })

  it('渲染待办流条目', async () => {
    renderWithQuery(<WarehouseDashboard />)

    expect(await screen.findByText('低库存物料')).toBeInTheDocument()
    expect(screen.getByText('ST-1')).toBeInTheDocument()
  })

  it('渲染全部图表区块', async () => {
    renderWithQuery(<WarehouseDashboard />)

    // 等查询完成后各图区块才渲染（数据未到时显示 Spin）
    expect(await screen.findByText(/低库存物料/)).toBeInTheDocument()
    expect(screen.getAllByTestId('echart')).toHaveLength(5)
  })
})

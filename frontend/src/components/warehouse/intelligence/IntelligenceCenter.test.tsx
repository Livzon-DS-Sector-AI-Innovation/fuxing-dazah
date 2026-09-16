import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IntelligenceCenter } from './IntelligenceCenter'
import { renderWithQuery } from '@/test/utils'
import type { AlertRecordItem } from '@/types/warehouse'

vi.mock('@/lib/api/warehouse-intelligence', () => ({
  fetchAlertsClient: vi.fn(),
  fetchAlertSummaryClient: vi.fn(),
  fetchIntelligenceRulesClient: vi.fn(),
  fetchSuggestionsClient: vi.fn(),
}))
vi.mock('@/actions/warehouse', () => ({
  resolveIntelligenceAlert: vi.fn(),
  runIntelligenceScanAction: vi.fn(),
  setSuggestionStatusAction: vi.fn(),
  updateIntelligenceRuleAction: vi.fn(),
}))

import {
  fetchAlertsClient,
  fetchAlertSummaryClient,
  fetchSuggestionsClient,
} from '@/lib/api/warehouse-intelligence'

const mockedAlerts = vi.mocked(fetchAlertsClient)
const mockedSummary = vi.mocked(fetchAlertSummaryClient)
const mockedSuggestions = vi.mocked(fetchSuggestionsClient)

const alert: AlertRecordItem = {
  id: 'a1',
  rule_key: 'low_stock',
  level: 'warning',
  status: 'open',
  material_code: 'MAT-LOW',
  material_name: '低库存物料',
  batch_no: '',
  location_name: 'A 库位',
  detail: { total_quantity: 30, safety_stock: 100 },
  created_at: '2026-09-16T08:00:00+08:00',
  resolved_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedAlerts.mockResolvedValue({ items: [alert], total: 1, page: 1, page_size: 100 })
  mockedSummary.mockResolvedValue({
    rule_key: 'low_stock',
    text: '当前低库存风险较高，建议尽快补货。',
    source: 'fallback',
    open_count: 1,
  })
  mockedSuggestions.mockResolvedValue({
    items: [
      {
        id: 's1',
        material_code: 'MAT-FAST',
        material_name: '快消耗物料',
        avg_daily_outbound: 2,
        days_cover: 5,
        suggested_qty: 18,
        status: 'pending',
        handled_at: null,
      },
    ],
    total: 1,
    page: 1,
    page_size: 100,
  })
})

describe('IntelligenceCenter', () => {
  it('异常检测 Tab 渲染摘要条与异常列表', async () => {
    renderWithQuery(<IntelligenceCenter />)

    expect(await screen.findByText(/当前低库存风险较高/)).toBeInTheDocument()
    expect(await screen.findByText('MAT-LOW')).toBeInTheDocument()
  })

  it('补货建议 Tab 渲染建议行', async () => {
    renderWithQuery(<IntelligenceCenter />)

    await userEvent.setup().click(await screen.findByRole('tab', { name: '补货建议' }))
    expect(await screen.findByText('快消耗物料')).toBeInTheDocument()
    expect(screen.getByText('18')).toBeInTheDocument()
  })

  it('效期与呆滞 Tab 显示空态', async () => {
    renderWithQuery(<IntelligenceCenter />)

    await userEvent.setup().click(await screen.findByRole('tab', { name: '效期与呆滞' }))
    expect(await screen.findByText('暂无临期批次')).toBeInTheDocument()
    expect(screen.getByText('暂无呆滞物料')).toBeInTheDocument()
  })
})

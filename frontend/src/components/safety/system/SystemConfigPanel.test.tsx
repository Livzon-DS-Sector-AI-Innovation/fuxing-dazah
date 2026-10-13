import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SystemConfigPanel from './SystemConfigPanel'
import { renderWithQuery } from '@/test/utils'

// 六个 Tab 内容段以桩代替（各段内部行为由各自测试覆盖；本测试只验容器编排与 URL 直达/同步）
vi.mock('../aiConfig/AiModelsSection', () => ({
  default: () => <div data-testid="tab-ai-models" />,
}))
vi.mock('../aiConfig/AiScenarioSection', () => ({
  default: () => <div data-testid="tab-ai-scenarios" />,
}))
vi.mock('../BitableConfigPanel', () => ({
  default: () => <div data-testid="tab-bitable" />,
}))
vi.mock('../ScheduledTasksPanel', () => ({
  default: () => <div data-testid="tab-scheduler" />,
}))
vi.mock('../AppConfigPanel', () => ({
  default: () => <div data-testid="tab-app" />,
}))
vi.mock('../AiAuditPanel', () => ({
  default: () => <div data-testid="tab-ai-audits" />,
}))

const searchParamsMock = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('next/navigation', () => ({
  useSearchParams: () => searchParamsMock,
}))

// AiConfigController 顶层 import '@/actions/safety'（模块加载期校验 API_BASE_URL），
// factory mock 避免触达真实模块；本测试不驱动其行为
const actionMocks = vi.hoisted(() => ({
  fetchAiConfig: vi.fn(),
  testAiModelProfile: vi.fn(),
  updateAiModelConfig: vi.fn(),
  updateAiScenario: vi.fn(),
}))
vi.mock('@/actions/safety', () => ({ ...actionMocks }))

beforeEach(() => {
  vi.clearAllMocks()
  searchParamsMock.get.mockReturnValue(null)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SystemConfigPanel（/safety/system 六 Tab 配置单页）', () => {
  it('渲染页头与六个 Tab，默认激活 AI 模型', () => {
    renderWithQuery(<SystemConfigPanel />)

    expect(screen.getByText('系统配置')).toBeInTheDocument()
    expect(screen.getByText(/安全模块系统配置中心/)).toBeInTheDocument()
    expect(screen.getByText(/配置变更实时生效，无需重启/)).toBeInTheDocument()
    for (const label of [
      'AI 模型',
      'AI 场景',
      '多维表格',
      '定时任务',
      '应用配置',
      'AI 调用审计',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // 默认 Tab = AI 模型（懒挂载：其余 Tab 段不渲染）
    expect(screen.getByTestId('tab-ai-models')).toBeInTheDocument()
    expect(screen.queryByTestId('tab-bitable')).not.toBeInTheDocument()
  })

  it('?tab= 直达对应 Tab（非法值回默认）', () => {
    searchParamsMock.get.mockReturnValue('bitable')
    const { unmount } = renderWithQuery(<SystemConfigPanel />)
    expect(screen.getByTestId('tab-bitable')).toBeInTheDocument()
    unmount()

    searchParamsMock.get.mockReturnValue('not-a-tab')
    renderWithQuery(<SystemConfigPanel />)
    expect(screen.getByTestId('tab-ai-models')).toBeInTheDocument()
  })

  it('切换 Tab 同步地址栏（浅路由，不触发导航）', async () => {
    const user = userEvent.setup()
    const replaceStateSpy = vi.spyOn(window.history, 'replaceState')
    renderWithQuery(<SystemConfigPanel />)

    await user.click(screen.getByText('多维表格'))
    expect(screen.getByTestId('tab-bitable')).toBeInTheDocument()
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/safety/system?tab=bitable')
  })
})

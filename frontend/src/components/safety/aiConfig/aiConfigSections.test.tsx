import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AiConfigProvider } from './AiConfigController'
import AiModelsSection from './AiModelsSection'
import AiScenarioSection from './AiScenarioSection'
import AiConfigChangeAuditSection from './AiConfigChangeAuditSection'
import AiAuditPanel from '../AiAuditPanel'
import { renderWithQuery } from '@/test/utils'
import type { AiConfigData, AiModelConfig } from '@/types/safety'

// @ant-design/charts 依赖 canvas，happy-dom 下以占位元素代替
vi.mock('@ant-design/charts', () => ({
  Column: () => <div data-testid="column-chart" />,
}))

// server actions 统一 mock（vi.hoisted：factory 提升到文件顶部）
const mocks = vi.hoisted(() => ({
  fetchAiConfig: vi.fn(),
  testAiModelProfile: vi.fn(),
  updateAiModelConfig: vi.fn(),
  updateAiScenario: vi.fn(),
  fetchAiConfigAudits: vi.fn(),
  fetchAiScenarioAudits: vi.fn(),
  getAiAuditStats: vi.fn(),
  getAiCallAudit: vi.fn(),
  listAiCallAudits: vi.fn(),
}))
vi.mock('@/actions/safety', () => ({ ...mocks }))

function mkModel(model: string): AiModelConfig {
  return {
    base_url: 'https://api.example.com/v1',
    model,
    temperature: 0.3,
    timeout: 30,
    api_key_masked: 'sk-***ab',
    api_key_set: true,
    source: 'db',
    configured: true,
    backup: null,
  }
}

const AI_CONFIG: AiConfigData = {
  text_model: mkModel('deepseek-chat'),
  text_backup_model: mkModel('deepseek-chat-backup'),
  vision_model: mkModel('glm-4v'),
  embedding_model: mkModel('text-embedding-3'),
  rerank_model: mkModel('bge-reranker'),
  functions: [
    {
      id: 'hazard_digest',
      label: '隐患日报生成',
      description: '每日隐患速递 AI 生成',
      model_type: 'text',
      channel: 'safety',
      enabled: true,
      model_profile: null,
      effective_profile: 'text',
      source: 'default',
      status: 'enabled',
      allowed_profiles: ['text', 'text_backup'],
    },
    {
      id: 'vision_check',
      label: '图片隐患识别',
      description: '上传图片识别隐患',
      model_type: 'vision',
      channel: 'safety',
      enabled: false,
      allowed_profiles: ['vision'],
    },
  ],
}

const CONFIG_AUDITS = [
  {
    id: 'a1',
    profile: 'text',
    action: 'update',
    before_json: { model: 'a' },
    after_json: { model: 'b' },
    operator_name: '管理员',
    created_at: '2026-10-12T09:00:00+08:00',
  },
]

const SCENARIO_AUDITS = [
  {
    id: 's1',
    scenario: 'hazard_digest',
    action: 'enable',
    before_json: { enabled: false },
    after_json: { enabled: true },
    operator_name: '管理员',
    created_at: '2026-10-12T10:00:00+08:00',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  mocks.fetchAiConfig.mockResolvedValue({ code: 200, message: 'ok', data: AI_CONFIG })
  mocks.fetchAiConfigAudits.mockResolvedValue({ code: 200, message: 'ok', data: CONFIG_AUDITS })
  mocks.fetchAiScenarioAudits.mockResolvedValue({ code: 200, message: 'ok', data: SCENARIO_AUDITS })
  mocks.getAiAuditStats.mockResolvedValue({
    code: 200,
    message: 'ok',
    data: {
      days: 7,
      date_from: '2026-10-06T00:00:00+08:00',
      date_to: '2026-10-13T00:00:00+08:00',
      totals: {
        calls: 10,
        input_tokens: 100,
        output_tokens: 50,
        cache_hit_tokens: 0,
        cache_miss_tokens: 0,
        failed: 1,
      },
      prev_totals: {
        calls: 8,
        input_tokens: 80,
        output_tokens: 40,
        cache_hit_tokens: 0,
        cache_miss_tokens: 0,
        failed: 0,
      },
      by_scenario: [],
      daily: [],
    },
  })
  mocks.listAiCallAudits.mockResolvedValue({
    code: 200,
    message: 'ok',
    data: [],
    meta: { total: 0 },
  })
})

describe('AI 配置拆分段（prefactor）', () => {
  it('AI 模型段渲染五张模型卡；模型段+场景段共享一次取数（ensure 幂等）', async () => {
    renderWithQuery(
      <AiConfigProvider>
        <AiModelsSection />
        <AiScenarioSection />
      </AiConfigProvider>,
    )

    for (const label of ['文本模型', '文本备用模型', '视觉模型', '向量模型', '重排模型']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(mocks.fetchAiConfig).toHaveBeenCalledTimes(1)
  })

  it('AI 场景段渲染功能表：计数摘要、启停开关与绑定控件', async () => {
    renderWithQuery(
      <AiConfigProvider>
        <AiScenarioSection />
      </AiConfigProvider>,
    )

    expect(await screen.findByText('隐患日报生成')).toBeInTheDocument()
    expect(screen.getByText(/共 2 项 · 已启用 1 · 已停用 1/)).toBeInTheDocument()
    // 白名单 >1 → 可编辑绑定下拉；=1 → 固定
    expect(screen.getByTestId('ai-scenario-binding-hazard_digest')).toBeInTheDocument()
    expect(screen.getByText('固定')).toBeInTheDocument()
    expect(screen.getByTestId('ai-scenario-switch-hazard_digest')).toBeInTheDocument()
  })

  it('配置变更审计段：默认模型配置表，切换场景配置表且场景列用中文名', async () => {
    const user = userEvent.setup()
    renderWithQuery(
      <AiConfigProvider>
        <AiConfigChangeAuditSection />
      </AiConfigProvider>,
    )

    // 默认「模型配置」→ 拉取模型配置审计
    expect(await screen.findByText('管理员')).toBeInTheDocument()
    expect(mocks.fetchAiConfigAudits).toHaveBeenCalledTimes(1)

    // 切「场景配置」→ 拉取场景审计，场景列显示中文名（labels 来自共享数据）
    await user.click(screen.getByText('场景配置'))
    expect(mocks.fetchAiScenarioAudits).toHaveBeenCalled()
    expect(await screen.findByText('隐患日报生成')).toBeInTheDocument()
  })
})

describe('AiAuditPanel 顶层审计视图切换', () => {
  it('默认调用审计；切「配置变更审计」渲染配置变更审计段', async () => {
    const user = userEvent.setup()
    renderWithQuery(<AiAuditPanel />)

    // 默认调用审计：KPI 带渲染
    expect(await screen.findByText('总调用')).toBeInTheDocument()
    expect(mocks.fetchAiConfigAudits).not.toHaveBeenCalled()

    // 顶层 Segmented 切到配置变更审计（无 Provider → 自取 labels + 拉审计）
    await user.click(screen.getByText('配置变更审计'))
    expect(mocks.fetchAiConfigAudits).toHaveBeenCalled()
    expect(mocks.fetchAiConfig).toHaveBeenCalled()
    expect(await screen.findByText('管理员')).toBeInTheDocument()
  })
})

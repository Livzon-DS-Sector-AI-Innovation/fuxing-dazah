'use client'

// AI 配置共享数据层（三期配置单页 prefactor：从 AiConfigPanel 抽出）
// 模型五卡（AiModelsSection）与场景功能表（AiScenarioSection）共用同一份 GET /ai-config 数据；
// 保存/启停/绑定成功 → auditRefreshKey+1，供配置变更审计表重拉。
// Provider 不自动拉取：各 Section 挂载时调用 ensure()（幂等，首次触发），
// 保持配置单页多 Tab 下的懒加载语义（不看的 Tab 不发请求）。

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { App } from 'antd'

import {
  fetchAiConfig,
  testAiModelProfile,
  updateAiModelConfig,
  updateAiScenario,
} from '@/actions/safety'
import type {
  AiConfigData,
  AiFunctionItem,
  AiModelProfile,
  AiModelTestResult,
  AiScenarioConfig,
  ApiResponse,
  UpdateAiConfigInput,
} from '@/types/safety'

/** 绑定下拉「默认」项（null = 按场景类型默认） */
export const DEFAULT_BINDING = '__default__'

/** PUT 成功响应 → 行内补丁（仅覆盖后端实际返回的字段，避免用 undefined 覆盖行快照） */
function mergeScenarioConfig(d: AiScenarioConfig): Partial<AiFunctionItem> {
  const patch: Partial<AiFunctionItem> = {}
  if (d.enabled !== undefined) patch.enabled = d.enabled
  if (d.model_profile !== undefined) patch.model_profile = d.model_profile
  if (d.effective_profile !== undefined) patch.effective_profile = d.effective_profile
  if (d.source !== undefined) patch.source = d.source
  if (d.status !== undefined) patch.status = d.status
  if (d.allowed_profiles !== undefined) patch.allowed_profiles = d.allowed_profiles
  return patch
}

export interface AiConfigControllerValue {
  data: AiConfigData | null
  loading: boolean
  loadError: string | null
  savingProfile: AiModelProfile | null
  savingScenarios: Set<string>
  /** 场景 id → 中文名（配置变更审计表场景列用；后端审计项只返回 scenario id） */
  scenarioLabels: Record<string, string>
  /** 配置保存/启停/绑定成功后 +1（配置变更审计表重拉钩子） */
  auditRefreshKey: number
  /** 幂等：未拉取过才触发 load（Section 挂载时调用） */
  ensure: () => void
  load: () => Promise<void>
  handleSave: (
    profile: AiModelProfile,
    values: UpdateAiConfigInput,
  ) => Promise<boolean>
  handleTest: (
    profile: AiModelProfile,
    values: UpdateAiConfigInput,
  ) => Promise<ApiResponse<AiModelTestResult>>
  handleToggleScenario: (f: AiFunctionItem, v: boolean) => Promise<void>
  handleChangeBinding: (f: AiFunctionItem, value: string) => Promise<void>
}

const AiConfigContext = createContext<AiConfigControllerValue | null>(null)

export function AiConfigProvider({ children }: { children: ReactNode }) {
  const { message } = App.useApp()

  const [data, setData] = useState<AiConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [savingProfile, setSavingProfile] = useState<AiModelProfile | null>(null)
  const [auditRefreshKey, setAuditRefreshKey] = useState(0)
  const [savingScenarios, setSavingScenarios] = useState<Set<string>>(new Set())
  const dataRef = useRef<AiConfigData | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    dataRef.current = data
  }, [data])

  const applyLoadResult = useCallback(
    (res: { code: number; message: string; data: AiConfigData | null }) => {
      if (res.code >= 200 && res.code < 300 && res.data) {
        setData(res.data)
        setLoadError(null)
      } else if (dataRef.current) {
        message.error(res.message || '刷新 AI 配置失败')
      } else {
        setLoadError(res.message || '加载 AI 配置失败')
      }
    },
    [message],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      applyLoadResult(await fetchAiConfig())
    } finally {
      setLoading(false)
    }
  }, [applyLoadResult])

  const ensure = useCallback(() => {
    if (startedRef.current) return
    startedRef.current = true
    void load()
  }, [load])

  // ── 保存：PUT 成功 → 提示 → 重拉 GET（draft 由 config prop 变化重置）→ 审计刷新 ──
  const handleSave = useCallback(
    async (profile: AiModelProfile, values: UpdateAiConfigInput) => {
      setSavingProfile(profile)
      try {
        const res = await updateAiModelConfig(profile, values)
        if (res.code >= 200 && res.code < 300) {
          message.success('配置已保存，实时生效')
          await load()
          setAuditRefreshKey((k) => k + 1)
          return true
        }
        if (res.code === 403) message.error('无权限修改 AI 配置')
        else if (res.code === 404) message.error('该配置组不存在或不可编辑')
        else message.error(res.message || '保存失败')
        return false
      } finally {
        setSavingProfile(null)
      }
    },
    [load, message],
  )

  // ── 测试：只读探测，结果由卡内 Alert 呈现 ──
  const handleTest = useCallback(
    (profile: AiModelProfile, values: UpdateAiConfigInput): Promise<ApiResponse<AiModelTestResult>> =>
      testAiModelProfile(profile, values),
    [],
  )

  // ── 行内即时 PUT：函数式 setState + 行快照整行回滚，保证并发安全 ──
  const applyScenarioPatch = useCallback((id: string, patch: Partial<AiFunctionItem>) => {
    setData((prev) =>
      prev
        ? {
            ...prev,
            functions: prev.functions.map((f) => (f.id === id ? { ...f, ...patch } : f)),
          }
        : prev,
    )
  }, [])

  /** 统一错误矩阵：403/404/422 专属文案；422 后端已回退默认 → 全量 load() 兜底 */
  const reportScenarioError = useCallback(
    (code: number, fallbackMessage: string) => {
      if (code === 403) message.error('无权限修改 AI 场景配置')
      else if (code === 404) message.error('该场景不存在或已下线')
      else if (code === 422) {
        message.error('该绑定与场景类型不匹配，已按默认处理')
        void load()
      } else message.error(fallbackMessage || '保存失败')
    },
    [load, message],
  )

  /** 开关切换：乐观更新 → PUT {enabled} → 成功回填 + audit 顶刷；失败整行回滚 */
  const handleToggleScenario = useCallback(
    async (f: AiFunctionItem, v: boolean) => {
      if (savingScenarios.has(f.id)) return
      const snapshot = { ...f }
      applyScenarioPatch(f.id, { enabled: v, source: 'db' })
      setSavingScenarios((s) => new Set(s).add(f.id))
      try {
        const res = await updateAiScenario(f.id, { enabled: v })
        if (res.code >= 200 && res.code < 300 && res.data) {
          applyScenarioPatch(f.id, mergeScenarioConfig(res.data))
          message.success(v ? '已启用，实时生效' : '已停用，AI 调用将被拦截')
          setAuditRefreshKey((k) => k + 1)
        } else {
          applyScenarioPatch(f.id, snapshot)
          reportScenarioError(res.code, res.message)
        }
      } catch (e) {
        applyScenarioPatch(f.id, snapshot)
        message.error(e instanceof Error ? e.message : '保存失败')
      } finally {
        setSavingScenarios((s) => {
          const next = new Set(s)
          next.delete(f.id)
          return next
        })
      }
    },
    [applyScenarioPatch, message, reportScenarioError, savingScenarios],
  )

  /** 绑定变更：即时 PUT {model_profile}；__default__ → null（按场景类型默认）；失败整行回滚 */
  const handleChangeBinding = useCallback(
    async (f: AiFunctionItem, value: string) => {
      if (savingScenarios.has(f.id)) return
      const snapshot = { ...f }
      const profile = value === DEFAULT_BINDING ? null : (value as AiModelProfile)
      applyScenarioPatch(f.id, {
        model_profile: profile,
        effective_profile: profile ?? f.effective_profile,
        source: 'db',
      })
      setSavingScenarios((s) => new Set(s).add(f.id))
      try {
        const res = await updateAiScenario(f.id, { model_profile: profile })
        if (res.code >= 200 && res.code < 300 && res.data) {
          applyScenarioPatch(f.id, mergeScenarioConfig(res.data))
          message.success('模型绑定已更新，实时生效')
          setAuditRefreshKey((k) => k + 1)
        } else {
          applyScenarioPatch(f.id, snapshot)
          reportScenarioError(res.code, res.message)
        }
      } catch (e) {
        applyScenarioPatch(f.id, snapshot)
        message.error(e instanceof Error ? e.message : '保存失败')
      } finally {
        setSavingScenarios((s) => {
          const next = new Set(s)
          next.delete(f.id)
          return next
        })
      }
    },
    [applyScenarioPatch, message, reportScenarioError, savingScenarios],
  )

  const scenarioLabels = useMemo(() => {
    const map: Record<string, string> = {}
    for (const f of data?.functions ?? []) map[f.id] = f.label
    return map
  }, [data])

  const value = useMemo<AiConfigControllerValue>(
    () => ({
      data,
      loading,
      loadError,
      savingProfile,
      savingScenarios,
      scenarioLabels,
      auditRefreshKey,
      ensure,
      load,
      handleSave,
      handleTest,
      handleToggleScenario,
      handleChangeBinding,
    }),
    [
      data,
      loading,
      loadError,
      savingProfile,
      savingScenarios,
      scenarioLabels,
      auditRefreshKey,
      ensure,
      load,
      handleSave,
      handleTest,
      handleToggleScenario,
      handleChangeBinding,
    ],
  )

  return <AiConfigContext.Provider value={value}>{children}</AiConfigContext.Provider>
}

/** 消费共享数据层（必须在 AiConfigProvider 内使用） */
export function useAiConfigController(): AiConfigControllerValue {
  const ctx = useContext(AiConfigContext)
  if (!ctx) throw new Error('useAiConfigController 必须在 AiConfigProvider 内使用')
  return ctx
}

/** 可选消费（配置变更审计段在无 Provider 场景下降级自取 labels） */
export function useAiConfigControllerOptional(): AiConfigControllerValue | null {
  return useContext(AiConfigContext)
}

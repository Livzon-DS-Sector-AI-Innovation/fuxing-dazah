'use client'

// AI 配置中心主面板（design.md §1-§2）
// 双 Tab：模型配置（五张可编辑卡：对话组 3 列 + RAG 组 2 列 + AI 调用功能表）/ 审计记录（懒挂载，首次激活才拉取）
// 取数链路：挂载 → GET /ai-config → 成功渲染 5 卡（draft=当前生效值）+ SourceTag；
//           失败 → 整区 Alert(error) + 重试（修复一期遗留：data=null && loading=false 不再永久 Skeleton）
// 保存：PUT /ai-config/{profile} → message.success → 重拉 GET（卡片不动，draft 由 config 重置）→ 审计 refreshKey+1
// 三期（ai-config-phase3）：AI 调用功能表升级为行内可配置——启用 Switch / 模型绑定下拉（白名单为
//   allowed_profiles 事实源，length<=1 只读「固定」）/ 生效来源列；开关与绑定均即时 PUT（乐观更新 +
//   失败回滚 + message.error，行级锁 savingScenarios：同行互斥、异行并行；422 回退默认时全量 load()）；
//   状态 Segmented 筛选 + 「已启用 X · 已停用 Y」计数；审计 Tab 内 Segmented「模型配置 / 场景配置」。
// 旧后端兼容：enabled 等三期字段缺省 → Switch disabled + 绑定「—」+ 来源「—」（只读降级，不误导 PUT）。
// status 字段后端当前语义为 enabled/disabled（非 design 假设的 ok），故仅当非「正常值」时绑定列
// 才出现「已回退默认」tooltip，避免整列误报。

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Alert, App, Button, Empty, Input, Segmented, Select, Skeleton, Space, Switch, Table, Tabs, Tag, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import {
  fetchAiConfig,
  testAiModelProfile,
  updateAiModelConfig,
  updateAiScenario,
} from '@/actions/safety'
import type {
  AiConfigData,
  AiConfigSource,
  AiFunctionItem,
  AiModelConfig,
  AiModelProfile,
  AiModelTestResult,
  AiScenarioConfig,
  ApiResponse,
  UpdateAiConfigInput,
} from '@/types/safety'
import AiConfigModelCard from './AiConfigModelCard'
import AiConfigAuditTable from './AiConfigAuditTable'
import AiScenarioAuditTable from './AiScenarioAuditTable'
import { AI_PROFILE_UI, CARD_STYLE, MONO_FONT, UI, ModelTypeTag, SourceTag } from './schedulerConfigConstants'
import { ChannelTag } from './aiAuditConstants'

const MODEL_TYPE_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '文本', value: 'text' },
  { label: '视觉', value: 'vision' },
]

/** 启用状态筛选（design §2.5；enabled 未返回的行不参与特定态过滤） */
const ENABLED_STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '启用', value: 'enabled' },
  { label: '停用', value: 'disabled' },
]

/** 绑定下拉「默认」项（null = 按场景类型默认） */
const DEFAULT_BINDING = '__default__'

/** 五卡分组（对话模型组 3 列 / RAG 检索模型组 2 列） */
const DIALOG_GROUP: AiModelProfile[] = ['text', 'text_backup', 'vision']
const RAG_GROUP: AiModelProfile[] = ['embedding', 'rerank']

/**
 * 绑定白名单（design §1.2）：后端 allowed_profiles 为事实源；
 * 缺省/空时按 model_type/id 推导（text→[text,text_backup]、vision→[vision]、embedding/rerank→[自身]）。
 */
function getAllowedProfiles(f: AiFunctionItem): AiModelProfile[] {
  if (f.allowed_profiles && f.allowed_profiles.length > 0) return f.allowed_profiles
  if (f.model_type === 'vision') return ['vision']
  if (f.id === 'embedding') return ['embedding']
  if (f.id === 'rerank') return ['rerank']
  return ['text', 'text_backup']
}

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

/**
 * profile → 模型配置（text_backup 适配：后端维持嵌套时以 text_model.backup 回退构造；
 * backup 仅含 configured/model/api_key_masked，base_url/timeout/source 未知 → 空值/隐藏 tag）
 */
function getProfileModel(
  data: AiConfigData | null,
  profile: AiModelProfile,
): AiModelConfig | null | undefined {
  if (!data) return undefined
  switch (profile) {
    case 'text':
      return data.text_model ?? null
    case 'text_backup': {
      if (data.text_backup_model !== undefined && data.text_backup_model !== null) {
        return data.text_backup_model
      }
      const backup = data.text_model.backup
      if (!backup) return null
      return {
        configured: backup.configured,
        model: backup.model,
        base_url: backup.base_url ?? null,
        timeout: backup.timeout ?? null,
        temperature: null,
        api_key_masked: backup.api_key_masked,
        api_key_set: backup.api_key_set,
        source: backup.source,
        backup: null,
      }
    }
    case 'vision':
      return data.vision_model ?? null
    case 'embedding':
      return data.embedding_model ?? null
    case 'rerank':
      return data.rerank_model ?? null
  }
}

export default function AiConfigPanel() {
  const { message } = App.useApp()

  const [data, setData] = useState<AiConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('models')
  const [savingProfile, setSavingProfile] = useState<AiModelProfile | null>(null)
  const [auditRefreshKey, setAuditRefreshKey] = useState(0)
  // 功能表筛选
  const [keyword, setKeyword] = useState('')
  const [modelType, setModelType] = useState<string>('all')
  const [channel, setChannel] = useState<string | undefined>()
  // 三期：启用状态筛选 / 行级保存锁 / 审计子类
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [savingScenarios, setSavingScenarios] = useState<Set<string>>(new Set())
  const [auditKind, setAuditKind] = useState<'profile' | 'scenario'>('profile')
  const dataRef = useRef<AiConfigData | null>(null)

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

  // 挂载拉取：setState 全部发生在异步续体中（react-hooks/set-state-in-effect）
  // try/catch/finally：server action 传输失败（网络中断/连接重置）时走错误 Alert + 重试，
  // 避免永久 Skeleton（与下方 loadError 分支的设计意图一致）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetchAiConfig()
        if (cancelled) return
        applyLoadResult(res)
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载 AI 配置失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [applyLoadResult])

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

  // ── 三期：行内即时 PUT（design §2.1-§2.4）──
  // 行内补丁用函数式 setState + 行快照整行回滚，保证并发安全（对齐二期 dataRef 先例）
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

  /** 统一错误矩阵（design §5.3）：403/404/422 专属文案；422 后端已回退默认 → 全量 load() 兜底 */
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

  // 前端筛选：搜索 + 模型类型 + 渠道 + 启用状态（design §2.5：enabled 未返回的行不参与特定态过滤）
  const filteredFunctions = useMemo(() => {
    const list = data?.functions ?? []
    const kw = keyword.trim().toLowerCase()
    return list.filter((f) => {
      if (modelType !== 'all' && f.model_type !== modelType) return false
      if (channel && f.channel !== channel) return false
      if (enabledFilter === 'enabled' && f.enabled !== true) return false
      if (enabledFilter === 'disabled' && f.enabled !== false) return false
      if (
        kw &&
        !(
          f.label.toLowerCase().includes(kw) ||
          f.id.toLowerCase().includes(kw) ||
          (f.description ?? '').toLowerCase().includes(kw)
        )
      )
        return false
      return true
    })
  }, [data, keyword, modelType, channel, enabledFilter])

  const channelOptions = useMemo(() => {
    const set = new Set(
      (data?.functions ?? []).map((f) => f.channel).filter((c): c is string => !!c),
    )
    return [...set].map((c) => ({ value: c, label: c }))
  }, [data])

  /** 场景 id → 中文名（审计表场景列用；后端审计项只返回 scenario id） */
  const scenarioLabels = useMemo(() => {
    const map: Record<string, string> = {}
    for (const f of data?.functions ?? []) map[f.id] = f.label
    return map
  }, [data])

  /** 启停计数（全量，非筛选后：design §2.5 计数摘要） */
  const enabledCount = useMemo(
    () => (data?.functions ?? []).filter((f) => f.enabled === true).length,
    [data],
  )
  const disabledCount = useMemo(
    () => (data?.functions ?? []).filter((f) => f.enabled === false).length,
    [data],
  )

  /** 模型绑定单元格：旧后端降级「—」/ 白名单 ≤1 只读「固定」/ 可编辑 Select（design §1.2） */
  const renderBindingCell = (f: AiFunctionItem) => {
    if (f.enabled === undefined) {
      return <span style={{ fontSize: 12, color: UI.muted }}>—</span>
    }
    const allowed = getAllowedProfiles(f)
    if (allowed.length <= 1) {
      const effective = f.effective_profile ?? allowed[0]
      const label = effective ? AI_PROFILE_UI[effective]?.label ?? effective : null
      const cell = (
        <span style={{ whiteSpace: 'nowrap' }}>
          <span style={{ fontSize: 13, color: UI.slate }}>
            {effective && label ? `${label}（${effective}）` : '—'}
          </span>
          <Tag
            style={{
              marginLeft: 8,
              borderRadius: 6,
              background: UI.gray,
              color: UI.steel,
              borderColor: UI.hairline,
            }}
          >
            固定
          </Tag>
        </span>
      )
      const tip = effective ? `该场景仅可使用 ${effective}，绑定不可修改` : '该场景绑定不可修改'
      return <Tooltip title={tip}>{cell}</Tooltip>
    }
    const select = (
      <Select
        size="small"
        style={{ width: 184 }}
        value={f.model_profile ?? DEFAULT_BINDING}
        data-testid={`ai-scenario-binding-${f.id}`}
        disabled={savingScenarios.has(f.id)}
        options={[
          { value: DEFAULT_BINDING, label: '默认（按场景类型）' },
          ...allowed.map((p) => ({ value: p, label: `${AI_PROFILE_UI[p]?.label ?? p}（${p}）` })),
        ]}
        onChange={(v) => void handleChangeBinding(f, v)}
      />
    )
    // MINOR4 修复：agent_chat 场景绑定不生效（Agent 模型模块级创建，重启生效），
    // 行级 Tooltip 明确标注，避免管理员误以为热切换；控件保留可编辑（后端允许）
    const editable: ReactNode =
      f.id === 'agent_chat' ? (
        <Tooltip title="该场景绑定不生效（Agent 模型模块级创建）">{select}</Tooltip>
      ) : (
        select
      )
    // status 非正常语义值（后端当前为 enabled/disabled）时提示已回退默认；后续语义未定前不做主列渲染
    const degraded =
      !!f.status && f.status !== 'ok' && f.status !== 'enabled' && f.status !== 'disabled'
    return degraded ? <Tooltip title="绑定与场景类型不匹配，已回退默认">{editable}</Tooltip> : editable
  }

  const columns: ColumnsType<AiFunctionItem> = [
    {
      title: '功能名称',
      dataIndex: 'label',
      width: 160,
      render: (v: string, f: AiFunctionItem) => (
        <span style={{ fontWeight: 600, color: UI.ink }}>
          {v || '—'}
          {f.deprecated === true && (
            <Tooltip title="已废弃场景，保留兼容可配置">
              <Tag
                style={{
                  marginLeft: 6,
                  borderRadius: 6,
                  fontSize: 10,
                  lineHeight: '16px',
                  padding: '0 4px',
                  background: UI.gray,
                  color: UI.steel,
                  borderColor: UI.hairline,
                }}
              >
                废弃
              </Tag>
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      title: '场景值',
      dataIndex: 'id',
      width: 200,
      render: (v: string) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>{v}</span>
      ),
    },
    {
      title: '启用',
      key: 'enabled',
      width: 80,
      render: (_, f) => {
        const readOnly = f.enabled === undefined
        const sw = (
          <Switch
            size="small"
            checked={!!f.enabled}
            loading={savingScenarios.has(f.id)}
            disabled={readOnly}
            data-testid={`ai-scenario-switch-${f.id}`}
            onChange={(v) => void handleToggleScenario(f, v)}
          />
        )
        return readOnly ? <Tooltip title="后端未返回场景配置">{sw}</Tooltip> : sw
      },
    },
    {
      title: '模型绑定',
      key: 'model_profile',
      width: 200,
      render: (_, f) => renderBindingCell(f),
    },
    {
      title: '生效来源',
      key: 'source',
      width: 100,
      render: (_, f) =>
        f.source ? (
          <SourceTag source={f.source as AiConfigSource} />
        ) : (
          <span style={{ fontSize: 12, color: UI.muted }}>—</span>
        ),
    },
    {
      title: '模型类型',
      dataIndex: 'model_type',
      width: 100,
      render: (v: string) => <ModelTypeTag type={v} />,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 90,
      render: (v: string) => <ChannelTag channel={v} />,
    },
    {
      title: '描述',
      dataIndex: 'description',
      render: (v: string) => (
        <span style={{ fontSize: 13, color: UI.slate }}>{v || '—'}</span>
      ),
    },
  ]

  const renderCardGrid = (profiles: AiModelProfile[]) => (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
        gap: 16,
        alignItems: 'stretch',
      }}
    >
      {profiles.map((profile) => (
        <AiConfigModelCard
          key={profile}
          profile={profile}
          color={AI_PROFILE_UI[profile].color}
          hint={AI_PROFILE_UI[profile].hint}
          config={getProfileModel(data, profile)}
          loading={loading && !data}
          saving={savingProfile === profile}
          onSave={handleSave}
          onTest={handleTest}
        />
      ))}
    </div>
  )

  const sectionTitle = (text: string) => (
    <div style={{ fontSize: 13, fontWeight: 600, color: UI.slate, marginBottom: 8, marginTop: 20 }}>
      {text}
    </div>
  )

  return (
    <div style={{ padding: 24, maxWidth: 1280 }}>
      {/* ── 页头 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>AI 配置</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            安全管理模块 AI 模型与调用能力管理（保存即生效，无需重启）
          </div>
        </div>
        <Space size={12}>
          <span style={{ fontSize: 12, color: UI.steel }}>
            配置变更实时生效；飞书业务 Agent 需重启后生效
          </span>
          <Tooltip title="重拉配置（未保存修改将被丢弃）">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void load()}
              loading={loading}
              disabled={savingScenarios.size > 0}
              title="刷新"
            />
          </Tooltip>
        </Space>
      </div>

      {/* ── 双 Tab：模型配置 / 审计记录（审计懒挂载：首次激活才 fetch） ── */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        style={{ marginTop: 8 }}
        items={[
          {
            key: 'models',
            label: '模型配置',
            children: (
              <div>
                {loading && !data ? (
                  /* 区级 Skeleton（初始加载） */
                  <div style={{ ...CARD_STYLE, padding: 16 }}>
                    <Skeleton active paragraph={{ rows: 10 }} />
                  </div>
                ) : loadError ? (
                  /* GET 失败：整区 Alert + 重试（修复永久 Skeleton 遗留） */
                  <Alert
                    type="error"
                    showIcon
                    style={{ ...CARD_STYLE, padding: 16 }}
                    message={<span style={{ fontSize: 13, fontWeight: 600 }}>AI 配置加载失败</span>}
                    description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
                    action={
                      <Button size="small" onClick={() => void load()}>
                        重试
                      </Button>
                    }
                  />
                ) : (
                  <>
                    {/* 对话模型组（文本 / 文本备用 / 视觉，3 列） */}
                    {sectionTitle('对话模型')}
                    {renderCardGrid(DIALOG_GROUP)}

                    {/* RAG 检索模型组（向量 / 重排，2 列） */}
                    {sectionTitle('RAG 检索模型')}
                    {renderCardGrid(RAG_GROUP)}
                  </>
                )}

                {/* ── AI 调用功能表（延续既有样式；数据失败时维持空态位） ── */}
                <div style={{ ...CARD_STYLE, padding: 16, marginTop: 20 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: 12,
                    }}
                  >
                    <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 调用功能</div>
                    <span style={{ fontSize: 12, color: UI.steel }}>
                      共 {filteredFunctions.length} 项 · 已启用 {enabledCount} · 已停用 {disabledCount}
                    </span>
                  </div>

                  <Space wrap style={{ margin: '12px 0' }}>
                    <Input.Search
                      placeholder="功能名称/场景值/描述"
                      style={{ width: 240 }}
                      value={keyword}
                      onChange={(e) => setKeyword(e.target.value)}
                      allowClear
                    />
                    <Segmented
                      options={MODEL_TYPE_OPTIONS}
                      value={modelType}
                      onChange={(v) => setModelType(v as string)}
                    />
                    <Segmented
                      options={ENABLED_STATUS_OPTIONS}
                      value={enabledFilter}
                      onChange={(v) => setEnabledFilter(v as 'all' | 'enabled' | 'disabled')}
                    />
                    <Select
                      allowClear
                      placeholder="渠道"
                      style={{ width: 120 }}
                      options={channelOptions}
                      value={channel}
                      onChange={(v) => setChannel(v || undefined)}
                    />
                    <Button
                      icon={<ReloadOutlined />}
                      onClick={() => void load()}
                      disabled={savingScenarios.size > 0}
                      title="刷新"
                    />
                  </Space>

                  {loading ? (
                    <Skeleton active paragraph={{ rows: 6 }} />
                  ) : (
                    <Table<AiFunctionItem>
                      rowKey="id"
                      size="small"
                      columns={columns}
                      dataSource={filteredFunctions}
                      scroll={{ x: 1160 }}
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="当前无已注册场景"
                          />
                        ),
                      }}
                      pagination={
                        filteredFunctions.length > 10
                          ? { pageSize: 10, showSizeChanger: false }
                          : false
                      }
                    />
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'audits',
            label: '审计记录',
            children:
              activeTab === 'audits' ? (
                <div>
                  {/* 审计子类（design §7）：模型配置（二期原样）/ 场景配置（三期新增） */}
                  <Segmented
                    options={[
                      { label: '模型配置', value: 'profile' },
                      { label: '场景配置', value: 'scenario' },
                    ]}
                    value={auditKind}
                    onChange={(v) => setAuditKind(v as 'profile' | 'scenario')}
                    style={{ marginBottom: 12 }}
                  />
                  {auditKind === 'profile' ? (
                    <AiConfigAuditTable refreshKey={auditRefreshKey} />
                  ) : (
                    <AiScenarioAuditTable refreshKey={auditRefreshKey} scenarioLabels={scenarioLabels} />
                  )}
                </div>
              ) : null,
          },
        ]}
      />
    </div>
  )
}

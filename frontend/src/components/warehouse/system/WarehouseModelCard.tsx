'use client'

// 仓库 AI 模型可编辑卡（对齐 safety/AiConfigModelCard 范式）
// 始终内联编辑：Form 行内标签 + 输入框；dirty 才可保存；
// api_key 密码框回显脱敏占位，留空提交 = 不带 api_key（不修改语义）；
// 「连通性测试」对**已保存配置**探测（后端只收 {profile}，不吃表单值），
// 结果展示 ok / latency / model / 错误摘要；「启用」开关即时 PUT {enabled}。

import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Form, Input, InputNumber, Skeleton, Space, Switch, Tooltip } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'

import { testWarehouseAiModel, updateWarehouseAiModel } from '@/actions/warehouse'
import type {
  WarehouseAiModelView,
  WarehouseAiModelUpdateInput,
  WarehouseConfigSource,
} from '@/types/warehouse'
import {
  CARD_STYLE,
  FieldSource,
  MONO_FONT,
  SAVE_OK_MESSAGE,
  SourceTag,
  UI,
  WAREHOUSE_PROFILE_UI,
  apiKeyPlaceholder,
  formatLatency,
} from './systemConfigConstants'

interface WarehouseModelCardProps {
  profile: string
  /** undefined=加载中（Skeleton）；null=未配置 */
  view?: WarehouseAiModelView | null
  canUpdate: boolean
  /** 保存成功后面板重拉 GET，draft 由 view prop 变化重置 */
  onSaved: () => void
  onToggled: () => void
}

interface ModelFormValues {
  base_url?: string
  model?: string
  api_key?: string
  temperature?: number | null
  max_tokens?: number | null
  timeout?: number | null
}

function fieldSourceOf(
  view: WarehouseAiModelView | null | undefined,
  field: string,
): WarehouseConfigSource | null {
  return view?.sources?.[field] ?? null
}

export default function WarehouseModelCard({
  profile,
  view,
  canUpdate,
  onSaved,
  onToggled,
}: WarehouseModelCardProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<ModelFormValues>()
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  const meta = WAREHOUSE_PROFILE_UI[profile] ?? {
    label: profile,
    color: UI.steel,
    fields: ['base_url', 'model', 'api_key', 'timeout'] as const,
  }

  // 外部刷新（保存成功重拉）：以 view 为准回填（api_key 恒空，绝不回显明文）
  useEffect(() => {
    if (view === undefined) return
    form.setFieldsValue({
      base_url: view?.config.base_url ?? '',
      model: view?.config.model ?? '',
      api_key: '',
      temperature: view?.config.temperature ?? null,
      max_tokens: view?.config.max_tokens ?? null,
      timeout: view?.config.timeout ?? null,
    })
  }, [view, form])

  const wBaseUrl = Form.useWatch('base_url', form)
  const wModel = Form.useWatch('model', form)
  const wApiKey = Form.useWatch('api_key', form)
  const wTemperature = Form.useWatch('temperature', form)
  const wMaxTokens = Form.useWatch('max_tokens', form)
  const wTimeout = Form.useWatch('timeout', form)

  // dirty：draft 与 config 逐字段比较 + api_key 非空即 dirty
  const dirty = useMemo(() => {
    const norm = (a: unknown): string => (a === undefined || a === null ? '' : String(a).trim())
    if (norm(wApiKey) !== '') return true
    return (
      norm(wBaseUrl) !== norm(view?.config.base_url) ||
      norm(wModel) !== norm(view?.config.model) ||
      norm(wTemperature) !== norm(view?.config.temperature) ||
      norm(wMaxTokens) !== norm(view?.config.max_tokens) ||
      norm(wTimeout) !== norm(view?.config.timeout)
    )
  }, [wBaseUrl, wModel, wApiKey, wTemperature, wMaxTokens, wTimeout, view])

  const modelName = (wModel ?? '').trim() || view?.config.model || '—'

  if (view === undefined) {
    return (
      <div style={{ ...CARD_STYLE, padding: 20, minWidth: 0 }} data-testid={`wh-model-card-${profile}`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: meta.color }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: UI.ink }}>{meta.label}</span>
        </div>
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginTop: 12 }} />
      </div>
    )
  }

  const fieldRow = (
    name: keyof ModelFormValues,
    label: string,
    control: React.ReactNode,
    rules?: { type: 'url'; message: string }[],
  ) => (
    <div
      key={name}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '4px 0',
        borderBottom: `1px solid ${UI.hairlineSoft}`,
      }}
    >
      <span style={{ width: 88, flexShrink: 0, fontSize: 12, color: UI.steel, display: 'inline-flex', alignItems: 'center' }}>
        {label}
        <FieldSource source={fieldSourceOf(view, name)} />
      </span>
      <Form.Item name={name} rules={rules} style={{ flex: 1, marginBottom: 0 }}>
        {control}
      </Form.Item>
    </div>
  )

  const buildPayload = (v: ModelFormValues | undefined): WarehouseAiModelUpdateInput => {
    const payload: WarehouseAiModelUpdateInput = {}
    if (!v) return payload
    if (v.base_url?.trim()) payload.base_url = v.base_url.trim()
    if (v.model?.trim()) payload.model = v.model.trim()
    if (v.api_key?.trim()) payload.api_key = v.api_key.trim() // 空串 = 不修改（不带键）
    if (v.temperature != null && meta.fields.includes('temperature')) {
      payload.temperature = v.temperature
    }
    if (v.max_tokens != null && meta.fields.includes('max_tokens')) {
      payload.max_tokens = Math.round(v.max_tokens)
    }
    if (v.timeout != null) payload.timeout = Math.round(v.timeout)
    return payload
  }

  const handleSave = async () => {
    let values: ModelFormValues
    try {
      values = await form.validateFields()
    } catch {
      return // antd 已标红，不提交
    }
    setSaving(true)
    try {
      await updateWarehouseAiModel(profile, buildPayload(values))
      message.success(SAVE_OK_MESSAGE)
      setTestResult(null)
      onSaved()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 连通性测试：后端只接收 profile，对**已保存**的合并配置做真实调用探测
  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testWarehouseAiModel(profile)
      if (res.ok) {
        const parts = ['连通性验证通过']
        if (res.model) parts.push(`模型 ${res.model}`)
        if (res.latency_ms != null) parts.push(`耗时 ${formatLatency(res.latency_ms)}`)
        setTestResult({ ok: true, text: parts.join(' · ') })
      } else {
        setTestResult({ ok: false, text: res.error || '连接失败' })
      }
    } catch (e) {
      setTestResult({ ok: false, text: e instanceof Error ? e.message : '测试失败' })
    } finally {
      setTesting(false)
    }
  }

  const handleToggle = async (enabled: boolean) => {
    if (!canUpdate || toggling) return
    setToggling(true)
    try {
      await updateWarehouseAiModel(profile, { enabled })
      message.success(enabled ? '已启用，实时生效' : '已停用，调用将回落 env/default')
      onToggled()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败')
    } finally {
      setToggling(false)
    }
  }

  return (
    <div
      style={{ ...CARD_STYLE, padding: 20, minWidth: 0, display: 'flex', flexDirection: 'column' }}
      data-testid={`wh-model-card-${profile}`}
    >
      {/* header：色点 + 标题 + profile key + 状态徽标 + 启用开关 */}
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: meta.color }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: UI.ink }}>{meta.label}</span>
        <span style={{ flex: 1 }} />
        <span style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: UI.muted, fontFamily: MONO_FONT }}>{profile}</span>
          <span style={{ marginLeft: 8, display: 'inline-flex', alignItems: 'center' }}>
            <SourceTag source={view?.status} />
          </span>
        </span>
        <Tooltip title={canUpdate ? '停用后整行回落 env/default' : '需要 warehouse:system-config:update 权限'}>
          <Switch
            size="small"
            checked={view?.enabled ?? true}
            loading={toggling}
            disabled={!canUpdate || saving}
            data-testid={`wh-model-switch-${profile}`}
            onChange={(v) => void handleToggle(v)}
          />
        </Tooltip>
      </div>

      {/* 大号 mono 模型名 */}
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          color: UI.ink,
          margin: '10px 0 6px',
          fontFamily: MONO_FONT,
          letterSpacing: -0.2,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {modelName}
      </div>

      <Form form={form} layout="vertical" requiredMark={false} component={false} style={{ flex: 1 }}>
        {meta.fields.map((f) => {
          switch (f) {
            case 'base_url':
              return fieldRow(
                'base_url',
                'Base URL',
                <Input
                  disabled={saving || !canUpdate}
                  placeholder="https://…"
                  style={{ fontFamily: MONO_FONT, fontSize: 13 }}
                />,
                [{ type: 'url', message: '请输入 http(s):// 开头的完整地址' }],
              )
            case 'model':
              return fieldRow(
                'model',
                '模型',
                <Input
                  disabled={saving || !canUpdate}
                  placeholder="模型名，如 deepseek-flash"
                  style={{ fontFamily: MONO_FONT, fontSize: 13 }}
                />,
              )
            case 'api_key':
              return fieldRow(
                'api_key',
                'API Key',
                <Input.Password
                  disabled={saving || !canUpdate}
                  autoComplete="new-password"
                  placeholder={apiKeyPlaceholder(view?.api_key_masked)}
                  style={{ fontFamily: MONO_FONT, fontSize: 13 }}
                />,
              )
            case 'temperature':
              return fieldRow(
                'temperature',
                '温度',
                <InputNumber
                  disabled={saving || !canUpdate}
                  min={0}
                  max={2}
                  step={0.1}
                  style={{ width: '100%', fontSize: 13 }}
                />,
              )
            case 'max_tokens':
              return fieldRow(
                'max_tokens',
                '最大 Token',
                <InputNumber
                  disabled={saving || !canUpdate}
                  min={256}
                  max={65536}
                  precision={0}
                  style={{ width: '100%', fontSize: 13 }}
                />,
              )
            case 'timeout':
              return fieldRow(
                'timeout',
                '超时(s)',
                <InputNumber
                  disabled={saving || !canUpdate}
                  min={1}
                  max={600}
                  precision={0}
                  style={{ width: '100%', fontSize: 13 }}
                />,
              )
            default:
              return null
          }
        })}
      </Form>

      {meta.hint ? <div style={{ fontSize: 12, color: UI.muted, marginTop: 8 }}>{meta.hint}</div> : null}
      {!canUpdate ? (
        <div style={{ fontSize: 12, color: UI.warning, marginTop: 4 }}>
          当前账号仅有查看权限（保存/测试需 warehouse:system-config:update）
        </div>
      ) : null}

      {/* footer：连通性测试 / 重置 + 保存 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 12,
          paddingTop: 12,
          borderTop: `1px solid ${UI.hairlineSoft}`,
        }}
      >
        <Space size={8}>
          <Tooltip title="对已保存配置做真实调用探测（不写库不写审计）">
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              loading={testing}
              disabled={!canUpdate || saving}
              onClick={() => void handleTest()}
            >
              连通性测试
            </Button>
          </Tooltip>
          <Button
            size="small"
            disabled={!dirty || saving || !canUpdate}
            onClick={() =>
              form.setFieldsValue({
                base_url: view?.config.base_url ?? '',
                model: view?.config.model ?? '',
                api_key: '',
                temperature: view?.config.temperature ?? null,
                max_tokens: view?.config.max_tokens ?? null,
                timeout: view?.config.timeout ?? null,
              })
            }
          >
            重置
          </Button>
        </Space>
        <Button
          size="small"
          type="primary"
          loading={saving}
          disabled={!dirty || !canUpdate}
          onClick={() => void handleSave()}
          data-testid={`wh-model-card-save-${profile}`}
        >
          保存
        </Button>
      </div>

      {/* 测试结果 Alert */}
      {testResult &&
        (testResult.ok ? (
          <Alert
            type="success"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{testResult.text}</span>}
          />
        ) : (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{`连通性验证失败：${testResult.text}`}</span>}
            description={
              <span style={{ fontSize: 12, color: UI.muted }}>
                1. 确认 base_url 与模型名拼写与供应商文档一致；2. 确认 API Key 有效且未过期；3. 修改后请先保存再测试。
              </span>
            }
          />
        ))}
    </div>
  )
}

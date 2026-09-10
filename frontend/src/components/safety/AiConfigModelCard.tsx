'use client'

// AI 配置可编辑模型卡（design.md §1.3 / §2）
// 始终内联编辑（无查看/编辑切换）：Form 行内标签（88px）+ 输入框；
// dirty 才可保存；「测试」用表单当前值 POST /test，卡内 Alert 展示结果（不写库不写审计）；
// 表单值模型 AiModelFormValues：api_key 空=不修改（提交时过滤）。

import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Skeleton, Space } from 'antd'
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'

import type {
  ApiResponse,
  AiModelConfig,
  AiModelProfile,
  AiModelTestResult,
  UpdateAiConfigInput,
} from '@/types/safety'
import {
  AI_PROFILE_UI,
  CARD_STYLE,
  MONO_FONT,
  SourceTag,
  UI,
  apiKeyPlaceholder,
} from './schedulerConfigConstants'

interface AiConfigModelCardProps {
  profile: AiModelProfile
  color: string
  hint?: string
  /** undefined=加载中（Skeleton）；null=未配置（渲染空值表单） */
  config?: AiModelConfig | null
  loading?: boolean
  saving?: boolean
  /** 返回 true=保存成功（面板已重拉 GET，draft 由 config prop 变化重置） */
  onSave: (profile: AiModelProfile, values: UpdateAiConfigInput) => Promise<boolean>
  /** 返回测试响应，由卡内渲染 Alert */
  onTest: (
    profile: AiModelProfile,
    values: UpdateAiConfigInput,
  ) => Promise<ApiResponse<AiModelTestResult>>
}

interface AiModelFormValues {
  base_url?: string
  model?: string
  api_key?: string
  dims?: number | null
  temperature?: number | null
  timeout?: number | null
}

/** 测试失败排查建议（design.md §2.3 固定文案） */
const TROUBLESHOOTING =
  '1. 确认 base_url 与模型名拼写与供应商文档一致；2. 确认 API Key 有效且未过期；' +
  '3. Embedding/重排请确认模型在当前 base_url 下可用。'

/** 提交体：仅收集非空字段（api_key 空串直接剔除=不修改） */
function buildPayload(v: AiModelFormValues | undefined): UpdateAiConfigInput {
  const payload: UpdateAiConfigInput = {}
  if (!v) return payload
  if (v.base_url?.trim()) payload.base_url = v.base_url.trim()
  if (v.model?.trim()) payload.model = v.model.trim()
  if (v.api_key?.trim()) payload.api_key = v.api_key.trim()
  if (v.dims != null) payload.dims = v.dims
  if (v.temperature != null) payload.temperature = v.temperature
  if (v.timeout != null) payload.timeout = v.timeout
  return payload
}

/** 从 config 提取表单初值（api_key 恒空，绝不回显；保存后重置时清空残留输入） */
function initialValuesFrom(config?: AiModelConfig | null): AiModelFormValues {
  return {
    base_url: config?.base_url ?? '',
    model: config?.model ?? '',
    api_key: '',
    dims: config?.dims ?? null,
    temperature: config?.temperature ?? null,
    timeout: config?.timeout ?? null,
  }
}

export default function AiConfigModelCard({
  profile,
  color,
  hint,
  config,
  loading,
  saving,
  onSave,
  onTest,
}: AiConfigModelCardProps) {
  const [form] = Form.useForm<AiModelFormValues>()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null)

  const title = AI_PROFILE_UI[profile].label
  const meta = AI_PROFILE_UI[profile]

  // 外部刷新（保存成功重拉 / 页头刷新）= 重置 draft：以 config 为准回填（design.md §1.6）
  useEffect(() => {
    if (config === undefined) return
    form.setFieldsValue(initialValuesFrom(config))
  }, [config, form])

  // 逐字段 watch（无显式 values 状态）：dirty 判定与模型名联动均依赖
  const wBaseUrl = Form.useWatch('base_url', form)
  const wModel = Form.useWatch('model', form)
  const wApiKey = Form.useWatch('api_key', form)
  const wDims = Form.useWatch('dims', form)
  const wTemperature = Form.useWatch('temperature', form)
  const wTimeout = Form.useWatch('timeout', form)

  // dirty 判定：draft 与 config 逐字段比较 + api_key 非空即 dirty（design.md §2.2）
  const dirty = useMemo(() => {
    const norm = (a: unknown): string => (a === undefined || a === null ? '' : String(a).trim())
    const cfg = config as AiModelConfig | null | undefined
    if (norm(wApiKey) !== '') return true
    return (
      norm(wBaseUrl) !== norm(cfg?.base_url) ||
      norm(wModel) !== norm(cfg?.model) ||
      norm(wDims) !== norm(cfg?.dims) ||
      norm(wTemperature) !== norm(cfg?.temperature) ||
      norm(wTimeout) !== norm(cfg?.timeout)
    )
  }, [wBaseUrl, wModel, wApiKey, wDims, wTemperature, wTimeout, config])

  // 卡顶大号 mono 模型名回显（与表单 model 字段联动，空 = '—'）
  const modelName = (wModel ?? '').trim() || config?.model || '—'

  if (loading) {
    return (
      <div
        style={{ ...CARD_STYLE, padding: 20, minWidth: 0 }}
        data-testid={`ai-model-card-${profile}`}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: UI.ink }}>{title}</span>
        </div>
        <Skeleton active paragraph={{ rows: 4 }} style={{ marginTop: 12 }} />
      </div>
    )
  }

  const fieldRow = (
    name: keyof AiModelFormValues,
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
      <span style={{ width: 88, flexShrink: 0, fontSize: 12, color: UI.steel }}>{label}</span>
      <Form.Item name={name} rules={rules} style={{ flex: 1, marginBottom: 0 }}>
        {control}
      </Form.Item>
    </div>
  )

  const handleSave = async () => {
    let valuesOut: AiModelFormValues
    try {
      valuesOut = await form.validateFields()
    } catch {
      return // antd 已标红，不提交
    }
    await onSave(profile, buildPayload(valuesOut))
  }

  const handleTest = async () => {
    const valuesOut = form.getFieldsValue(true)
    setTesting(true)
    setTestResult(null)
    try {
      const res = await onTest(profile, buildPayload(valuesOut))
      if (res.code >= 200 && res.code < 300 && res.data) {
        if (res.data.ok) {
          const status = res.data.status_code ? `（HTTP ${res.data.status_code}）` : ''
          setTestResult({ ok: true, text: `连通性验证通过${status}` })
        } else {
          setTestResult({ ok: false, text: res.data.message || '连接失败' })
        }
      } else {
        setTestResult({ ok: false, text: res.message || `测试失败（HTTP ${res.code}）` })
      }
    } finally {
      setTesting(false)
    }
  }

  return (
    <div
      style={{
        ...CARD_STYLE,
        padding: 20,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
      }}
      data-testid={`ai-model-card-${profile}`}
    >
      {/* header：色点 + 标题 + profile key + 生效来源 */}
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: UI.ink }}>{title}</span>
        <span style={{ flex: 1 }} />
        <span style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: UI.muted, fontFamily: MONO_FONT }}>{profile}</span>
          <SourceTag source={config?.source} />
        </span>
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
                  disabled={saving}
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
                  disabled={saving}
                  placeholder="模型名，如 deepseek-v4-flash"
                  style={{ fontFamily: MONO_FONT, fontSize: 13 }}
                />,
              )
            case 'api_key':
              return fieldRow(
                'api_key',
                'API Key',
                <Input.Password
                  disabled={saving}
                  autoComplete="new-password"
                  placeholder={apiKeyPlaceholder(config)}
                  style={{ fontFamily: MONO_FONT, fontSize: 13 }}
                />,
              )
            case 'dims':
              return fieldRow(
                'dims',
                '向量维度',
                <InputNumber
                  disabled={saving}
                  min={1}
                  precision={0}
                  style={{ width: '100%', fontSize: 13 }}
                  placeholder="仅嵌入模型"
                />,
              )
            case 'temperature':
              return fieldRow(
                'temperature',
                '温度',
                <InputNumber
                  disabled={saving}
                  min={0}
                  max={2}
                  step={0.1}
                  style={{ width: '100%', fontSize: 13 }}
                />,
              )
            case 'timeout':
              return fieldRow(
                'timeout',
                '超时(s)',
                <InputNumber
                  disabled={saving}
                  min={1}
                  max={600}
                  precision={0}
                  style={{ width: '100%', fontSize: 13 }}
                />,
              )
          }
        })}
      </Form>

      {/* hint 卡备注 */}
      {hint ? (
        <div style={{ fontSize: 12, color: UI.muted, marginTop: 8 }}>{hint}</div>
      ) : null}

      {/* footer：测试 / 重置 + 保存 */}
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
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testing}
            disabled={saving}
            onClick={() => void handleTest()}
          >
            {testing ? '测试中…' : '测试'}
          </Button>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={!dirty || saving}
            onClick={() => form.setFieldsValue(initialValuesFrom(config))}
          >
            重置
          </Button>
        </Space>
        <Button
          size="small"
          type="primary"
          loading={saving}
          disabled={!dirty}
          onClick={() => void handleSave()}
          data-testid={`ai-model-card-save-${profile}`}
        >
          保存
        </Button>
      </div>

      {/* 测试结果 Alert（仅测试后出现；测试通过不代表已保存） */}
      {testResult &&
        (testResult.ok ? (
          <Alert
            type="success"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{testResult.text}</span>}
            description={
              <span style={{ fontSize: 12, color: UI.slate }}>
                测试使用表单当前值，尚未保存，确认无误后请保存
              </span>
            }
          />
        ) : (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{`连通性验证失败：${testResult.text}`}</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{TROUBLESHOOTING}</span>}
          />
        ))}
    </div>
  )
}

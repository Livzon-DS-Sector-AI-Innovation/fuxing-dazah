'use client'

// 运行参数 Tab：8 个参数按 group 分组渲染（确认与草稿/Runner/会话/识别/提醒/提示词）
// 每行：label/key/当前值编辑（int/float 数字框、str 文本域）/默认值/范围提示/来源；
// 保存 = PUT {value}；恢复默认 = PUT 默认值。成功后以返回视图回填该行。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Input, InputNumber, Skeleton, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { getWarehouseRuntimeConfigs, updateWarehouseRuntimeConfig } from '@/actions/warehouse'
import type { WarehouseRuntimeValue, WarehouseRuntimeView } from '@/types/warehouse'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import {
  CARD_STYLE,
  FieldSource,
  MONO_FONT,
  SAVE_OK_MESSAGE,
  UI,
} from './systemConfigConstants'

/** 行内组件以 key={key:value} 受控重建（value 变化 = 重挂载重置草稿，规避 effect 同步 setState） */
function RuntimeRow({
  config,
  canUpdate,
  onSaved,
}: {
  config: WarehouseRuntimeView
  canUpdate: boolean
  onSaved: (view: WarehouseRuntimeView) => void
}) {
  const { message } = App.useApp()
  const [draft, setDraft] = useState<WarehouseRuntimeValue>(config.value)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)

  const dirty = String(draft ?? '') !== String(config.value ?? '')

  const rangeHint =
    config.value_type === 'int' || config.value_type === 'float'
      ? `范围 ${config.min_value ?? '-∞'} ~ ${config.max_value ?? '+∞'}`
      : config.max_length != null
        ? `最长 ${config.max_length} 字符`
        : ''

  const submit = async (raw: WarehouseRuntimeValue) => {
    let value: WarehouseRuntimeValue = raw
    if (config.value_type === 'int') {
      if (raw === null || raw === '' || typeof raw !== 'number') {
        message.error(`${config.label} 必须为整数`)
        return
      }
      value = Math.round(raw)
    } else if (config.value_type === 'float') {
      if (raw === null || raw === '' || typeof raw !== 'number') {
        message.error(`${config.label} 必须为数值`)
        return
      }
      value = raw
    } else {
      value = String(raw ?? '')
    }
    setSaving(true)
    try {
      const view = await updateWarehouseRuntimeConfig(config.key, value)
      message.success(SAVE_OK_MESSAGE)
      onSaved(view)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setResetting(true)
    try {
      const view = await updateWarehouseRuntimeConfig(config.key, config.default)
      message.success('已恢复默认，实时生效')
      onSaved(view)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '恢复默认失败')
    } finally {
      setResetting(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 16,
        padding: '12px 0',
        borderBottom: `1px solid ${UI.hairlineSoft}`,
        flexWrap: 'wrap',
      }}
      data-testid={`wh-runtime-row-${config.key}`}
    >
      {/* 名称与说明 */}
      <div style={{ width: 260, minWidth: 220, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: UI.ink }}>{config.label}</span>
          <FieldSource source={config.source} />
        </div>
        <div style={{ fontFamily: MONO_FONT, fontSize: 11, color: UI.muted, marginTop: 2 }}>
          {config.key}
        </div>
        <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>{config.description}</div>
      </div>

      {/* 编辑器 */}
      <div style={{ flex: 1, minWidth: 240 }}>
        {config.value_type === 'str' ? (
          <Input.TextArea
            value={String(draft ?? '')}
            maxLength={config.max_length ?? undefined}
            showCount={config.max_length != null}
            autoSize={{ minRows: 2, maxRows: 10 }}
            disabled={!canUpdate || saving || resetting}
            placeholder="留空 = 清空覆盖（回退 env/默认）"
            onChange={(e) => setDraft(e.target.value)}
          />
        ) : (
          <InputNumber
            value={draft === null || draft === '' ? null : Number(draft)}
            min={config.min_value ?? undefined}
            max={config.max_value ?? undefined}
            step={config.value_type === 'float' ? 0.05 : 1}
            precision={config.value_type === 'int' ? 0 : 2}
            style={{ width: 220, fontSize: 13 }}
            disabled={!canUpdate || saving || resetting}
            onChange={(v) => setDraft(v)}
          />
        )}
        <div style={{ fontSize: 11, color: UI.muted, marginTop: 4 }}>
          {rangeHint}
          {config.default !== null && config.default !== '' ? (
            <span>
              {' '}
              · 默认值 <span style={{ fontFamily: MONO_FONT }}>{String(config.default)}</span>
            </span>
          ) : null}
        </div>
      </div>

      {/* 操作 */}
      <div style={{ display: 'flex', gap: 8, flexShrink: 0, paddingTop: 2 }}>
        <Button
          size="small"
          type="primary"
          loading={saving}
          disabled={!canUpdate || resetting || !dirty}
          onClick={() => void submit(draft)}
        >
          保存
        </Button>
        <Tooltip title={`PUT 默认值${config.default === '' ? '（空串=清空覆盖）' : ''}`}>
          <Button
            size="small"
            loading={resetting}
            disabled={!canUpdate || saving || String(config.value ?? '') === String(config.default ?? '')}
            onClick={() => void handleReset()}
          >
            恢复默认
          </Button>
        </Tooltip>
      </div>
    </div>
  )
}

export default function RuntimeParamsTab({ canUpdate }: { canUpdate: boolean }) {
  const [configs, setConfigs] = useState<WarehouseRuntimeView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const auditRef = useRef<ConfigAuditHandle>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getWarehouseRuntimeConfigs()
      setConfigs(data.configs ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载运行参数失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehouseRuntimeConfigs()
        if (!cancelled) setConfigs(data.configs ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载运行参数失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  /** 单行保存成功：以 PUT 返回视图回填 + 顶刷审计 */
  const handleRowSaved = useCallback((view: WarehouseRuntimeView) => {
    setConfigs((prev) => (prev ? prev.map((c) => (c.key === view.key ? view : c)) : prev))
    auditRef.current?.refresh()
  }, [])

  // 按 group 分组（保持后端 registry 顺序）
  const groups: { group: string; items: WarehouseRuntimeView[] }[] = []
  for (const c of configs ?? []) {
    const last = groups[groups.length - 1]
    if (last && last.group === c.group) last.items.push(c)
    else groups.push({ group: c.group, items: [c] })
  }

  return (
    <div>
      <div style={{ ...CARD_STYLE, padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
            marginBottom: 8,
          }}
        >
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>Agent 运行参数</div>
            <div style={{ fontSize: 12, color: UI.steel, marginTop: 2 }}>
              保存即时生效（下一次会话/识别/卡片渲染即采用新值），无需重启
            </div>
          </div>
          <Tooltip title="重拉参数（未保存修改将被丢弃）">
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void load()}
              loading={loading}
              title="刷新"
            />
          </Tooltip>
        </div>

        {loading && configs === null ? (
          <Skeleton active paragraph={{ rows: 12 }} />
        ) : loadError ? (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>运行参数加载失败</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : (
          groups.map(({ group, items }) => (
            <div key={group} style={{ marginTop: 12 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: UI.slate,
                  margin: '8px 0 4px',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                {group}
                <span
                  style={{ fontSize: 11, color: UI.muted, fontWeight: 400, marginLeft: 8 }}
                >
                  {items.length} 项
                </span>
              </div>
              {items.map((c) => (
                <RuntimeRow
                  key={`${c.key}:${String(c.value ?? '')}`}
                  config={c}
                  canUpdate={canUpdate}
                  onSaved={handleRowSaved}
                />
              ))}
            </div>
          ))
        )}
      </div>

      <ConfigAuditSection ref={auditRef} kind="runtime" />
    </div>
  )
}

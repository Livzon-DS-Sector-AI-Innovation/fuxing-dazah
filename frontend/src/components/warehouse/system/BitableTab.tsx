'use client'

// 多维表格 Tab：左侧 10 张表列表（table_key/name_cn/base_key），右侧连接卡
// base_token 密码框（脱敏回显 ****后4位；留空提交 = 清空覆盖，回退 env/快照默认）、
// table_id 输入、enabled 状态展示（PUT 仅收 base_token/table_id/note，无开关 API）、
// token/table_id 来源徽标；操作：保存 / 测试连接 / 刷新字段缓存。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Empty, Input, Modal, Skeleton, Space, Tooltip } from 'antd'
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'

import {
  getWarehouseBitableConnections,
  refreshWarehouseBitableFields,
  testWarehouseBitableConnection,
  updateWarehouseBitableConnection,
} from '@/actions/warehouse'
import type { WarehouseBitableView } from '@/types/warehouse'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import {
  CARD_STYLE,
  FieldSource,
  MONO_FONT,
  SAVE_OK_MESSAGE,
  SourceTag,
  StatusTag,
  UI,
  bitableTokenPlaceholder,
} from './systemConfigConstants'

/** 右侧连接卡（以 key={table_key:table_id} 受控重建，草稿初值即 props，规避 effect setState） */
function ConnectionCard({
  view,
  canUpdate,
  onSaved,
}: {
  view: WarehouseBitableView
  canUpdate: boolean
  onSaved: (view: WarehouseBitableView) => void
}) {
  const { message } = App.useApp()
  const [tokenInput, setTokenInput] = useState('')
  const [tableIdInput, setTableIdInput] = useState(view.table_id ?? '')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  const tokenDirty = tokenInput.trim() !== ''
  const dirty = tokenDirty || tableIdInput.trim() !== String(view.table_id ?? '')

  const doSave = async (token: string, tableId: string) => {
    setSaving(true)
    try {
      const fresh = await updateWarehouseBitableConnection(view.table_key, {
        base_token: token, // 空串 = 清空覆盖（后端契约语义）
        table_id: tableId,
      })
      message.success(SAVE_OK_MESSAGE)
      setResult(null)
      onSaved(fresh)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSave = () => {
    const token = tokenInput.trim()
    const tableId = tableIdInput.trim()
    // 留空 base_token = 清空覆盖（后端语义：空串回落 env/默认）；已配置且留空时二次确认
    if (!token && view.base_token !== '未配置') {
      Modal.confirm({
        title: '确认清空 base_token？',
        content: '留空提交将清空该表 DB 覆盖并回退环境变量/代码默认坐标。',
        okText: '确认保存',
        cancelText: '返回',
        onOk: () => void doSave(token, tableId),
      })
      return
    }
    void doSave(token, tableId)
  }

  const handleTest = async () => {
    setTesting(true)
    setResult(null)
    try {
      const res = await testWarehouseBitableConnection(view.table_key)
      if (res.ok) {
        setResult({
          ok: true,
          text: `连接正常 · 字段 ${res.field_count ?? '—'} 个${res.table_id ? ` · table_id ${res.table_id}` : ''}`,
        })
      } else {
        setResult({ ok: false, text: res.error || '连接失败' })
      }
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : '测试失败' })
    } finally {
      setTesting(false)
    }
  }

  const handleRefreshFields = async () => {
    setRefreshing(true)
    setResult(null)
    try {
      const res = await refreshWarehouseBitableFields(view.table_key)
      if (res.ok) {
        setResult({ ok: true, text: `字段缓存已刷新 · 共 ${res.field_count ?? '—'} 个字段` })
      } else {
        setResult({ ok: false, text: res.error || '刷新失败' })
      }
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : '刷新失败' })
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>
          {view.name_cn || view.table_key}
        </span>
        <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
          {view.table_key}
        </span>
        <span style={{ flex: 1 }} />
        <Tooltip title="启用状态由系统管理（连接行创建即启用，API 不提供开关）">
          <span>
            <StatusTag enabled={view.enabled} />
          </span>
        </Tooltip>
        <SourceTag source={view.token_source} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, margin: '14px 0 4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span
            style={{
              width: 96,
              flexShrink: 0,
              fontSize: 12,
              color: UI.steel,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            Base Token
            <FieldSource source={view.token_source} />
          </span>
          <Input.Password
            value={tokenInput}
            autoComplete="new-password"
            disabled={!canUpdate || saving}
            placeholder={bitableTokenPlaceholder(view.base_token)}
            style={{ fontFamily: MONO_FONT, fontSize: 13 }}
            onChange={(e) => setTokenInput(e.target.value)}
            data-testid="wh-bitable-token"
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span
            style={{
              width: 96,
              flexShrink: 0,
              fontSize: 12,
              color: UI.steel,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            Table ID
            <FieldSource source={view.table_id_source} />
          </span>
          <Input
            value={tableIdInput}
            disabled={!canUpdate || saving}
            placeholder="tbl…"
            style={{ fontFamily: MONO_FONT, fontSize: 13 }}
            onChange={(e) => setTableIdInput(e.target.value)}
            data-testid="wh-bitable-table-id"
          />
        </div>
        <div style={{ fontSize: 11, color: UI.muted, paddingLeft: 108 }}>
          回退链：DB 覆盖 &gt; 环境变量 &gt; 代码快照；base_token 留空提交 = 清空覆盖（回退
          env/默认）
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 14,
          paddingTop: 12,
          borderTop: `1px solid ${UI.hairlineSoft}`,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <Space size={8}>
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testing}
            disabled={!canUpdate || saving || refreshing}
            onClick={() => void handleTest()}
          >
            测试连接
          </Button>
          <Tooltip title="只读拉取表头字段并重建字段缓存">
            <Button
              size="small"
              loading={refreshing}
              disabled={!canUpdate || saving || testing}
              onClick={() => void handleRefreshFields()}
            >
              刷新字段缓存
            </Button>
          </Tooltip>
        </Space>
        <Button
          size="small"
          type="primary"
          loading={saving}
          disabled={!canUpdate || !dirty || testing || refreshing}
          onClick={handleSave}
          data-testid="wh-bitable-save"
        >
          保存
        </Button>
      </div>

      {result &&
        (result.ok ? (
          <Alert
            type="success"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{result.text}</span>}
          />
        ) : (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            message={<span style={{ fontSize: 13 }}>{result.text}</span>}
            description={
              <span style={{ fontSize: 12, color: UI.muted }}>
                请确认 base_token / table_id 与多维表格实际坐标一致（测试只读拉取表头字段）。
              </span>
            }
          />
        ))}
    </>
  )
}

export default function BitableTab({ canUpdate }: { canUpdate: boolean }) {
  const [connections, setConnections] = useState<WarehouseBitableView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const auditRef = useRef<ConfigAuditHandle>(null)

  const applyList = useCallback((list: WarehouseBitableView[]) => {
    setConnections(list)
    setSelectedKey((prev) => prev ?? list[0]?.table_key ?? null)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getWarehouseBitableConnections()
      applyList(data.connections ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载多维表格连接失败')
    } finally {
      setLoading(false)
    }
  }, [applyList])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehouseBitableConnections()
        if (!cancelled) applyList(data.connections ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载多维表格连接失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [applyList])

  const selected = connections?.find((c) => c.table_key === selectedKey) ?? null

  /** 连接保存成功：以 PUT 返回视图回填列表 + 顶刷审计 */
  const handleSaved = useCallback((view: WarehouseBitableView) => {
    setConnections((prev) =>
      prev ? prev.map((c) => (c.table_key === view.table_key ? view : c)) : prev,
    )
    auditRef.current?.refresh()
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* ── 左：表列表 ── */}
        <div style={{ ...CARD_STYLE, padding: 12, width: 320, flexShrink: 0 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 8,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 600, color: UI.ink }}>
              表连接（{connections?.length ?? 0}）
            </span>
            <Tooltip title="重拉连接配置">
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                onClick={() => void load()}
                loading={loading}
                title="刷新"
              />
            </Tooltip>
          </div>
          {loading && connections === null ? (
            <Skeleton active paragraph={{ rows: 8 }} />
          ) : loadError ? (
            <Alert
              type="error"
              showIcon
              message="加载失败"
              description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
              action={
                <Button size="small" onClick={() => void load()}>
                  重试
                </Button>
              }
            />
          ) : !connections || connections.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无已注册表" />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {connections.map((c) => {
                const active = c.table_key === selectedKey
                return (
                  <button
                    key={c.table_key}
                    onClick={() => setSelectedKey(c.table_key)}
                    style={{
                      textAlign: 'left',
                      border: `1px solid ${active ? UI.primary : UI.hairline}`,
                      background: active ? UI.lavender : UI.canvas,
                      borderRadius: 8,
                      padding: '8px 10px',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                    data-testid={`wh-bitable-item-${c.table_key}`}
                  >
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: UI.ink,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {c.name_cn || c.table_key}
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        gap: 8,
                        marginTop: 2,
                      }}
                    >
                      <span style={{ fontFamily: MONO_FONT, fontSize: 11, color: UI.steel }}>
                        {c.base_key} · {c.table_key}
                      </span>
                      <span style={{ fontSize: 11, color: UI.muted, flexShrink: 0 }}>
                        {c.base_token === '未配置' ? '未配置' : '****' + c.base_token.slice(-4)}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* ── 右：连接卡（table_id 变化时受控重建重置草稿） ── */}
        <div style={{ ...CARD_STYLE, padding: 20, flex: 1, minWidth: 360 }}>
          {!selected ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧表查看连接配置" />
          ) : (
            <ConnectionCard
              key={`${selected.table_key}:${selected.table_id}`}
              view={selected}
              canUpdate={canUpdate}
              onSaved={handleSaved}
            />
          )}
        </div>
      </div>

      <ConfigAuditSection ref={auditRef} kind="bitable" />
    </div>
  )
}

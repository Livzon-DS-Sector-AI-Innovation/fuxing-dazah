'use client'

// AI 场景 Tab：agent_chat 仓库助手对话 / receipt_recognition 送货单识别入库 两行场景表
// enabled Switch 与 model_profile 下拉均即时 PUT（PUT 返回视图回填 = 行内刷新），
// 失败整行回滚；状态列 / 生效 profile / 来源列只读展示。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Empty, Select, Skeleton, Space, Switch, Table, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { getWarehouseAiScenarios, updateWarehouseAiScenario } from '@/actions/warehouse'
import type {
  WarehouseAiScenarioView,
  WarehouseProfileName,
} from '@/types/warehouse'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import {
  CARD_STYLE,
  MONO_FONT,
  SAVE_OK_MESSAGE,
  SourceTag,
  StatusTag,
  UI,
  scenarioLabel,
} from './systemConfigConstants'

const DEFAULT_BINDING = '__default__'

const PROFILE_LABELS: Record<string, string> = {
  agent: '主模型',
  agent_backup: '备用模型',
}

export default function AiScenariosTab({ canUpdate }: { canUpdate: boolean }) {
  const { message } = App.useApp()
  const [scenarios, setScenarios] = useState<WarehouseAiScenarioView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [savingKeys, setSavingKeys] = useState<Set<string>>(new Set())
  const auditRef = useRef<ConfigAuditHandle>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getWarehouseAiScenarios()
      setScenarios(data.scenarios ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载 AI 场景配置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehouseAiScenarios()
        if (!cancelled) setScenarios(data.scenarios ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载 AI 场景配置失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  /** 行内补丁（PUT 返回视图覆盖该行）+ 行级锁 */
  const patchRow = useCallback((scenario: string, view: WarehouseAiScenarioView) => {
    setScenarios((prev) =>
      prev ? prev.map((s) => (s.scenario === scenario ? view : s)) : prev,
    )
  }, [])

  const withRowLock = useCallback(
    async (scenario: string, fn: () => Promise<void>) => {
      setSavingKeys((s) => new Set(s).add(scenario))
      try {
        await fn()
      } finally {
        setSavingKeys((s) => {
          const next = new Set(s)
          next.delete(scenario)
          return next
        })
      }
    },
    [],
  )

  const handleToggle = useCallback(
    (row: WarehouseAiScenarioView, enabled: boolean) => {
      if (!canUpdate || savingKeys.has(row.scenario)) return
      const snapshot = row
      void withRowLock(row.scenario, async () => {
        try {
          const view = await updateWarehouseAiScenario(row.scenario, { enabled })
          patchRow(row.scenario, view)
          message.success(enabled ? '已启用，实时生效' : '已停用，该场景 AI 调用将被拦截')
          auditRef.current?.refresh()
        } catch (e) {
          patchRow(row.scenario, snapshot)
          message.error(e instanceof Error ? e.message : '操作失败')
        }
      })
    },
    [canUpdate, savingKeys, withRowLock, patchRow, message],
  )

  const handleBinding = useCallback(
    (row: WarehouseAiScenarioView, value: string) => {
      if (!canUpdate || savingKeys.has(row.scenario)) return
      const snapshot = row
      const model_profile = value === DEFAULT_BINDING ? null : (value as WarehouseProfileName)
      void withRowLock(row.scenario, async () => {
        try {
          const view = await updateWarehouseAiScenario(row.scenario, { model_profile })
          patchRow(row.scenario, view)
          message.success(SAVE_OK_MESSAGE)
          auditRef.current?.refresh()
        } catch (e) {
          patchRow(row.scenario, snapshot)
          message.error(e instanceof Error ? e.message : '保存失败')
        }
      })
    },
    [canUpdate, savingKeys, withRowLock, patchRow, message],
  )

  const columns: ColumnsType<WarehouseAiScenarioView> = [
    {
      title: '场景',
      key: 'scenario',
      width: 220,
      render: (_, r) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: UI.ink }}>
            {scenarioLabel(r.scenario)}
          </span>
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
            {r.scenario}
          </span>
        </div>
      ),
    },
    {
      title: '说明',
      dataIndex: 'description',
      render: (v: string) => <span style={{ fontSize: 13, color: UI.slate }}>{v || '—'}</span>,
    },
    {
      title: '启用',
      key: 'enabled',
      width: 80,
      render: (_, r) => (
        <Switch
          size="small"
          checked={r.enabled}
          loading={savingKeys.has(r.scenario)}
          disabled={!canUpdate}
          data-testid={`wh-scenario-switch-${r.scenario}`}
          onChange={(v) => handleToggle(r, v)}
        />
      ),
    },
    {
      title: '模型绑定',
      key: 'model_profile',
      width: 200,
      render: (_, r) => {
        const allowed = r.allowed_profiles?.length
          ? r.allowed_profiles
          : (['agent', 'agent_backup'] as WarehouseProfileName[])
        return (
          <Select
            size="small"
            style={{ width: 184 }}
            value={r.model_profile ?? DEFAULT_BINDING}
            data-testid={`wh-scenario-binding-${r.scenario}`}
            disabled={!canUpdate || savingKeys.has(r.scenario)}
            options={[
              { value: DEFAULT_BINDING, label: '默认（按场景）' },
              ...allowed.map((p) => ({
                value: p,
                label: `${PROFILE_LABELS[p] ?? p}（${p}）`,
              })),
            ]}
            onChange={(v) => handleBinding(r, v as string)}
          />
        )
      },
    },
    {
      title: '生效模型',
      key: 'effective_profile',
      width: 170,
      render: (_, r) => (
        <Tooltip title="场景绑定 > 场景默认（已解析的实际生效 profile）">
          <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.ink }}>
            {r.effective_profile || '—'}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 84,
      render: (v: string) => <StatusTag enabled={v === 'enabled'} />,
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 110,
      render: (v: string) => <SourceTag source={v} />,
    },
  ]

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
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 调用场景</div>
          <Space size={12}>
            <span style={{ fontSize: 12, color: UI.steel }}>
              开关与模型绑定保存后即时生效（熔断拦截下一次调用）
            </span>
            <Tooltip title="重拉配置">
              <Button
                icon={<ReloadOutlined />}
                onClick={() => void load()}
                loading={loading}
                disabled={savingKeys.size > 0}
                title="刷新"
              />
            </Tooltip>
          </Space>
        </div>

        {loading && scenarios === null ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : loadError ? (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>AI 场景配置加载失败</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : (
          <Table<WarehouseAiScenarioView>
            rowKey="scenario"
            size="small"
            columns={columns}
            dataSource={scenarios ?? []}
            loading={loading}
            scroll={{ x: 1080 }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前无已注册场景" />
              ),
            }}
            pagination={false}
          />
        )}
      </div>

      <ConfigAuditSection ref={auditRef} kind="ai-scenario" />
    </div>
  )
}

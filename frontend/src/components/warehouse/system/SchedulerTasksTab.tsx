'use client'

// 定时任务 Tab：3 行任务表（system_alert 系统告警目标 / draft_expire_stale 草稿过期清扫 /
// reminder_recover 提醒重启恢复）。enabled Switch 即时 PUT（乐观回滚）；
// schedule 行内编辑（事件触发 null / interval 秒数 ≥30 / 高级 cron expr）+ target_chat_id
// （system_alert 行提示 env 兜底 WAREHOUSE_ALERT_CHAT_ID）；行尾「保存」提交 schedule/target。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Empty, Input, InputNumber, Segmented, Skeleton, Switch, Tooltip } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

import { getWarehouseSchedulerTasks, updateWarehouseSchedulerTask } from '@/actions/warehouse'
import type {
  WarehouseSchedule,
  WarehouseSchedulerTaskView,
} from '@/types/warehouse'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import {
  CARD_STYLE,
  MONO_FONT,
  SAVE_OK_MESSAGE,
  UI,
  formatSchedule,
} from './systemConfigConstants'

const MIN_INTERVAL_SECONDS = 30

/** 行内 schedule 编辑态 */
type ScheduleDraft =
  | { kind: 'none' }
  | { kind: 'interval'; seconds: number | null }
  | { kind: 'cron'; expr: string }

function draftFromSchedule(schedule: WarehouseSchedule): ScheduleDraft {
  if (!schedule) return { kind: 'none' }
  if (schedule.type === 'interval') return { kind: 'interval', seconds: schedule.seconds }
  return { kind: 'cron', expr: schedule.expr }
}

/** 行组件：schedule/target 草稿 + 启用开关（以 key={job_name} 挂载，外部刷新经 view prop 重建草稿基线） */
function TaskRow({
  task,
  canUpdate,
  saving,
  onToggle,
  onSaved,
}: {
  task: WarehouseSchedulerTaskView
  canUpdate: boolean
  saving: boolean
  onToggle: (task: WarehouseSchedulerTaskView, enabled: boolean) => void
  onSaved: (view: WarehouseSchedulerTaskView) => void
}) {
  const { message } = App.useApp()
  const [draft, setDraft] = useState<ScheduleDraft>(() => draftFromSchedule(task.schedule))
  const [savingRow, setSavingRow] = useState(false)

  const scheduleDirty =
    JSON.stringify(draftFromSchedule(task.schedule)) !== JSON.stringify(draft)

  const isAlertTarget = task.job_name === 'system_alert'

  type ScheduleBuildResult =
    | { ok: true; schedule: WarehouseSchedule }
    | { ok: false; error: string }

  const buildSchedule = (): ScheduleBuildResult => {
    if (draft.kind === 'none') return { ok: true, schedule: null }
    if (draft.kind === 'interval') {
      if (draft.seconds == null || draft.seconds < MIN_INTERVAL_SECONDS) {
        return { ok: false, error: `间隔必须 ≥ ${MIN_INTERVAL_SECONDS} 秒` }
      }
      return { ok: true, schedule: { type: 'interval', seconds: Math.round(draft.seconds) } }
    }
    if (!draft.expr.trim()) return { ok: false, error: 'cron expr 不能为空' }
    return { ok: true, schedule: { type: 'cron', expr: draft.expr.trim() } }
  }

  const handleSave = async () => {
    const built = buildSchedule()
    if (!built.ok) {
      message.error(built.error)
      return
    }
    setSavingRow(true)
    try {
      const view = await updateWarehouseSchedulerTask(task.job_name, { schedule: built.schedule })
      message.success(SAVE_OK_MESSAGE)
      onSaved(view)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSavingRow(false)
    }
  }

  const scheduleOptions = [
    { label: '事件触发', value: 'none' },
    { label: '固定间隔', value: 'interval' },
    { label: 'Cron（高级）', value: 'cron' },
  ]

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
      data-testid={`wh-scheduler-row-${task.job_name}`}
    >
      {/* 任务名 */}
      <div style={{ width: 250, minWidth: 220, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: UI.ink }}>{task.label}</span>
          <span style={{ fontFamily: MONO_FONT, fontSize: 11, color: UI.muted }}>
            {task.job_name}
          </span>
        </div>
        <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>{task.description}</div>
      </div>

      {/* 启用开关 */}
      <div style={{ width: 60, flexShrink: 0, paddingTop: 2 }}>
        <Switch
          size="small"
          checked={task.enabled}
          loading={saving}
          disabled={!canUpdate}
          onChange={(v) => onToggle(task, v)}
        />
      </div>

      {/* schedule 编辑 */}
      <div style={{ flex: 1, minWidth: 300 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Segmented
            size="small"
            options={scheduleOptions}
            value={draft.kind}
            onChange={(v) => {
              const kind = v as ScheduleDraft['kind']
              if (kind === 'none') setDraft({ kind: 'none' })
              else if (kind === 'interval')
                setDraft({
                  kind: 'interval',
                  seconds:
                    draft.kind === 'interval' ? draft.seconds : (task.schedule?.type === 'interval' ? task.schedule.seconds : 300),
                })
              else
                setDraft({
                  kind: 'cron',
                  expr: draft.kind === 'cron' ? draft.expr : '',
                })
            }}
            disabled={!canUpdate}
          />
          {draft.kind === 'interval' ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <InputNumber
                size="small"
                min={MIN_INTERVAL_SECONDS}
                precision={0}
                value={draft.seconds}
                disabled={!canUpdate}
                style={{ width: 110 }}
                onChange={(v) => setDraft({ kind: 'interval', seconds: v })}
              />
              <span style={{ fontSize: 12, color: UI.steel }}>秒（≥30）</span>
            </span>
          ) : null}
          {draft.kind === 'cron' ? (
            <Input
              size="small"
              value={draft.expr}
              disabled={!canUpdate}
              placeholder="cron 表达式，如 0 8 * * *"
              style={{ width: 200, fontFamily: MONO_FONT }}
              onChange={(e) => setDraft({ kind: 'cron', expr: e.target.value })}
            />
          ) : null}
        </div>
        <div style={{ fontSize: 11, color: UI.muted, marginTop: 4 }}>
          当前生效：{formatSchedule(task.schedule)}
          {draft.kind === 'none' && task.schedule !== null ? '（提交后停止周期调度）' : ''}
        </div>
      </div>

      {/* 告警目标 */}
      <div style={{ width: 260, minWidth: 220, flexShrink: 0 }}>
        {isAlertTarget ? (
          <>
            <AlertTargetInput task={task} canUpdate={canUpdate} onSaved={onSaved} />
            <div style={{ fontSize: 11, color: UI.muted, marginTop: 4 }}>
              留空回退环境变量 WAREHOUSE_ALERT_CHAT_ID
            </div>
          </>
        ) : (
          <span style={{ fontSize: 12, color: UI.muted }}>—</span>
        )}
      </div>

      {/* 保存 */}
      <div style={{ flexShrink: 0, paddingTop: 2 }}>
        <Button
          size="small"
          type="primary"
          loading={savingRow}
          disabled={!canUpdate || !scheduleDirty}
          onClick={() => void handleSave()}
        >
          保存
        </Button>
      </div>
    </div>
  )
}

/** system_alert 的告警目标输入（独立小状态，回车/失焦提交 PUT {target_chat_id}） */
function AlertTargetInput({
  task,
  canUpdate,
  onSaved,
}: {
  task: WarehouseSchedulerTaskView
  canUpdate: boolean
  onSaved: (view: WarehouseSchedulerTaskView) => void
}) {
  const { message } = App.useApp()
  const [value, setValue] = useState(task.target_chat_id ?? '')
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    const text = value.trim()
    if (text === String(task.target_chat_id ?? '')) return
    setSaving(true)
    try {
      const view = await updateWarehouseSchedulerTask(task.job_name, {
        target_chat_id: text || null, // 空串 = 清空覆盖（回退 env）
      })
      message.success(SAVE_OK_MESSAGE)
      onSaved(view)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
      setValue(task.target_chat_id ?? '')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Input.Search
      size="small"
      enterButton="保存"
      value={value}
      disabled={!canUpdate || saving}
      placeholder="告警目标群 chat_id"
      style={{ fontFamily: MONO_FONT }}
      onChange={(e) => setValue(e.target.value)}
      onSearch={() => void submit()}
      data-testid="wh-scheduler-target"
    />
  )
}

export default function SchedulerTasksTab({ canUpdate }: { canUpdate: boolean }) {
  const { message } = App.useApp()
  const [tasks, setTasks] = useState<WarehouseSchedulerTaskView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [togglingKeys, setTogglingKeys] = useState<Set<string>>(new Set())
  const auditRef = useRef<ConfigAuditHandle>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getWarehouseSchedulerTasks()
      setTasks(data.tasks ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载定时任务失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehouseSchedulerTasks()
        if (!cancelled) setTasks(data.tasks ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载定时任务失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleToggle = useCallback(
    async (task: WarehouseSchedulerTaskView, enabled: boolean) => {
      if (!canUpdate || togglingKeys.has(task.job_name)) return
      setTogglingKeys((s) => new Set(s).add(task.job_name))
      try {
        const view = await updateWarehouseSchedulerTask(task.job_name, { enabled })
        setTasks((prev) =>
          prev ? prev.map((t) => (t.job_name === view.job_name ? view : t)) : prev,
        )
        message.success(enabled ? '已启用，实时生效' : '已停用，任务不再触发')
        auditRef.current?.refresh()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '操作失败')
      } finally {
        setTogglingKeys((s) => {
          const next = new Set(s)
          next.delete(task.job_name)
          return next
        })
      }
    },
    [canUpdate, togglingKeys, message],
  )

  const handleSaved = useCallback((view: WarehouseSchedulerTaskView) => {
    setTasks((prev) => (prev ? prev.map((t) => (t.job_name === view.job_name ? view : t)) : prev))
    auditRef.current?.refresh()
  }, [])

  const rows = tasks ?? []

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
            marginBottom: 4,
          }}
        >
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>定时任务与告警目标</div>
            <div style={{ fontSize: 12, color: UI.steel, marginTop: 2 }}>
              开关与频率保存后即时生效，无需重启
            </div>
          </div>
          <Tooltip title="重拉任务配置">
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading} title="刷新" />
          </Tooltip>
        </div>

        {loading && tasks === null ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : loadError ? (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>定时任务加载失败</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : rows.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有定时任务" />
        ) : (
          <div style={{ marginTop: 8 }}>
            {rows.map((t) => (
              <TaskRow
                key={t.job_name}
                task={t}
                canUpdate={canUpdate}
                saving={togglingKeys.has(t.job_name)}
                onToggle={(task, enabled) => void handleToggle(task, enabled)}
                onSaved={handleSaved}
              />
            ))}
          </div>
        )}
      </div>

      <ConfigAuditSection ref={auditRef} kind="scheduler" />
    </div>
  )
}

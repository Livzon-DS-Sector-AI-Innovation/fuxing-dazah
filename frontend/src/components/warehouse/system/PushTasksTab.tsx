'use client'

// 推送任务 Tab（V3.0 分期A 推送订阅中心）：5 行任务表（晨报/周报/月报/清单/快递通知）。
// enabled Switch 即时 PUT（乐观回滚）；目标列表（逗号分隔 chat_id/open_id）回车/按钮保存；
// 手动触发（可选演练模式 dry_run 不真发，上线前验证链路）；频率只读展示（registry 默认，
// 需调整走 API）。保存/启停后顶刷审计区。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Checkbox, Collapse, Empty, Input, Skeleton, Switch, Table, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined, SendOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import {
  getWarehousePushLogs,
  getWarehousePushTasks,
  triggerWarehousePushTask,
  updateWarehousePushTask,
} from '@/actions/warehouse'
import type {
  WarehousePushLogEntry,
  WarehousePushSchedule,
  WarehousePushTaskView,
} from '@/types/warehouse'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import { CARD_STYLE, MONO_FONT, SAVE_OK_MESSAGE, UI } from './systemConfigConstants'

const WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日'] as const

/** 频率展示（只读；schedule 结构见后端 push_center registry） */
function formatPushSchedule(schedule: WarehousePushSchedule): string {
  if (!schedule) return '事件触发'
  switch (schedule.type) {
    case 'daily':
      return `每日 ${schedule.time}`
    case 'weekly':
      return `每周${WEEKDAY_NAMES[schedule.weekday] ?? '?'} ${schedule.time}`
    case 'monthly':
      return `每月 ${schedule.day} 日 ${schedule.time}`
    case 'interval':
      return `每 ${schedule.seconds} 秒`
  }
}

/** 触发状态 → 展示文案 */
const TRIGGER_STATUS_TEXT: Record<string, string> = {
  executed: '推送已执行',
  failed: '推送失败（详见推送日志）',
  skipped_no_target: '未执行：目标未配置',
  skipped_disabled: '未执行：任务已停用',
  skipped_busy: '未执行：上一轮仍在进行',
  skipped_not_scheduled: '未执行：事件型任务不支持手动定时触发',
}

/** 行组件：启停 + 目标编辑 + 手动触发（以 key={task_name} 挂载，外部刷新经 view prop 重建基线） */
function TaskRow({
  task,
  canUpdate,
  saving,
  onToggle,
  onSaved,
}: {
  task: WarehousePushTaskView
  canUpdate: boolean
  saving: boolean
  onToggle: (task: WarehousePushTaskView, enabled: boolean) => void
  onSaved: (view: WarehousePushTaskView) => void
}) {
  const { message } = App.useApp()
  const [targetDraft, setTargetDraft] = useState(task.targets.join(','))
  const [savingTargets, setSavingTargets] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [dryRun, setDryRun] = useState(false)

  const targetDirty = targetDraft.trim() !== task.targets.join(',')

  const saveTargets = async () => {
    const text = targetDraft.trim()
    if (!targetDirty) return
    setSavingTargets(true)
    try {
      const view = await updateWarehousePushTask(task.task_name, {
        targets: text || null, // 空串 = 清空覆盖（回退 env 兜底）
      })
      message.success(SAVE_OK_MESSAGE)
      onSaved(view)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
      setTargetDraft(task.targets.join(','))
    } finally {
      setSavingTargets(false)
    }
  }

  const handleTrigger = async () => {
    if (triggering) return
    setTriggering(true)
    try {
      const result = await triggerWarehousePushTask(task.task_name, dryRun)
      const text = TRIGGER_STATUS_TEXT[result.status] ?? `触发完成（${result.status}）`
      if (result.status === 'executed') {
        message.success(text + (dryRun ? '（演练，未真发）' : ''))
      } else if (result.status === 'failed') {
        message.error(text)
      } else {
        message.warning(text)
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '触发失败')
    } finally {
      setTriggering(false)
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
      data-testid={`wh-push-row-${task.task_name}`}
    >
      {/* 任务名 */}
      <div style={{ width: 250, minWidth: 220, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: UI.ink }}>{task.label}</span>
          <span style={{ fontFamily: MONO_FONT, fontSize: 11, color: UI.muted }}>
            {task.task_name}
          </span>
        </div>
        <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>{task.description}</div>
        <div style={{ fontSize: 11, color: UI.muted, marginTop: 2 }}>
          频率：{formatPushSchedule(task.schedule)}
        </div>
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

      {/* 目标列表 */}
      <div style={{ flex: 1, minWidth: 280 }}>
        <Input.Search
          size="small"
          enterButton="保存"
          value={targetDraft}
          disabled={!canUpdate || savingTargets}
          loading={savingTargets}
          placeholder="推送目标（逗号分隔：群 chat_id / 个人 open_id），留空回退环境变量"
          style={{ fontFamily: MONO_FONT, maxWidth: 420 }}
          onChange={(e) => setTargetDraft(e.target.value)}
          onSearch={() => void saveTargets()}
          data-testid={`wh-push-target-${task.task_name}`}
        />
        <div style={{ fontSize: 11, color: UI.muted, marginTop: 4 }}>
          当前生效：{task.targets.length > 0 ? task.targets.join('，') : '未配置（回退 env）'}
        </div>
      </div>

      {/* 手动触发 */}
      <div style={{ flexShrink: 0, paddingTop: 2, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Checkbox
          checked={dryRun}
          disabled={!canUpdate || triggering}
          onChange={(e) => setDryRun(e.target.checked)}
        >
          <span style={{ fontSize: 12, color: UI.steel }}>演练</span>
        </Checkbox>
        <Tooltip title="立即执行一次（绕过定时，仍写推送日志）">
          <Button
            size="small"
            icon={<SendOutlined />}
            loading={triggering}
            disabled={!canUpdate || !task.enabled}
            onClick={() => void handleTrigger()}
            data-testid={`wh-push-trigger-${task.task_name}`}
          >
            手动推送
          </Button>
        </Tooltip>
      </div>
    </div>
  )
}

/** 推送日志区（懒加载：首次展开才取数；最近 50 条，含失败原因） */
function PushLogsSection({ taskName }: { taskName: string | undefined }) {
  const [logs, setLogs] = useState<WarehousePushLogEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getWarehousePushLogs({ page_size: 50, task_name: taskName })
      setLogs(data.items ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载推送日志失败')
    } finally {
      setLoading(false)
    }
  }, [taskName])

  const columns: ColumnsType<WarehousePushLogEntry> = [
    { title: '时间', dataIndex: 'created_at', width: 140, render: (v: string) => (v ? dayjs(v).format('MM-DD HH:mm:ss') : '-') },
    { title: '任务', dataIndex: 'task_name', width: 150, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: string) => (
        <span style={{ color: v === 'success' ? 'var(--wh-ok)' : v === 'failed' ? 'var(--wh-danger)' : 'var(--wh-warn)' }}>
          {v === 'success' ? '成功' : v === 'failed' ? '失败' : '跳过'}
        </span>
      ),
    },
    { title: '目标', dataIndex: 'target', width: 150, ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '触发', dataIndex: 'trigger', width: 90 },
    { title: '原因/错误', dataIndex: 'error', ellipsis: true, render: (v: string | null) => v ?? '-' },
  ]

  return (
    <Collapse
      ghost
      items={[
        {
          key: 'logs',
          label: <span style={{ fontSize: 13, color: UI.ink }}>推送日志（最近 50 条）</span>,
          children: (
            <>
              {error ? (
                <Alert
                  type="error" showIcon
                  message={<span style={{ fontSize: 12 }}>推送日志加载失败</span>}
                  description={<span style={{ fontSize: 12, color: UI.muted }}>{error}</span>}
                  action={<Button size="small" onClick={() => void load()}>重试</Button>}
                  style={{ marginBottom: 8 }}
                />
              ) : null}
              {loading && logs === null ? (
                <Skeleton active paragraph={{ rows: 4 }} />
              ) : logs && logs.length > 0 ? (
                <Table<WarehousePushLogEntry>
                  rowKey="id"
                  size="small"
                  columns={columns}
                  dataSource={logs}
                  pagination={false}
                  scroll={{ x: 720 }}
                />
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  暂无推送记录
                </Typography.Text>
              )}
            </>
          ),
        },
      ]}
      onChange={openKeys => {
        if (openKeys.length > 0 && logs === null && !loading) void load()
      }}
    />
  )
}

export default function PushTasksTab({ canUpdate }: { canUpdate: boolean }) {
  const { message } = App.useApp()
  const [tasks, setTasks] = useState<WarehousePushTaskView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [togglingKeys, setTogglingKeys] = useState<Set<string>>(new Set())
  const auditRef = useRef<ConfigAuditHandle>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getWarehousePushTasks()
      setTasks(data.tasks ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载推送任务失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehousePushTasks()
        if (!cancelled) setTasks(data.tasks ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载推送任务失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleToggle = useCallback(
    async (task: WarehousePushTaskView, enabled: boolean) => {
      if (!canUpdate || togglingKeys.has(task.task_name)) return
      setTogglingKeys((s) => new Set(s).add(task.task_name))
      try {
        const view = await updateWarehousePushTask(task.task_name, { enabled })
        setTasks((prev) =>
          prev ? prev.map((t) => (t.task_name === view.task_name ? view : t)) : prev,
        )
        message.success(enabled ? '已启用，实时生效' : '已停用，任务不再触发')
        auditRef.current?.refresh()
      } catch (e) {
        message.error(e instanceof Error ? e.message : '操作失败')
      } finally {
        setTogglingKeys((s) => {
          const next = new Set(s)
          next.delete(task.task_name)
          return next
        })
      }
    },
    [canUpdate, togglingKeys, message],
  )

  const handleSaved = useCallback((view: WarehousePushTaskView) => {
    setTasks((prev) =>
      prev ? prev.map((t) => (t.task_name === view.task_name ? view : t)) : prev,
    )
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
            <div style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>推送任务</div>
            <div style={{ fontSize: 12, color: UI.steel, marginTop: 2 }}>
              晨报 / 周报 / 月报 / 呆滞与不合格清单定时推送，快递通知事件推送；目标与开关保存后即时生效
            </div>
          </div>
          <Tooltip title="重拉推送任务配置">
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading} title="刷新" />
          </Tooltip>
        </div>

        {loading && tasks === null ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : loadError ? (
          <Alert
            type="error"
            showIcon
            message={<span style={{ fontSize: 13 }}>推送任务加载失败</span>}
            description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
            action={
              <Button size="small" onClick={() => void load()}>
                重试
              </Button>
            }
          />
        ) : rows.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有推送任务" />
        ) : (
          <div style={{ marginTop: 8 }}>
            {rows.map((t) => (
              <TaskRow
                key={t.task_name}
                task={t}
                canUpdate={canUpdate}
                saving={togglingKeys.has(t.task_name)}
                onToggle={(task, enabled) => void handleToggle(task, enabled)}
                onSaved={handleSaved}
              />
            ))}
          </div>
        )}
      </div>

      <ConfigAuditSection ref={auditRef} kind="push" />
      <div style={{ ...CARD_STYLE, padding: 8, marginTop: 12 }}>
        <PushLogsSection taskName={undefined} />
      </div>
    </div>
  )
}

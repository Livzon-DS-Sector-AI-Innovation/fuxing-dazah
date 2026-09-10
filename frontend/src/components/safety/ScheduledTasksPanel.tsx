'use client'

// 定时任务页 — 查看 + 管理（发送对象展示「生效值」，来源：DB 覆写 > env > 代码默认）
// 视觉严格对齐 dazah-frontend/DESIGN.md（Notion 设计系统 tokens）

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Empty,
  Input,
  Select,
  Skeleton,
  Space,
  Table,
  Tooltip,
} from 'antd'
import {
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { fetchScheduledTasks } from '@/actions/safety'
import type { SchedulerRunState, ScheduledTask } from '@/types/safety'
import ScheduledTaskEditDrawer from './ScheduledTaskEditDrawer'
import {
  CARD_STYLE,
  MONO_FONT,
  UI,
  RunStateTag,
  StatusTag,
  formatCronText,
} from './schedulerConfigConstants'

const STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '启用', value: 'enabled' },
  { label: '停用', value: 'disabled' },
]

const RUN_STATUS_OPTIONS = [
  { label: '全部', value: 'all' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
  { label: '待触发', value: 'pending' },
]

const runStatusOf = (runState?: SchedulerRunState | null): 'success' | 'failed' | 'pending' => {
  if (!runState || !runState.status) return 'pending'
  return runState.status
}

function TargetCell({ task }: { task: ScheduledTask }) {
  const { target_chat_id: id, target_chat_name: name, target_type: type } = task
  const isPerson = type === 'person'
  const dynamic = isPerson && !id // 个人动态名单（如消防报警私发：涉及部门负责人+安全员）
  const typeUi = isPerson
    ? { label: '个人', bg: UI.lavender, color: '#5645d4' }
    : { label: '群聊', bg: UI.sky, color: '#005bab' }
  return (
    <Tooltip
      title={
        id
          ? `${name ?? id}（${id}）｜${isPerson ? '个人 DM' : '群聊'}`
          : dynamic
            ? '个人目标（动态名单：涉及部门负责人+分管安全员）'
            : '该任务未配置发送对象（结果走个人通知 / 仅落库）'
      }
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 13, color: name ? UI.ink : UI.slate }}>
          {dynamic ? '个人（动态名单）' : name || id || '—'}
        </span>
        <span
          style={{
            background: typeUi.bg,
            color: typeUi.color,
            fontSize: 11,
            fontWeight: 600,
            lineHeight: '17px',
            padding: '0 6px',
            borderRadius: 4,
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          {typeUi.label}
        </span>
      </span>
    </Tooltip>
  )
}

export default function ScheduledTasksPanel() {
  const { message } = App.useApp()

  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [loading, setLoading] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [runFilter, setRunFilter] = useState<string>('all')
  const [editTask, setEditTask] = useState<ScheduledTask | null>(null)
  const [editOpen, setEditOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchScheduledTasks()
      if (res.code >= 200 && res.code < 300) {
        setTasks(res.data ?? [])
      } else {
        message.error(res.message || '加载定时任务失败')
      }
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return tasks.filter((t) => {
      if (statusFilter === 'enabled' && !t.enabled) return false
      if (statusFilter === 'disabled' && t.enabled) return false
      if (runFilter !== 'all' && runStatusOf(t.run_state) !== runFilter) return false
      if (
        kw &&
        !(
          t.job_name.toLowerCase().includes(kw) ||
          (t.description ?? '').toLowerCase().includes(kw) ||
          (t.target_chat_name ?? '').toLowerCase().includes(kw) ||
          (t.target_chat_id ?? '').toLowerCase().includes(kw)
        )
      )
        return false
      return true
    })
  }, [tasks, keyword, statusFilter, runFilter])

  const columns: ColumnsType<ScheduledTask> = [
    {
      title: '任务名',
      key: 'job_name',
      width: 250,
      render: (_, r) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, color: UI.ink }}>
            {r.report_type && <FileTextOutlined style={{ color: UI.primary, fontSize: 12 }} />}
            {r.job_name}
          </span>
          <span
            style={{
              fontSize: 12,
              color: UI.muted,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: 240,
            }}
          >
            {r.description || '—'}
          </span>
        </div>
      ),
    },
    {
      title: '执行计划',
      key: 'schedule',
      width: 150,
      render: (_, r) => (
        <span style={{ fontFamily: MONO_FONT, fontSize: 13, color: UI.ink, whiteSpace: 'nowrap' }}>
          {formatCronText(r.hour, r.minute, r.dow)}
        </span>
      ),
    },
    {
      title: '发送对象',
      key: 'target',
      width: 220,
      render: (_, r) => <TargetCell task={r} />,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 84,
      render: (v: boolean) => <StatusTag enabled={v} />,
    },
    {
      title: '今日运行',
      dataIndex: 'run_state',
      key: 'run_state',
      width: 120,
      render: (v: SchedulerRunState | null | undefined) => <RunStateTag runState={v} />,
    },
    {
      title: '操作',
      key: 'action',
      width: 232,
      render: (_: unknown, r) => (
        <Space size={6}>
          <Tooltip title="编辑任务配置">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setEditTask(r)
                setEditOpen(true)
              }}
            >
              编辑
            </Button>
          </Tooltip>
          <Tooltip title={r.report_type ? '预览报告内容' : '该任务暂不支持预览'}>
            <Button size="small" icon={<EyeOutlined />} disabled={!r.report_type}>
              预览
            </Button>
          </Tooltip>
          <Tooltip title="立即执行一次（真实推送）">
            <Button size="small" icon={<PlayCircleOutlined />} danger>
              执行一次
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ]

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
          marginBottom: 20,
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>定时任务</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            安全模块定时任务查看与管理
          </div>
        </div>
        <Space size={12}>
          <span style={{ fontSize: 12, color: UI.steel }}>
            配置变更实时生效，无需重启
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} title="刷新" />
        </Space>
      </div>

      {/* ── FilterBar ── */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
        <Input.Search
          placeholder="任务名 / 描述 / 发送对象"
          style={{ width: 280 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
        />
        <Select
          style={{ width: 110 }}
          options={STATUS_OPTIONS}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as string)}
        />
        <Select
          style={{ width: 120 }}
          options={RUN_STATUS_OPTIONS}
          value={runFilter}
          onChange={(v) => setRunFilter(v as string)}
        />
        <span style={{ fontSize: 12, color: UI.steel }}>共 {filtered.length} 个任务</span>
      </div>

      {/* ── 表格卡 ── */}
      <div style={{ ...CARD_STYLE, padding: 16 }}>
        {loading && tasks.length === 0 ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : (
          <Table<ScheduledTask>
            rowKey="job_name"
            size="middle"
            loading={loading}
            columns={columns}
            dataSource={filtered}
            scroll={{ x: 1060 }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前没有定时任务"
                />
              ),
            }}
            pagination={false}
          />
        )}
      </div>

      <ScheduledTaskEditDrawer
        open={editOpen}
        task={editTask}
        onClose={() => setEditOpen(false)}
        onSaved={() => void load()}
      />
    </div>
  )
}

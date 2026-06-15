'use client'

import { useState } from 'react'
import {
  Button,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  PlusOutlined,
  PlayCircleOutlined,
  EditOutlined,
  DeleteOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import type { ScheduledTask } from '@/types/safety'
import {
  deleteScheduledTask,
  toggleScheduledTask,
  runScheduledTaskNow,
  getScheduledTasks,
} from '@/actions/safety'
import ScheduledTaskLogDrawer from './ScheduledTaskLogDrawer'

interface ScheduledTaskListProps {
  initialData: ScheduledTask[]
  initialTotal: number
}

export default function ScheduledTaskList({ initialData, initialTotal }: ScheduledTaskListProps) {
  const router = useRouter()
  const [tasks, setTasks] = useState<ScheduledTask[]>(initialData)
  const [total, setTotal] = useState(initialTotal)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [logDrawer, setLogDrawer] = useState<{ open: boolean; taskId: string; taskName: string }>({
    open: false,
    taskId: '',
    taskName: '',
  })

  const fetchTasks = async (p: number) => {
    setLoading(true)
    try {
      const res = await getScheduledTasks({ page: p, page_size: 20 })
      if (res.code === 200 && res.data) {
        setTasks(res.data)
        setTotal(res.meta?.total || 0)
      }
    } catch {
      message.error('获取任务列表失败')
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (id: string, enabled: boolean) => {
    const res = await toggleScheduledTask(id, enabled)
    if (res.code === 200) {
      message.success(enabled ? '已启用' : '已禁用')
      setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, is_enabled: enabled } : t)))
    } else {
      message.error('操作失败')
    }
  }

  const handleRun = async (id: string) => {
    const res = await runScheduledTaskNow(id)
    if (res.code === 200) {
      message.success('已触发执行')
      fetchTasks(page)
    } else {
      message.error('执行失败: ' + (res.message || '未知错误'))
    }
  }

  const handleDelete = async (id: string) => {
    const res = await deleteScheduledTask(id)
    if (res.code === 200) {
      message.success('已删除')
      fetchTasks(page)
    } else {
      message.error('删除失败')
    }
  }

  const statusColors: Record<string, string> = {
    success: 'success',
    failure: 'error',
  }

  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      width: 200,
      ellipsis: true,
      render: (v: string, r: ScheduledTask) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{v}</span>
          {r.cron_desc && <span style={{ fontSize: 12, color: '#999' }}>{r.cron_desc}</span>}
        </Space>
      ),
    },
    {
      title: 'Cron 表达式',
      dataIndex: 'cron_expression',
      width: 130,
      render: (v: string) => <code>{v}</code>,
    },
    {
      title: '目标群聊',
      dataIndex: 'feishu_chat_name',
      width: 130,
      ellipsis: true,
      render: (v: string | undefined) => v || '-',
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      width: 60,
      render: (v: boolean, r: ScheduledTask) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(r.id, checked)} />
      ),
    },
    {
      title: '上次执行',
      width: 170,
      render: (_: unknown, r: ScheduledTask) => (
        <Space direction="vertical" size={0}>
          {r.last_run_at ? (
            <span style={{ fontSize: 13 }}>
              {new Date(r.last_run_at).toLocaleString('zh-CN')}
            </span>
          ) : (
            <span style={{ color: '#999' }}>-</span>
          )}
          {r.last_run_status && (
            <Tag
              color={statusColors[r.last_run_status] || 'default'}
              style={{ fontSize: 11 }}
            >
              {r.last_run_status === 'success' ? '成功' : r.last_run_status === 'failure' ? '失败' : r.last_run_status}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '下次执行',
      dataIndex: 'next_run_at',
      width: 170,
      render: (v: string | undefined) =>
        v ? new Date(v).toLocaleString('zh-CN') : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '操作',
      width: 200,
      render: (_: unknown, r: ScheduledTask) => (
        <Space size="small">
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleRun(r.id)}
            title="立即执行"
          />
          <Button
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => setLogDrawer({ open: true, taskId: r.id, taskName: r.name })}
            title="查看日志"
          />
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => router.push(`/safety/scheduled-tasks/${r.id}`)}
            title="编辑"
          />
          <Popconfirm
            title="确定删除此定时任务？"
            onConfirm={() => handleDelete(r.id)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} title="删除" />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Typography.Text type="secondary">
          共 {total} 个定时任务，调度器每30秒检查一次到期任务
        </Typography.Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => router.push('/safety/scheduled-tasks/new')}>
          新建任务
        </Button>
      </div>
      <Table
        dataSource={tasks}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="middle"
        pagination={{
          current: page,
          pageSize: 20,
          total,
          onChange: (p) => {
            setPage(p)
            fetchTasks(p)
          },
          showTotal: (t) => `共 ${t} 个任务`,
        }}
      />
      <ScheduledTaskLogDrawer
        open={logDrawer.open}
        taskId={logDrawer.taskId}
        taskName={logDrawer.taskName}
        onClose={() => setLogDrawer({ open: false, taskId: '', taskName: '' })}
      />
    </>
  )
}

'use client'

// 督办留痕面板（方向 C）—— 系统配置第 7 个 Tab。
// 数据=底座留痕表聚合：按隐患的催办发送（outbox 留痕行）+ 表单提交（trigger）。
// 交互：窗口切换（7/30/90 天）+ 编号/record_id 检索 + 行展开时间线（懒加载）。

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Empty,
  Input,
  Segmented,
  Table,
  Tag,
  Timeline,
  Tooltip,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

import { getHazardAuditTimeline, listHazardAudit } from '@/actions/safety'
import type { HazardAuditEvent, HazardAuditItem } from '@/types/safety'
import { UI } from '../schedulerConfigConstants'

const RANGE_OPTIONS = [
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' },
]

const fmt = (at: string | null | undefined) =>
  at ? dayjs(at).format('MM-DD HH:mm') : '—'

function EventTimeline({ events }: { events: HazardAuditEvent[] }) {
  if (!events.length) {
    return <Empty description="窗口内无留痕事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  return (
    <Timeline
      style={{ marginTop: 8, marginBottom: 0 }}
      items={events.map((e) => {
        if (e.kind === 'dunning') {
          return {
            color: 'blue',
            children: (
              <span style={{ fontSize: 13, color: UI.ink }}>
                <Tag color="blue" style={{ marginRight: 6 }}>催办卡</Tag>
                {fmt(e.at)}　发送 → {e.role} {e.name}
                <span style={{ color: UI.steel, fontSize: 12, marginLeft: 6 }}>
                  {e.receive_id}
                </span>
              </span>
            ),
          }
        }
        const failed = e.outcome === 'failed'
        return {
          color: failed ? 'red' : 'green',
          children: (
            <span style={{ fontSize: 13, color: UI.ink }}>
              <Tag color={failed ? 'red' : 'green'} style={{ marginRight: 6 }}>
                {failed ? '提交失败' : '提交'}
              </Tag>
              {fmt(e.at)}　{e.operator || '—'}：{e.text}
            </span>
          ),
        }
      })}
    />
  )
}

export default function HazardAuditPanel() {
  const { message } = App.useApp()
  const [days, setDays] = useState('30')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<HazardAuditItem[]>([])
  const [timelineByRecord, setTimelineByRecord] = useState<Record<string, HazardAuditEvent[]>>({})

  const load = useCallback(
    async (nextDays?: string) => {
      setLoading(true)
      try {
        const res = await listHazardAudit({
          days: Number(nextDays ?? days),
          keyword: keyword.trim() || undefined,
        })
        if (res.code === 200) {
          setItems(res.data ?? [])
        } else {
          message.error(res.message || '查询失败')
        }
      } finally {
        setLoading(false)
      }
    },
    [days, keyword, message],
  )

  useEffect(() => {
    void load()
    // 仅窗口变化自动刷新；关键词按显式搜索/防手滑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days])

  const expandTimeline = async (record: HazardAuditItem) => {
    if (timelineByRecord[record.record_id]) return
    const res = await getHazardAuditTimeline(record.record_id)
    if (res.code === 200) {
      setTimelineByRecord((prev) => ({
        ...prev,
        [record.record_id]: res.data ?? [],
      }))
    } else {
      message.error(res.message || '时间线查询失败')
    }
  }

  const columns: ColumnsType<HazardAuditItem> = [
    {
      title: '隐患编号',
      dataIndex: 'hazard_no',
      width: 150,
      render: (no: string, r) =>
        no || <span style={{ color: UI.steel }}>{r.record_id.slice(0, 14)}…</span>,
    },
    {
      title: '催办',
      width: 130,
      align: 'center',
      render: (_, r) => (
        <span>
          {r.dunning_count} 次
          <span style={{ color: UI.steel, fontSize: 12, marginLeft: 4 }}>
            / {r.dunning_recipient_count} 人
          </span>
        </span>
      ),
    },
    {
      title: '提交',
      width: 110,
      align: 'center',
      render: (_, r) => (
        <span>
          {r.submission_count} 次
          {r.submission_failed > 0 && (
            <Tooltip title={`含 ${r.submission_failed} 次失败`}>
              <Tag color="red" style={{ marginLeft: 4 }}>{r.submission_failed} 败</Tag>
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      title: '最近提交',
      ellipsis: true,
      render: (_, r) =>
        r.last_submission ? (
          <span style={{ fontSize: 13 }}>
            <span style={{ color: UI.slate }}>{fmt(r.last_submission.at)}</span>
            　{r.last_submission.operator || '—'}：{r.last_submission.text}
          </span>
        ) : (
          <span style={{ color: UI.steel }}>未提交</span>
        ),
    },
    {
      title: '最近活动',
      dataIndex: 'last_activity_at',
      width: 120,
      render: (at: string | null) => (
        <span style={{ color: UI.slate, fontSize: 12 }}>{fmt(at)}</span>
      ),
    },
  ]

  return (
    <div style={{ paddingTop: 4 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, alignItems: 'center' }}>
        <Segmented options={RANGE_OPTIONS} value={days} onChange={(v) => setDays(String(v))} />
        <Input.Search
          placeholder="隐患编号 / record_id"
          style={{ width: 260 }}
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={() => void load()}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
          刷新
        </Button>
        <span style={{ color: UI.steel, fontSize: 12, marginLeft: 'auto' }}>
          催办发送与表单提交的结构化留痕（台账原文见隐患台账「目前进展」）
        </span>
      </div>
      <Table<HazardAuditItem>
        rowKey="record_id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={items}
        locale={{ emptyText: <Empty description="窗口内无督办留痕（开关开启后自动积累）" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 条隐患` }}
        expandable={{
          onExpand: (_, record) => void expandTimeline(record),
          expandedRowRender: (record) => (
            <EventTimeline events={timelineByRecord[record.record_id] ?? []} />
          ),
        }}
      />
    </div>
  )
}

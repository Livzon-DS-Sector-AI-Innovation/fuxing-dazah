'use client'

// 五金库温湿度日检（二期 M5）：快捷录入（当日 upsert 幂等）+ 近 30 天记录。
// 每日 17:00 定时提醒当天未填。设计 §2.6。

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Button, Card, DatePicker, Input, InputNumber, Space, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import {
  fetchHardwareEnvLogsClient,
  upsertHardwareEnvLogClient,
} from '@/lib/api/warehouse-hardware'
import type { HardwareEnvLogRecord } from '@/types/warehouse-hardware'
import { usePermission } from '@/hooks/usePermission'
import { PageHeader } from '@/components/warehouse'

export function HardwareEnvDailyBoard() {
  const { message } = App.useApp()
  const qc = useQueryClient()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('warehouse:hardware:env:manage')

  const [date, setDate] = useState<Dayjs>(dayjs())
  const [temperature, setTemperature] = useState<number | null>(null)
  const [humidity, setHumidity] = useState<number | null>(null)
  const [checker, setChecker] = useState('')
  const [note, setNote] = useState('')

  const logs = useQuery({
    queryKey: ['hardware-env-logs'],
    queryFn: () => fetchHardwareEnvLogsClient(30),
  })

  const upsertMut = useMutation({
    mutationFn: () =>
      upsertHardwareEnvLogClient({
        log_date: date.format('YYYY-MM-DD'),
        temperature: temperature ?? undefined,
        humidity: humidity ?? undefined,
        checked_by: checker.trim() || undefined,
        abnormal_note: note.trim() || undefined,
      }),
    onSuccess: () => {
      message.success('日检已登记（当日重复提交覆盖更新）')
      qc.invalidateQueries({ queryKey: ['hardware-env-logs'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: TableColumnsType<HardwareEnvLogRecord> = [
    { title: '日期', dataIndex: 'log_date', width: 110 },
    { title: '温度 ℃', dataIndex: 'temperature', width: 90, render: (v) => v ?? '—' },
    { title: '湿度 %RH', dataIndex: 'humidity', width: 90, render: (v) => v ?? '—' },
    { title: '检查人', dataIndex: 'checked_by', width: 100, render: (v) => v || '—' },
    {
      title: '异常说明',
      dataIndex: 'abnormal_note',
      render: (v: string | null) =>
        v ? <Tag color="orange">{v}</Tag> : <span className="text-gray-300">正常</span>,
    },
  ]

  const todayDone = (logs.data ?? []).some((l) => l.log_date === dayjs().format('YYYY-MM-DD'))

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumb={['仓储管理', '五金库', '温湿度日检']}
        title="五金库温湿度日检"
        description="每日一行（当日重复提交覆盖更新）；17:00 未填写自动提醒仓管员"
      />

      {canManage && (
        <Card size="small" title="快捷录入">
          <Space wrap size={12}>
            <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
            <InputNumber
              placeholder="温度 ℃"
              min={-50}
              max={80}
              value={temperature ?? undefined}
              onChange={(v) => setTemperature(v ?? null)}
              style={{ width: 110 }}
            />
            <InputNumber
              placeholder="湿度 %RH"
              min={0}
              max={100}
              value={humidity ?? undefined}
              onChange={(v) => setHumidity(v ?? null)}
              style={{ width: 110 }}
            />
            <Input
              placeholder="检查人"
              value={checker}
              onChange={(e) => setChecker(e.target.value)}
              style={{ width: 120 }}
            />
            <Input
              placeholder="异常说明（选填）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              style={{ width: 220 }}
            />
            <Button type="primary" loading={upsertMut.isPending} onClick={() => upsertMut.mutate()}>
              登记
            </Button>
            {!todayDone && <Tag color="orange">今日尚未填写</Tag>}
          </Space>
        </Card>
      )}

      <Table
        rowKey="id"
        size="small"
        loading={logs.isLoading}
        dataSource={logs.data ?? []}
        columns={columns}
        pagination={{ pageSize: 30, showTotal: (t) => `近 30 天 ${t} 条` }}
      />
    </div>
  )
}

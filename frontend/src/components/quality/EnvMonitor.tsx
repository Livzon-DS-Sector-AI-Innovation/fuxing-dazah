'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  App, Button, DatePicker, Form, Input, InputNumber, Modal, Popconfirm,
  Segmented, Select, Space, Spin, Table, Tabs, Tag, Typography,
} from 'antd'
import { DownloadOutlined, LineChartOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type { EnvMonitorType, EnvPoint, EnvRecord, EnvTrend } from '@/types/quality'
import {
  fetchEnvPoints, createEnvPoint, updateEnvPoint, deleteEnvPoint,
  fetchEnvRecords, createEnvRecord, deleteEnvRecord, exportEnvRecords, fetchEnvTrend,
} from '@/actions/quality'
import { EnvTrendChart } from '@/components/quality'

const TYPE_META: Record<string, { label: string; color: string }> = {
  settle: { label: '沉降菌', color: 'green' },
  float: { label: '浮游菌', color: 'cyan' },
  particle: { label: '悬浮粒子', color: 'blue' },
  temp_humidity: { label: '温湿度', color: 'orange' },
  pressure: { label: '压差', color: 'purple' },
}

const FREQ_META: Record<string, string> = {
  per_batch: '每批',
  weekly: '每周',
  monthly: '每月',
}

const JUDGE_META: Record<string, { label: string; color: string }> = {
  pass: { label: '合格', color: 'green' },
  alert: { label: '超警戒', color: 'orange' },
  action: { label: '超行动', color: 'red' },
}

export default function EnvMonitor() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('quality:env:manage')
  const [tab, setTab] = useState('points')

  // ─── 监测点台账 ───
  const [points, setPoints] = useState<EnvPoint[]>([])
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointEditOpen, setPointEditOpen] = useState(false)
  const [editingPoint, setEditingPoint] = useState<EnvPoint | null>(null)
  const [pointSaving, setPointSaving] = useState(false)
  const [pointForm] = Form.useForm()

  const loadPoints = useCallback(async () => {
    setPointsLoading(true)
    try {
      const res = await fetchEnvPoints()
      setPoints(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取监测点失败')
    } finally {
      setPointsLoading(false)
    }
  }, [message])

  useEffect(() => { (async () => { await loadPoints() })() }, [loadPoints])

  const openPointCreate = () => {
    setEditingPoint(null)
    pointForm.resetFields()
    setPointEditOpen(true)
  }

  const openPointEdit = (item: EnvPoint) => {
    setEditingPoint(item)
    pointForm.setFieldsValue({
      room: item.room,
      point_no: item.point_no,
      monitor_type: item.monitor_type,
      frequency: item.frequency ?? undefined,
      alert_limit: item.alert_limit ?? undefined,
      action_limit: item.action_limit ?? undefined,
      status: item.status,
      remark: item.remark ?? undefined,
    })
    setPointEditOpen(true)
  }

  const onPointSave = async () => {
    const values = await pointForm.validateFields()
    setPointSaving(true)
    try {
      if (editingPoint) {
        await updateEnvPoint(editingPoint.id, values)
        message.success('监测点已更新')
      } else {
        await createEnvPoint(values)
        message.success('监测点已保存')
      }
      setPointEditOpen(false)
      loadPoints()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setPointSaving(false)
    }
  }

  // ─── 监测记录 ───
  const [records, setRecords] = useState<EnvRecord[]>([])
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [judgeFilter, setJudgeFilter] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [recordOpen, setRecordOpen] = useState(false)
  const [recordSaving, setRecordSaving] = useState(false)
  const [recordForm] = Form.useForm()

  const loadRecords = useCallback(async () => {
    setRecordsLoading(true)
    try {
      const res = await fetchEnvRecords({
        judge: judgeFilter,
        dateFrom: dateRange?.[0]?.format('YYYY-MM-DD'),
        dateTo: dateRange?.[1]?.format('YYYY-MM-DD'),
      })
      setRecords(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取监测记录失败')
    } finally {
      setRecordsLoading(false)
    }
  }, [message, judgeFilter, dateRange])

  useEffect(() => { (async () => { await loadRecords() })() }, [loadRecords])

  const openRecordCreate = () => {
    recordForm.resetFields()
    recordForm.setFieldsValue({ record_date: dayjs() })
    setRecordOpen(true)
  }

  // ─── 趋势图 ───
  const [trendOpen, setTrendOpen] = useState(false)
  const [trendPointId, setTrendPointId] = useState<string | undefined>()
  const [trendDays, setTrendDays] = useState<number>(90)
  const [trend, setTrend] = useState<EnvTrend | null>(null)
  const [trendLoading, setTrendLoading] = useState(false)

  const loadTrend = useCallback(async (pointId: string, days: number) => {
    setTrendLoading(true)
    try {
      const res = await fetchEnvTrend(pointId, days)
      setTrend(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取趋势失败')
      setTrend(null)
    } finally {
      setTrendLoading(false)
    }
  }, [message])

  const openTrend = () => {
    const firstPoint = points.find((p) => p.status === 'active')
    const pid = firstPoint?.id
    setTrendPointId(pid)
    setTrendDays(90)
    setTrend(null)
    setTrendOpen(true)
    if (pid) void loadTrend(pid, 90)
  }

  const onRecordSave = async () => {
    const values = await recordForm.validateFields()
    setRecordSaving(true)
    try {
      const res = await createEnvRecord({
        point_id: values.point_id,
        record_date: (values.record_date as Dayjs).format('YYYY-MM-DD'),
        result_value: values.result_value ?? null,
        remark: values.remark,
      })
      message.success(res.message)
      setRecordOpen(false)
      loadRecords()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '记录保存失败')
    } finally {
      setRecordSaving(false)
    }
  }

  const onExportRecords = async () => {
    try {
      const blob = await exportEnvRecords({
        judge: judgeFilter,
        dateFrom: dateRange?.[0]?.format('YYYY-MM-DD'),
        dateTo: dateRange?.[1]?.format('YYYY-MM-DD'),
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '环境监测记录.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '导出失败')
    }
  }

  const pointOptions = points
    .filter((p) => p.status === 'active')
    .map((p) => ({
      value: p.id,
      label: `${p.room} ${p.point_no}（${TYPE_META[p.monitor_type]?.label ?? p.monitor_type}）`,
    }))

  const pointColumns = [
    { title: '房间/区域', dataIndex: 'room', width: 160 },
    { title: '点位编号', dataIndex: 'point_no', width: 120 },
    {
      title: '类型', dataIndex: 'monitor_type', width: 100,
      render: (v: EnvMonitorType) => <Tag color={TYPE_META[v]?.color}>{TYPE_META[v]?.label ?? v}</Tag>,
    },
    { title: '频次', dataIndex: 'frequency', width: 80, render: (v: string | null) => (v ? FREQ_META[v] ?? v : '-') },
    { title: '警戒限', dataIndex: 'alert_limit', width: 90, render: (v: number | null) => v ?? '-' },
    { title: '行动限', dataIndex: 'action_limit', width: 90, render: (v: number | null) => v ?? '-' },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v: string) => (v === 'active' ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    { title: '备注', dataIndex: 'remark', width: 140, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '操作', key: 'actions', width: 110, fixed: 'right' as const,
      render: (_: unknown, item: EnvPoint) => (
        canManage ? (
          <Space size="small">
            <Button size="small" type="link" onClick={() => openPointEdit(item)}>编辑</Button>
            <Popconfirm title="确认删除该监测点？" onConfirm={async () => {
              try { await deleteEnvPoint(item.id); message.success('已删除'); loadPoints() } catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '删除失败') }
            }}>
              <Button size="small" type="link" danger>删除</Button>
            </Popconfirm>
          </Space>
        ) : '-'
      ),
    },
  ]

  const recordColumns = [
    { title: '房间/区域', dataIndex: 'room', width: 150 },
    { title: '点位', dataIndex: 'point_no', width: 110 },
    {
      title: '类型', dataIndex: 'monitor_type', width: 95,
      render: (v: EnvMonitorType) => <Tag color={TYPE_META[v]?.color}>{TYPE_META[v]?.label ?? v}</Tag>,
    },
    { title: '监测日期', dataIndex: 'record_date', width: 110 },
    { title: '结果值', dataIndex: 'result_value', width: 90, render: (v: number | null) => v ?? '-' },
    { title: '警戒限', dataIndex: 'alert_limit', width: 85, render: (v: number | null) => v ?? '-' },
    { title: '行动限', dataIndex: 'action_limit', width: 85, render: (v: number | null) => v ?? '-' },
    {
      title: '判定', dataIndex: 'judge', width: 95,
      render: (v: string | null) => (v ? <Tag color={JUDGE_META[v]?.color}>{JUDGE_META[v]?.label ?? v}</Tag> : '-'),
    },
    { title: '填报人', dataIndex: 'recorded_by_name', width: 90, render: (v: string | null) => v || '-' },
    { title: '备注', dataIndex: 'remark', width: 130, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '操作', key: 'actions', width: 80, fixed: 'right' as const,
      render: (_: unknown, item: EnvRecord) => (
        canManage ? (
          <Popconfirm title="确认删除该记录？（填报纠错用）" onConfirm={async () => {
            try { await deleteEnvRecord(item.id); message.success('已删除'); loadRecords() } catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '删除失败') }
          }}>
            <Button size="small" type="link" danger>删除</Button>
          </Popconfirm>
        ) : '-'
      ),
    },
  ]

  return (
    <>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'points',
            label: '监测点台账',
            children: (
              <>
                <Space wrap style={{ marginBottom: 12 }}>
                  {canManage && (
                    <Button type="primary" icon={<PlusOutlined />} onClick={openPointCreate}>新增监测点</Button>
                  )}
                </Space>
                <Table
                  rowKey="id" size="small" loading={pointsLoading} dataSource={points}
                  scroll={{ x: 1080 }} pagination={{ pageSize: 20 }} columns={pointColumns}
                />
              </>
            ),
          },
          {
            key: 'records',
            label: '监测记录',
            children: (
              <>
                <Space wrap style={{ marginBottom: 12 }}>
                  <Select
                    allowClear placeholder="判定筛选" style={{ width: 120 }}
                    value={judgeFilter}
                    onChange={(v) => setJudgeFilter(v)}
                    options={[
                      { value: 'pass', label: '合格' },
                      { value: 'alert', label: '超警戒' },
                      { value: 'action', label: '超行动' },
                    ]}
                  />
                  <DatePicker.RangePicker value={dateRange} onChange={(v) => setDateRange(v as [Dayjs, Dayjs] | null)} />
                  {canManage && (
                    <Button type="primary" icon={<PlusOutlined />} onClick={openRecordCreate}>填报记录</Button>
                  )}
                  <Button icon={<LineChartOutlined />} onClick={openTrend}>趋势图</Button>
                  <Button icon={<DownloadOutlined />} onClick={onExportRecords}>导出 Excel</Button>
                </Space>
                <Table
                  rowKey="id" size="small" loading={recordsLoading} dataSource={records}
                  scroll={{ x: 1150 }} pagination={{ pageSize: 20 }} columns={recordColumns}
                />
              </>
            ),
          },
        ]}
      />

      <Modal
        title={editingPoint ? '编辑监测点' : '新增监测点'}
        open={pointEditOpen}
        onCancel={() => setPointEditOpen(false)}
        onOk={onPointSave}
        confirmLoading={pointSaving}
        okText="保存"
        width={520}
      >
        <Form form={pointForm} layout="vertical" initialValues={{ status: 'active' }}>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="room" label="房间/区域" rules={[{ required: true, message: '必填' }]} style={{ flex: 1 }}>
              <Input maxLength={128} placeholder="如 灌装间" />
            </Form.Item>
            <Form.Item name="point_no" label="点位编号" rules={[{ required: true, message: '必填' }]} style={{ flex: 1 }}>
              <Input maxLength={64} placeholder="如 P-001" />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="monitor_type" label="监测类型" rules={[{ required: true }]} style={{ flex: 1 }}>
              <Select options={Object.entries(TYPE_META).map(([value, m]) => ({ value, label: m.label }))} />
            </Form.Item>
            <Form.Item name="frequency" label="监测频次" style={{ flex: 1 }}>
              <Select
                allowClear
                options={Object.entries(FREQ_META).map(([value, label]) => ({ value, label }))}
              />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="alert_limit" label="警戒限" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="action_limit" label="行动限" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="status" label="状态" style={{ flex: 1 }}>
              <Select options={[
                { value: 'active', label: '启用' },
                { value: 'inactive', label: '停用' },
              ]} />
            </Form.Item>
            <Form.Item name="remark" label="备注" style={{ flex: 1 }}>
              <Input maxLength={200} />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title={`监测趋势${trend ? `（${trend.room} ${trend.point_no}）` : ''}`}
        open={trendOpen}
        onCancel={() => setTrendOpen(false)}
        footer={null}
        width={840}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择点位（房间+编号+类型）"
            style={{ width: 320 }}
            value={trendPointId}
            onChange={(v) => { setTrendPointId(v); void loadTrend(v, trendDays) }}
            options={pointOptions}
          />
          <Segmented
            value={trendDays}
            onChange={(v) => { const d = v as number; setTrendDays(d); if (trendPointId) void loadTrend(trendPointId, d) }}
            options={[
              { value: 30, label: '近30天' },
              { value: 90, label: '近90天' },
              { value: 180, label: '近180天' },
            ]}
          />
        </Space>
        <Spin spinning={trendLoading}>
          <div style={{ minHeight: 200 }}>
            {trend ? (
              <EnvTrendChart trend={trend} />
            ) : (
              <Typography.Text type="secondary">选择点位后展示：数据折线 + 警戒限/行动限虚线，超限点按判定着色。</Typography.Text>
            )}
          </div>
        </Spin>
      </Modal>

      <Modal
        title="填报监测记录"
        open={recordOpen}
        onCancel={() => setRecordOpen(false)}
        onOk={onRecordSave}
        confirmLoading={recordSaving}
        okText="保存"
        width={480}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          保存后按该点位的警戒限/行动限自动判定（合格/超警戒/超行动），超行动限会立即在质量群预警。
        </Typography.Paragraph>
        <Form form={recordForm} layout="vertical">
          <Form.Item name="point_id" label="监测点" rules={[{ required: true, message: '必选' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择点位（房间+编号+类型）"
              options={pointOptions}
            />
          </Form.Item>
          <Space size={12} style={{ display: 'flex' }}>
            <Form.Item name="record_date" label="监测日期" rules={[{ required: true, message: '必填' }]} style={{ flex: 1 }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="result_value" label="结果值" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Space>
          <Form.Item name="remark" label="备注">
            <Input maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

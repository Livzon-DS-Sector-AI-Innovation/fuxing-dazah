'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Alert, Button, Card, Drawer, Space, Table, Tag, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { TableColumnsType } from 'antd'
import { App as AntdApp } from 'antd'

const BASE = '/api/v1/warehouse/reconciliation'

interface ReconciliationRun {
  id: string
  status: string
  total_local: number
  total_feishu: number
  cnt_match: number
  cnt_missing_in_feishu: number
  cnt_mismatch: number
  cnt_missing_local: number
  error_message?: string | null
  duration_ms: number
  created_at?: string | null
}

interface ReconciliationResult {
  status: string
  material_code: string
  material_name: string
  batch_no: string
  local_qty: number | null
  feishu_qty: number | null
  detail: Record<string, string>
}

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  completed: { label: '已完成', color: 'green' },
  running: { label: '运行中', color: 'blue' },
  failed: { label: '失败', color: 'red' },
}

const RESULT_LABEL: Record<string, { label: string; color: string }> = {
  missing_in_feishu: { label: '飞书缺失', color: 'orange' },
  mismatch: { label: '数量不一致', color: 'red' },
  missing_local: { label: '本地缺失', color: 'purple' },
}

export function ReconciliationCenter() {
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const [detailRunId, setDetailRunId] = useState<string | null>(null)
  const [detailStatus, setDetailStatus] = useState<string | undefined>(undefined)

  const { data: runs, isLoading } = useQuery({
    queryKey: ['warehouse', 'reconciliation', 'runs'],
    queryFn: async () => {
      const resp = await fetch(`${BASE}/runs?page=1&page_size=20`)
      const body = await resp.json()
      return body.data as ReconciliationRun[]
    },
  })

  const runMutation = useMutation({
    mutationFn: async () => {
      const resp = await fetch(`${BASE}/run`, { method: 'POST' })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.message ?? '对账失败')
      return body.data as ReconciliationRun
    },
    onSuccess: data => {
      message.success(`对账完成：一致 ${data.cnt_match}，飞书缺失 ${data.cnt_missing_in_feishu}，不一致 ${data.cnt_mismatch}`)
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'reconciliation'] })
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const columns: TableColumnsType<ReconciliationRun> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: v => <Tag color={STATUS_LABEL[v]?.color ?? 'default'}>{STATUS_LABEL[v]?.label ?? v}</Tag>,
    },
    { title: '本地', dataIndex: 'total_local', width: 70, align: 'right' },
    { title: '飞书', dataIndex: 'total_feishu', width: 70, align: 'right' },
    { title: '一致', dataIndex: 'cnt_match', width: 70, align: 'right' },
    { title: '飞书缺失', dataIndex: 'cnt_missing_in_feishu', width: 90, align: 'right' },
    { title: '不一致', dataIndex: 'cnt_mismatch', width: 80, align: 'right' },
    { title: '本地缺失', dataIndex: 'cnt_missing_local', width: 90, align: 'right' },
    { title: '耗时(ms)', dataIndex: 'duration_ms', width: 90, align: 'right' },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 150,
      render: v => (v ? dayjs(v).format('MM-DD HH:mm') : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_, record) => (
        <Button size="small" type="link" onClick={() => setDetailRunId(record.id)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message='对账仅展示差异，不做覆盖操作。点击"发起对账"将拉取飞书库存台账与本地逐条比对。'
        style={{ marginBottom: 12 }}
      />
      <Button
        type="primary"
        icon={<PlayCircleOutlined />}
        loading={runMutation.isPending}
        onClick={() => runMutation.mutate()}
        style={{ marginBottom: 12 }}
      >
        发起对账
      </Button>
      <Table<ReconciliationRun>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={runs ?? []}
        loading={isLoading}
        pagination={false}
        scroll={{ x: 900 }}
      />

      <Drawer
        title={`对账明细 ${detailRunId ? dayjs().format('') : ''}`}
        open={!!detailRunId}
        width={720}
        onClose={() => setDetailRunId(null)}
        destroyOnHidden
      >
        {detailRunId && <ResultDetail runId={detailRunId} />}
      </Drawer>
    </div>
  )
}

function ResultDetail({ runId }: { runId: string }) {
  const [status, setStatus] = useState<string | undefined>(undefined)
  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'reconciliation', 'results', runId, status],
    queryFn: async () => {
      const params = new URLSearchParams({ run_id: runId, page_size: '200' })
      if (status) params.set('status', status)
      const resp = await fetch(`${BASE}/runs/${runId}/results?${params}`)
      return (await resp.json()).data as ReconciliationResult[]
    },
  })

  const columns: TableColumnsType<ReconciliationResult> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: v => <Tag color={RESULT_LABEL[v]?.color ?? 'default'}>{RESULT_LABEL[v]?.label ?? v}</Tag>,
    },
    { title: '物料编码', dataIndex: 'material_code', width: 130 },
    { title: '物料名称', dataIndex: 'material_name', ellipsis: true },
    { title: '批次', dataIndex: 'batch_no', width: 90, render: v => v || '-' },
    { title: '本地', dataIndex: 'local_qty', width: 80, align: 'right', render: v => v ?? '-' },
    { title: '飞书', dataIndex: 'feishu_qty', width: 80, align: 'right', render: v => v ?? '-' },
  ]

  if (isLoading) return <Typography.Text>加载中…</Typography.Text>
  return <Table rowKey="id" size="small" columns={columns} dataSource={res ?? []} pagination={false} />
}

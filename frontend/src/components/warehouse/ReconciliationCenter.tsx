'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App as AntdApp, Button, Drawer, Input, Space, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { PlayCircle } from 'lucide-react'
import dayjs from 'dayjs'
import { PageHeader } from './PageHeader'
import { EmptyGuide } from './ui/EmptyGuide'
import { StatCard } from './ui/StatCard'
import { StatusTag } from './ui/StatusTag'
import type { Tone } from './ui/tokens'

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
  id: string
  status: string
  material_code: string
  material_name: string
  batch_no: string
  local_qty: number | null
  feishu_qty: number | null
  repair_status?: string | null
  repaired_at?: string | null
  detail: Record<string, string>
}

const STATUS_META: Record<string, { label: string; tone: Tone }> = {
  completed: { label: '已完成', tone: 'ok' },
  running: { label: '运行中', tone: 'info' },
  failed: { label: '失败', tone: 'danger' },
}

const RESULT_META: Record<string, { label: string; tone: Tone }> = {
  missing_in_feishu: { label: '飞书缺失', tone: 'warn' },
  mismatch: { label: '数量不一致', tone: 'danger' },
  missing_local: { label: '本地缺失', tone: 'info' },
}

function matchRate(run: ReconciliationRun | undefined): string {
  if (!run) return '-'
  const total = run.total_local || 0
  if (total <= 0) return '-'
  return `${Math.round((run.cnt_match / total) * 100)}%`
}

export function ReconciliationCenter() {
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const [detailRunId, setDetailRunId] = useState<string | null>(null)

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

  const latest = runs?.[0]
  const diffCount = latest
    ? latest.cnt_missing_in_feishu + latest.cnt_mismatch + latest.cnt_missing_local
    : 0

  const columns: TableColumnsType<ReconciliationRun> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: v => {
        const meta = STATUS_META[v]
        return <StatusTag tone={meta?.tone ?? 'default'} label={meta?.label ?? v} />
      },
    },
    { title: '本地', dataIndex: 'total_local', width: 70, align: 'right' },
    { title: '飞书', dataIndex: 'total_feishu', width: 70, align: 'right' },
    { title: '一致', dataIndex: 'cnt_match', width: 70, align: 'right' },
    {
      title: '差异',
      key: 'diff',
      width: 110,
      align: 'right',
      render: (_, record) => {
        const diff = record.cnt_missing_in_feishu + record.cnt_mismatch + record.cnt_missing_local
        return (
          <span
            className="tabular-nums"
            style={{ color: diff > 0 ? 'var(--wh-danger)' : 'var(--wh-ok)', fontWeight: diff > 0 ? 600 : 500 }}
          >
            {diff}
          </span>
        )
      },
    },
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

  const detailDate = runs?.find(r => r.id === detailRunId)?.created_at

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '对账中心']}
        title="对账中心"
        description="本地库存与飞书台账一致性核对；差异默认以飞书台账为准，本地修复为人工一键操作（本地多出仅标记待处置，不自动删除）"
        actions={
          <Button
            type="primary"
            icon={<PlayCircle size={14} />}
            loading={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            发起对账
          </Button>
        }
      />

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <StatCard
          label="最近一次一致率"
          tone={diffCount === 0 ? 'ok' : 'warn'}
          value={matchRate(latest)}
          sub={latest?.created_at ? dayjs(latest.created_at).format('MM-DD HH:mm') : '尚未发起对账'}
        />
        <StatCard
          label="差异行数"
          tone={latest && diffCount > 0 ? 'danger' : 'ok'}
          value={latest ? diffCount : '-'}
          sub={latest ? `飞书缺失 ${latest.cnt_missing_in_feishu} · 不一致 ${latest.cnt_mismatch} · 本地缺失 ${latest.cnt_missing_local}` : '-'}
          onClick={latest && diffCount > 0 ? () => setDetailRunId(latest.id) : undefined}
        />
        <StatCard
          label="对账耗时"
          tone="default"
          value={latest ? `${latest.duration_ms}` : '-'}
          sub={latest ? `本地 ${latest.total_local} 行 · 飞书 ${latest.total_feishu} 行` : '-'}
        />
      </div>

      {runs && runs.length === 0 && !isLoading ? (
        <EmptyGuide
          icon={<PlayCircle />}
          title="还没有对账记录"
          description="发起对账将拉取飞书库存台账，与本地库存逐条比对，生成差异报告"
          actionText="发起对账"
          onAction={() => runMutation.mutate()}
        />
      ) : (
        <Table<ReconciliationRun>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={runs ?? []}
          loading={isLoading}
          pagination={false}
          scroll={{ x: 900 }}
        />
      )}

      <Drawer
        title={`对账明细${
          detailRunId && detailDate ? ` · ${dayjs(detailDate).format('YYYY-MM-DD HH:mm')}` : ''
        }`}
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
  const queryClient = useQueryClient()
  const { message } = AntdApp.useApp()
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [keyword, setKeyword] = useState('')
  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'reconciliation', 'results', runId, status],
    queryFn: async () => {
      const params = new URLSearchParams({ run_id: runId, page_size: '200' })
      if (status) params.set('status', status)
      const resp = await fetch(`${BASE}/runs/${runId}/results?${params}`)
      return (await resp.json()).data as ReconciliationResult[]
    },
  })

  // 按 Base 修复本地（V3.0 分期A 裁决反转）：mismatch 调数 / missing_local 补行 /
  // missing_in_feishu 仅标记待人工处置（删除属红区，绝不自动删）
  const repairMutation = useMutation({
    mutationFn: async (resultId: string) => {
      const resp = await fetch(`${BASE}/results/${resultId}/repair`, { method: 'POST' })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body?.detail ?? body?.message ?? '修复失败')
      return body.data as { repair_status: string | null }
    },
    onSuccess: data => {
      message.success(
        data.repair_status === 'manual' ? '已标记待人工处置' : '已按 Base 修复本地',
      )
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'reconciliation'] })
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const filtered = (res ?? []).filter(r =>
    !keyword ||
    r.material_code.toLowerCase().includes(keyword.toLowerCase()) ||
    r.material_name.toLowerCase().includes(keyword.toLowerCase()),
  )

  const columns: TableColumnsType<ReconciliationResult> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: v => {
        const meta = RESULT_META[v]
        return <StatusTag tone={meta?.tone ?? 'default'} label={meta?.label ?? v} />
      },
    },
    { title: '物料编码', dataIndex: 'material_code', width: 130 },
    { title: '物料名称', dataIndex: 'material_name', ellipsis: true },
    { title: '批次', dataIndex: 'batch_no', width: 90, render: v => v || '-' },
    { title: '本地', dataIndex: 'local_qty', width: 80, align: 'right', render: v => v ?? '-' },
    { title: '飞书', dataIndex: 'feishu_qty', width: 80, align: 'right', render: v => v ?? '-' },
    {
      title: '修复（以 Base 为准）',
      key: 'repair',
      width: 150,
      render: (_, record) => {
        if (record.repair_status === 'repaired') {
          return <StatusTag tone="ok" label="已按 Base 修复" />
        }
        if (record.repair_status === 'manual') {
          return <StatusTag tone="warn" label="待人工处置" />
        }
        const isMissingInFeishu = record.status === 'missing_in_feishu'
        return (
          <Button
            size="small"
            danger={isMissingInFeishu}
            type="link"
            loading={repairMutation.isPending && repairMutation.variables === record.id}
            onClick={() => repairMutation.mutate(record.id)}
          >
            {isMissingInFeishu ? '标记人工处置' : '按 Base 修复'}
          </Button>
        )
      },
    },
  ]

  if (isLoading) return <Typography.Text>加载中…</Typography.Text>
  return (
    <div>
      <Space.Compact block className="mb-3">
        <Input
          allowClear
          placeholder="搜索物料编码/名称"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
        />
      </Space.Compact>
      <Table
        rowKey={r => r.id}
        size="small"
        columns={columns}
        dataSource={filtered}
        pagination={filtered.length > 50 ? { pageSize: 50 } : false}
        locale={{ emptyText: <EmptyGuide compact title="没有匹配的差异行" /> }}
      />
    </div>
  )
}

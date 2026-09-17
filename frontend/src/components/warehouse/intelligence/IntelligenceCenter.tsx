'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Button, Drawer, InputNumber, Space, Switch, Tabs, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { Card } from 'antd'
import { RefreshCw, Settings2 } from 'lucide-react'
import dayjs from 'dayjs'
import {
  fetchAlertSummaryClient,
  fetchAlertsClient,
  fetchIntelligenceRulesClient,
  fetchSuggestionsClient,
} from '@/lib/api/warehouse-intelligence'
import {
  resolveIntelligenceAlert,
  runIntelligenceScanAction,
  setSuggestionStatusAction,
  updateIntelligenceRuleAction,
} from '@/actions/warehouse'
import type {
  AlertRecordItem,
  IntelligenceRule,
  ReplenishmentSuggestionItem,
} from '@/types/warehouse'
import { DataTable } from '../DataTable'
import { PageHeader } from '../PageHeader'
import { EmptyGuide } from '../ui/EmptyGuide'
import { StatCard } from '../ui/StatCard'
import { StatusTag } from '../ui/StatusTag'
import type { Tone } from '../ui/tokens'

const RULE_LABEL: Record<string, string> = {
  low_stock: '低库存',
  zero_stock: '零库存',
  idle: '呆滞',
  expiry: '效期临期',
}

const RULE_TONE: Record<string, Tone> = {
  low_stock: 'danger',
  zero_stock: 'default',
  idle: 'warn',
  expiry: 'warn',
}

/** 单规则摘要行（规则/AI 文案 + 未处理数），替代重型 Alert */
function AlertSummaryLine({ ruleKey }: { ruleKey: string }) {
  const { data } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'summary', ruleKey],
    queryFn: () => fetchAlertSummaryClient(ruleKey),
  })
  if (!data) return null
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg px-3.5 py-2 text-[13px]"
      style={{
        background: data.source === 'llm' ? 'var(--wh-info-bg)' : 'var(--color-surface)',
        color: 'var(--color-charcoal)',
      }}
    >
      <StatusTag tone={data.source === 'llm' ? 'info' : 'default'} label={data.source === 'llm' ? 'AI 解读' : '规则摘要'} />
      <span className="min-w-0 flex-1">{data.text}</span>
      <span className="shrink-0 text-[var(--color-steel)]">未处理 {data.open_count} 项</span>
    </div>
  )
}

function AlertsTab() {
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const [ruleTab, setRuleTab] = useState('low_stock')
  const [status, setStatus] = useState<'open' | 'resolved'>('open')

  const {
    data: res,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'alerts', { ruleTab, status }],
    queryFn: () => fetchAlertsClient({ rule_key: ruleTab, status, page: 1, page_size: 100 }),
  })

  const resolveMutation = useMutation({
    mutationFn: (id: string) => resolveIntelligenceAlert(id),
    onSuccess: () => {
      message.success('已标记处理完成')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'intelligence'] })
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const columns: TableColumnsType<AlertRecordItem> = [
    {
      title: '物料',
      dataIndex: 'material_name',
      width: 240,
      render: (_, record) => (
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
            {record.material_name}
          </div>
          <div className="truncate text-[12px] leading-4 text-[var(--color-steel)]">
            {record.material_code}
          </div>
        </div>
      ),
    },
    {
      title: '级别',
      dataIndex: 'level',
      width: 84,
      render: (v: string) => (
        <StatusTag tone={v === 'critical' ? 'danger' : 'warn'} label={v === 'critical' ? '紧急' : '关注'} />
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      render: (detail: Record<string, number | string>) =>
        Object.entries(detail)
          .map(([k, v]) => `${k}: ${v}`)
          .join('，'),
    },
    {
      title: '产生时间',
      dataIndex: 'created_at',
      width: 150,
      render: v => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
    ...(status === 'open'
      ? ([
          {
            title: '操作',
            key: 'actions',
            width: 110,
            render: (_, record: AlertRecordItem) => (
              <Button size="small" type="link" onClick={() => resolveMutation.mutate(record.id)}>
                标记已处理
              </Button>
            ),
          },
        ] as TableColumnsType<AlertRecordItem>)
      : []),
  ]

  return (
    <div>
      <AlertSummaryLine ruleKey={ruleTab} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Space.Compact>
          {Object.entries(RULE_LABEL).map(([key, label]) => (
            <Button
              key={key}
              type={ruleTab === key ? 'primary' : 'default'}
              size="small"
              onClick={() => setRuleTab(key)}
            >
              {label}
            </Button>
          ))}
        </Space.Compact>
        <span className="mx-1 h-4 w-px bg-[var(--color-hairline)]" aria-hidden />
        <Space.Compact>
          <Button size="small" type={status === 'open' ? 'primary' : 'default'} onClick={() => setStatus('open')}>
            未处理
          </Button>
          <Button size="small" type={status === 'resolved' ? 'primary' : 'default'} onClick={() => setStatus('resolved')}>
            已处理
          </Button>
        </Space.Compact>
      </div>
      {isError ? (
        <EmptyGuide title="加载失败，请重试" />
      ) : (
        <DataTable
          columns={columns}
          dataSource={res?.items ?? []}
          loading={isLoading}
          emptyText="当前没有该类异常"
          scrollX={760}
        />
      )}
    </div>
  )
}

function SuggestionsTab() {
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'suggestions'],
    queryFn: () => fetchSuggestionsClient({ status: 'pending', page: 1, page_size: 100 }),
  })

  const statusMutation = useMutation({
    mutationFn: (input: { id: string; status: 'handled' | 'ignored' }) =>
      setSuggestionStatusAction(input.id, input.status),
    onSuccess: (_, input) => {
      message.success(input.status === 'handled' ? '已标记处理' : '已忽略')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'intelligence', 'suggestions'] })
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  const columns: TableColumnsType<ReplenishmentSuggestionItem> = [
    {
      title: '物料',
      dataIndex: 'material_name',
      width: 240,
      render: (_, record) => (
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
            {record.material_name}
          </div>
          <div className="truncate text-[12px] leading-4 text-[var(--color-steel)]">
            {record.material_code}
          </div>
        </div>
      ),
    },
    { title: '日均消耗', dataIndex: 'avg_daily_outbound', width: 100, align: 'right' },
    {
      title: '可支撑天数',
      dataIndex: 'days_cover',
      width: 110,
      align: 'right',
      render: v => (v == null ? '-' : v),
    },
    { title: '建议采购量', dataIndex: 'suggested_qty', width: 110, align: 'right' },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            type="link"
            onClick={() => statusMutation.mutate({ id: record.id, status: 'handled' })}
          >
            已处理
          </Button>
          <Button
            size="small"
            type="link"
            danger
            onClick={() => statusMutation.mutate({ id: record.id, status: 'ignored' })}
          >
            忽略
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <DataTable
      columns={columns}
      dataSource={res?.items ?? []}
      loading={isLoading}
      emptyText="暂无待处理补货建议"
      scrollX={720}
    />
  )
}

function ExpiryIdleTab() {
  const { data: res, isLoading } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'alerts', 'expiry-idle'],
    queryFn: () => fetchAlertsClient({ page: 1, page_size: 200 }),
  })
  const expiry = (res?.items ?? []).filter(a => a.rule_key === 'expiry')
  const idle = (res?.items ?? []).filter(a => a.rule_key === 'idle')

  if (isLoading) return null
  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
      <section>
        <Typography.Paragraph strong className="mb-2">
          临期批次（按剩余天数升序）
        </Typography.Paragraph>
        {expiry.length === 0 ? (
          <EmptyGuide compact title="暂无临期批次" />
        ) : (
          <div className="flex flex-col gap-2">
            {expiry.map(record => {
              const days = Number(record.detail?.days_left ?? 0)
              return (
                <div
                  key={record.id}
                  className="flex items-center gap-3 rounded-lg border border-[var(--color-hairline)] bg-white px-3.5 py-2.5"
                >
                  <StatusTag tone={days <= 7 ? 'danger' : days <= 15 ? 'warn' : 'ok'} label={`剩 ${days} 天`} />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--color-charcoal)]">
                    {record.material_name}
                  </span>
                  <span className="shrink-0 text-[12px] text-[var(--color-steel)]">
                    批次 {record.batch_no || '-'} · 库存 {String(record.detail?.quantity ?? '-')}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </section>
      <section>
        <Typography.Paragraph strong className="mb-2">
          呆滞物料（90 天无入库）
        </Typography.Paragraph>
        {idle.length === 0 ? (
          <EmptyGuide compact title="暂无呆滞物料" />
        ) : (
          <div className="flex flex-col gap-2">
            {idle.map(record => (
              <div
                key={record.id}
                className="flex items-center gap-3 rounded-lg border border-[var(--color-hairline)] bg-white px-3.5 py-2.5"
              >
                <StatusTag tone="warn" label={`${record.detail?.days_idle ?? '-'} 天`} />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--color-charcoal)]">
                  {record.material_name}
                </span>
                <span className="shrink-0 text-[12px] tabular-nums text-[var(--color-steel)]">
                  库存 {String(record.detail?.total_quantity ?? '-')}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function RuleConfigDrawer(props: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const { data: rules, isLoading } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'rules'],
    queryFn: () => fetchIntelligenceRulesClient(),
    enabled: props.open,
  })

  const updateMutation = useMutation({
    mutationFn: (input: {
      rule: IntelligenceRule
      threshold: Record<string, number>
      enabled: boolean
    }) =>
      updateIntelligenceRuleAction(input.rule.rule_key, {
        threshold: input.threshold,
        enabled: input.enabled,
      }),
    onSuccess: () => {
      message.success('规则已更新')
      queryClient.invalidateQueries({ queryKey: ['warehouse', 'intelligence', 'rules'] })
    },
    onError: (e: unknown) => {
      if (e instanceof Error) message.error(e.message)
    },
  })

  return (
    <Drawer title="预警配置" open={props.open} width={520} onClose={props.onClose} destroyOnHidden>
      {isLoading && <Typography.Text>加载中…</Typography.Text>}
      {(rules ?? []).map(rule => (
        <RuleRow key={rule.rule_key} rule={rule} onSave={updateMutation.mutate} />
      ))}
    </Drawer>
  )
}

function RuleRow({
  rule,
  onSave,
}: {
  rule: IntelligenceRule
  onSave: (input: {
    rule: IntelligenceRule
    threshold: Record<string, number>
    enabled: boolean
  }) => void
}) {
  const daysKeys = Object.keys(rule.threshold)
  const [enabled, setEnabled] = useState(rule.enabled)
  const [values, setValues] = useState<Record<string, number>>(() => ({ ...rule.threshold }))

  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Text strong>{rule.name}</Typography.Text>
        <Switch
          checked={enabled}
          onChange={v => {
            setEnabled(v)
            onSave({ rule, threshold: values, enabled: v })
          }}
        />
      </Space>
      {daysKeys.map(key => (
        <div key={key} style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">{key === 'days' ? '天数' : key}</Typography.Text>
          <InputNumber
            min={1}
            value={values[key]}
            style={{ width: 120, marginLeft: 8 }}
            onChange={v => setValues(prev => ({ ...prev, [key]: v ?? 1 }))}
          />
        </div>
      ))}
      {daysKeys.length > 0 && (
        <Button
          size="small"
          style={{ marginTop: 8 }}
          type="primary"
          onClick={() => onSave({ rule, threshold: values, enabled })}
        >
          保存阈值
        </Button>
      )}
    </Card>
  )
}

/** 单规则未处理数 hook（RuleStatCards 固定调用 4 次，键为常量） */
function useAlertSummary(key: string) {
  return useQuery({
    queryKey: ['warehouse', 'intelligence', 'summary', key],
    queryFn: () => fetchAlertSummaryClient(key),
    staleTime: 30_000,
  })
}

/** 按规则类型的未处理计数卡 */
function RuleStatCards() {
  const lowStock = useAlertSummary('low_stock')
  const zeroStock = useAlertSummary('zero_stock')
  const idle = useAlertSummary('idle')
  const expiry = useAlertSummary('expiry')
  const cards: { key: string; label: string; tone: Tone; q: typeof lowStock }[] = [
    { key: 'low_stock', label: RULE_LABEL.low_stock, tone: RULE_TONE.low_stock, q: lowStock },
    { key: 'zero_stock', label: RULE_LABEL.zero_stock, tone: RULE_TONE.zero_stock, q: zeroStock },
    { key: 'idle', label: RULE_LABEL.idle, tone: RULE_TONE.idle, q: idle },
    { key: 'expiry', label: RULE_LABEL.expiry, tone: RULE_TONE.expiry, q: expiry },
  ]
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
      {cards.map(({ key, label, tone, q }) => (
        <StatCard
          key={key}
          label={label}
          tone={tone}
          value={q.data?.open_count ?? 0}
          loading={q.isLoading}
          sub="未处理"
        />
      ))}
    </div>
  )
}

export function IntelligenceCenter() {
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const [configOpen, setConfigOpen] = useState(false)
  const [scanning, setScanning] = useState(false)

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '智能中心']}
        title="智能中心"
        description="异常检测、补货建议与效期呆滞监控"
        actions={
          <>
            <Button
              icon={<RefreshCw size={14} />}
              loading={scanning}
              onClick={async () => {
                setScanning(true)
                try {
                  const result = await runIntelligenceScanAction()
                  const counts = result.counts ?? {}
                  message.success(`扫描完成：${JSON.stringify(counts)}`)
                  queryClient.invalidateQueries({ queryKey: ['warehouse', 'intelligence'] })
                } finally {
                  setScanning(false)
                }
              }}
            >
              手动扫描
            </Button>
            <Button icon={<Settings2 size={14} />} onClick={() => setConfigOpen(true)}>
              预警配置
            </Button>
          </>
        }
      />

      <RuleStatCards />

      <Tabs
        defaultActiveKey="alerts"
        items={[
          { key: 'alerts', label: '异常检测', children: <AlertsTab /> },
          { key: 'replenishment', label: '补货建议', children: <SuggestionsTab /> },
          { key: 'expiry-idle', label: '效期与呆滞', children: <ExpiryIdleTab /> },
        ]}
      />

      <RuleConfigDrawer open={configOpen} onClose={() => setConfigOpen(false)} />
    </div>
  )
}

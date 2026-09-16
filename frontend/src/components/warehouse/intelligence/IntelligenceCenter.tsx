'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Alert, Button, Card, Drawer, Empty, InputNumber, Space, Switch, Tabs, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
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

const RULE_LABEL: Record<string, string> = {
  low_stock: '低库存',
  zero_stock: '零库存',
  idle: '呆滞',
  expiry: '效期临期',
}

function AlertSummaryBar({ ruleKey }: { ruleKey: string }) {
  const { data } = useQuery({
    queryKey: ['warehouse', 'intelligence', 'summary', ruleKey],
    queryFn: () => fetchAlertSummaryClient(ruleKey),
  })
  if (!data) return null
  return (
    <Alert
      type={data.source === 'llm' ? 'info' : 'warning'}
      showIcon
      message={data.text}
      description={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {data.source === 'llm' ? 'AI 解读' : '规则摘要'} · 未处理 {data.open_count} 项
        </Typography.Text>
      }
      style={{ marginBottom: 12 }}
    />
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
    { title: '物料编码', dataIndex: 'material_code', width: 140 },
    { title: '物料名称', dataIndex: 'material_name', width: 180 },
    {
      title: '级别',
      dataIndex: 'level',
      width: 80,
      render: (v: string) =>
        v === 'critical' ? <Tag color="red">紧急</Tag> : <Tag color="gold">关注</Tag>,
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
      <AlertSummaryBar ruleKey={ruleTab} />
      <Space style={{ marginBottom: 12 }} wrap>
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
        <Button
          size="small"
          type={status === 'open' ? 'primary' : 'default'}
          onClick={() => setStatus('open')}
        >
          未处理
        </Button>
        <Button
          size="small"
          type={status === 'resolved' ? 'primary' : 'default'}
          onClick={() => setStatus('resolved')}
        >
          已处理
        </Button>
      </Space>
      <DataTable
        columns={columns}
        dataSource={res?.items ?? []}
        loading={isLoading}
        emptyText={isError ? '加载失败，请重试' : '当前没有该类异常'}
        scrollX={760}
      />
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
    { title: '物料编码', dataIndex: 'material_code', width: 140 },
    { title: '物料名称', dataIndex: 'material_name', width: 180 },
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
    <div>
      <Typography.Paragraph strong>临期批次（按剩余天数升序）</Typography.Paragraph>
      {expiry.length === 0 ? (
        <Empty description="暂无临期批次" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table<AlertRecordItem>
          rowKey="id"
          size="small"
          columns={[
            { title: '物料名称', dataIndex: 'material_name' },
            { title: '批次号', dataIndex: 'batch_no', render: v => v || '-' },
            {
              title: '剩余天数',
              width: 110,
              render: (_, record) => {
                const days = Number(record.detail?.days_left ?? 0)
                return <Tag color={days <= 7 ? 'red' : days <= 15 ? 'orange' : 'default'}>{days} 天</Tag>
              },
            },
            {
              title: '库存',
              width: 110,
              align: 'right',
              render: (_, record) => String(record.detail?.quantity ?? '-'),
            },
          ]}
          dataSource={expiry}
          pagination={false}
        />
      )}
      <Typography.Paragraph strong style={{ marginTop: 16 }}>
        呆滞物料（90 天无入库）
      </Typography.Paragraph>
      {idle.length === 0 ? (
        <Empty description="暂无呆滞物料" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Table<AlertRecordItem>
          rowKey="id"
          size="small"
          columns={[
            { title: '物料名称', dataIndex: 'material_name' },
            {
              title: '呆滞天数',
              width: 110,
              render: (_, record) => `${record.detail?.days_idle ?? '-'} 天`,
            },
            {
              title: '库存',
              width: 110,
              align: 'right',
              render: (_, record) => String(record.detail?.total_quantity ?? '-'),
            },
          ]}
          dataSource={idle}
          pagination={false}
        />
      )}
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

export function IntelligenceCenter() {
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const [configOpen, setConfigOpen] = useState(false)
  const [scanning, setScanning] = useState(false)

  return (
    <Tabs
      defaultActiveKey="alerts"
      items={[
        { key: 'alerts', label: '异常检测', children: <AlertsTab /> },
        { key: 'replenishment', label: '补货建议', children: <SuggestionsTab /> },
        { key: 'expiry-idle', label: '效期与呆滞', children: <ExpiryIdleTab /> },
      ]}
      tabBarExtraContent={
        <Space>
          <Button
            icon={<ReloadOutlined />}
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
          <Button onClick={() => setConfigOpen(true)}>预警配置</Button>
        </Space>
      }
    />
  )
}

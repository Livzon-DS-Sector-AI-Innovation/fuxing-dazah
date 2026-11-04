'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  App,
  Button,
  Card,
  Drawer,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'
import { PlayCircle } from 'lucide-react'
import {
  fetchAnalysisLatestClient,
  fetchAnalysisReportsClient,
  runAnalysisClient,
  type AnalysisReportItem,
} from '@/lib/api/warehouse-intelligence'
import { EmptyGuide, StatCard } from '@/components/ui-kit'

const CATEGORY_LABEL: Record<string, string> = {
  raw: '原辅料',
  auxiliary: '辅料',
  packaging: '包材',
  intermediate: '中间体',
  finished: '成品',
}

function KpiCards({ report }: { report: AnalysisReportItem }) {
  const kpi = report.summary.kpi
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
      <StatCard label="库存总量" value={kpi.total_quantity.toLocaleString()} />
      <StatCard label="批次行数" value={kpi.stock_rows.toLocaleString()} />
      <StatCard label="在库 SKU" value={kpi.stock_skus.toLocaleString()} />
      <StatCard label="物料总数" value={kpi.material_count.toLocaleString()} />
      <StatCard label="呆滞预警" value={kpi.frozen_count > 0 ? `${kpi.frozen_count} 冻结` : `${kpi.frozen_count}`} tone={kpi.frozen_count > 0 ? 'danger' : undefined} />
      <StatCard label="待检批次" value={kpi.quarantine_count.toLocaleString()} tone={kpi.quarantine_count > 0 ? 'warn' : undefined} />
      <StatCard label="零库存 SKU" value={kpi.zero_stock_count.toLocaleString()} />
      <StatCard label="临期批次" value={report.summary.alerts.expiry_count.toLocaleString()} tone={report.summary.alerts.expiry_count > 0 ? 'warn' : undefined} />
    </div>
  )
}

function TopTables({ report }: { report: AnalysisReportItem }) {
  const turnoverCols: TableColumnsType<AnalysisReportItem['summary']['top']['turnover'][number]> = [
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '30天出库', dataIndex: 'outbound_qty', width: 100, align: 'right' },
    { title: '当前库存', dataIndex: 'current_stock', width: 100, align: 'right' },
    {
      title: '周转率', dataIndex: 'turnover', width: 90, align: 'right',
      render: (v: number | null) => (v == null ? '—' : v.toFixed(2)),
    },
  ]
  const consumptionCols: TableColumnsType<AnalysisReportItem['summary']['top']['consumption'][number]> = [
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '单位', dataIndex: 'unit', width: 70 },
    { title: '30天消耗', dataIndex: 'outbound_qty', width: 110, align: 'right' },
  ]
  return (
    <Tabs
      items={[
        {
          key: 'turnover',
          label: '周转 Top 10（30 天）',
          children: (
            <Table
              size="small" rowKey="material_code" pagination={false}
              columns={turnoverCols} dataSource={report.summary.top.turnover}
            />
          ),
        },
        {
          key: 'consumption',
          label: '消耗 Top 10（30 天）',
          children: (
            <Table
              size="small" rowKey="material_code" pagination={false}
              columns={consumptionCols} dataSource={report.summary.top.consumption}
            />
          ),
        },
      ]}
    />
  )
}

function AlertsBlock({ report }: { report: AnalysisReportItem }) {
  const { alerts } = report.summary
  const expiryCols: TableColumnsType<AnalysisReportItem['summary']['alerts']['expiry'][number]> = [
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '批次', dataIndex: 'batch_no', width: 140, ellipsis: true },
    { title: '效期至', dataIndex: 'expiry_date', width: 110 },
    {
      title: '剩余天数', dataIndex: 'days_left', width: 100, align: 'right',
      render: (v: number) => (
        <Tag color={v < 0 ? 'red' : v <= 30 ? 'orange' : 'default'}>
          {v < 0 ? `已过期 ${-v} 天` : `${v} 天`}
        </Tag>
      ),
    },
  ]
  return (
    <Card size="small" title={`临期预警（${alerts.expiry_count} 批，前 50）`} style={{ marginTop: 12 }}>
      {alerts.expiry.length === 0 ? (
        <EmptyGuide title="无临期批次" />
      ) : (
        <Table size="small" rowKey={(r) => `${r.material_code}-${r.batch_no}`} pagination={false} columns={expiryCols} dataSource={alerts.expiry} />
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        呆滞预警 {alerts.idle_count} 项（最后入库 ≥90 天）；低库存规则需先在生产表维护安全库存基准，当前恒为 0。
      </Typography.Text>
    </Card>
  )
}

export function AnalysisSection() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [detail, setDetail] = useState<AnalysisReportItem | null>(null)
  const [historyPage, setHistoryPage] = useState(1)

  const latest = useQuery({
    queryKey: ['warehouse', 'analysis', 'latest'],
    queryFn: fetchAnalysisLatestClient,
  })
  const history = useQuery({
    queryKey: ['warehouse', 'analysis', 'reports', historyPage],
    queryFn: () => fetchAnalysisReportsClient(historyPage),
  })
  const runMutation = useMutation({
    mutationFn: runAnalysisClient,
    onSuccess: (row) => {
      message.success(`分析已生成（${row.report_date}，耗时 ${row.duration_ms}ms）`)
      void queryClient.invalidateQueries({ queryKey: ['warehouse', 'analysis'] })
    },
    onError: (e: Error) => message.error(e instanceof Error ? e.message : '生成失败'),
  })

  const report = latest.data
  const historyCols: TableColumnsType<AnalysisReportItem> = [
    { title: '日期', dataIndex: 'report_date', width: 110 },
    {
      title: '触发', dataIndex: 'trigger', width: 90,
      render: (v: string) => (
        <Tag color={v === 'manual' ? 'blue' : 'default'}>{v === 'manual' ? '手动' : '定时'}</Tag>
      ),
    },
    { title: '在库 SKU', dataIndex: ['summary', 'kpi', 'stock_skus'], width: 100, align: 'right' },
    { title: '临期批次', dataIndex: ['summary', 'alerts', 'expiry_count'], width: 100, align: 'right' },
    { title: '呆滞项', dataIndex: ['summary', 'alerts', 'idle_count'], width: 90, align: 'right' },
    { title: '耗时', dataIndex: 'duration_ms', width: 90, align: 'right', render: (v: number) => `${v}ms` },
    {
      title: '生成时间', dataIndex: 'created_at', width: 160,
      render: (v: string | null) => (v ? dayjs(v).format('MM-DD HH:mm') : '-'),
    },
    {
      title: '操作', width: 80,
      render: (_, record) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setDetail(record)}>
          查看
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Typography.Text type="secondary">
          每日 00:30 自动定档；数据来自生产多维表格直读（当日重跑覆盖）。
          首次生成需全量拉取台账，约 1 分钟，请耐心等待。
        </Typography.Text>
        <Button
          type="primary" icon={<PlayCircle size={14} />}
          loading={runMutation.isPending} onClick={() => runMutation.mutate()}
        >
          生成分析
        </Button>
      </div>
      {report ? (
        <>
          <KpiCards report={report} />
          <Card size="small" title={`分类分布（${dayjs(report.report_date).format('YYYY-MM-DD')} 定档）`} style={{ marginTop: 12 }}>
            {report.summary.distribution.map((d) => (
              <Tag key={d.category} style={{ marginBottom: 4 }}>
                {CATEGORY_LABEL[d.category] ?? d.category}：{d.total_quantity.toLocaleString()}
              </Tag>
            ))}
          </Card>
          <Card size="small" style={{ marginTop: 12 }} title="排行">
            <TopTables report={report} />
          </Card>
          <AlertsBlock report={report} />
        </>
      ) : (
        <EmptyGuide
          title={latest.isLoading ? '加载中…' : '尚无分析记录'}
          description="点击右上角「生成分析」立即产出第一份定档报告"
        />
      )}

      <Card size="small" title="历史定档" style={{ marginTop: 16 }}>
        <Table
          size="small" rowKey="id"
          columns={historyCols}
          dataSource={history.data?.items ?? []}
          loading={history.isLoading}
          pagination={{
            current: historyPage,
            pageSize: 20,
            total: history.data?.total ?? 0,
            onChange: setHistoryPage,
            showSizeChanger: false,
          }}
        />
      </Card>

      <Drawer
        title={detail ? `分析定档 ${detail.report_date}` : ''}
        width={720} open={!!detail} onClose={() => setDetail(null)}
      >
        {detail && (
          <>
            <KpiCards report={detail} />
            <AlertsBlock report={detail} />
          </>
        )}
      </Drawer>
    </div>
  )
}

'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Button, DatePicker, Input, Modal, Select, Space, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { Download, Sparkles } from 'lucide-react'
import { PageHeader } from '../PageHeader'
import { SectionCard } from '../ui/SectionCard'
import { StatCard } from '../ui/StatCard'
import { RankBarChart } from '../ui/charts'
import { TONE_HEX } from '../ui/tokens'

const BASE = '/api/v1/warehouse/reports'

interface MonthlyData {
  year: number; month: number
  summary: { inbound_count: number; inbound_qty: number; outbound_count: number; outbound_qty: number }
  items: { material_code: string; material_name: string; unit: string; inbound_qty: number; outbound_qty: number }[]
}

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}/${path}`)
  const body = await resp.json()
  return body.data as T
}

interface AnnualData {
  year: number
  summary: { inbound_count: number; inbound_qty: number; outbound_count: number; outbound_qty: number }
  months: { month: number; inbound_qty: number; outbound_qty: number }[]
  items: { material_code: string; material_name: string; unit: string; inbound_qty: number; outbound_qty: number }[]
}

interface HazardousData {
  days: number
  total: number
  items: { material_name: string; category: string; legal_class: string; outbound_qty: number; current_stock: number }[]
}

interface UsageCompareData {
  year: number; month: number; total: number; no_baseline_with_usage: number
  items: { material_name: string; actual_qty: number; expected_qty: number; deviation: number | null }[]
}

async function fetchMonthly(year: number, month: number): Promise<MonthlyData> {
  return fetchJson<MonthlyData>(`monthly?year=${year}&month=${month}`)
}

function exportExcel(path: string, filename: string) {
  const link = document.createElement('a')
  link.href = `${BASE}/${path}`
  link.download = filename
  link.click()
}

function topItems(items: MonthlyData['items'], key: 'inbound_qty' | 'outbound_qty', n = 10) {
  return [...items]
    .filter(it => Number(it[key]) > 0)
    .sort((a, b) => Number(b[key]) - Number(a[key]))
    .slice(0, n)
}

function NlExportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const [nlQuery, setNlQuery] = useState('')
  const [exporting, setExporting] = useState(false)

  const handleNlExport = async () => {
    if (!nlQuery.trim()) { message.warning('请输入导出条件'); return }
    setExporting(true)
    try {
      const resp = await fetch(`${BASE}/nl-export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: nlQuery }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => null)
        throw new Error(body?.message ?? `导出失败（${resp.status}）`)
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = '导出数据.xlsx'; a.click()
      URL.revokeObjectURL(url)
      message.success('导出成功')
      onClose()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  return (
    <Modal
      title={
        <span className="inline-flex items-center gap-2">
          <Sparkles size={16} style={{ color: 'var(--color-primary)' }} />
          AI 自然语言导出
        </span>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <Space.Compact block className="mt-2">
        <Input
          autoFocus
          placeholder="如：导出 9 月出库大于 100 的物料"
          value={nlQuery}
          onChange={e => setNlQuery(e.target.value)}
          onPressEnter={handleNlExport}
        />
        <Button type="primary" loading={exporting} onClick={handleNlExport}>导出</Button>
      </Space.Compact>
      <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
        用一句中文描述要导出的数据；解析失败时自动降级为整表导出
      </Typography.Text>
    </Modal>
  )
}

export function ReportCenter() {
  const [month, setMonth] = useState<Dayjs>(dayjs())
  const [annualYear, setAnnualYear] = useState<Dayjs>(dayjs())
  const [compareMonth, setCompareMonth] = useState<Dayjs>(dayjs().subtract(1, 'month'))
  const [hazardousDays, setHazardousDays] = useState(90)
  const [nlOpen, setNlOpen] = useState(false)

  const { data: monthly, isLoading: loadingMonthly } = useQuery({
    queryKey: ['warehouse', 'reports', 'monthly', month.year(), month.month() + 1],
    queryFn: () => fetchMonthly(month.year(), month.month() + 1),
  })
  const { data: annual } = useQuery({
    queryKey: ['warehouse', 'reports', 'annual', annualYear.year()],
    queryFn: () => fetchJson<AnnualData>(`annual?year=${annualYear.year()}`),
  })
  const { data: hazardous } = useQuery({
    queryKey: ['warehouse', 'reports', 'hazardous', hazardousDays],
    queryFn: () => fetchJson<HazardousData>(`hazardous?days=${hazardousDays}`),
  })
  const { data: usageCompare } = useQuery({
    queryKey: ['warehouse', 'reports', 'usage-compare', compareMonth.year(), compareMonth.month() + 1],
    queryFn: () => fetchJson<UsageCompareData>(`usage-compare?year=${compareMonth.year()}&month=${compareMonth.month() + 1}`),
  })

  const monthlyColumns: TableColumnsType<MonthlyData['items'][0]> = [
    {
      title: '物料 / 单位',
      dataIndex: 'material_name',
      width: 260,
      render: (_, record) => (
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium text-[var(--color-charcoal)]">
            {record.material_name}
          </div>
          <div className="truncate text-[12px] leading-4 text-[var(--color-steel)]">
            {record.material_code} · {record.unit}
          </div>
        </div>
      ),
    },
    { title: '入库数量', dataIndex: 'inbound_qty', width: 120, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
    { title: '出库数量', dataIndex: 'outbound_qty', width: 120, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
  ]

  const summary = monthly?.summary

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '报表中心']}
        title="报表中心"
        description="出入库月报、库存快照与自然语言导出"
        actions={
          <>
            <Button icon={<Download size={14} />} onClick={() => exportExcel('stock/export', '当前库存报表.xlsx')}>
              库存快照
            </Button>
            <Button type="primary" icon={<Sparkles size={14} />} onClick={() => setNlOpen(true)}>
              AI 导出
            </Button>
          </>
        }
      />

      <SectionCard
        title="出入库月报"
        description="按月汇总物料出入库数量"
        action={
          <Space>
            <DatePicker picker="month" value={month} onChange={v => v && setMonth(v)} allowClear={false} />
            <Button
              size="small"
              icon={<Download size={13} />}
              onClick={() => exportExcel(`monthly/export?year=${month.year()}&month=${month.month() + 1}`, `出入库月报-${month.format('YYYY-MM')}.xlsx`)}
            >
              导出 Excel
            </Button>
          </Space>
        }
      >
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="入库笔数" tone="ok" value={summary?.inbound_count ?? 0} loading={!monthly} />
          <StatCard label="入库数量" tone="ok" value={summary?.inbound_qty ?? 0} loading={!monthly} />
          <StatCard label="出库笔数" tone="danger" value={summary?.outbound_count ?? 0} loading={!monthly} />
          <StatCard label="出库数量" tone="danger" value={summary?.outbound_qty ?? 0} loading={!monthly} />
        </div>

        <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div>
            <div className="mb-1 text-[13px] font-medium text-[var(--color-charcoal)]">
              入库 Top10 <span className="font-normal text-[var(--color-steel)]">（{month.format('YYYY-MM')}）</span>
            </div>
            <RankBarChart
              names={topItems(monthly?.items ?? [], 'inbound_qty').map(it => it.material_name)}
              values={topItems(monthly?.items ?? [], 'inbound_qty').map(it => Number(it.inbound_qty))}
              color={TONE_HEX.ok}
              height={260}
              emptyText="本月暂无入库"
            />
          </div>
          <div>
            <div className="mb-1 text-[13px] font-medium text-[var(--color-charcoal)]">
              出库 Top10 <span className="font-normal text-[var(--color-steel)]">（{month.format('YYYY-MM')}）</span>
            </div>
            <RankBarChart
              names={topItems(monthly?.items ?? [], 'outbound_qty').map(it => it.material_name)}
              values={topItems(monthly?.items ?? [], 'outbound_qty').map(it => Number(it.outbound_qty))}
              color={TONE_HEX.danger}
              height={260}
              emptyText="本月暂无出库"
            />
          </div>
        </div>

        <Table
          rowKey="material_code"
          size="small"
          columns={monthlyColumns}
          dataSource={monthly?.items ?? []}
          loading={loadingMonthly}
          pagination={((monthly?.items.length ?? 0) > 20 ? { pageSize: 20 } : false)}
        />
      </SectionCard>

      <SectionCard
        title="出入库年报"
        description="12 个月月报聚合：年度汇总、逐月趋势与物料年度明细"
        action={
          <Space>
            <DatePicker picker="year" value={annualYear} onChange={v => v && setAnnualYear(v)} allowClear={false} />
            <Button
              size="small"
              icon={<Download size={13} />}
              onClick={() => exportExcel(`annual/export?year=${annualYear.year()}`, `出入库年报-${annualYear.year()}.xlsx`)}
            >
              导出 Excel
            </Button>
          </Space>
        }
      >
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="入库笔数" tone="ok" value={annual?.summary.inbound_count ?? 0} loading={!annual} />
          <StatCard label="入库数量" tone="ok" value={annual?.summary.inbound_qty ?? 0} loading={!annual} />
          <StatCard label="出库笔数" tone="danger" value={annual?.summary.outbound_count ?? 0} loading={!annual} />
          <StatCard label="出库数量" tone="danger" value={annual?.summary.outbound_qty ?? 0} loading={!annual} />
        </div>
        <RankBarChart
          names={(annual?.months ?? []).map(m => `${annualYear.year()}-${String(m.month).padStart(2, '0')}`)}
          values={(annual?.months ?? []).map(m => Number(m.outbound_qty))}
          color={TONE_HEX.danger}
          height={220}
          emptyText="本年度暂无出库"
        />
      </SectionCard>

      <SectionCard
        title="危化品 / 易制毒 / 易制爆专项"
        description="按物料大类与法规危险性分类过滤，关联期间出库与当前库存"
        action={
          <Space>
            <Select
              size="small"
              value={hazardousDays}
              onChange={setHazardousDays}
              style={{ width: 130 }}
              options={[30, 90, 180, 365].map(d => ({ value: d, label: `近 ${d} 天` }))}
            />
            <Button
              size="small"
              icon={<Download size={13} />}
              onClick={() => exportExcel(`hazardous/export?days=${hazardousDays}`, `危化品专项报表-${hazardousDays}天.xlsx`)}
            >
              导出 Excel
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="material_name"
          size="small"
          columns={[
            { title: '物料名称', dataIndex: 'material_name' },
            { title: '物料大类', dataIndex: 'category', width: 110 },
            { title: '法规危险性分类', dataIndex: 'legal_class', width: 170 },
            { title: `近 ${hazardousDays} 天出库`, dataIndex: 'outbound_qty', width: 130, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
            { title: '当前库存', dataIndex: 'current_stock', width: 110, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
          ]}
          dataSource={hazardous?.items ?? []}
          loading={!hazardous}
          pagination={((hazardous?.items.length ?? 0) > 20 ? { pageSize: 20 } : false)}
        />
      </SectionCard>

      <SectionCard
        title="月度实际 vs 预期用量"
        description="物料月度实际领用与主数据「月度预期用量」基准对比（基准在物料主数据维护）"
        action={
          <Space>
            <DatePicker picker="month" value={compareMonth} onChange={v => v && setCompareMonth(v)} allowClear={false} />
            <Button
              size="small"
              icon={<Download size={13} />}
              onClick={() => exportExcel(`usage-compare/export?year=${compareMonth.year()}&month=${compareMonth.month() + 1}`, `用量对比-${compareMonth.format('YYYY-MM')}.xlsx`)}
            >
              导出 Excel
            </Button>
          </Space>
        }
      >
        {usageCompare && usageCompare.no_baseline_with_usage > 0 && (
          <Typography.Text type="warning" style={{ display: 'block', marginBottom: 8 }}>
            有 {usageCompare.no_baseline_with_usage} 种物料产生用量但未设基准（请在物料主数据「月度预期用量」列维护）
          </Typography.Text>
        )}
        <Table
          rowKey="material_name"
          size="small"
          columns={[
            { title: '物料名称', dataIndex: 'material_name' },
            { title: '实际用量', dataIndex: 'actual_qty', width: 120, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
            { title: '预期基准', dataIndex: 'expected_qty', width: 120, align: 'right', render: v => <span className="tabular-nums">{v}</span> },
            {
              title: '偏差率',
              dataIndex: 'deviation',
              width: 110,
              align: 'right',
              render: v => (v === null ? <span className="text-[var(--color-steel)]">-</span> : <span className="tabular-nums">{(v * 100).toFixed(0)}%</span>),
            },
          ]}
          dataSource={usageCompare?.items ?? []}
          loading={!usageCompare}
          pagination={((usageCompare?.items.length ?? 0) > 20 ? { pageSize: 20 } : false)}
        />
      </SectionCard>

      <NlExportModal open={nlOpen} onClose={() => setNlOpen(false)} />
    </div>
  )
}

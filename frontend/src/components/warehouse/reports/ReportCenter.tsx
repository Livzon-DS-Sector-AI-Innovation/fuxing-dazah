'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Alert, App, Button, Card, DatePicker, Input, Space, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { ReloadOutlined } from '@ant-design/icons'

const BASE = '/api/v1/warehouse/reports'

interface MonthlyData {
  year: number; month: number
  summary: { inbound_count: number; inbound_qty: number; outbound_count: number; outbound_qty: number }
  items: { material_code: string; material_name: string; unit: string; inbound_qty: number; outbound_qty: number }[]
}

async function fetchMonthly(year: number, month: number): Promise<MonthlyData> {
  const resp = await fetch(`${BASE}/monthly?year=${year}&month=${month}`)
  const body = await resp.json()
  return body.data
}

function exportExcel(path: string, filename: string) {
  const link = document.createElement('a')
  link.href = `${BASE}/${path}`
  link.download = filename
  link.click()
}

export function ReportCenter() {
  const { message } = App.useApp()
  const [month, setMonth] = useState<Dayjs>(dayjs())
  const [nlQuery, setNlQuery] = useState('')

  const { data: monthly, isLoading: loadingMonthly } = useQuery({
    queryKey: ['warehouse', 'reports', 'monthly', month.year(), month.month() + 1],
    queryFn: () => fetchMonthly(month.year(), month.month() + 1),
  })

  const monthlyColumns: TableColumnsType<MonthlyData['items'][0]> = [
    { title: '物料编码', dataIndex: 'material_code', width: 140 },
    { title: '物料名称', dataIndex: 'material_name', width: 180 },
    { title: '单位', dataIndex: 'unit', width: 70 },
    { title: '入库数量', dataIndex: 'inbound_qty', width: 110, align: 'right' },
    { title: '出库数量', dataIndex: 'outbound_qty', width: 110, align: 'right' },
  ]

  const handleNlExport = async () => {
    if (!nlQuery.trim()) { message.warning('请输入导出条件'); return }
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
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败')
    }
  }

  return (
    <div>
      <Card size="small" title="AI 自然语言导出" style={{ marginBottom: 12 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="如：导出 9 月出库大于 100 的物料"
            value={nlQuery}
            onChange={e => setNlQuery(e.target.value)}
            onPressEnter={handleNlExport}
          />
          <Button type="primary" onClick={handleNlExport}>导出</Button>
        </Space.Compact>
        <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
          解析失败时自动降级为当前筛选条件导出
        </Typography.Text>
      </Card>

      <Card size="small" title="出入库月报" extra={
        <Space>
          <DatePicker picker="month" value={month} onChange={v => v && setMonth(v)} />
          <Button size="small" icon={<ReloadOutlined />} onClick={() => exportExcel(`monthly/export?year=${month.year()}&month=${month.month() + 1}`, `出入库月报-${month.format('YYYY-MM')}.xlsx`)}>
            导出
          </Button>
        </Space>
      }>
        {monthly && (
          <Space wrap style={{ marginBottom: 12 }}>
            <Typography.Text>入库 {monthly.summary.inbound_count} 笔 / {monthly.summary.inbound_qty}</Typography.Text>
            <Typography.Text>出库 {monthly.summary.outbound_count} 笔 / {monthly.summary.outbound_qty}</Typography.Text>
          </Space>
        )}
        <Table
          rowKey="material_code" size="small" columns={monthlyColumns}
          dataSource={monthly?.items ?? []} loading={loadingMonthly} pagination={false}
        />
      </Card>

      <Card size="small" title="当前库存报表" style={{ marginTop: 12 }} extra={
        <Button size="small" onClick={() => exportExcel('stock/export', '当前库存报表.xlsx')}>导出</Button>
      }>
        <Typography.Text type="secondary">在"库存管理"页查看明细，此处提供全量导出入口</Typography.Text>
      </Card>
    </div>
  )
}

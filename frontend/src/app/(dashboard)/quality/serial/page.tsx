'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Card, Table, DatePicker, Space, Button, App, Segmented, Input } from 'antd'
import { PrinterOutlined, SearchOutlined, DownloadOutlined, FileExcelOutlined, EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import * as XLSX from 'xlsx'
import type { DailyReportItem, MonthlyReportSummary } from '@/types/quality'
import { fetchDailyReports, fetchMonthlyReports, downloadReportFile } from '@/actions/quality'
import { CoaPreviewModal } from '@/components/quality'

const { Title, Paragraph } = Typography

type ViewMode = 'day' | 'month'

export default function SerialRegistryPage() {
  const { message } = App.useApp()
  const [viewMode, setViewMode] = useState<ViewMode>('day')
  const [date, setDate] = useState(dayjs())
  const [month, setMonth] = useState(dayjs())
  // 在线预览
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewTitle, setPreviewTitle] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<DailyReportItem[]>([])
  const [monthly, setMonthly] = useState<MonthlyReportSummary | null>(null)
  // 产品筛选（草稿/提交两态：点搜索才生效）
  const [productDraft, setProductDraft] = useState('')
  const [productSearch, setProductSearch] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      if (viewMode === 'day') {
        const res = await fetchDailyReports(date.format('YYYY-MM-DD'), productSearch || undefined)
        setData(res.data || [])
      } else {
        const res = await fetchMonthlyReports(month.format('YYYY-MM'), productSearch || undefined)
        setMonthly(res.data)
      }
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '查询失败')
    } finally {
      setLoading(false)
    }
  }, [viewMode, date, month, productSearch, message])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openPreview = (r: DailyReportItem) => {
    setPreviewId(r.report_id)
    setPreviewTitle(`报告单预览（${r.serial_no}｜批号 ${r.batch_number}）`)
  }

  const handleDownload = async (r: DailyReportItem) => {
    try {
      const blob = await downloadReportFile(r.report_id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `COA-${r.batch_number}.docx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '下载失败')
    }
  }

  const handleExport = () => {
    if (!data.length) {
      message.warning('当日暂无流水记录可导出')
      return
    }
    const wb = XLSX.utils.book_new()
    const rows = data.map((r) => ({
      '流水号': r.serial_no,
      '产品名称': r.product_name,
      '批号': r.batch_number,
      '模板': r.template_path,
      '时间': r.created_at,
    }))
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), '报告单流水')
    XLSX.writeFile(wb, `报告单流水-${date.format('YYYYMMDD')}.xlsx`)
  }

  const handleExportMonth = () => {
    if (!monthly || !monthly.total) {
      message.warning('当月暂无流水记录可导出')
      return
    }
    const wb = XLSX.utils.book_new()
    const rows = monthly.days.flatMap((d) =>
      d.items.map((r) => ({
        '日期': d.date,
        '流水号': r.serial_no,
        '产品名称': r.product_name,
        '批号': r.batch_number,
        '模板': r.template_path,
        '时间': r.created_at,
      })),
    )
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), '月度流水')
    XLSX.writeFile(wb, `报告单流水-${monthly.month}.xlsx`)
  }

  const itemColumns = [
    { title: '流水号', dataIndex: 'serial_no', key: 'serial_no', width: 120 },
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', ellipsis: true },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 140 },
    { title: '模板', dataIndex: 'template_path', key: 'template_path', width: 140, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 90 },
    {
      title: '操作', key: 'actions', width: 160,
      render: (_: unknown, r: DailyReportItem) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => openPreview(r)}>预览</Button>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(r)}>下载</Button>
        </Space>
      ),
    },
  ]

  const monthColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', width: 130 },
    { title: '份数', dataIndex: 'count', key: 'count', width: 80 },
    {
      title: '流水号范围', key: 'serial_range', ellipsis: true,
      render: (_: unknown, d: MonthlyReportSummary['days'][number]) => {
        const serials = d.items.map((i) => i.serial_no).filter((s) => s !== '-')
        if (!serials.length) return '-'
        const sorted = [...serials].sort()
        return sorted.length === 1 ? sorted[0] : `${sorted[0]} ~ ${sorted[sorted.length - 1]}`
      },
    },
  ]

  return (
    <div className="space-y-4">
      <style>{`
        @media print {
          body * { visibility: hidden; }
          #serial-print-area, #serial-print-area * { visibility: visible; }
          #serial-print-area { position: absolute; left: 0; top: 0; width: 100%; }
          #serial-print-area table { width: 100%; border-collapse: collapse; font-size: 13px; }
          #serial-print-area th, #serial-print-area td { border: 1px solid #333; padding: 6px 10px; text-align: left; }
        }
      `}</style>

      <div>
        <Title level={3} style={{ marginBottom: 4 }}>📇 报告单流水</Title>
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          按日或按月查询报告单流水号（流水号｜产品｜批号），支持打印存档与 Excel 导出。打印模板接入后可按正式版式出单。
        </Paragraph>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Segmented
          value={viewMode}
          onChange={(v) => setViewMode(v as ViewMode)}
          options={[{ label: '按日', value: 'day' }, { label: '按月', value: 'month' }]}
        />
        {viewMode === 'day' ? (
          <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
        ) : (
          <DatePicker
            picker="month"
            value={month}
            onChange={(d) => d && setMonth(d)}
            allowClear={false}
          />
        )}
        <Input
          placeholder="产品名称筛选（可选）"
          allowClear
          value={productDraft}
          onChange={(e) => setProductDraft(e.target.value)}
          onPressEnter={() => setProductSearch(productDraft)}
          style={{ width: 180 }}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={() => { setProductSearch(productDraft); load() }}>查询</Button>
        {viewMode === 'day' ? (
          <>
            <Button icon={<FileExcelOutlined />} onClick={handleExport}>导出 Excel</Button>
            <Button icon={<PrinterOutlined />} onClick={() => window.print()}>打印</Button>
          </>
        ) : (
          <Button icon={<FileExcelOutlined />} onClick={handleExportMonth}>导出当月 Excel</Button>
        )}
      </Space>

      {/* 打印区：纯表格版式（打印模板接入后替换为模板样式）。
          注意：不能再用 inline display:none（会压过 @media print 规则导致打印空白），
          改为 Tailwind 的 hidden + print:block。 */}
      <div id="serial-print-area" className="hidden print:block">
        <h2 style={{ textAlign: 'center' }}>{date.format('YYYY-MM-DD')} 报告单流水</h2>
        <table>
          <thead>
            <tr><th>流水号</th><th>产品名称</th><th>批号</th><th>模板</th><th>时间</th></tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.report_id}>
                <td>{r.serial_no}</td>
                <td>{r.product_name}</td>
                <td>{r.batch_number}</td>
                <td>{r.template_path}</td>
                <td>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {viewMode === 'day' ? (
        <Card size="small" title={`${date.format('YYYY-MM-DD')} 报告单流水（${data.length} 份）`}>
          <Table
            rowKey="report_id"
            scroll={{ x: 800 }}
            columns={itemColumns}
            dataSource={data}
            loading={loading}
            size="small"
            pagination={false}
          />
        </Card>
      ) : (
        <Card size="small" title={`${monthly?.month || month.format('YYYY-MM')} 月度流水汇总（共 ${monthly?.total ?? 0} 份，${monthly?.days.length ?? 0} 个出报日）`}>
          <Table
            rowKey="date"
            columns={monthColumns}
            dataSource={monthly?.days || []}
            loading={loading}
            size="small"
            pagination={false}
            expandable={{
              expandedRowRender: (d) => (
                <Table
                  rowKey="report_id"
                  scroll={{ x: 800 }}
                  columns={itemColumns}
                  dataSource={d.items}
                  size="small"
                  pagination={false}
                />
              ),
            }}
          />
        </Card>
      )}

      <CoaPreviewModal
        open={!!previewId}
        reportId={previewId}
        title={previewTitle}
        onClose={() => setPreviewId(null)}
      />
    </div>
  )
}

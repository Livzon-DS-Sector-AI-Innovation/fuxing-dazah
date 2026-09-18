'use client'

import { useEffect, useState, useCallback } from 'react'
import { Typography, Card, Table, DatePicker, Space, Button, App } from 'antd'
import { PrinterOutlined, SearchOutlined, DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { DailyReportItem } from '@/types/quality'
import { fetchDailyReports, downloadReportFile } from '@/actions/quality'

const { Title, Paragraph } = Typography

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export default function SerialRegistryPage() {
  const { message } = App.useApp()
  const [date, setDate] = useState(dayjs())
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<DailyReportItem[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchDailyReports(date.format('YYYY-MM-DD'))
      setData(res.data || [])
    } catch (err: any) {
      message.error(err.message || '查询失败')
    } finally {
      setLoading(false)
    }
  }, [date, message])

  useEffect(() => { load() }, [load])

  const handleDownload = async (r: DailyReportItem) => {
    try {
      const blob = await downloadReportFile(r.report_id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `COA-${r.batch_number}.docx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      message.error(err.message || '下载失败')
    }
  }

  const columns = [
    { title: '流水号', dataIndex: 'serial_no', key: 'serial_no', width: 120 },
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', ellipsis: true },
    { title: '批号', dataIndex: 'batch_number', key: 'batch_number', width: 140 },
    { title: '模板', dataIndex: 'template_path', key: 'template_path', width: 140, ellipsis: true },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 90 },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_: unknown, r: DailyReportItem) => (
        <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(r)}>下载</Button>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <style>{`
        @media print {
          body * { visibility: hidden; }
          #serial-print-area, #serial-print-area * { visibility: visible; }
          #serial-print-area { display: block; position: absolute; left: 0; top: 0; width: 100%; }
          #serial-print-area table { width: 100%; border-collapse: collapse; font-size: 13px; }
          #serial-print-area th, #serial-print-area td { border: 1px solid #333; padding: 6px 10px; text-align: left; }
        }
      `}</style>

      <div>
        <Title level={3} style={{ marginBottom: 4 }}>📇 报告单流水</Title>
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          按日期查询报告单流水号（流水号｜产品｜批号），支持打印存档。打印模板接入后可按正式版式出单。
        </Paragraph>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
        <Button type="primary" icon={<SearchOutlined />} onClick={load}>查询</Button>
        <Button icon={<PrinterOutlined />} onClick={() => window.print()}>打印</Button>
      </Space>

      {/* 打印区：纯表格版式（打印模板接入后替换为模板样式） */}
      <div id="serial-print-area" style={{ display: 'none' }}>
        <h2 style={{ textAlign: 'center' }}>{date.format('YYYY-MM-DD')} 报告单流水</h2>
        <table>
          <thead>
            <tr><th>流水号</th><th>产品名称</th><th>批号</th><th>时间</th></tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.report_id}>
                <td>{r.serial_no}</td>
                <td>{r.product_name}</td>
                <td>{r.batch_number}</td>
                <td>{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Card size="small" title={`${date.format('YYYY-MM-DD')} 报告单流水（${data.length} 份）`}>
        <Table
          rowKey="report_id"
          columns={columns}
          dataSource={data}
          loading={loading}
          size="small"
          pagination={false}
        />
      </Card>
    </div>
  )
}

'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, Table, Select, DatePicker, Space, Statistic, Row, Col, App, Typography } from 'antd'
import { BarChartOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined } from '@ant-design/icons'
import type { HistorySummary, ProductSummary } from '@/types/quality'
import { fetchHistorySummary, fetchSummaryProducts } from '@/actions/quality'

const { Title } = Typography
const { RangePicker } = DatePicker

export default function SummaryView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<HistorySummary | null>(null)
  const [products, setProducts] = useState<string[]>([])
  const [selectedProduct, setSelectedProduct] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)

  useEffect(() => {
    fetchSummaryProducts().then(setProducts).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchHistorySummary(
        selectedProduct,
        dateRange?.[0],
        dateRange?.[1],
      )
      setSummary(data)
    } catch {
      message.error('加载汇总失败')
    } finally {
      setLoading(false)
    }
  }, [selectedProduct, dateRange, message])

  useEffect(() => { load() }, [load])

  const productColumns = [
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name' },
    { title: '检验次数', dataIndex: 'total', key: 'total' },
    {
      title: '合格率', key: 'pass_rate',
      render: (_: any, r: ProductSummary) =>
        `${r.total > 0 ? (r.pass_count / r.total * 100).toFixed(1) : 0}%`,
    },
    { title: '合格/不合格', key: 'pass_fail',
      render: (_: any, r: ProductSummary) =>
        `${r.pass_count} / ${r.fail_count}` },
    { title: 'OOT 次数', dataIndex: 'oot_count', key: 'oot_count' },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Select
          placeholder="全部产品"
          allowClear
          value={selectedProduct}
          onChange={setSelectedProduct}
          options={products.map(p => ({ value: p, label: p }))}
          style={{ width: 200 }}
        />
        <RangePicker
          onChange={(_, dateStrings) => {
            setDateRange(dateStrings[0] && dateStrings[1] ? dateStrings as [string, string] : null)
          }}
        />
      </Space>

      {summary && (
        <>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="检验总次数" value={summary.total} prefix={<BarChartOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="合格率" value={summary.pass_rate}
                  suffix="%" valueStyle={{ color: summary.pass_rate >= 95 ? '#52c41a' : '#faad14' }}
                  prefix={<CheckCircleOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="不合格" value={summary.fail_count}
                  valueStyle={{ color: summary.fail_count > 0 ? '#ff4d4f' : '#52c41a' }}
                  prefix={<CloseCircleOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="OOT 次数" value={summary.oot_count}
                  valueStyle={{ color: summary.oot_count > 0 ? '#faad14' : '#52c41a' }}
                  prefix={<WarningOutlined />} />
              </Card>
            </Col>
          </Row>

          <Card size="small" title="按产品分组统计">
            <Table
              columns={productColumns}
              dataSource={summary.products.map((p, i) => ({ ...p, key: i }))}
              loading={loading}
              pagination={false}
              size="small"
            />
          </Card>
        </>
      )}
    </div>
  )
}

'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Alert, Card, Col, List, Row, Spin, Statistic, Tag, Typography } from 'antd'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DatabaseOutlined,
  InboxOutlined,
  MinusOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import {
  fetchDashboardSummaryClient,
  fetchDashboardTodosClient,
  fetchLowStockTopClient,
  fetchMovementTrendClient,
  fetchStockDistributionClient,
} from '@/lib/api/warehouse'
import {
  MATERIAL_CATEGORY_LABEL,
  type DashboardSummary,
  type LowStockTop,
  type MovementTrendPoint,
  type StockDistribution,
  type DashboardTodos,
} from '@/types/warehouse'

const LOCATION_TYPE_LABEL: Record<string, string> = {
  normal: '常温',
  cold: '冷藏',
  danger: '危险品',
}

const CHART_HEIGHT = 240

function categoryLabel(key: string): string {
  return MATERIAL_CATEGORY_LABEL[key as keyof typeof MATERIAL_CATEGORY_LABEL] ?? key
}

function TrendChart({ data }: { data: MovementTrendPoint[] | undefined }) {
  if (!data) return <Spin />
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['入库', '出库'], bottom: 0 },
    grid: { left: 48, right: 16, top: 24, bottom: 48 },
    xAxis: { type: 'category', data: data.map(p => p.date.slice(5)) },
    yAxis: { type: 'value' },
    series: [
      { name: '入库', type: 'line', smooth: true, data: data.map(p => p.inbound) },
      { name: '出库', type: 'line', smooth: true, data: data.map(p => p.outbound) },
    ],
  }
  return <ReactECharts option={option} style={{ height: CHART_HEIGHT }} notMerge />
}

function DistributionCharts({ data }: { data: StockDistribution | undefined }) {
  if (!data) return <Spin />
  const pieOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['38%', '66%'],
        data: data.by_category.map(item => ({
          name: categoryLabel(item.category),
          value: item.total_quantity,
        })),
      },
    ],
  }
  const barOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 64, right: 24, top: 16, bottom: 32 },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: data.by_location_type.map(item => LOCATION_TYPE_LABEL[item.location_type] ?? item.location_type),
    },
    series: [{ type: 'bar', barMaxWidth: 24, data: data.by_location_type.map(item => item.total_quantity) }],
  }
  return (
    <Row gutter={12}>
      <Col span={12}>
        <Typography.Text type="secondary">按物料分类</Typography.Text>
        <ReactECharts option={pieOption} style={{ height: CHART_HEIGHT }} notMerge />
      </Col>
      <Col span={12}>
        <Typography.Text type="secondary">按库位类型</Typography.Text>
        <ReactECharts option={barOption} style={{ height: CHART_HEIGHT }} notMerge />
      </Col>
    </Row>
  )
}

function TopBars({
  data,
  onDrill,
}: {
  data: LowStockTop | undefined
  onDrill: (keyword: string) => void
}) {
  if (!data) return <Spin />
  const barOption = (title: string, names: string[], values: number[]) => ({
    title: { text: title, left: 'center', textStyle: { fontSize: 13 } },
    tooltip: { trigger: 'axis' },
    grid: { left: 100, right: 32, top: 32, bottom: 24 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: names, axisLabel: { width: 88, overflow: 'truncate' } },
    series: [{ type: 'bar', barMaxWidth: 18, data: values }],
  })
  return (
    <Row gutter={12}>
      <Col span={12}>
        <ReactECharts
          option={barOption(
            '低库存（库存 < 安全库存）',
            data.low_stock.map(i => i.material_name),
            data.low_stock.map(i => i.total_quantity),
          )}
          style={{ height: CHART_HEIGHT }}
          notMerge
          onEvents={{
            click: (params: { name: string }) => onDrill(params.name),
          }}
        />
        {data.low_stock.length === 0 && (
          <Typography.Text type="secondary">暂无低库存物料</Typography.Text>
        )}
      </Col>
      <Col span={12}>
        <ReactECharts
          option={barOption(
            `呆滞（${90} 天无入库）`,
            data.idle.map(i => i.material_name),
            data.idle.map(i => i.total_quantity),
          )}
          style={{ height: CHART_HEIGHT }}
          notMerge
          onEvents={{
            click: (params: { name: string }) => onDrill(params.name),
          }}
        />
        {data.idle.length === 0 && (
          <Typography.Text type="secondary">暂无呆滞物料</Typography.Text>
        )}
      </Col>
    </Row>
  )
}

function TodosPanel({ data }: { data: DashboardTodos | undefined }) {
  const router = useRouter()
  if (!data) return <Spin />
  return (
    <div>
      <Typography.Text strong>低库存（前 5）</Typography.Text>
      <List
        size="small"
        dataSource={data.low_stock_items}
        locale={{ emptyText: '暂无低库存物料' }}
        renderItem={item => (
          <List.Item
            style={{ cursor: 'pointer' }}
            onClick={() => router.push(`/warehouse/inventory?keyword=${encodeURIComponent(item.material_code)}`)}
          >
            <Typography.Text>
              <WarningOutlined style={{ color: '#dd5b00', marginRight: 6 }} />
              {item.material_name}
            </Typography.Text>
            <Typography.Text type="secondary">
              {item.total_quantity} / 安全 {item.safety_stock}
            </Typography.Text>
          </List.Item>
        )}
      />
      <Typography.Text strong>进行中盘点</Typography.Text>
      <List
        size="small"
        dataSource={data.draft_stocktakes}
        locale={{ emptyText: '暂无草稿盘点单' }}
        renderItem={item => (
          <List.Item style={{ cursor: 'pointer' }} onClick={() => router.push('/warehouse/stocktake')}>
            <Typography.Text>{item.stocktake_no}</Typography.Text>
            <Typography.Text type="secondary">{item.remark ?? '-'}</Typography.Text>
          </List.Item>
        )}
      />
      <Typography.Text strong>最近出入库</Typography.Text>
      <List
        size="small"
        dataSource={data.recent_movements}
        locale={{ emptyText: '暂无出入库记录' }}
        renderItem={item => (
          <List.Item style={{ cursor: 'pointer' }} onClick={() => router.push('/warehouse/inout')}>
            <Typography.Text>
              {item.direction === 'inbound' ? (
                <Tag color="green">入</Tag>
              ) : item.direction === 'outbound' ? (
                <Tag color="red">出</Tag>
              ) : (
                <Tag color="orange">调</Tag>
              )}
              {item.material_name} × {item.quantity}
              {item.unit}
            </Typography.Text>
          </List.Item>
        )}
      />
    </div>
  )
}

function KpiCards({ summary }: { summary: DashboardSummary | undefined }) {
  const router = useRouter()
  const change = summary?.total_quantity_change
  return (
    <Row gutter={[12, 12]}>
      <Col xs={12} md={8} xl={5}>
        <Card size="small">
          <Statistic
            title="库存总量"
            value={summary?.total_quantity ?? 0}
            precision={2}
            prefix={<DatabaseOutlined />}
            suffix={
              change === null || change === undefined ? (
                <Tag style={{ fontSize: 12 }}>快照积累中</Tag>
              ) : change >= 0 ? (
                <span style={{ fontSize: 13, color: '#3f8f5f' }}>
                  <ArrowUpOutlined /> {change}
                </span>
              ) : (
                <span style={{ fontSize: 13, color: '#cf4444' }}>
                  <ArrowDownOutlined /> {Math.abs(change)}
                </span>
              )
            }
          />
        </Card>
      </Col>
      <Col xs={12} md={8} xl={5}>
        <Card size="small">
          <Statistic
            title="今日入库"
            value={summary?.today_inbound_quantity ?? 0}
            precision={2}
            prefix={<InboxOutlined />}
            suffix={<span style={{ fontSize: 13 }}>{summary?.today_inbound_count ?? 0} 笔</span>}
          />
        </Card>
      </Col>
      <Col xs={12} md={8} xl={5}>
        <Card size="small">
          <Statistic
            title="今日出库"
            value={summary?.today_outbound_quantity ?? 0}
            precision={2}
            prefix={<MinusOutlined />}
            suffix={<span style={{ fontSize: 13 }}>{summary?.today_outbound_count ?? 0} 笔</span>}
          />
        </Card>
      </Col>
      <Col xs={12} md={12} xl={4}>
        <Card
          size="small"
          hoverable
          onClick={() => router.push('/warehouse/inventory')}
        >
          <Statistic
            title="低库存项"
            value={summary?.low_stock_count ?? 0}
            valueStyle={summary && summary.low_stock_count > 0 ? { color: '#cf4444' } : undefined}
            prefix={<WarningOutlined />}
          />
        </Card>
      </Col>
      <Col xs={24} md={12} xl={5}>
        <Card
          size="small"
          hoverable
          onClick={() => router.push('/warehouse/stocktake')}
        >
          <Statistic title="进行中盘点" value={summary?.draft_stocktake_count ?? 0} />
        </Card>
      </Col>
    </Row>
  )
}

export function WarehouseDashboard() {
  const router = useRouter()

  const { data: summary } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'summary'],
    queryFn: fetchDashboardSummaryClient,
  })
  const { data: trend } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'trend'],
    queryFn: () => fetchMovementTrendClient(30),
  })
  const { data: distribution } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'distribution'],
    queryFn: fetchStockDistributionClient,
  })
  const { data: lowStockTop } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'low-stock-top'],
    queryFn: () => fetchLowStockTopClient(10),
  })
  const { data: todos } = useQuery({
    queryKey: ['warehouse', 'dashboard', 'todos'],
    queryFn: fetchDashboardTodosClient,
  })

  const drillToInventory = (keyword: string) => {
    if (keyword) router.push(`/warehouse/inventory?keyword=${encodeURIComponent(keyword)}`)
  }

  return (
    <div>
      <Alert type="info" showIcon message={summary?.summary_text ?? '正在加载驾驶舱摘要…'} style={{ marginBottom: 12 }} />
      <KpiCards summary={summary} />
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={16}>
          <Card size="small" title="出入库趋势（近 30 天）">
            <TrendChart data={trend} />
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="待办与预警">
            <TodosPanel data={todos} />
          </Card>
        </Col>
      </Row>
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col span={24}>
          <Card size="small" title="库存分布">
            <DistributionCharts data={distribution} />
          </Card>
        </Col>
      </Row>
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col span={24}>
          <Card size="small" title="重点关注 Top10（点击图条目下钻）">
            <TopBars data={lowStockTop} onDrill={drillToInventory} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

'use client'

import { Card, Descriptions, Table, Tag, Typography, Divider, Collapse, Statistic, Row, Col, Space } from 'antd'
import {
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import type { LcReportData, ImpurityResult, CalculatedResult } from '@/types/quality'

const { Title, Text } = Typography

interface Props {
  report: LcReportData
}

/** 将小数转为百分比显示 */
function toPct(val: number | null, decimals: number = 2): string {
  if (val === null || val === undefined) return '-'
  // 万古霉素B 值约 0.95（已是小数），杂质值约 0.002（已是小数）
  const pct = val * 100
  return pct.toFixed(decimals) + '%'
}

/** 取报告值（四舍五入后的值）*/
function reportVal(result: CalculatedResult): string {
  if (result.name === '总杂质') {
    return toPct(result.first_percent, 2)
  }
  // 取第一份和第二份中较大的
  const r1 = result.rounded_first || result.first_percent
  const r2 = result.rounded_second || result.second_percent
  if (r2 && r2 > 0) {
    return `${r1} / ${r2}`
  }
  return String(r1)
}

export default function LcReportView({ report }: Props) {
  // 整理杂质表格数据
  const impurityColumns = [
    { title: '杂质名称', dataIndex: 'name', key: 'name', width: 130 },
    {
      title: '第一份(%)',
      dataIndex: 'first_percent',
      key: 'first',
      width: 100,
      render: (_: any, r: ImpurityResult) => toPct(r.first_percent, 4),
    },
    {
      title: '第二份(%)',
      dataIndex: 'second_percent',
      key: 'second',
      width: 100,
      render: (_: any, r: ImpurityResult) => toPct(r.second_percent, 4),
    },
    {
      title: '限度(%)',
      dataIndex: 'limit',
      key: 'limit',
      width: 100,
      render: (_: any, r: ImpurityResult) => toPct(r.limit, 4),
    },
    {
      title: '判定',
      dataIndex: 'is_pass',
      key: 'pass',
      width: 70,
      render: (v: boolean) =>
        v ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>,
    },
    {
      title: 'OOT',
      dataIndex: 'is_oot',
      key: 'oot',
      width: 60,
      render: (v: boolean) =>
        v ? <Tag color="warning">OOT</Tag> : null,
    },
  ]

  // 质量标准表格
  const standardColumns = [
    { title: '项目', dataIndex: 'name', key: 'name', width: 130 },
    {
      title: '标准',
      dataIndex: 'limit',
      key: 'limit',
      width: 120,
      render: (_: any, s: any) => {
        const op = s.operator || '≤'
        return s.limit ? `${op} ${toPct(s.limit)}` : '-'
      },
    },
    {
      title: 'OOT(HAF)',
      dataIndex: 'oot_haf',
      key: 'oot_haf',
      width: 100,
      render: (v: number | null) => (v ? toPct(v) : '-'),
    },
    {
      title: 'OOT(HAA)',
      dataIndex: 'oot_haa',
      key: 'oot_haa',
      width: 100,
      render: (v: number | null) => (v ? toPct(v) : '-'),
    },
  ]

  return (
    <div style={{ maxWidth: 900 }}>
      {/* 标题 */}
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ marginBottom: 4 }}>
          <ExperimentOutlined /> {report.product_name}
        </Title>
        <Space size="large">
          <Text>批号: <Text strong>{report.batch_number}</Text></Text>
          <Text>标准: <Tag color="blue">{report.standard_type || 'USP'}</Tag></Text>
          <Text>表号: <Text code>{report.form_id}</Text></Text>
        </Space>
      </div>

      {/* 判定结果总览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="整体判定"
              value={report.all_pass ? '全部合格' : '存在不合格'}
              valueStyle={{ color: report.all_pass ? '#52c41a' : '#ff4d4f' }}
              prefix={report.all_pass ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="OOT 状态"
              value={report.has_oot ? '存在超趋势' : '无超趋势'}
              valueStyle={{ color: report.has_oot ? '#faad14' : '#52c41a' }}
              prefix={report.has_oot ? <WarningOutlined /> : <CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="杂质项目"
              value={report.impurity_results.length}
              suffix="项"
              prefix={<SafetyOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 峰面积数据 */}
      <Collapse
        defaultActiveKey={[]}
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'peak-areas',
            label: <><FileTextOutlined /> 供试液峰面积（原始数据）</>,
            children: (
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="供试液A 总峰面积 1st">
                  {report.total_peak_area_a_first?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="供试液A 总峰面积 2nd">
                  {report.total_peak_area_a_second?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="供试液A 主峰面积 1st">
                  {report.main_peak_area_a_first?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="供试液A 主峰面积 2nd">
                  {report.main_peak_area_a_second?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="供试液B 主峰面积(Ab) 1st">
                  {report.main_peak_area_b_first?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="供试液B 主峰面积(Ab) 2nd">
                  {report.main_peak_area_b_second?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="杂质总峰面积(At) 1st">
                  {report.total_impurity_area_first?.toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="杂质总峰面积(At) 2nd">
                  {report.total_impurity_area_second?.toLocaleString()}
                </Descriptions.Item>
              </Descriptions>
            ),
          },
        ]}
      />

      {/* 主要结果 */}
      <Card size="small" title="主要计算结果" style={{ marginBottom: 16 }}>
        {report.vancomycin_b && (
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="万古霉素B 报告值">
              <Text strong>{reportVal(report.vancomycin_b)}</Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>
                (计算值: {toPct(report.vancomycin_b.first_percent)} / {toPct(report.vancomycin_b.second_percent)})
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="限度">
              ≥ {toPct(report.vancomycin_b.limit)}
            </Descriptions.Item>
            <Descriptions.Item label="判定">
              {report.vancomycin_b.is_pass
                ? <Tag color="success">合格</Tag>
                : <Tag color="error">不合格</Tag>}
            </Descriptions.Item>
          </Descriptions>
        )}
        {report.total_impurities && (
          <Descriptions bordered size="small" column={2} style={{ marginTop: 8 }}>
            <Descriptions.Item label="总杂质">
              <Text strong>{toPct(report.total_impurities.first_percent, 2)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="限度">
              ≤ {toPct(report.total_impurities.limit)}
            </Descriptions.Item>
            <Descriptions.Item label="判定">
              {report.total_impurities.is_pass
                ? <Tag color="success">合格</Tag>
                : <Tag color="error">不合格</Tag>}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      {/* 杂质明细 */}
      <Card size="small" title="有关物质（杂质）明细" style={{ marginBottom: 16 }}>
        <Table
          columns={impurityColumns}
          dataSource={report.impurity_results.map((r, i) => ({ ...r, key: i }))}
          pagination={false}
          size="small"
          scroll={{ y: 400 }}
        />
      </Card>

      {/* 质量标准 */}
      <Collapse
        defaultActiveKey={[]}
        items={[
          {
            key: 'standards',
            label: <><SafetyOutlined /> 质量标准（共 {report.standards.length} 项）</>,
            children: (
              <Table
                columns={standardColumns}
                dataSource={report.standards.map((s, i) => ({ ...s, key: i }))}
                pagination={false}
                size="small"
              />
            ),
          },
        ]}
      />
    </div>
  )
}

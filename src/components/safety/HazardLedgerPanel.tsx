'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  Input,
  Select,
  Button,
  Space,
  Tag,
  App,
  Typography,
  Modal,
  Descriptions,
  Spin,
  Card,
  Row,
  Col,
  Statistic,
  DatePicker,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  ExportOutlined,
  DownloadOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
  AlertOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  getHazardIdentifications,
  getHILedgerStats,
  exportHazardLedgerPdf,
} from '@/actions/safety'
import type { HazardIdentification, HazardLedgerStats } from '@/types/safety'
import {
  OVERALL_STATUS_OPTIONS_HI,
  RISK_LEVEL_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Text } = Typography
const { RangePicker } = DatePicker

// 风险等级图标映射
const RISK_ICONS: Record<string, React.ReactNode> = {
  level_1: <SafetyCertificateOutlined style={{ color: '#f5222d' }} />,
  level_2: <WarningOutlined style={{ color: '#fa8c16' }} />,
  level_3: <AlertOutlined style={{ color: '#faad14' }} />,
  level_4: <InfoCircleOutlined style={{ color: '#52c41a' }} />,
}

// 风险等级卡片配置
const RISK_CARD_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  level_1: { label: '重大风险', color: '#f5222d', bgColor: '#fff1f0' },
  level_2: { label: '较大风险', color: '#fa8c16', bgColor: '#fff7e6' },
  level_3: { label: '一般风险', color: '#faad14', bgColor: '#fffbe6' },
  level_4: { label: '低风险', color: '#52c41a', bgColor: '#f6ffed' },
}

export default function HazardLedgerPanel() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<HazardIdentification[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<HazardLedgerStats>({
    total: 0, level_1: 0, level_2: 0, level_3: 0, level_4: 0,
  })
  const [queryParams, setQueryParams] = useState({ page: 1, page_size: 20 })
  const [keyword, setKeyword] = useState('')
  const [department, setDepartment] = useState<string | undefined>()
  const [position, setPosition] = useState<string | undefined>()
  const [riskLevel, setRiskLevel] = useState<string | undefined>()
  const [dateRange, setDateRange] = useState<[string, string] | null>(null)
  const { message } = App.useApp()

  // ── AI 导出 Modal 状态 ──
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [naturalQuery, setNaturalQuery] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportStep, setExportStep] = useState<string>('')

  // ── 展开行 key ──
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([])

  const loadStats = async () => {
    try {
      const res = await getHILedgerStats({
        department,
        position,
        risk_level: riskLevel,
        date_from: dateRange?.[0],
        date_to: dateRange?.[1],
      })
      if (res.code === 200 && res.data) {
        setStats(res.data as HazardLedgerStats)
      }
    } catch {
      // non-critical
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await getHazardIdentifications({
        ...queryParams,
        overall_status: 'completed',
        keyword: keyword || undefined,
        department,
        position,
        risk_level: riskLevel,
        date_from: dateRange?.[0],
        date_to: dateRange?.[1],
      })
      if (res.code === 200) {
        setData(res.data as HazardIdentification[])
        setTotal(res.meta?.total || 0)
      }
    } catch {
      message.error('加载台账失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
  }, [])

  useEffect(() => {
    loadData()
  }, [queryParams])

  const handleSearch = () => {
    setQueryParams({ page: 1, page_size: queryParams.page_size })
    loadData()
    loadStats()
  }

  const handleReset = () => {
    setKeyword('')
    setDepartment(undefined)
    setPosition(undefined)
    setRiskLevel(undefined)
    setDateRange(null)
    setQueryParams({ page: 1, page_size: 20 })
  }

  // ── base64 → Blob → 触发下载（客户端） ──
  const downloadBase64 = (base64: string, filename: string, mimeType: string) => {
    const byteCharacters = atob(base64)
    const byteNumbers = new Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i)
    }
    const byteArray = new Uint8Array(byteNumbers)
    const blob = new Blob([byteArray], { type: mimeType })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  }

  // ── 导出 PDF（AI 解析 → 筛选 → Excel标准化填表 → PDF）──
  const handleExportPdf = async () => {
    setExporting(true)
    setExportStep('AI 正在解析筛选条件…')
    try {
      const base64 = await exportHazardLedgerPdf({
        natural_query: naturalQuery.trim() || undefined,
      })
      setExportStep('下载中…')
      downloadBase64(
        base64,
        `危险源辨识台账_${new Date().toISOString().slice(0, 10)}.pdf`,
        'application/pdf'
      )
      message.success('PDF 导出成功')
      setExportModalOpen(false)
    } catch {
      message.error('PDF 导出失败')
    } finally {
      setExporting(false)
      setExportStep('')
    }
  }

  // ── 关闭弹窗时重置状态 ──
  const handleCloseExportModal = () => {
    setExportModalOpen(false)
    setNaturalQuery('')
  }

  const getRiskTag = (level?: string, label?: string) => {
    if (!level) return '-'
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <Tag color={opt?.color}>{label || level}</Tag>
  }

  const getControlLevelTag = (level?: string) => {
    if (!level) return '-'
    const colorMap: Record<string, string> = {
      '公司级': 'red',
      '部门级': 'orange',
      '班组级': 'blue',
    }
    return <Tag color={colorMap[level] || 'default'}>{level}</Tag>
  }

  const columns: ColumnsType<HazardIdentification> = [
    { title: '编号', dataIndex: 'hazard_id_no', key: 'hazard_id_no', width: 120 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 90, ellipsis: true },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 90, ellipsis: true },
    {
      title: '生产步骤', dataIndex: 'production_step', key: 'production_step', width: 140, ellipsis: true,
    },
    {
      title: '作业活动', dataIndex: 'specific_activity', key: 'specific_activity', width: 140, ellipsis: true,
      render: (v?: string) => v || '-',
    },
    {
      title: '事故类型', dataIndex: 'possible_accident', key: 'possible_accident', width: 100, ellipsis: true,
      render: (v?: string) => v || '-',
    },
    {
      title: '固有风险', key: 'inherent_risk', width: 90,
      render: (_, r) => getRiskTag(r.inherent_risk_level, r.inherent_risk_label),
    },
    {
      title: '残余风险', key: 'residual_risk', width: 90,
      render: (_, r) => getRiskTag(r.residual_risk_level, r.residual_risk_label),
    },
    {
      title: '措施后风险', key: 'post_risk', width: 90,
      render: (_, r) => getRiskTag(r.post_risk_level, r.post_risk_label),
    },
    {
      title: '管控层级', dataIndex: 'control_level', key: 'control_level', width: 80,
      render: (v?: string) => getControlLevelTag(v),
    },
    { title: '责任人', dataIndex: 'responsible_person', key: 'responsible_person', width: 80, ellipsis: true },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 110,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '操作', key: 'action', width: 70, fixed: 'right',
      render: (_, r) => (
        <Button
          type="link" size="small"
          onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
        >
          查看
        </Button>
      ),
    },
  ]

  // ── 展开行渲染 ──
  const expandedRowRender = (record: HazardIdentification) => {
    const lecRow = (label: string, l?: number, e?: number, c?: number, d?: number, level?: string, levelLabel?: string) => (
      <Descriptions
        size="small"
        column={6}
        colon={false}
        title={<Text strong style={{ fontSize: 13 }}>{label}</Text>}
        style={{ marginBottom: 0 }}
      >
        <Descriptions.Item label="L">{l ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="E">{e ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="C">{c ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="D">{d ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="等级" span={2}>
          {level ? getRiskTag(level, levelLabel) : '-'}
        </Descriptions.Item>
      </Descriptions>
    )

    return (
      <div style={{ padding: '12px 24px', background: '#fafafa', borderRadius: 8 }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {lecRow('固有风险评价', record.l_inherent, record.e_inherent, record.c_inherent, record.d_inherent, record.inherent_risk_level, record.inherent_risk_label)}

          {(record.existing_engineering_controls || record.existing_management_controls || record.existing_ppe || record.existing_emergency_measures) && (
            <Descriptions size="small" column={2} colon={false} title={<Text strong style={{ fontSize: 13 }}>现有控制措施</Text>}>
              {record.existing_engineering_controls && (
                <Descriptions.Item label="工程控制">{record.existing_engineering_controls}</Descriptions.Item>
              )}
              {record.existing_management_controls && (
                <Descriptions.Item label="管理措施">{record.existing_management_controls}</Descriptions.Item>
              )}
              {record.existing_ppe && (
                <Descriptions.Item label="PPE">{record.existing_ppe}</Descriptions.Item>
              )}
              {record.existing_emergency_measures && (
                <Descriptions.Item label="应急措施">{record.existing_emergency_measures}</Descriptions.Item>
              )}
            </Descriptions>
          )}

          {lecRow('残余风险评价', record.l_residual, record.e_residual, record.c_residual, record.d_residual, record.residual_risk_level, record.residual_risk_label)}

          {record.recommendation_content && (
            <Descriptions size="small" column={2} colon={false} title={<Text strong style={{ fontSize: 13 }}>建议措施</Text>}>
              {record.recommendation_type && (
                <Descriptions.Item label="类型">{record.recommendation_type}</Descriptions.Item>
              )}
              {record.recommendation_priority && (
                <Descriptions.Item label="优先级">
                  <Tag>{record.recommendation_priority}</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="内容" span={2}>{record.recommendation_content}</Descriptions.Item>
            </Descriptions>
          )}

          {lecRow('措施后风险评价', record.l_post, record.e_post, record.c_post, record.d_post, record.post_risk_level, record.post_risk_label)}
        </Space>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        marginBottom: 24,
      }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
            危险源辨识台账
          </h1>
          <p style={{ fontSize: 14, color: '#5d5b54', margin: '4px 0 0' }}>
            已完成危险源辨识记录的查询、统计与导出
          </p>
        </div>
        <Space>
          <Button type="primary" icon={<ExportOutlined />} onClick={() => setExportModalOpen(true)}>
            导出 PDF
          </Button>
        </Space>
      </div>

      {/* Stat Cards */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={4}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Statistic
              title="总记录数"
              value={stats.total}
              styles={{ content: { color: '#1677ff', fontSize: 24 } }}
            />
          </Card>
        </Col>
        {['level_1', 'level_2', 'level_3', 'level_4'].map((level) => {
          const cfg = RISK_CARD_CONFIG[level]
          const count = stats[level as keyof HazardLedgerStats] as number
          return (
            <Col xs={12} sm={5} key={level}>
              <Card
                size="small"
                style={{
                  borderRadius: 12,
                  border: `1px solid ${cfg.color}20`,
                  background: cfg.bgColor,
                }}
                styles={{ body: { padding: '16px 20px' } }}
              >
                <Statistic
                  title={cfg.label}
                  value={count}
                  prefix={RISK_ICONS[level]}
                  styles={{ content: { color: cfg.color, fontSize: 24 } }}
                />
              </Card>
            </Col>
          )
        })}
      </Row>

      {/* Filter Bar */}
      <div style={{
        background: '#f6f5f4', borderRadius: 12, border: '1px solid #e5e3df',
        padding: '16px 20px', marginBottom: 16,
      }}>
        <Space wrap>
          <Input
            placeholder="搜索编号/部门/岗位/作业"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 200 }}
            allowClear
          />
          <Input
            placeholder="部门"
            value={department}
            onChange={(e) => setDepartment(e.target.value || undefined)}
            onPressEnter={handleSearch}
            style={{ width: 120 }}
            allowClear
          />
          <Input
            placeholder="岗位"
            value={position}
            onChange={(e) => setPosition(e.target.value || undefined)}
            onPressEnter={handleSearch}
            style={{ width: 120 }}
            allowClear
          />
          <Select
            placeholder="风险等级"
            allowClear
            value={riskLevel}
            onChange={(v) => setRiskLevel(v)}
            style={{ width: 120 }}
            options={RISK_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
          <RangePicker
            placeholder={['开始日期', '结束日期']}
            value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')])
              } else {
                setDateRange(null)
              }
            }}
            style={{ width: 240 }}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            查询
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleReset}>
            重置
          </Button>
        </Space>
      </div>

      {/* Table */}
      <div style={{ borderRadius: 12, border: '1px solid #e5e3df', padding: 16, background: '#fff' }}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1400 }}
          size="small"
          expandable={{
            expandedRowRender,
            expandedRowKeys,
            onExpandedRowsChange: (keys) => setExpandedRowKeys(keys as string[]),
            rowExpandable: () => true,
          }}
          pagination={{
            current: queryParams.page,
            pageSize: queryParams.page_size,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => setQueryParams({ page, page_size: pageSize }),
          }}
        />
      </div>

      {/* ── 导出 PDF Modal（AI 解析→筛选→Excel标准化填表→PDF）── */}
      <Modal
        title={
          <span>
            <ExportOutlined style={{ marginRight: 8, color: '#5645D4' }} />
            导出 PDF
          </span>
        }
        open={exportModalOpen}
        onCancel={handleCloseExportModal}
        width={520}
        footer={[
          <Button key="cancel" onClick={handleCloseExportModal}>
            取消
          </Button>,
          <Button
            key="export"
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExportPdf}
          >
            导出 PDF
          </Button>,
        ]}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 自然语言输入 */}
          <div>
            <Text strong style={{ display: 'block', marginBottom: 6 }}>
              用自然语言描述要导出哪些记录：
            </Text>
            <Input.TextArea
              placeholder={'例如：\n- "上月所有重大风险记录"\n- "合成岗位最近三个月的数据"\n- "生产部一级和二级风险的危险源"'}
              value={naturalQuery}
              onChange={(e) => setNaturalQuery(e.target.value)}
              rows={3}
            />
            <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
              留空则导出全部已完成记录；输入自然语言后点击「导出 PDF」，AI 将自动解析筛选条件并导出。
            </Text>
          </div>

          {/* 导出进度提示 */}
          {exporting && (
            <div style={{ textAlign: 'center', padding: 16 }}>
              <Spin tip={exportStep || '正在导出…'} />
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}

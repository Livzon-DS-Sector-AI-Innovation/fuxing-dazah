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
  Modal,
  Card,
  Row,
  Col,
  Statistic,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  FileTextOutlined,
  SyncOutlined,
  AuditOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { getHazardIdentifications, deleteHazardIdentification, getHIStats } from '@/actions/safety'
import type { HazardIdentification, HazardIdentificationStats } from '@/types/safety'
import {
  AI_NODE_PROGRESS_OPTIONS,
  OVERALL_STATUS_OPTIONS_HI,
  RISK_LEVEL_OPTIONS,
} from '@/types/safety'

// AI 进度 → 步骤标签映射
const STEP_LABELS: Record<string, { step: number; label: string }> = {
  pending_input: { step: 0, label: '待填写基础信息' },
  pending_script1: { step: 1, label: '第1步：解析附件' },
  pending_script2: { step: 2, label: '第2步：危险源辨识' },
  pending_script3: { step: 3, label: '第3步：固有风险评价' },
  pending_script4: { step: 4, label: '第4步：控制措施' },
  pending_script5: { step: 5, label: '第5步：残余风险评价' },
  pending_script6: { step: 6, label: '第6步：建议措施' },
  pending_script7: { step: 7, label: '第7步：措施后评价' },
  completed: { step: 7, label: '已完成' },
}

// 搜索栏 AI 进度筛选项（排除 initial 状态 pending_input）
const AI_PROGRESS_FILTER_OPTIONS = AI_NODE_PROGRESS_OPTIONS.filter(
  (o) => o.value !== 'pending_input'
).map((o) => ({ value: o.value, label: o.label }))

// 筛选栏状态选项（排除 cancelled）
const STATUS_FILTER_OPTIONS = OVERALL_STATUS_OPTIONS_HI.filter(
  (o) => o.value !== 'cancelled'
)

export default function WorkflowListPanel() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<HazardIdentification[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<HazardIdentificationStats>({
    total_draft: 0,
    total_in_progress: 0,
    total_pending_review: 0,
    total_completed: 0,
  })
  const [queryParams, setQueryParams] = useState({ page: 1, page_size: 20 })
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [progressFilter, setProgressFilter] = useState<string | undefined>()
  const [deptFilter, setDeptFilter] = useState<string | undefined>()
  const { message } = App.useApp()

  const loadStats = async () => {
    try {
      const res = await getHIStats()
      if (res.code === 200 && res.data) {
        setStats(res.data as HazardIdentificationStats)
      }
    } catch {
      // stats load failure is non-critical
    }
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await getHazardIdentifications({
        ...queryParams,
        keyword: keyword || undefined,
        overall_status: statusFilter,
        ai_node_progress: progressFilter,
        department: deptFilter,
      })
      if (res.code === 200) {
        setData(res.data as HazardIdentification[])
        setTotal(res.meta?.total || 0)
      }
    } catch {
      message.error('加载列表失败')
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

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该危险源辨识记录吗？',
      onOk: async () => {
        const res = await deleteHazardIdentification(id)
        if (res.code === 200) {
          message.success('删除成功')
          loadData()
          loadStats()
        } else {
          message.error(res.message || '删除失败')
        }
      },
    })
  }

  const getStatusTag = (status: string) => {
    const opt = OVERALL_STATUS_OPTIONS_HI.find((o) => o.value === status)
    return <Tag color={opt?.color}>{opt?.label || status}</Tag>
  }

  const getStepTag = (progress: string) => {
    const step = STEP_LABELS[progress]
    if (!step) return <Tag>{progress}</Tag>
    const colorMap: Record<number, string> = {
      0: 'default', 1: 'processing', 2: 'processing', 3: 'processing',
      4: 'processing', 5: 'processing', 6: 'processing', 7: 'success',
    }
    return <Tag color={colorMap[step.step] || 'default'}>{step.label}</Tag>
  }

  const getRiskTag = (level?: string, label?: string) => {
    if (!level) return '-'
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <Tag color={opt?.color}>{label || level}</Tag>
  }

  const columns: ColumnsType<HazardIdentification> = [
    { title: '编号', dataIndex: 'hazard_id_no', key: 'hazard_id_no', width: 120 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, ellipsis: true },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 90, ellipsis: true },
    {
      title: '生产步骤', dataIndex: 'production_step', key: 'production_step', width: 160, ellipsis: true,
    },
    {
      title: '当前步骤', dataIndex: 'ai_node_progress', key: 'ai_node_progress', width: 140,
      render: (v: string) => getStepTag(v),
    },
    {
      title: '状态', dataIndex: 'overall_status', key: 'overall_status', width: 80,
      render: (v: string) => getStatusTag(v),
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 120,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      }) : '-',
    },
    {
      title: '操作', key: 'action', width: 160, fixed: 'right',
      render: (_, r) => (
        <Space size="small">
          {r.overall_status === 'in_progress' && (
            <Button
              type="link" size="small" icon={<PlayCircleOutlined />}
              onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
            >
              继续
            </Button>
          )}
          <Button
            type="link" size="small" icon={<EyeOutlined />}
            onClick={() => router.push(`/safety/hazard-identification/${r.id}`)}
          >
            查看
          </Button>
          {(r.overall_status === 'draft' || r.overall_status === 'cancelled') && (
            <Button
              type="link" size="small" danger icon={<DeleteOutlined />}
              onClick={() => handleDelete(r.id)}
            >
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        marginBottom: 24,
      }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
            危险源辨识工作流
          </h1>
          <p style={{ fontSize: 14, color: '#5d5b54', margin: '4px 0 0' }}>
            AI 7步危险源辨识与风险评价管理
          </p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => router.push('/safety/hazard-identification/new')}
        >
          新建辨识
        </Button>
      </div>

      {/* Stat Cards */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Statistic
              title="待提交"
              value={stats.total_draft}
              prefix={<FileTextOutlined style={{ color: '#8c8c8c' }} />}
              styles={{ content: { color: '#8c8c8c', fontSize: 24 } }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Statistic
              title="进行中"
              value={stats.total_in_progress}
              prefix={<SyncOutlined style={{ color: '#1677ff' }} />}
              styles={{ content: { color: '#1677ff', fontSize: 24 } }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Statistic
              title="待审核"
              value={stats.total_pending_review}
              prefix={<AuditOutlined style={{ color: '#fa8c16' }} />}
              styles={{ content: { color: '#fa8c16', fontSize: 24 } }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: '16px 20px' } }}
          >
            <Statistic
              title="已完成"
              value={stats.total_completed}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              styles={{ content: { color: '#52c41a', fontSize: 24 } }}
            />
          </Card>
        </Col>
      </Row>

      {/* Filter Bar */}
      <div style={{
        background: '#f6f5f4', borderRadius: 12, border: '1px solid #e5e3df',
        padding: '16px 20px', marginBottom: 16,
      }}>
        <Space wrap>
          <Input
            placeholder="搜索编号/部门/岗位"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            placeholder="AI 进度"
            allowClear
            value={progressFilter}
            onChange={(v) => setProgressFilter(v)}
            style={{ width: 160 }}
            options={AI_PROGRESS_FILTER_OPTIONS}
          />
          <Select
            placeholder="状态"
            allowClear
            value={statusFilter}
            onChange={(v) => setStatusFilter(v)}
            style={{ width: 110 }}
            options={STATUS_FILTER_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
          <Input
            placeholder="部门"
            value={deptFilter}
            onChange={(e) => setDeptFilter(e.target.value || undefined)}
            onPressEnter={handleSearch}
            style={{ width: 140 }}
            allowClear
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            查询
          </Button>
        </Space>
      </div>

      {/* Table */}
      <div style={{
        borderRadius: 12, border: '1px solid #e5e3df', padding: 16, background: '#fff',
      }}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1000 }}
          size="small"
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
    </div>
  )
}

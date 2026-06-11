'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Statistic,
  Modal,
  Descriptions,
  Alert,
  App,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  RobotOutlined,
  WarningOutlined,
  ClockCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  AuditOutlined,
  CloseCircleOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getHazards,
  updateHazard,
  reviewHazardAI,
  runHazardAI,
  deleteHazards,
} from '@/actions/safety'
import type {
  HazardReport,
  HazardLevel,
} from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_STATUS_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
  VERIFY_LEVEL_OPTIONS,
  VERIFY_LEVEL_STATUS_OPTIONS,
} from '@/types/safety'
import HazardRectificationReplyModal from '@/components/safety/HazardRectificationReplyModal'
import HazardVerifyModal from '@/components/safety/HazardVerifyModal'
import dayjs from 'dayjs'

const { Text, Title } = Typography

// ── AI 输出字段标签 ──
const AI_FIELD_LABELS: Record<string, string> = {
  hazard_type: '隐患分类',
  hazard_level: '隐患等级',
  hazard_category: '隐患类别',
  description: '隐患描述',
  location: '地点/部位',
  key_defect: '重点缺陷',
  major_hazard_basis: '判定依据',
  control_measures: '管控措施',
  corrective_preventive_measures: '纠正预防措施',
}

// ── 隐患类别标签映射 ──
const HAZARD_CATEGORY_LABEL_MAP: Record<string, string> = {}
HAZARD_CATEGORY_OPTIONS.forEach((o) => { HAZARD_CATEGORY_LABEL_MAP[o.value] = o.label })

export default function HazardLedgerPage() {
  const router = useRouter()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [levelFilter, setLevelFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [sourceFilter, setSourceFilter] = useState<string | undefined>()
  // ── AI 审核状态 ──
  const [reviewModalVisible, setReviewModalVisible] = useState(false)
  const [reviewingRecord, setReviewingRecord] = useState<HazardReport | null>(null)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [rerunLoading, setRerunLoading] = useState(false)
  // ── 整改回复 & 三级复核 ──
  const [replyModalVisible, setReplyModalVisible] = useState(false)
  const [replyMode, setReplyMode] = useState<'reply' | 'rework'>('reply')
  const [replyRecord, setReplyRecord] = useState<HazardReport | null>(null)
  const [verifyModalVisible, setVerifyModalVisible] = useState(false)
  const [verifyRecord, setVerifyRecord] = useState<HazardReport | null>(null)
  // ── 批量选择 & 删除 ──
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [deleting, setDeleting] = useState(false)

  const {
    hazards,
    hazardTotal,
    hazardQueryParams,
    setHazards,
    setHazardTotal,
    setHazardQueryParams,
    updateHazard: updateHazardInStore,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getHazards({
        ...hazardQueryParams,
        status: statusFilter,
        hazard_type: typeFilter,
        hazard_level: levelFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setHazards(response.data)
        setHazardTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载台账失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setSelectedRowKeys([])
    loadData()
  }, [hazardQueryParams.page, hazardQueryParams.page_size, statusFilter, typeFilter, levelFilter, sourceFilter])

  const handleSearch = () => {
    setHazardQueryParams({ page: 1 })
    loadData()
  }

  // ── 整改回复 ──
  const handleReply = (record: HazardReport) => {
    setReplyMode(record.rectification_status === 'rejected' ? 'rework' : 'reply')
    setReplyRecord(record)
    setReplyModalVisible(true)
  }

  // ── 三级复核 ──
  const handleVerifyLevel = (record: HazardReport) => {
    setVerifyRecord(record)
    setVerifyModalVisible(true)
  }

  // ── Modal 成功回调 ──
  const handleReplySuccess = (updated: HazardReport) => {
    updateHazardInStore(updated.id, updated)
  }

  const handleVerifySuccess = (updated: HazardReport) => {
    updateHazardInStore(updated.id, updated)
  }

  // ── 批量删除 ──
  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除选中的 ${selectedRowKeys.length} 条隐患记录吗？此操作不可撤销。`,
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setDeleting(true)
        try {
          const ids = selectedRowKeys as string[]
          const result = await deleteHazards(ids)
          if (result.failed === 0) {
            message.success(`成功删除 ${result.succeeded} 条记录`)
          } else {
            message.warning(`删除完成：${result.succeeded} 条成功，${result.failed} 条失败`)
          }
          setSelectedRowKeys([])
          await loadData()
        } catch {
          message.error('批量删除失败')
        } finally {
          setDeleting(false)
        }
      },
    })
  }

  // ── AI 审核 ──
  const handleOpenReview = (record: HazardReport) => {
    setReviewingRecord(record)
    setReviewModalVisible(true)
  }

  const handleReviewApprove = async () => {
    if (!reviewingRecord) return
    setReviewLoading(true)
    try {
      const response = await reviewHazardAI(reviewingRecord.id, 0, 'approved')
      if (response.code === 200) {
        message.success('审核通过，隐患已进入整改流程')
        updateHazardInStore(reviewingRecord.id, response.data)
        setReviewModalVisible(false)
      } else {
        message.error(response.message || '审核失败')
      }
    } catch {
      message.error('审核操作失败')
    } finally {
      setReviewLoading(false)
    }
  }

  const handleReviewReject = async () => {
    if (!reviewingRecord) return
    setReviewLoading(true)
    try {
      const response = await reviewHazardAI(reviewingRecord.id, 0, 'rejected')
      if (response.code === 200) {
        message.warning('已驳回，AI 将重新执行')
        updateHazardInStore(reviewingRecord.id, response.data)
        setReviewModalVisible(false)
      } else {
        message.error(response.message || '驳回失败')
      }
    } catch {
      message.error('驳回操作失败')
    } finally {
      setReviewLoading(false)
    }
  }

  const handleRerunAI = async (record: HazardReport) => {
    setRerunLoading(true)
    try {
      // 重跑 Step 1
      const r1 = await runHazardAI(record.id, 1)
      if (r1.code !== 200) {
        message.error('重新执行 AI 识别失败: ' + (r1.message || ''))
        return
      }
      updateHazardInStore(record.id, r1.data)
      // 重跑 Step 2
      const r2 = await runHazardAI(record.id, 2)
      if (r2.code === 200) {
        message.success('AI 已重新执行完成')
        updateHazardInStore(record.id, r2.data)
      } else {
        message.warning('AI 识别已完成，整改建议生成失败: ' + (r2.message || ''))
      }
    } catch {
      message.error('重新执行 AI 失败')
    } finally {
      setRerunLoading(false)
    }
  }

  const getLevelColor = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.color || 'default'
  }

  const getLevelLabel = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.label || level
  }

  // ── 统计 ──
  const stats = {
    total: hazardTotal,
    pendingReview: hazards.filter((h) => h.ai_generated && h.overall_status === 'completed').length,
    pending: hazards.filter((h) => h.rectification_status === 'pending' && h.status === 'open').length,
    inProgress: hazards.filter((h) => h.rectification_status === 'in_progress').length,
    replied: hazards.filter((h) => h.rectification_status === 'replied').length,
    verifying: hazards.filter(
      (h) => h.rectification_status === 'level1_approved' || h.rectification_status === 'level2_approved'
    ).length,
    rejected: hazards.filter((h) => h.rectification_status === 'rejected').length,
    closed: hazards.filter((h) => h.rectification_status === 'closed' || h.status === 'closed').length,
    overdue: hazards.filter(
      (h) => h.deadline && dayjs(h.deadline).isBefore(dayjs()) && h.status !== 'closed'
    ).length,
  }

  // ── 单操作按钮渲染（按状态优先级）──
  const renderAction = (record: HazardReport) => {
    // 1. AI 待审核
    if (record.ai_generated && record.overall_status === 'completed') {
      return (
        <Button
          type="link"
          size="small"
          icon={<AuditOutlined />}
          onClick={() => handleOpenReview(record)}
          style={{ color: '#dd5b00' }}
        >
          审核
        </Button>
      )
    }
    // 2. AI 错误 → 重试
    if (record.ai_error_message) {
      return (
        <Button
          type="link"
          size="small"
          loading={rerunLoading}
          onClick={() => handleRerunAI(record)}
        >
          重跑AI
        </Button>
      )
    }
    // 3. 整改状态机（pending 和 in_progress 均可直接整改回复）
    if (record.rectification_status === 'pending' || record.rectification_status === 'in_progress') {
      if (record.status !== 'open') return <Text type="secondary">-</Text>
      return (
        <Button
          type="link"
          size="small"
          icon={<CheckCircleOutlined />}
          onClick={() => handleReply(record)}
        >
          整改回复
        </Button>
      )
    }
    if (record.rectification_status === 'replied') {
      return (
        <Button
          type="link"
          size="small"
          icon={<SafetyCertificateOutlined />}
          onClick={() => handleVerifyLevel(record)}
        >
          一级复核
        </Button>
      )
    }
    if (record.rectification_status === 'level1_approved') {
      const nextLabel = record.hazard_level === 'general' ? '三级复核' : '二级复核'
      return (
        <Button
          type="link"
          size="small"
          icon={<SafetyCertificateOutlined />}
          onClick={() => handleVerifyLevel(record)}
        >
          {nextLabel}
        </Button>
      )
    }
    if (record.rectification_status === 'level2_approved') {
      return (
        <Button
          type="link"
          size="small"
          icon={<SafetyCertificateOutlined />}
          onClick={() => handleVerifyLevel(record)}
        >
          三级复核
        </Button>
      )
    }
    if (record.rectification_status === 'rejected') {
      return (
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleReply(record)}
          style={{ color: '#e03131' }}
        >
          重新整改
        </Button>
      )
    }
    // closed / 无需操作
    return <Text type="secondary">-</Text>
  }

  const columns: ColumnsType<HazardReport> = [
    {
      title: '隐患编号',
      dataIndex: 'hazard_no',
      key: 'hazard_no',
      width: 150,
      render: (text: string, record: HazardReport) => (
        <Link
          href={`/safety/hazard/${record.id}`}
          style={{ color: '#1677ff', fontWeight: 500 }}
        >
          {text}
        </Link>
      ),
    },
    {
      title: '等级',
      dataIndex: 'hazard_level',
      key: 'hazard_level',
      width: 80,
      render: (level: HazardLevel) => (
        <Tag color={getLevelColor(level)}>{getLevelLabel(level)}</Tag>
      ),
    },
    {
      title: '隐患类型',
      dataIndex: 'hazard_type',
      key: 'hazard_type',
      width: 120,
      render: (type: string) => {
        const option = HAZARD_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag>{option?.label || type}</Tag>
      },
    },
    {
      title: '隐患描述',
      dataIndex: 'description',
      key: 'description',
      width: 220,
      ellipsis: true,
    },
    {
      title: '责任部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
    },
    {
      title: '整改状态',
      dataIndex: 'rectification_status',
      key: 'rectification_status',
      width: 100,
      render: (status: string) => {
        const option = RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={option?.color}>{option?.label || status}</Tag>
      },
    },
    {
      title: '复核进度',
      key: 'verify_progress',
      width: 140,
      render: (_: unknown, record: HazardReport) => {
        const levels = [
          { status: record.verify_level_1_status || 'pending', label: '一' },
          { status: record.verify_level_2_status || 'pending', label: '二' },
          { status: record.verify_level_3_status || 'pending', label: '三' },
        ]
        return (
          <Space size={4}>
            {levels.map((lv) => {
              const opt = VERIFY_LEVEL_STATUS_OPTIONS.find((o) => o.value === lv.status)
              return (
                <Tag
                  key={lv.label}
                  color={opt?.color || 'default'}
                  style={{ fontSize: 11, padding: '0 4px', margin: 0 }}
                >
                  {lv.label}
                </Tag>
              )
            })}
          </Space>
        )
      },
    },
    {
      title: '整改期限',
      dataIndex: 'deadline',
      key: 'deadline',
      width: 110,
      render: (date: string) => {
        if (!date) return '-'
        const isOverdue = dayjs(date).isBefore(dayjs())
        return (
          <Text type={isOverdue ? 'danger' : undefined}>
            {dayjs(date).format('YYYY-MM-DD')}
          </Text>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
      align: 'center',
      render: (_, record) => renderAction(record),
    },
  ]

  return (
    <div className="p-6">
      {/* 标题 */}
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
          隐患台账
        </h1>
        <Text style={{ color: '#5d5b54' }}>隐患治理统计与追踪</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="AI待审核"
              value={stats.pendingReview}
              prefix={<AuditOutlined style={{ color: '#dd5b00' }} />}
              styles={{ content: { fontSize: 24, color: '#dd5b00' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="待整改"
              value={stats.pending}
              prefix={<WarningOutlined style={{ color: '#dd5b00' }} />}
              styles={{ content: { fontSize: 24, color: '#dd5b00' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="整改中"
              value={stats.inProgress}
              prefix={<ClockCircleOutlined style={{ color: '#0075de' }} />}
              styles={{ content: { fontSize: 24, color: '#0075de' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="待复核"
              value={stats.replied}
              prefix={<SafetyCertificateOutlined style={{ color: '#dd5b00' }} />}
              styles={{ content: { fontSize: 24, color: '#dd5b00' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="复核中"
              value={stats.verifying}
              prefix={<AuditOutlined style={{ color: '#0075de' }} />}
              styles={{ content: { fontSize: 24, color: '#0075de' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="已驳回"
              value={stats.rejected}
              prefix={<CloseCircleOutlined style={{ color: '#e03131' }} />}
              styles={{ content: { fontSize: 24, color: '#e03131' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="已关闭"
              value={stats.closed}
              prefix={<CheckCircleOutlined style={{ color: '#5645d4' }} />}
              styles={{ content: { fontSize: 24, color: '#5645d4' } }}
            />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small" style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
            <Statistic
              title="逾期"
              value={stats.overdue}
              prefix={<CloseOutlined style={{ color: '#e03131' }} />}
              styles={{ content: { fontSize: 24, color: '#e03131' } }}
            />
          </Card>
        </Col>
      </Row>

      {/* 筛选 */}
      <Card style={{ borderRadius: 12, border: '1px solid #e5e3df' }}>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={5}>
            <Input
              placeholder="搜索隐患编号/描述"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="隐患等级"
              allowClear
              value={levelFilter}
              onChange={(v) => { setLevelFilter(v); setHazardQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="隐患类型"
              allowClear
              value={typeFilter}
              onChange={(v) => { setTypeFilter(v); setHazardQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="整改状态"
              allowClear
              value={statusFilter}
              onChange={(v) => { setStatusFilter(v); setHazardQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={RECTIFICATION_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={3}>
            <Select
              placeholder="来源"
              allowClear
              value={sourceFilter}
              onChange={(v) => { setSourceFilter(v); setHazardQueryParams({ page: 1 }) }}
              style={{ width: '100%' }}
              options={[
                { value: 'ai', label: 'AI识别' },
                { value: 'manual', label: '人工录入' },
              ]}
            />
          </Col>
          <Col span={3}>
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
              查询
            </Button>
          </Col>
          {selectedRowKeys.length > 0 && (
            <Col span={3}>
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={deleting}
                onClick={handleBatchDelete}
              >
                删除 ({selectedRowKeys.length})
              </Button>
            </Col>
          )}
        </Row>

        <Table
          columns={columns}
          dataSource={hazards}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1500 }}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
          }}
          pagination={{
            current: hazardQueryParams.page,
            pageSize: hazardQueryParams.page_size,
            total: hazardTotal,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (page, pageSize) => {
              setHazardQueryParams({ page, page_size: pageSize })
            },
          }}
        />
      </Card>

      {/* AI 审核 Modal */}
      <Modal
        title={
          <Space>
            <AuditOutlined style={{ color: '#dd5b00' }} />
            <span>AI 识别结果审核</span>
            {reviewingRecord && <Tag>编号：{reviewingRecord.hazard_no}</Tag>}
          </Space>
        }
        open={reviewModalVisible}
        onCancel={() => setReviewModalVisible(false)}
        width={800}
        footer={
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button
              danger
              icon={<CloseCircleOutlined />}
              onClick={handleReviewReject}
              loading={reviewLoading}
            >
              驳回（重新执行AI）
            </Button>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={handleReviewApprove}
              loading={reviewLoading}
            >
              审核通过（进入整改流程）
            </Button>
          </Space>
        }
      >
        {reviewingRecord && (
          <div>
            <Alert
              type="warning"
              showIcon
              title="请仔细审核 AI 生成的隐患识别结果和整改建议，确认无误后点击审核通过"
              style={{ marginBottom: 16, borderRadius: 8 }}
            />

            {/* 基础信息摘要 */}
            <Descriptions column={3} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="隐患编号">{reviewingRecord.hazard_no}</Descriptions.Item>
              <Descriptions.Item label="责任部门">{reviewingRecord.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="地点/部位">{reviewingRecord.location || '-'}</Descriptions.Item>
              <Descriptions.Item label="发现人">{reviewingRecord.discovered_by_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="发现时间">
                {reviewingRecord.discovered_at
                  ? dayjs(reviewingRecord.discovered_at).format('YYYY-MM-DD HH:mm')
                  : '（默认为创建记录的日期）'}
              </Descriptions.Item>
              <Descriptions.Item label="整改期限">
                {reviewingRecord.deadline
                  ? dayjs(reviewingRecord.deadline).format('YYYY-MM-DD')
                  : '（默认为创建记录的日期加两个月）'}
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                <Tag icon={<RobotOutlined />} color="purple">AI识别</Tag>
              </Descriptions.Item>
            </Descriptions>

            <Title level={5} style={{ marginTop: 16, marginBottom: 12 }}>
              🤖 AI 隐患识别结果（Step 1）
            </Title>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="隐患等级">
                {reviewingRecord.hazard_level ? (
                  <Tag color={getLevelColor(reviewingRecord.hazard_level as HazardLevel)}>
                    {getLevelLabel(reviewingRecord.hazard_level as HazardLevel)}
                  </Tag>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="隐患类别">
                {reviewingRecord.hazard_category ? (
                  <Tag>{HAZARD_CATEGORY_LABEL_MAP[reviewingRecord.hazard_category] || reviewingRecord.hazard_category}</Tag>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="隐患描述">
                <div style={{ whiteSpace: 'pre-wrap' }}>{reviewingRecord.description || '-'}</div>
              </Descriptions.Item>
              <Descriptions.Item label="判定依据">
                <div style={{ whiteSpace: 'pre-wrap' }}>{reviewingRecord.major_hazard_basis || '-'}</div>
              </Descriptions.Item>
            </Descriptions>

            <Title level={5} style={{ marginTop: 16, marginBottom: 12 }}>
              📝 AI 整改建议（Step 2）
            </Title>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="纠正预防措施">
                <div style={{ whiteSpace: 'pre-wrap' }}>{reviewingRecord.corrective_preventive_measures || '-'}</div>
              </Descriptions.Item>
            </Descriptions>

            {reviewingRecord.ai_error_message && (
              <Alert
                type="error"
                showIcon
                title="AI 执行错误"
                description={reviewingRecord.ai_error_message}
                style={{ marginTop: 16, borderRadius: 8 }}
              />
            )}
          </div>
        )}
      </Modal>

      {/* 整改回复 Modal */}
      <HazardRectificationReplyModal
        open={replyModalVisible}
        record={replyRecord}
        mode={replyMode}
        onClose={() => setReplyModalVisible(false)}
        onSuccess={handleReplySuccess}
      />

      {/* 三级复核 Modal */}
      <HazardVerifyModal
        open={verifyModalVisible}
        record={verifyRecord}
        onClose={() => setVerifyModalVisible(false)}
        onSuccess={handleVerifySuccess}
      />
    </div>
  )
}

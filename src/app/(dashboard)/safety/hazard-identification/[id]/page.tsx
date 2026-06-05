'use client'

import { useEffect, useState } from 'react'
import { useRouter, useParams } from 'next/navigation'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Space,
  Typography,
  message,
  Spin,
  Divider,
  Steps,
  Result,
  Modal,
  Input,
  Row,
  Col,
  Statistic,
  Table,
  Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
  SafetyOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  RobotOutlined,
  EditOutlined,
} from '@ant-design/icons'
import {
  getHazardIdentification,
  runHazardScript,
  reviewHazardScript,
  updateHazardIdentification,
} from '@/actions/safety'
import type { HazardIdentification } from '@/types/safety'
import {
  AI_NODE_PROGRESS_OPTIONS,
  OVERALL_STATUS_OPTIONS_HI,
  REVIEW_STATUS_OPTIONS,
  RISK_LEVEL_OPTIONS,
  RECOMMENDATION_PRIORITY_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'

const { Title, Text } = Typography

const SCRIPT_CONFIG = [
  { num: 1, title: '附件解析', icon: <FileTextOutlined />,
    desc: 'AI提取基础作业信息：作业活动、设备设施、原辅料' },
  { num: 2, title: '危险源辨识', icon: <RobotOutlined />,
    desc: 'AI从人机料法环角度识别危险源、事故类型' },
  { num: 3, title: '固有风险评价', icon: <ExperimentOutlined />,
    desc: 'AI进行LEC固有风险评价' },
  { num: 4, title: '现有控制措施', icon: <SafetyOutlined />,
    desc: 'AI识别现有工程/管理/PPE/应急措施' },
  { num: 5, title: '残余风险评价', icon: <ExperimentOutlined />,
    desc: 'AI对现有措施后的残余风险进行LEC评价' },
  { num: 6, title: '建议措施', icon: <ThunderboltOutlined />,
    desc: 'AI提出针对性改进建议措施' },
  { num: 7, title: '措施后风险评价', icon: <SafetyOutlined />,
    desc: 'AI评价建议措施实施后的风险水平' },
]

export default function HazardIdentificationDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string

  const [record, setRecord] = useState<HazardIdentification | null>(null)
  const [loading, setLoading] = useState(true)
  const [runningScript, setRunningScript] = useState<number | null>(null)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingScript, setEditingScript] = useState<number>(0)
  const [editForm, setEditForm] = useState<Record<string, any>>({})

  const loadRecord = async () => {
    try {
      const response = await getHazardIdentification(id)
      if (response.code === 200) {
        setRecord(response.data)
      } else {
        message.error('加载失败')
        router.push('/safety/hazard-identification')
      }
    } catch {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (id) loadRecord()
  }, [id])

  // ── 执行AI脚本 ──
  const handleRunScript = async (scriptNum: number) => {
    setRunningScript(scriptNum)
    try {
      const response = await runHazardScript(id, scriptNum)
      if (response.code === 200) {
        if (response.data.ai_error_message) {
          message.warning(`脚本${scriptNum}执行异常：${response.data.ai_error_message}`)
        } else {
          message.success(`脚本${scriptNum}「${SCRIPT_CONFIG[scriptNum - 1].title}」执行完成`)
        }
        setRecord(response.data)
      } else {
        message.error(response.message || '脚本执行失败')
      }
    } catch {
      message.error('脚本执行失败')
    } finally {
      setRunningScript(null)
    }
  }

  // ── 审核脚本 ──
  const handleReview = async (scriptNum: number, action: 'approved' | 'rejected') => {
    try {
      const response = await reviewHazardScript(id, scriptNum, action)
      if (response.code === 200) {
        message.success(action === 'approved' ? '审核通过' : '已驳回')
        setRecord(response.data)
      } else {
        message.error(response.message || '审核操作失败')
      }
    } catch {
      message.error('审核操作失败')
    }
  }

  // ── 编辑确认脚本字段 ──
  const handleEditConfirm = async () => {
    try {
      const response = await updateHazardIdentification(id, editForm)
      if (response.code === 200) {
        message.success('更新成功')
        setRecord(response.data)
        setEditModalVisible(false)
      } else {
        message.error(response.message || '更新失败')
      }
    } catch {
      message.error('更新失败')
    }
  }

  const openEditModal = (scriptNum: number, fields: Record<string, any>) => {
    setEditingScript(scriptNum)
    setEditForm(fields)
    setEditModalVisible(true)
  }

  const getProgressStep = (nodeProgress: string) => {
    if (nodeProgress === 'completed') return AI_NODE_PROGRESS_OPTIONS.length - 1
    const idx = AI_NODE_PROGRESS_OPTIONS.findIndex((o) => o.value === nodeProgress)
    return Math.max(0, idx - 1)
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <Spin size="large" />
      </div>
    )
  }

  if (!record) return null

  const currentStep = getProgressStep(record.ai_node_progress)

  // ── 渲染脚本卡片 ──
  const renderScriptCard = (config: typeof SCRIPT_CONFIG[0]) => {
    const { num, title, icon, desc } = config
    const reviewStatus = (record as any)[`script${num}_review_status`] as string
    const isCurrent =
      record.ai_node_progress === `pending_script${num}`
    const isPast = num <= currentStep
    const isCompleted = record.ai_node_progress === 'completed' && num === 7
    const canRun = isCurrent || reviewStatus === 'rejected'

    // 获取该脚本的输出字段
    const outputFields = getScriptOutputFields(num, record)
    const hasOutput = Object.values(outputFields).some((v) => v !== null && v !== undefined && v !== '')

    return (
      <Card
        key={num}
        size="small"
        title={
          <Space>
            {icon}
            <span>脚本{num}：{title}</span>
            {isCurrent && <Tag color="processing">当前节点</Tag>}
          </Space>
        }
        extra={
          <Space>
            {canRun && (
              <Button
                type="primary"
                size="small"
                icon={<ThunderboltOutlined />}
                loading={runningScript === num}
                onClick={() => handleRunScript(num)}
              >
                执行AI脚本
              </Button>
            )}
            {hasOutput && (
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => openEditModal(num, outputFields)}
              >
                编辑
              </Button>
            )}
            {isPast && reviewStatus === 'pending' && hasOutput && (
              <>
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  onClick={() => handleReview(num, 'approved')}
                >
                  审核通过
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<CloseCircleOutlined />}
                  onClick={() => handleReview(num, 'rejected')}
                >
                  驳回
                </Button>
              </>
            )}
            {reviewStatus === 'approved' && (
              <Tag color="success" icon={<CheckCircleOutlined />}>已审核</Tag>
            )}
            {reviewStatus === 'rejected' && (
              <Tag color="error" icon={<CloseCircleOutlined />}>已驳回</Tag>
            )}
          </Space>
        }
        className="mb-3"
      >
        <Text type="secondary" className="block mb-2">{desc}</Text>
        {reviewStatus === 'rejected' && record.ai_error_message && (
          <div className="mb-2 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-600">
            ⚠️ {record.ai_error_message}
          </div>
        )}
        {hasOutput ? (
          <Descriptions size="small" column={1} bordered>
            {Object.entries(outputFields).filter(([_, v]) => v !== null && v !== undefined && v !== '').map(
              ([key, val]) => (
                <Descriptions.Item key={key} label={getFieldLabel(num, key)}>
                  {renderFieldValue(num, key, val)}
                </Descriptions.Item>
              )
            )}
          </Descriptions>
        ) : (
          <Text type="secondary" italic>
            {isCurrent || reviewStatus === 'rejected'
              ? '点击「执行AI脚本」按钮运行'
              : num <= currentStep || isCompleted
                ? '等待前序脚本审核通过后自动执行'
                : '等待前序脚本完成'}
          </Text>
        )}
      </Card>
    )
  }

  // ── 渲染风险等级卡片 ──
  const renderRiskCard = (label: string, levelKey?: string, levelLabel?: string, dValue?: number) => {
    if (!levelKey) return null
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === levelKey)
    return (
      <Col span={8}>
        <Card size="small" className="text-center">
          <Statistic
            title={label}
            value={dValue ?? '-'}
            suffix={dValue ? 'D值' : ''}
            styles={{ content: { color: opt?.color || '#000' } }}
          />
          <Tag color={opt?.color} className="mt-2">{levelLabel || levelKey}</Tag>
        </Card>
      </Col>
    )
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Space className="mb-4">
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push('/safety/hazard-identification')}
        >
          返回列表
        </Button>
      </Space>

      {/* ── 基础信息 ── */}
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>基础信息</span>
          </Space>
        }
        extra={
          <Space>
            {getStatusTag(record.overall_status)}
            {getProgressTag(record.ai_node_progress)}
          </Space>
        }
        className="mb-4"
      >
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="危险源编号">{record.hazard_id_no}</Descriptions.Item>
          <Descriptions.Item label="部门">{record.department}</Descriptions.Item>
          <Descriptions.Item label="岗位">{record.position}</Descriptions.Item>
          <Descriptions.Item label="生产步骤" span={3}>
            {record.production_step}
          </Descriptions.Item>
          {record.attachment_original_name && (
            <Descriptions.Item label="附件" span={3}>
              {record.attachment_original_name}
            </Descriptions.Item>
          )}
          <Descriptions.Item label="创建时间">
            {dayjs(record.created_at).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {dayjs(record.updated_at).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
          {record.notes && (
            <Descriptions.Item label="备注" span={3}>
              {record.notes}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      {/* ── 流程概览步骤 ── */}
      <Card title="AI辨识流程" className="mb-4">
        <Steps
          current={currentStep}
          status={record.overall_status === 'completed' ? 'finish' : 'process'}
          items={AI_NODE_PROGRESS_OPTIONS.filter((o) => o.value !== 'pending_input').map(
            (o) => ({
              title: o.label.replace('待AI', '').replace('待', ''),
              status: record.ai_node_progress === 'completed'
                ? 'finish'
                : AI_NODE_PROGRESS_OPTIONS.findIndex((p) => p.value === record.ai_node_progress) >=
                    AI_NODE_PROGRESS_OPTIONS.findIndex((p) => p.value === o.value)
                  ? 'finish'
                  : 'wait',
            })
          )}
        />
      </Card>

      {/* ── 脚本1-7 ── */}
      <Title level={5} className="mb-3">脚本执行区</Title>
      {SCRIPT_CONFIG.map(renderScriptCard)}

      {/* ── 风险等级汇总 ── */}
      {record.inherent_risk_level && (
        <>
          <Divider />
          <Title level={5} className="mb-3">风险等级汇总</Title>
          <Row gutter={16}>
            {renderRiskCard('固有风险', record.inherent_risk_level, record.inherent_risk_label, record.d_inherent)}
            {renderRiskCard('残余风险', record.residual_risk_level, record.residual_risk_label, record.d_residual)}
            {renderRiskCard('建议措施后风险', record.post_risk_level, record.post_risk_label, record.d_post)}
          </Row>

          {record.control_level && (
            <Card size="small" className="mt-3">
              <Space>
                <SafetyOutlined style={{ color: '#5645d4' }} />
                <Text strong>管控层级：{record.control_level}</Text>
                <Text type="secondary">责任人：{record.responsible_person}</Text>
              </Space>
            </Card>
          )}
        </>
      )}

      {/* ── 编辑Modal ── */}
      <Modal
        title={`编辑脚本${editingScript}字段`}
        open={editModalVisible}
        onOk={handleEditConfirm}
        onCancel={() => setEditModalVisible(false)}
        okText="确认"
        cancelText="取消"
        width={600}
      >
        {Object.entries(editForm).map(([key, val]) => (
          <div key={key} className="mb-3">
            <Text strong className="block mb-1">{getFieldLabel(editingScript, key)}</Text>
            <Input.TextArea
              rows={2}
              value={val as string}
              onChange={(e) => setEditForm((prev) => ({ ...prev, [key]: e.target.value }))}
            />
          </div>
        ))}
      </Modal>
    </div>
  )
}

// ==================== Helper Functions ====================

function getProgressTag(value: string) {
  const opt = AI_NODE_PROGRESS_OPTIONS.find((o) => o.value === value)
  return <Tag color={opt?.color}>{opt?.label || value}</Tag>
}

function getStatusTag(value: string) {
  const opt = OVERALL_STATUS_OPTIONS_HI.find((o) => o.value === value)
  return <Tag color={opt?.color}>{opt?.label || value}</Tag>
}

function getReviewTag(value: string) {
  const opt = REVIEW_STATUS_OPTIONS.find((o) => o.value === value)
  if (!opt) return null
  return <Tag color={opt.color}>{opt.label}</Tag>
}

function getFieldLabel(scriptNum: number, field: string): string {
  const labels: Record<string, Record<string, string>> = {
    1: {
      specific_activity: '具体作业活动',
      equipment_facilities: '设备设施',
      raw_auxiliary_materials: '原辅料',
      operation_frequency: '作业频次',
      operator_count: '操作人数',
    },
    2: {
      hazard_type: '危险类型',
      possible_accident: '可能导致事故',
      unsafe_behavior: '不规范作业行为表现',
    },
    3: {
      l_inherent: '可能性L（固有）',
      e_inherent: '暴露频率E（固有）',
      c_inherent: '严重性C（固有）',
      d_inherent: '风险值D（固有）',
      inherent_risk_level: '固有风险等级',
      inherent_risk_label: '固有风险等级名称',
    },
    4: {
      existing_engineering_controls: '现有工程控制措施',
      existing_management_controls: '现有管理控制措施',
      existing_ppe: '现有个人防护措施',
      existing_emergency_measures: '现有应急措施',
    },
    5: {
      l_residual: '可能性L（残余）',
      e_residual: '暴露频率E（残余）',
      c_residual: '严重性C（残余）',
      d_residual: '风险值D（残余）',
      residual_risk_level: '残余风险等级',
      residual_risk_label: '残余风险等级名称',
    },
    6: {
      needs_recommendation: '是否需提出建议措施',
      recommendation_type: '建议措施类型',
      recommendation_content: '建议措施内容',
      recommendation_priority: '建议措施优先级',
    },
    7: {
      l_post: '可能性L（措施后）',
      e_post: '暴露频率E（措施后）',
      c_post: '严重性C（措施后）',
      d_post: '风险值D（措施后）',
      post_risk_level: '措施后风险等级',
      post_risk_label: '措施后风险等级名称',
    },
  }
  return labels[scriptNum]?.[field] || field
}

function renderFieldValue(scriptNum: number, key: string, val: any) {
  if (scriptNum === 3 && key === 'inherent_risk_level') {
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || val}</Tag>
  }
  if (scriptNum === 5 && key === 'residual_risk_level') {
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || val}</Tag>
  }
  if (scriptNum === 7 && key === 'post_risk_level') {
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || val}</Tag>
  }
  if (scriptNum === 6 && key === 'recommendation_priority') {
    const opt = RECOMMENDATION_PRIORITY_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || val}</Tag>
  }
  return String(val ?? '-')
}

function getScriptOutputFields(scriptNum: number, record: HazardIdentification): Record<string, any> {
  const fieldMaps: Record<number, string[]> = {
    1: ['specific_activity', 'equipment_facilities', 'raw_auxiliary_materials', 'operation_frequency', 'operator_count'],
    2: ['hazard_type', 'possible_accident', 'unsafe_behavior'],
    3: ['l_inherent', 'e_inherent', 'c_inherent', 'd_inherent', 'inherent_risk_level', 'inherent_risk_label'],
    4: ['existing_engineering_controls', 'existing_management_controls', 'existing_ppe', 'existing_emergency_measures'],
    5: ['l_residual', 'e_residual', 'c_residual', 'd_residual', 'residual_risk_level', 'residual_risk_label'],
    6: ['needs_recommendation', 'recommendation_type', 'recommendation_content', 'recommendation_priority'],
    7: ['l_post', 'e_post', 'c_post', 'd_post', 'post_risk_level', 'post_risk_label'],
  }

  const fields = fieldMaps[scriptNum] || []
  const result: Record<string, any> = {}
  for (const f of fields) {
    result[f] = (record as any)[f]
  }
  return result
}

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
  App,
  Spin,
  Divider,
  Steps,
  Modal,
  Input,
  Row,
  Col,
  Statistic,
  Collapse,
  Tooltip,
  Badge,
  Progress,
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
  ExclamationCircleOutlined,
  LineChartOutlined,
  LockOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
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
import { getWorkflowStepList } from '@/lib/workflow-templates'

const { Title, Text, Paragraph } = Typography

// ── 本地样式辅助函数（与隐患台账对齐）──
const statusPill = (color: string, bg: string): React.CSSProperties => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: '2px 10px',
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  lineHeight: '20px',
  color,
  background: bg,
})

const actionLink = (color: string): React.CSSProperties => ({
  color,
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  background: 'transparent',
  border: 'none',
  padding: 0,
  lineHeight: '22px',
})

// ── 状态颜色配置 ──
const STATUS_COLOR_CONFIG: Record<string, { color: string; bg: string }> = {
  draft:        { color: '#5d5b54', bg: '#f0eeec' },
  in_progress:  { color: '#0075de', bg: '#dcecfa' },
  completed:    { color: '#1aae39', bg: '#d9f3e1' },
  cancelled:    { color: '#e03131', bg: '#fde0ec' },
}

// ── 步骤图标映射 ──
const STEP_ICONS: Record<number, React.ReactNode> = {
  1: <FileTextOutlined />,
  2: <RobotOutlined />,
  3: <ExperimentOutlined />,
  4: <SafetyOutlined />,
  5: <ExperimentOutlined />,
  6: <ThunderboltOutlined />,
  7: <SafetyOutlined />,
}

// ── 风险等级颜色映射 ──
const RISK_COLORS: Record<string, { bg: string; border: string; text: string; bar: string }> = {
  level_1: { bg: '#fff2f0', border: '#ff4d4f', text: '#cf1322', bar: '#ff4d4f' },
  level_2: { bg: '#fff7e6', border: '#fa8c16', text: '#d46b08', bar: '#fa8c16' },
  level_3: { bg: '#fffbe6', border: '#fadb14', text: '#d4b106', bar: '#1677ff' },
  level_4: { bg: '#f6ffed', border: '#52c41a', text: '#389e0d', bar: '#52c41a' },
}

// ── 工作流步骤配置 ──
const WORKFLOW_STEPS = getWorkflowStepList('hazard-identification').map((s) => ({
  ...s,
  icon: STEP_ICONS[s.num] || <RobotOutlined />,
}))

export default function HazardIdentificationDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string

  const [record, setRecord] = useState<HazardIdentification | null>(null)
  const [loading, setLoading] = useState(true)
  const [runningScript, setRunningScript] = useState<number | null>(null)
  const [selectedStep, setSelectedStep] = useState(1)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingScript, setEditingScript] = useState<number>(0)
  const [editForm, setEditForm] = useState<Record<string, unknown>>({})
  const { message } = App.useApp()

  const loadRecord = async () => {
    try {
      const response = await getHazardIdentification(id)
      if (response.code === 200) {
        setRecord(response.data as HazardIdentification)
        const data = response.data as HazardIdentification
        const cur = getCurrentStepNum(data.ai_node_progress)
        setSelectedStep(cur)
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

  const getCurrentStepNum = (progress: string): number => {
    if (progress === 'completed') return 7
    const match = progress.match(/script(\d)/)
    return match ? parseInt(match[1]) : 1
  }

  const getScriptReviewStatus = (scriptNum: number): string => {
    return ((record as unknown as Record<string, unknown>)?.[`script${scriptNum}_review_status`] as string) || 'pending'
  }

  // ── 每个步骤的状态 ──
  const getStepState = (scriptNum: number) => {
    if (!record) return 'wait'
    const currentNum = getCurrentStepNum(record.ai_node_progress)
    const rs = getScriptReviewStatus(scriptNum)

    if (record.overall_status === 'completed') return 'finish'
    if (rs === 'rejected') return 'error'
    if (rs === 'approved') return 'finish'
    if (scriptNum < currentNum) return 'finish'
    if (scriptNum === currentNum) return 'process'
    return 'wait'
  }

  const handleRunScript = async (scriptNum: number) => {
    setRunningScript(scriptNum)
    try {
      const response = await runHazardScript(id, scriptNum)
      if (response.code === 200) {
        const data = response.data as HazardIdentification
        if (data.ai_error_message) {
          message.warning(`步骤${scriptNum}执行异常：${data.ai_error_message}`)
        } else {
          message.success(`步骤${scriptNum}「${WORKFLOW_STEPS[scriptNum - 1].title}」执行完成`)
        }
        setRecord(data)
        const nextStep = getCurrentStepNum(data.ai_node_progress)
        setSelectedStep(nextStep)
      } else {
        message.error(response.message || '执行失败')
      }
    } catch {
      message.error('执行失败')
    } finally {
      setRunningScript(null)
    }
  }

  const handleReview = async (scriptNum: number, action: 'approved' | 'rejected') => {
    try {
      const response = await reviewHazardScript(id, scriptNum, action)
      if (response.code === 200) {
        message.success(action === 'approved' ? '审核通过，已推进至下一步' : '已驳回，请重新执行AI')
        setRecord(response.data as HazardIdentification)
      } else {
        message.error(response.message || '审核操作失败')
      }
    } catch {
      message.error('审核操作失败')
    }
  }

  const handleEditConfirm = async () => {
    try {
      const response = await updateHazardIdentification(id, editForm as Record<string, unknown>)
      if (response.code === 200) {
        message.success('更新成功')
        setRecord(response.data as HazardIdentification)
        setEditModalVisible(false)
      } else {
        message.error(response.message || '更新失败')
      }
    } catch {
      message.error('更新失败')
    }
  }

  const openEditModal = (scriptNum: number, fields: Record<string, unknown>) => {
    setEditingScript(scriptNum)
    setEditForm(fields)
    setEditModalVisible(true)
  }

  // ── 加载态 ──
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!record) return null

  const currentStepNum = getCurrentStepNum(record.ai_node_progress)
  const currentStep = WORKFLOW_STEPS[selectedStep - 1]
  const currentOutputFields = getScriptOutputFields(selectedStep, record, WORKFLOW_STEPS)
  const hasOutput = Object.values(currentOutputFields).some(
    (v) => v !== null && v !== undefined && v !== ''
  )
  const reviewStatus = getScriptReviewStatus(selectedStep)
  const stepState = getStepState(selectedStep)
  const canRun = stepState === 'process' || reviewStatus === 'rejected'
  const canReview = hasOutput && reviewStatus === 'pending' && stepState === 'finish'
  const isLocked = stepState === 'wait'

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      {/* ── 顶部导航 ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push('/safety/hazard-identification')}
          />
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a', margin: 0, lineHeight: 1.3 }}>
              危险源辨识详情
            </h2>
            <Text style={{ color: '#787671', fontSize: 13 }}>
              {record.hazard_id_no} · {record.department} · {record.position}
            </Text>
          </div>
        </div>
        <Space size={8}>
          {record.overall_status && (
            <span style={statusPill(
              STATUS_COLOR_CONFIG[record.overall_status]?.color || '#5d5b54',
              STATUS_COLOR_CONFIG[record.overall_status]?.bg || '#f0eeec',
            )}>
              {OVERALL_STATUS_OPTIONS_HI.find((o) => o.value === record.overall_status)?.label || record.overall_status}
            </span>
          )}
          {record.ai_node_progress && (
            <span style={statusPill(
              record.ai_node_progress === 'completed' ? '#1aae39' : '#0075de',
              record.ai_node_progress === 'completed' ? '#d9f3e1' : '#dcecfa',
            )}>
              {AI_NODE_PROGRESS_OPTIONS.find((o) => o.value === record.ai_node_progress)?.label || record.ai_node_progress}
            </span>
          )}
        </Space>
      </div>

      {/* ── 基础信息 + 工作流进度 ── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {/* 基础信息卡片 */}
        <Col span={8}>
          <Card
            size="small"
            title={<Space><FileTextOutlined style={{ color: '#5645d4' }} /><span>基础信息</span></Space>}
            style={{ borderRadius: 12, border: '1px solid #e5e3df', height: '100%' }}
          >
            <Descriptions size="small" column={1} colon={false}>
              <Descriptions.Item label="编号">
                <Text strong style={{ color: '#0075de' }}>{record.hazard_id_no}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="部门">{record.department}</Descriptions.Item>
              <Descriptions.Item label="岗位">{record.position}</Descriptions.Item>
              <Descriptions.Item label="生产步骤">{record.production_step}</Descriptions.Item>
              {record.attachment_original_name && (
                <Descriptions.Item label="附件">
                  <Tag icon={<FileTextOutlined />}>{record.attachment_original_name}</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="创建时间">
                {dayjs(record.created_at).format('YYYY-MM-DD HH:mm')}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {/* 工作流进度 Steps */}
        <Col span={16}>
          <Card
            size="small"
            title={<Space><LineChartOutlined style={{ color: '#5645d4' }} /><span>AI 工作流进度</span></Space>}
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
          >
            <Steps
              current={currentStepNum - 1}
              status={record.overall_status === 'completed' ? 'finish' : 'process'}
              size="small"
              onChange={(step) => {
                const targetStep = step + 1
                if (targetStep <= currentStepNum) setSelectedStep(targetStep)
              }}
              style={{ cursor: 'pointer' }}
              items={WORKFLOW_STEPS.map((s) => {
                const rs = getScriptReviewStatus(s.num)
                const st = getStepState(s.num)
                return {
                  title: s.title,
                  status: st === 'error' ? 'error' : st === 'process' ? 'process' : st === 'finish' ? 'finish' : 'wait',
                  icon: rs === 'rejected' ? <CloseCircleOutlined style={{ color: '#ff4d4f' }} /> : undefined,
                  description: (
                    <Text style={{ fontSize: 11, color: '#787671' }}>
                      {st === 'process' && '⏳ 待执行'}
                      {st === 'wait' && <LockOutlined />}
                      {rs === 'approved' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
                      {rs === 'rejected' && <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
                    </Text>
                  ),
                }
              })}
            />
          </Card>
        </Col>
      </Row>

      {/* ── 左右分栏：步骤导航 + 输出区 ── */}
      <Row gutter={16}>
        {/* 左侧：步骤导航 */}
        <Col span={8}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            styles={{ body: { padding: 12 } }}
          >
            {WORKFLOW_STEPS.map((step) => {
              const st = getStepState(step.num)
              const rs = getScriptReviewStatus(step.num)
              const isSelected = selectedStep === step.num

              return (
                <div
                  key={step.num}
                  onClick={() => {
                    if (step.num <= currentStepNum) setSelectedStep(step.num)
                  }}
                  style={{
                    cursor: step.num <= currentStepNum ? 'pointer' : 'not-allowed',
                    padding: '10px 12px',
                    borderRadius: 8,
                    marginBottom: 6,
                    background: isSelected ? '#f0edff' : st === 'wait' ? '#fafaf9' : 'transparent',
                    border: isSelected
                      ? '1px solid #5645d4'
                      : st === 'process'
                        ? '1px solid #1677ff'
                        : '1px solid transparent',
                    transition: 'all 0.2s',
                    opacity: st === 'wait' ? 0.6 : 1,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Space size={8}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 24, height: 24, borderRadius: '50%',
                        background: isSelected ? '#5645d4' : st === 'finish' ? '#52c41a' : st === 'process' ? '#1677ff' : '#e5e3df',
                        color: isSelected || st === 'finish' || st === 'process' ? '#fff' : '#787671',
                        fontSize: 12, fontWeight: 600,
                      }}>
                        {st === 'finish' ? '✓' : st === 'error' ? '!' : step.num}
                      </span>
                      <div>
                        <Text
                          style={{
                            fontSize: 13,
                            fontWeight: isSelected ? 600 : 400,
                            color: isSelected ? '#5645d4' : '#37352f',
                          }}
                        >
                          {step.num}. {step.title}
                        </Text>
                      </div>
                    </Space>
                    <Space size={4}>
                      {rs === 'approved' && <span style={statusPill('#1aae39', '#d9f3e1')}>已审核</span>}
                      {rs === 'rejected' && <span style={statusPill('#e03131', '#fde0ec')}>已驳回</span>}
                      {st === 'process' && rs === 'pending' && <span style={statusPill('#0075de', '#dcecfa')}>当前</span>}
                    </Space>
                  </div>
                  <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4, marginLeft: 32 }}>
                    {step.desc}
                  </Text>
                </div>
              )
            })}
          </Card>
        </Col>

        {/* 右侧：输出结果 */}
        <Col span={16}>
          <Card
            size="small"
            style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
            title={
              <Space>
                {currentStep.icon}
                <span>步骤 {selectedStep}：{currentStep.title}</span>
                {isLocked && <LockOutlined style={{ color: '#a4a097' }} />}
              </Space>
            }
            extra={
              <Space>
                {/* AI 运行按钮 */}
                {canRun && (
                  <Button
                    type="primary"
                    size="small"
                    icon={runningScript === selectedStep ? <LoadingOutlined /> : <ThunderboltOutlined />}
                    loading={runningScript === selectedStep}
                    onClick={() => handleRunScript(selectedStep)}
                  >
                    执行 AI
                  </Button>
                )}

                {/* 编辑按钮 */}
                {hasOutput && (
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openEditModal(selectedStep, currentOutputFields)}
                  >
                    编辑
                  </Button>
                )}

                {/* 审核按钮 */}
                {canReview && (
                  <>
                    <Button
                      size="small"
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={() => handleReview(selectedStep, 'approved')}
                    >
                      审核通过
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<CloseCircleOutlined />}
                      onClick={() => handleReview(selectedStep, 'rejected')}
                    >
                      驳回
                    </Button>
                  </>
                )}

                {/* 已审核/已驳回状态标签 */}
                {reviewStatus === 'approved' && (
                  <span style={statusPill('#1aae39', '#d9f3e1')}>
                    <CheckCircleOutlined /> 已审核
                  </span>
                )}
                {reviewStatus === 'rejected' && (
                  <span style={statusPill('#e03131', '#fde0ec')}>
                    <CloseCircleOutlined /> 已驳回
                  </span>
                )}
              </Space>
            }
          >
            {/* 错误提示 */}
            {reviewStatus === 'rejected' && record.ai_error_message && (
              <div style={{
                marginBottom: 12, padding: '10px 14px', background: '#fff2f0',
                border: '1px solid #ffccc7', borderRadius: 8, fontSize: 13, color: '#e03131',
              }}>
                <ExclamationCircleOutlined style={{ marginRight: 6 }} />
                {record.ai_error_message}
              </div>
            )}

            {/* 锁定提示 */}
            {isLocked && !hasOutput && (
              <div style={{
                textAlign: 'center', padding: '40px 0', color: '#787671',
              }}>
                <LockOutlined style={{ fontSize: 32, marginBottom: 12, color: '#bbb8b1' }} />
                <p style={{ fontSize: 14 }}>
                  {selectedStep <= currentStepNum
                    ? '等待前序步骤审核通过'
                    : '请先完成前面步骤'}
                </p>
              </div>
            )}

            {/* 无输出提示 */}
            {!isLocked && !hasOutput && (
              <div style={{
                textAlign: 'center', padding: '40px 0', color: '#787671',
              }}>
                <ThunderboltOutlined style={{ fontSize: 32, marginBottom: 12, color: '#5645d4' }} />
                <p style={{ fontSize: 14, color: '#37352f', marginBottom: 4 }}>
                  点击「执行 AI」按钮启动分析
                </p>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  AI 将根据已确认的前置数据自动分析
                </Text>
              </div>
            )}

            {/* 输出字段 */}
            {hasOutput && (
              <Descriptions size="small" column={1} bordered>
                {Object.entries(currentOutputFields)
                  .filter(([, v]) => v !== null && v !== undefined && v !== '')
                  .map(([key, val]) => (
                    <Descriptions.Item key={key} label={getFieldLabel(selectedStep, key)}>
                      {renderFieldValue(selectedStep, key, val)}
                    </Descriptions.Item>
                  ))}
              </Descriptions>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── LEC 三阶段风险对比（脚本3+5+7完成后显示）── */}
      {(record.inherent_risk_level || record.residual_risk_level || record.post_risk_level) && (
        <>
          <Divider style={{ margin: '20px 0 16px' }} />
          <Title level={5} style={{ marginBottom: 16, color: '#1a1a1a' }}>
            <LineChartOutlined style={{ marginRight: 8 }} />
            LEC 三阶段风险对比
          </Title>
          <Row gutter={16}>
            {renderLecCard(
              '固有风险',
              '未考虑任何控制措施前',
              record.l_inherent, record.e_inherent, record.c_inherent,
              record.d_inherent, record.inherent_risk_level, record.inherent_risk_label,
            )}
            <Col span={1} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Text style={{ fontSize: 24, color: '#a4a097' }}>→</Text>
            </Col>
            {renderLecCard(
              '残余风险',
              '现有控制措施生效后',
              record.l_residual, record.e_residual, record.c_residual,
              record.d_residual, record.residual_risk_level, record.residual_risk_label,
            )}
            <Col span={1} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Text style={{ fontSize: 24, color: '#a4a097' }}>→</Text>
            </Col>
            {renderLecCard(
              '措施后风险',
              '建议措施实施后（最终）',
              record.l_post, record.e_post, record.c_post,
              record.d_post, record.post_risk_level, record.post_risk_label,
            )}
          </Row>

          {/* 管控信息 */}
          {record.control_level && (
            <Card
              size="small"
              style={{ marginTop: 16, borderRadius: 12, border: '1px solid #e5e3df' }}
            >
              <Row gutter={24}>
                <Col span={8}>
                  <Statistic
                    title="管控层级"
                    value={record.control_level}
                    prefix={<SafetyOutlined style={{ color: '#5645d4' }} />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="管控责任人"
                    value={record.responsible_person || '-'}
                    prefix={<InfoCircleOutlined style={{ color: '#1677ff' }} />}
                  />
                </Col>
                <Col span={8}>
                  {record.recommendation_priority && (
                    <Statistic
                      title="建议措施优先级"
                      valueRender={() => {
                        const opt = RECOMMENDATION_PRIORITY_OPTIONS.find(
                          (o) => o.value === record.recommendation_priority
                        )
                        return <Tag color={opt?.color}>{opt?.label || record.recommendation_priority}</Tag>
                      }}
                    />
                  )}
                </Col>
              </Row>
            </Card>
          )}
        </>
      )}

      {/* ── 编辑 Modal ── */}
      <Modal
        title={`编辑步骤 ${editingScript}：${WORKFLOW_STEPS[editingScript - 1]?.title || ''}`}
        open={editModalVisible}
        onOk={handleEditConfirm}
        onCancel={() => setEditModalVisible(false)}
        okText="确认"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        {Object.entries(editForm).map(([key, val]) => (
          <div key={key} style={{ marginBottom: 14 }}>
            <Text strong style={{ display: 'block', marginBottom: 6, fontSize: 13 }}>
              {getFieldLabel(editingScript, key)}
            </Text>
            <Input.TextArea
              rows={3}
              value={val as string}
              onChange={(e) => setEditForm((prev) => ({ ...prev, [key]: e.target.value }))}
            />
          </div>
        ))}
      </Modal>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════

function getFieldLabel(scriptNum: number, field: string): string {
  const labels: Record<string, Record<string, string>> = {
    1: {
      specific_activity: '具体作业活动',
      equipment_facilities: '设备设施',
      raw_auxiliary_materials: '原辅料',
    },
    2: {
      hazard_type: '危险类型（GB 6441）',
      possible_accident: '可能导致的事故',
      unsafe_behavior: '不规范作业行为表现',
    },
    3: {
      l_inherent: '可能性 L（固有）', e_inherent: '暴露频率 E（固有）',
      c_inherent: '严重性 C（固有）', d_inherent: '风险值 D（固有）',
      inherent_risk_level: '固有风险等级', inherent_risk_label: '等级名称',
    },
    4: {
      existing_engineering_controls: '现有工程控制措施',
      existing_management_controls: '现有管理控制措施',
      existing_ppe: '现有个人防护措施',
      existing_emergency_measures: '现有应急措施',
    },
    5: {
      l_residual: '可能性 L（残余）', e_residual: '暴露频率 E（残余）',
      c_residual: '严重性 C（残余）', d_residual: '风险值 D（残余）',
      residual_risk_level: '残余风险等级', residual_risk_label: '等级名称',
    },
    6: {
      needs_recommendation: '是否需提出建议措施',
      recommendation_type: '建议措施类型',
      recommendation_content: '建议措施内容',
      recommendation_priority: '建议措施优先级',
    },
    7: {
      l_post: '可能性 L（措施后）', e_post: '暴露频率 E（措施后）',
      c_post: '严重性 C（措施后）', d_post: '风险值 D（措施后）',
      post_risk_level: '措施后风险等级', post_risk_label: '等级名称',
    },
  }
  return labels[scriptNum]?.[field] || field
}

function renderFieldValue(scriptNum: number, key: string, val: unknown) {
  // 风险等级 → 彩色标签
  if (['inherent_risk_level', 'residual_risk_level', 'post_risk_level'].includes(key)) {
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || String(val)}</Tag>
  }
  // 建议优先级 → 彩色标签
  if (key === 'recommendation_priority') {
    const opt = RECOMMENDATION_PRIORITY_OPTIONS.find((o) => o.value === val)
    return <Tag color={opt?.color}>{opt?.label || String(val)}</Tag>
  }
  // D 值 → 格式化数字
  if (['d_inherent', 'd_residual', 'd_post'].includes(key) && typeof val === 'number') {
    return <Text strong style={{ fontFamily: 'monospace', fontSize: 15 }}>{val}</Text>
  }
  return String(val ?? '-')
}

function getScriptOutputFields(
  scriptNum: number,
  record: HazardIdentification,
  steps: typeof WORKFLOW_STEPS,
): Record<string, unknown> {
  const step = steps.find((s) => s.num === scriptNum)
  const fields = step?.expected_keys || []
  const result: Record<string, unknown> = {}
  for (const f of fields) {
    result[f] = (record as unknown as Record<string, unknown>)[f]
  }
  return result
}

// ── LEC 三阶段卡片 ──
function renderLecCard(
  title: string,
  subtitle: string,
  l?: number, e?: number, c?: number,
  d?: number, levelKey?: string, levelLabel?: string,
) {
  if (!levelKey && d === undefined && l === undefined) return null

  const colors = levelKey ? RISK_COLORS[levelKey] : undefined
  const opt = levelKey ? RISK_LEVEL_OPTIONS.find((o) => o.value === levelKey) : undefined

  return (
    <Col span={7}>
      <Card
        size="small"
        style={{
          borderRadius: 12,
          border: `2px solid ${colors?.border || '#e5e3df'}`,
          background: colors?.bg || '#fafaf9',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 12 }}>
          <Text strong style={{ fontSize: 14, color: '#1a1a1a' }}>{title}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 11 }}>{subtitle}</Text>
        </div>

        {/* D 值大数字 */}
        <div style={{ textAlign: 'center', marginBottom: 12 }}>
          <Text style={{
            fontSize: 36, fontWeight: 700, fontFamily: 'monospace',
            color: colors?.text || '#37352f',
          }}>
            {d !== undefined && d !== null ? d : '-'}
          </Text>
          <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>D = L×E×C</Text>
        </div>

        {/* L/E/C 明细 */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 10 }}>L</Text>
            <br />
            <Text strong style={{ fontSize: 14 }}>{l !== undefined && l !== null ? l : '-'}</Text>
          </div>
          <div style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 10 }}>E</Text>
            <br />
            <Text strong style={{ fontSize: 14 }}>{e !== undefined && e !== null ? e : '-'}</Text>
          </div>
          <div style={{ textAlign: 'center' }}>
            <Text type="secondary" style={{ fontSize: 10 }}>C</Text>
            <br />
            <Text strong style={{ fontSize: 14 }}>{c !== undefined && c !== null ? c : '-'}</Text>
          </div>
        </div>

        {/* 风险等级标签 */}
        {levelKey && (
          <div style={{ textAlign: 'center' }}>
            <Tag color={opt?.color} style={{ fontSize: 13, padding: '2px 12px' }}>
              {levelLabel || levelKey}
            </Tag>
          </div>
        )}

        {/* 风险进度条 */}
        {d !== undefined && d !== null && (
          <Progress
            percent={Math.min((d / 500) * 100, 100)}
            showInfo={false}
            strokeColor={colors?.bar || '#52c41a'}
            trailColor="#f0f0f0"
            size="small"
            style={{ marginTop: 8, marginBottom: 0 }}
          />
        )}
      </Card>
    </Col>
  )
}

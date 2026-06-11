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
  Timeline,
  Image,
  Row,
  Col,
  Empty,
  Select,
  Input,
  Divider,
  Alert,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  SafetyCertificateOutlined,
  EditOutlined,
  CloseOutlined,
  SaveOutlined,
  CloseCircleOutlined,
  RobotOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { getHazard, updateHazard, reviewHazardAI } from '@/actions/safety'
import type { HazardReport, HazardLevel } from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
  HAZARD_LOCATION_OPTIONS,
  RECTIFICATION_STATUS_OPTIONS,
  VERIFY_LEVEL_OPTIONS,
  VERIFY_LEVEL_STATUS_OPTIONS,
} from '@/types/safety'
import HazardRectificationReplyModal from '@/components/safety/HazardRectificationReplyModal'
import HazardVerifyModal from '@/components/safety/HazardVerifyModal'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const { TextArea } = Input

// ── 检查类别选项 ──
const INSPECTION_CATEGORY_OPTIONS = [
  { value: '日常检查', label: '日常检查' },
  { value: '专项检查', label: '专项检查' },
  { value: '季节性检查', label: '季节性检查' },
  { value: '节假日检查', label: '节假日检查' },
  { value: '综合性检查', label: '综合性检查' },
  { value: '事故类比排查', label: '事故类比排查' },
  { value: '外部检查', label: '外部检查' },
]

// ── 隐患类别标签映射 ──
const HAZARD_CATEGORY_LABEL_MAP: Record<string, string> = {}
HAZARD_CATEGORY_OPTIONS.forEach((o) => { HAZARD_CATEGORY_LABEL_MAP[o.value] = o.label })

// ── 后端静态文件基础 URL ──
const BACKEND_HOST = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
  .replace(/\/api\/v1$/, '')

// ── 解析照片 JSON 数组 → 完整 URL ──
function parsePhotos(photos?: string | null): string[] {
  if (!photos) return []
  let arr: string[] = []
  try {
    arr = JSON.parse(photos)
    if (!Array.isArray(arr)) return []
  } catch {
    arr = photos.split(',').map((s) => s.trim()).filter(Boolean)
  }
  return arr.map((url) => {
    if (url.startsWith('http')) return url
    return `${BACKEND_HOST}/${url.replace(/^\/+/, '')}`
  })
}

// ── 隐患等级颜色 ──
function getLevelColor(level: HazardLevel) {
  const opt = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
  return opt?.color || 'default'
}

function getLevelLabel(level: HazardLevel) {
  const opt = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
  return opt?.label || level
}

export default function HazardLedgerDetailPage() {
  const router = useRouter()
  const params = useParams()
  const id = params.id as string
  const { message, modal } = App.useApp()

  const [record, setRecord] = useState<HazardReport | null>(null)
  const [loading, setLoading] = useState(true)
  // ── Modal 状态 ──
  const [replyModalVisible, setReplyModalVisible] = useState(false)
  const [replyMode, setReplyMode] = useState<'reply' | 'rework'>('reply')
  const [verifyModalVisible, setVerifyModalVisible] = useState(false)

  // ── 编辑状态 ──
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<Partial<Record<string, string>>>({})
  const [saving, setSaving] = useState(false)
  const [reviewing, setReviewing] = useState(false)

  const loadRecord = async () => {
    try {
      const response = await getHazard(id)
      if (response.code === 200) {
        setRecord(response.data as HazardReport)
      } else {
        message.error('加载失败')
        router.push('/safety/hazard-ledger')
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

  // ── 编辑辅助 ──
  const getFieldValue = (field: string): string => {
    if (editing && field in edits) return edits[field] ?? (record as any)?.[field] ?? ''
    return (record as any)?.[field] ?? ''
  }

  // ── 编辑 Handler ──
  const handleSave = async () => {
    if (Object.keys(edits).length === 0) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      const res = await updateHazard(id, edits as any)
      if (res.code === 200) {
        message.success('修改已保存')
        setRecord(res.data as HazardReport)
        setEditing(false)
        setEdits({})
      } else {
        message.error(res.message || '保存失败')
      }
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  // ── AI 审核 Handler ──
  const handleApprove = async () => {
    setReviewing(true)
    try {
      if (Object.keys(edits).length > 0) {
        const saveRes = await updateHazard(id, edits as any)
        if (saveRes.code === 200) {
          setEdits({})
        } else {
          message.error(saveRes.message || '保存失败，无法审核')
          setReviewing(false)
          return
        }
      }
      const res = await reviewHazardAI(id, 0, 'approved')
      if (res.code === 200) {
        message.success('审核通过，隐患已进入整改流程')
        setRecord(res.data as HazardReport)
        setEditing(false)
        setEdits({})
      } else {
        message.error(res.message || '审核失败')
      }
    } catch {
      message.error('审核操作失败')
    } finally {
      setReviewing(false)
    }
  }

  const handleReject = async () => {
    modal.confirm({
      title: '驳回重分析',
      icon: <ExclamationCircleOutlined />,
      content: '驳回后 AI 将重新执行分析并覆盖当前结果，确定要继续吗？',
      okText: '确定驳回',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setReviewing(true)
        try {
          const res = await reviewHazardAI(id, 0, 'rejected')
          if (res.code === 200) {
            message.warning('已驳回，AI 将重新分析')
            setRecord(res.data as HazardReport)
            setEditing(false)
            setEdits({})
          } else {
            message.error(res.message || '驳回失败')
          }
        } catch {
          message.error('驳回操作失败')
        } finally {
          setReviewing(false)
        }
      },
    })
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!record) return null

  // ── 整改进度判定 ──
  const rStatus = record.rectification_status

  const nodeStatus = {
    registered: true,
    replied:
      ['replied', 'level1_approved', 'level2_approved', 'closed'].includes(rStatus),
    level1: {
      done: record.verify_level_1_status === 'approved' || record.verify_level_1_status === 'rejected',
      approved: record.verify_level_1_status === 'approved',
      rejected: record.verify_level_1_status === 'rejected',
    },
    level2: {
      done: record.verify_level_2_status === 'approved' || record.verify_level_2_status === 'rejected',
      approved: record.verify_level_2_status === 'approved',
      rejected: record.verify_level_2_status === 'rejected',
    },
    level3: {
      done: record.verify_level_3_status === 'approved' || record.verify_level_3_status === 'rejected',
      approved: record.verify_level_3_status === 'approved',
      rejected: record.verify_level_3_status === 'rejected',
    },
    closed: rStatus === 'closed' || record.status === 'closed',
  }

  const isGeneral = record.hazard_level === 'general'

  const currentLevel = (() => {
    if (!nodeStatus.replied) return null
    if (!nodeStatus.level1.done) return 1
    if (!isGeneral && !nodeStatus.level2.done) return 2
    if (!nodeStatus.level3.done) return isGeneral ? 3 : (nodeStatus.level2.done ? 3 : 2)
    return null
  })()

  const getRectificationTag = (status: string) => {
    const opt = RECTIFICATION_STATUS_OPTIONS.find((o) => o.value === status)
    return <Tag color={opt?.color}>{opt?.label || status}</Tag>
  }

  const dotColor = (done: boolean, rejected: boolean) => {
    if (rejected) return '#e03131'
    if (done) return '#1aae39'
    return '#d9d9d9'
  }

  // ── 操作按钮 ──
  const renderAction = () => {
    if ((record.rectification_status === 'pending' || record.rectification_status === 'in_progress') && record.status === 'open') {
      return (
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          size="middle"
          onClick={() => { setReplyMode('reply'); setReplyModalVisible(true) }}
        >
          整改回复
        </Button>
      )
    }
    if (record.rectification_status === 'replied') {
      return (
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          size="middle"
          onClick={() => setVerifyModalVisible(true)}
        >
          一级复核
        </Button>
      )
    }
    if (record.rectification_status === 'level1_approved') {
      return (
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          size="middle"
          onClick={() => setVerifyModalVisible(true)}
        >
          {isGeneral ? '三级复核' : '二级复核'}
        </Button>
      )
    }
    if (record.rectification_status === 'level2_approved') {
      return (
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          size="middle"
          onClick={() => setVerifyModalVisible(true)}
        >
          三级复核
        </Button>
      )
    }
    if (record.rectification_status === 'rejected') {
      return (
        <Button
          danger
          icon={<EditOutlined />}
          size="middle"
          onClick={() => { setReplyMode('rework'); setReplyModalVisible(true) }}
        >
          重新整改
        </Button>
      )
    }
    return null
  }

  // ── 照片列表 ──
  const defectPhotos = parsePhotos(record.defect_photos)
  const rectificationPhotos = parsePhotos(record.rectification_photos)

  // ── AI 审核阶段判定 ──
  const isAIReviewPhase = record.overall_status === 'completed' && record.ai_generated

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* ═══ 顶部标题栏 ═══ */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        marginBottom: 24,
      }}>
        <div>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push('/safety/hazard-ledger')}
            style={{ padding: 0, marginBottom: 12 }}
          >
            返回台账
          </Button>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#1a1a1a', margin: 0 }}>
            隐患台账详情
          </h1>
          <Text style={{ color: '#5d5b54', fontSize: 14 }}>
            编号：{record.hazard_no}
          </Text>
        </div>
        <Space>
          <Tag color={getLevelColor(record.hazard_level as HazardLevel)} style={{ fontSize: 14, padding: '2px 12px' }}>
            {getLevelLabel(record.hazard_level as HazardLevel)}
          </Tag>
          {getRectificationTag(record.rectification_status)}
        </Space>
      </div>

      {/* ═══ AI 审核阶段提示 ═══ */}
      {isAIReviewPhase && (
        <Alert
          type="info"
          showIcon
          icon={<RobotOutlined />}
          message="AI 分析已完成，请审核识别结果"
          description="可点击右上角「编辑」修改 AI 填充的字段，确认无误后点击「审核通过」进入整改流程。"
          style={{ marginBottom: 24, borderRadius: 8 }}
        />
      )}

      {/* ═══ ① 隐患信息卡片 ═══ */}
      <Card
        title="隐患信息"
        extra={
          <Button
            icon={editing ? <CloseOutlined /> : <EditOutlined />}
            onClick={() => {
              if (editing) { setEditing(false); setEdits({}) }
              else setEditing(true)
            }}
          >
            {editing ? '取消编辑' : '编辑'}
          </Button>
        }
        style={{ marginBottom: 24, borderRadius: 12, border: '1px solid #e5e3df' }}
      >
        {/* 照片展示（始终可见） */}
        {defectPhotos.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>缺陷照片</Text>
            <Image.PreviewGroup>
              <Row gutter={8}>
                {defectPhotos.map((url, i) => (
                  <Col key={i}>
                    <Image
                      src={url}
                      alt={`缺陷照片 ${i + 1}`}
                      width={120}
                      height={120}
                      style={{ objectFit: 'cover', borderRadius: 8, border: '1px solid #e5e3df' }}
                    />
                  </Col>
                ))}
              </Row>
            </Image.PreviewGroup>
          </div>
        )}

        {editing ? (
          /* ═══ 编辑模式 ═══ */
          <>
            <Row gutter={[12, 12]}>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>隐患分类</Text>
                <Select
                  value={getFieldValue('hazard_type')}
                  onChange={(v) => setEdits((p) => ({ ...p, hazard_type: v }))}
                  style={{ width: '100%' }}
                  options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
              </Col>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>隐患等级</Text>
                <Select
                  value={getFieldValue('hazard_level')}
                  onChange={(v) => setEdits((p) => ({ ...p, hazard_level: v }))}
                  style={{ width: '100%' }}
                  options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
              </Col>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>隐患类别</Text>
                <Select
                  value={getFieldValue('hazard_category')}
                  onChange={(v) => setEdits((p) => ({ ...p, hazard_category: v }))}
                  style={{ width: '100%' }}
                  options={HAZARD_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
              </Col>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>检查类别</Text>
                <Select
                  value={getFieldValue('inspection_category')}
                  onChange={(v) => setEdits((p) => ({ ...p, inspection_category: v }))}
                  style={{ width: '100%' }}
                  options={INSPECTION_CATEGORY_OPTIONS}
                />
              </Col>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>地点/部位</Text>
                <Select
                  mode="tags"
                  value={getFieldValue('location') ? getFieldValue('location').split(/[,，;；\s]+/).filter(Boolean) : []}
                  onChange={(vals) => setEdits((p) => ({ ...p, location: (vals as string[]).join('，') }))}
                  style={{ width: '100%' }}
                  options={HAZARD_LOCATION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                />
              </Col>
              <Col span={8}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>责任部门</Text>
                <Input
                  value={getFieldValue('department')}
                  onChange={(e) => setEdits((p) => ({ ...p, department: e.target.value }))}
                  placeholder="责任部门"
                />
              </Col>
              <Col span={12}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>重点缺陷</Text>
                <Input
                  value={getFieldValue('key_defect')}
                  onChange={(e) => setEdits((p) => ({ ...p, key_defect: e.target.value }))}
                  placeholder="重点缺陷"
                />
              </Col>
              <Col span={24}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>隐患描述</Text>
                <TextArea
                  rows={3}
                  value={getFieldValue('description')}
                  onChange={(e) => setEdits((p) => ({ ...p, description: e.target.value }))}
                  placeholder="隐患描述"
                />
              </Col>
              <Col span={24}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>重大隐患判定依据</Text>
                <TextArea
                  rows={2}
                  value={getFieldValue('major_hazard_basis')}
                  onChange={(e) => setEdits((p) => ({ ...p, major_hazard_basis: e.target.value }))}
                  placeholder="判定依据（如适用）"
                />
              </Col>
              <Col span={24}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>管控措施（临时）</Text>
                <TextArea
                  rows={3}
                  value={getFieldValue('control_measures')}
                  onChange={(e) => setEdits((p) => ({ ...p, control_measures: e.target.value }))}
                  placeholder="临时管控措施"
                />
              </Col>
              <Col span={24}>
                <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>纠正预防措施（永久）</Text>
                <TextArea
                  rows={3}
                  value={getFieldValue('corrective_preventive_measures')}
                  onChange={(e) => setEdits((p) => ({ ...p, corrective_preventive_measures: e.target.value }))}
                  placeholder="纠正预防措施"
                />
              </Col>
            </Row>
            {/* 编辑模式操作按钮 */}
            <div style={{ marginTop: 20, textAlign: 'center', borderTop: '1px solid #e5e3df', paddingTop: 16 }}>
              <Space size="middle">
                <Button icon={<SaveOutlined />} type="primary" loading={saving} onClick={handleSave}>
                  保存
                </Button>
                {isAIReviewPhase && (
                  <>
                    <Button
                      icon={<CheckCircleOutlined />}
                      style={{ background: '#52c41a', borderColor: '#52c41a' }}
                      type="primary"
                      loading={reviewing}
                      onClick={handleApprove}
                    >
                      审核通过，转入整改
                    </Button>
                    <Button
                      icon={<CloseCircleOutlined />}
                      danger
                      loading={reviewing}
                      onClick={handleReject}
                    >
                      驳回重分析
                    </Button>
                  </>
                )}
              </Space>
            </div>
          </>
        ) : (
          /* ═══ 查看模式 ═══ */
          <>
            {/* 信息表格 */}
            <Descriptions column={3} size="small" bordered>
              <Descriptions.Item label="隐患编号">{record.hazard_no}</Descriptions.Item>
              <Descriptions.Item label="隐患等级">
                <Tag color={getLevelColor(record.hazard_level as HazardLevel)}>
                  {getLevelLabel(record.hazard_level as HazardLevel)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="隐患类型">
                {(() => {
                  const opt = HAZARD_TYPE_OPTIONS.find((o) => o.value === record.hazard_type)
                  return <Tag>{opt?.label || record.hazard_type}</Tag>
                })()}
              </Descriptions.Item>
              <Descriptions.Item label="隐患类别">
                <Tag>{HAZARD_CATEGORY_LABEL_MAP[record.hazard_category || ''] || record.hazard_category || '-'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="责任部门">{record.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="地点/部位">{record.location || '-'}</Descriptions.Item>
              <Descriptions.Item label="发现人">{record.discovered_by_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="发现时间">
                {record.discovered_at ? dayjs(record.discovered_at).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="整改期限">
                {record.deadline ? (
                  <Text type={dayjs(record.deadline).isBefore(dayjs()) ? 'danger' : undefined}>
                    {dayjs(record.deadline).format('YYYY-MM-DD')}
                    {dayjs(record.deadline).isBefore(dayjs()) && ' (已逾期)'}
                  </Text>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                <Tag color={record.ai_generated ? 'purple' : 'default'}>
                  {record.ai_generated ? 'AI识别' : '人工录入'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="检查类别">{record.inspection_category || '-'}</Descriptions.Item>
              <Descriptions.Item label="检查编号">
                {record.check_id || '-'}
              </Descriptions.Item>
            </Descriptions>

            {/* 长文本字段 */}
            <div style={{ marginTop: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 8 }}>隐患描述</Text>
              <div style={{
                background: '#faf9f7', padding: 12, borderRadius: 8,
                fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #e5e3df',
              }}>
                {record.description || '-'}
              </div>
            </div>

            {record.key_defect ? (
              <div style={{ marginTop: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>重点缺陷</Text>
                <div style={{
                  background: '#fffbe6', padding: 12, borderRadius: 8,
                  fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #ffe58f',
                }}>
                  {record.key_defect}
                </div>
              </div>
            ) : null}

            {record.major_hazard_basis ? (
              <div style={{ marginTop: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>判定依据</Text>
                <div style={{
                  background: '#faf9f7', padding: 12, borderRadius: 8,
                  fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #e5e3df',
                }}>
                  {record.major_hazard_basis}
                </div>
              </div>
            ) : null}

            {record.control_measures ? (
              <div style={{ marginTop: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>管控措施</Text>
                <div style={{
                  background: '#faf9f7', padding: 12, borderRadius: 8,
                  fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #e5e3df',
                }}>
                  {record.control_measures}
                </div>
              </div>
            ) : null}

            {record.corrective_preventive_measures ? (
              <div style={{ marginTop: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>纠正预防措施</Text>
                <div style={{
                  background: '#faf9f7', padding: 12, borderRadius: 8,
                  fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #e5e3df',
                }}>
                  {record.corrective_preventive_measures}
                </div>
              </div>
            ) : null}

            {record.notes ? (
              <div style={{ marginTop: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>备注</Text>
                <div style={{
                  background: '#faf9f7', padding: 12, borderRadius: 8,
                  fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', border: '1px solid #e5e3df',
                }}>
                  {record.notes}
                </div>
              </div>
            ) : null}
          </>
        )}
      </Card>

      {/* ═══ ② 整改流程 Card ═══ */}
      {isAIReviewPhase ? (
        <Card
          title="整改流程"
          style={{ marginBottom: 24, borderRadius: 12, border: '1px solid #e5e3df' }}
        >
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <Alert
              type="info"
              showIcon
              message="AI 分析已完成，请审核结果"
              description="审核通过后，隐患将进入整改流程，届时可进行整改回复和复核操作。"
              style={{ borderRadius: 8 }}
            />
          </div>
        </Card>
      ) : (
        <Card
          title="整改流程"
          style={{ marginBottom: 24, borderRadius: 12, border: '1px solid #e5e3df' }}
        >
          <Timeline
            items={[
              // ① 隐患登记
              {
                color: dotColor(true, false),
                children: (
                  <div>
                    <Text strong>隐患登记</Text>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 2 }}>
                      {record.discovered_by_name || '-'}
                      {' · '}
                      {record.discovered_at
                        ? dayjs(record.discovered_at).format('YYYY-MM-DD HH:mm')
                        : '-'}
                    </div>
                    <div style={{ fontSize: 13, color: '#37352f', marginTop: 4 }}>
                      隐患审核通过，进入整改流程
                    </div>
                  </div>
                ),
              },
              // ② 整改回复
              {
                color: dotColor(nodeStatus.replied, false),
                children: nodeStatus.replied ? (
                  <div>
                    <Text strong>整改回复</Text>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 2 }}>
                      {record.rectification_replied_by_name || '-'}
                      {' · '}
                      {record.rectification_replied_at
                        ? dayjs(record.rectification_replied_at).format('YYYY-MM-DD HH:mm')
                        : '-'}
                    </div>
                    {record.rectification_reply && (
                      <div style={{
                        background: '#f0f7ff', padding: '8px 12px', borderRadius: 6,
                        fontSize: 13, lineHeight: 1.6, marginTop: 6, whiteSpace: 'pre-wrap',
                        border: '1px solid #b7d9ff',
                      }}>
                        {record.rectification_reply}
                      </div>
                    )}
                    {rectificationPhotos.length > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>整改后照片：</Text>
                        <Image.PreviewGroup>
                          <Space size={8} wrap style={{ marginTop: 4 }}>
                            {rectificationPhotos.map((url, i) => (
                              <Image
                                key={i}
                                src={url}
                                alt={`整改照片 ${i + 1}`}
                                width={80}
                                height={80}
                                style={{ objectFit: 'cover', borderRadius: 6, border: '1px solid #e5e3df' }}
                              />
                            ))}
                          </Space>
                        </Image.PreviewGroup>
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <Text strong style={{ color: '#999' }}>整改回复</Text>
                    <div style={{ fontSize: 13, color: '#bbb', marginTop: 2 }}>待进行</div>
                  </div>
                ),
              },
              // ③ 一级复核
              {
                color: dotColor(nodeStatus.level1.done, nodeStatus.level1.rejected),
                children: nodeStatus.level1.done ? (
                  <div>
                    <Space>
                      <Text strong>一级复核（部门负责人）</Text>
                      <Tag color={nodeStatus.level1.approved ? 'green' : 'red'}>
                        {nodeStatus.level1.approved ? '通过' : '驳回'}
                      </Tag>
                    </Space>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 2 }}>
                      {record.verify_level_1_by_name || '-'}
                      {' · '}
                      {record.verify_level_1_at
                        ? dayjs(record.verify_level_1_at).format('YYYY-MM-DD HH:mm')
                        : '-'}
                    </div>
                    {record.verify_level_1_opinion && (
                      <div style={{ fontSize: 13, color: '#37352f', marginTop: 4, fontStyle: 'italic' }}>
                        「{record.verify_level_1_opinion}」
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <Text strong style={currentLevel === 1 ? { color: '#1677ff' } : { color: '#999' }}>
                      一级复核（部门负责人）
                    </Text>
                    <div style={{ fontSize: 13, color: currentLevel === 1 ? '#1677ff' : '#bbb', marginTop: 2 }}>
                      {currentLevel === 1 ? '待复核' : '待进行'}
                    </div>
                  </div>
                ),
              },
              // ④ 二级复核（仅较大/重大隐患需要）
              ...(isGeneral ? [] : [{
                color: dotColor(nodeStatus.level2.done, nodeStatus.level2.rejected),
                children: nodeStatus.level2.done ? (
                  <div>
                    <Space>
                      <Text strong>二级复核（分管领导）</Text>
                      <Tag color={nodeStatus.level2.approved ? 'green' : 'red'}>
                        {nodeStatus.level2.approved ? '通过' : '驳回'}
                      </Tag>
                    </Space>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 2 }}>
                      {record.verify_level_2_by_name || '-'}
                      {' · '}
                      {record.verify_level_2_at
                        ? dayjs(record.verify_level_2_at).format('YYYY-MM-DD HH:mm')
                        : '-'}
                    </div>
                    {record.verify_level_2_opinion && (
                      <div style={{ fontSize: 13, color: '#37352f', marginTop: 4, fontStyle: 'italic' }}>
                        「{record.verify_level_2_opinion}」
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <Text strong style={currentLevel === 2 ? { color: '#1677ff' } : { color: '#999' }}>
                      二级复核（分管领导）
                    </Text>
                    <div style={{ fontSize: 13, color: currentLevel === 2 ? '#1677ff' : '#bbb', marginTop: 2 }}>
                      {currentLevel === 2 ? '待复核' : '待进行'}
                    </div>
                  </div>
                ),
              }]),
              // ⑤ 三级复核 + 关闭
              {
                color: dotColor(nodeStatus.level3.done, nodeStatus.level3.rejected),
                children: nodeStatus.level3.done ? (
                  <div>
                    <Space>
                      <Text strong>三级复核（隐患发现人）</Text>
                      {nodeStatus.closed ? (
                        <Tag color="purple">已关闭</Tag>
                      ) : (
                        <Tag color={nodeStatus.level3.approved ? 'green' : 'red'}>
                          {nodeStatus.level3.approved ? '通过' : '驳回'}
                        </Tag>
                      )}
                    </Space>
                    <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 2 }}>
                      {record.verify_level_3_by_name || '-'}
                      {' · '}
                      {record.verify_level_3_at
                        ? dayjs(record.verify_level_3_at).format('YYYY-MM-DD HH:mm')
                        : '-'}
                    </div>
                    {record.verify_level_3_opinion && (
                      <div style={{ fontSize: 13, color: '#37352f', marginTop: 4, fontStyle: 'italic' }}>
                        「{record.verify_level_3_opinion}」
                      </div>
                    )}
                  </div>
                ) : (
                  <div>
                    <Text strong style={currentLevel === 3 ? { color: '#1677ff' } : { color: '#999' }}>
                      三级复核（隐患发现人）
                    </Text>
                    <div style={{ fontSize: 13, color: currentLevel === 3 ? '#1677ff' : '#bbb', marginTop: 2 }}>
                      {currentLevel === 3 ? '待复核' : '待进行'}
                    </div>
                  </div>
                ),
              },
            ]}
          />

          {/* 操作按钮 */}
          {renderAction() && (
            <div style={{ textAlign: 'center', marginTop: 24, paddingTop: 16, borderTop: '1px solid #e5e3df' }}>
              {renderAction()}
            </div>
          )}

          {!renderAction() && nodeStatus.closed && (
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Tag color="purple" icon={<CheckCircleOutlined />} style={{ fontSize: 14, padding: '4px 16px' }}>
                整改已关闭
              </Tag>
            </div>
          )}
        </Card>
      )}

      {/* ═══ Modals ═══ */}
      <HazardRectificationReplyModal
        open={replyModalVisible}
        record={record}
        mode={replyMode}
        onClose={() => setReplyModalVisible(false)}
        onSuccess={(updated) => { setRecord(updated) }}
      />

      <HazardVerifyModal
        open={verifyModalVisible}
        record={record}
        onClose={() => setVerifyModalVisible(false)}
        onSuccess={(updated) => { setRecord(updated) }}
      />
    </div>
  )
}

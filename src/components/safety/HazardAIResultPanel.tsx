'use client'

import { useState } from 'react'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  Select,
  Input,
  Divider,
  Row,
  Col,
  App,
} from 'antd'
import {
  CheckCircleOutlined,
  EditOutlined,
  ReloadOutlined,
  RobotOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { HazardReport, HazardLevel } from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
} from '@/types/safety'

const { Text, Title } = Typography
const { TextArea } = Input

// HAZARD_CATEGORY_OPTIONS 没有暴露 LABEL_MAP，我们自己构建
const CATEGORY_LABELS: Record<string, string> = {}
HAZARD_CATEGORY_OPTIONS.forEach((o) => {
  CATEGORY_LABELS[o.value] = o.label
})

interface EditableFields {
  hazard_type: string
  hazard_level: string
  hazard_category: string
  description: string
  key_defect: string
  major_hazard_basis: string
  control_measures: string
  corrective_preventive_measures: string
}

interface Props {
  hazard: HazardReport
  confirming: boolean
  onConfirm: (edits: Partial<EditableFields>) => Promise<void>
  onRerun: () => Promise<void>
}

export default function HazardAIResultPanel({
  hazard,
  confirming,
  onConfirm,
  onRerun,
}: Props) {
  const { message, modal } = App.useApp()
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<Partial<EditableFields>>({})

  const getLevelColor = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.color || 'default'
  }

  const getLevelLabel = (level: HazardLevel) => {
    const option = HAZARD_LEVEL_OPTIONS.find((o) => o.value === level)
    return option?.label || level
  }

  const getTypeLabel = (type: string) => {
    const option = HAZARD_TYPE_OPTIONS.find((o) => o.value === type)
    return option?.label || type
  }

  const getFieldValue = (field: keyof EditableFields): string => {
    if (editing && field in edits) {
      return edits[field] ?? (hazard as any)[field] ?? ''
    }
    return (hazard as any)[field] ?? ''
  }

  const handleConfirm = async () => {
    if (editing) {
      // 保存编辑后的数据再确认
      await onConfirm(edits)
    } else {
      await onConfirm({})
    }
  }

  const handleRerun = () => {
    modal.confirm({
      title: '重新AI分析',
      icon: <ExclamationCircleOutlined />,
      content: '重新执行AI分析将覆盖当前的识别结果，确定要继续吗？',
      okText: '确定',
      cancelText: '取消',
      onOk: onRerun,
    })
  }

  // 从 AI 错误信息中提取内容提示
  const hasAIError = !!hazard.ai_error_message

  return (
    <Card
      style={{ borderRadius: 12, border: '1px solid #e5e3df', maxWidth: 800, margin: '0 auto' }}
    >
      <div style={{ marginBottom: 20 }}>
        <Space>
          <RobotOutlined style={{ fontSize: 20, color: '#722ed1' }} />
          <Title level={4} style={{ margin: 0 }}>
            AI 分析结果
          </Title>
          <Tag color="purple">编号：{hazard.hazard_no}</Tag>
        </Space>
        <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
          请审核 AI 生成的隐患识别结果和整改建议，可点击"修改"进行人工调整
        </Text>
      </div>

      {hasAIError && (
        <Alert
          type="warning"
          showIcon
          title="AI 处理警告"
          description={hazard.ai_error_message}
          style={{ marginBottom: 16, borderRadius: 8 }}
        />
      )}

      {/* ── Step 1 结果：隐患识别 ── */}
      <Title level={5} style={{ marginBottom: 12 }}>
        🤖 AI 隐患识别结果（Step 1）
      </Title>

      {editing ? (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              隐患分类
            </Text>
            <Select
              value={getFieldValue('hazard_type')}
              onChange={(v) => setEdits((p) => ({ ...p, hazard_type: v }))}
              style={{ width: '100%' }}
              options={HAZARD_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={12}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              隐患等级
            </Text>
            <Select
              value={getFieldValue('hazard_level')}
              onChange={(v) => setEdits((p) => ({ ...p, hazard_level: v }))}
              style={{ width: '100%' }}
              options={HAZARD_LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={12}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              隐患类别
            </Text>
            <Select
              value={getFieldValue('hazard_category')}
              onChange={(v) => setEdits((p) => ({ ...p, hazard_category: v }))}
              style={{ width: '100%' }}
              options={HAZARD_CATEGORY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            />
          </Col>
          <Col span={12}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              重点缺陷
            </Text>
            <Input
              value={getFieldValue('key_defect')}
              onChange={(e) => setEdits((p) => ({ ...p, key_defect: e.target.value }))}
              placeholder="重点缺陷"
            />
          </Col>
          <Col span={24}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              隐患描述
            </Text>
            <TextArea
              rows={3}
              value={getFieldValue('description')}
              onChange={(e) => setEdits((p) => ({ ...p, description: e.target.value }))}
              placeholder="隐患描述"
            />
          </Col>
          <Col span={24}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              重大隐患判定依据
            </Text>
            <TextArea
              rows={2}
              value={getFieldValue('major_hazard_basis')}
              onChange={(e) => setEdits((p) => ({ ...p, major_hazard_basis: e.target.value }))}
              placeholder="判定依据（如适用）"
            />
          </Col>
        </Row>
      ) : (
        <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
          <Descriptions.Item label="隐患分类">
            {hazard.hazard_type ? (
              <Tag>{getTypeLabel(hazard.hazard_type)}</Tag>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="隐患等级">
            {hazard.hazard_level ? (
              <Tag color={getLevelColor(hazard.hazard_level as HazardLevel)}>
                {getLevelLabel(hazard.hazard_level as HazardLevel)}
              </Tag>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="隐患类别">
            {hazard.hazard_category ? (
              <Tag>{CATEGORY_LABELS[hazard.hazard_category] || hazard.hazard_category}</Tag>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="隐患重点">
            {hazard.key_defect || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="隐患描述" span={2}>
            <div style={{ whiteSpace: 'pre-wrap' }}>{hazard.description || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="判定依据" span={2}>
            <div style={{ whiteSpace: 'pre-wrap' }}>{hazard.major_hazard_basis || '-'}</div>
          </Descriptions.Item>
        </Descriptions>
      )}

      <Divider />

      {/* ── Step 2 结果：整改建议 ── */}
      <Title level={5} style={{ marginBottom: 12 }}>
        📝 AI 整改建议（Step 2）
      </Title>

      {editing ? (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col span={24}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              管控措施（临时）
            </Text>
            <TextArea
              rows={3}
              value={getFieldValue('control_measures')}
              onChange={(e) => setEdits((p) => ({ ...p, control_measures: e.target.value }))}
              placeholder="临时管控措施"
            />
          </Col>
          <Col span={24}>
            <Text strong style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              纠正预防措施（永久）
            </Text>
            <TextArea
              rows={3}
              value={getFieldValue('corrective_preventive_measures')}
              onChange={(e) =>
                setEdits((p) => ({ ...p, corrective_preventive_measures: e.target.value }))
              }
              placeholder="纠正预防措施"
            />
          </Col>
        </Row>
      ) : (
        <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
          <Descriptions.Item label="管控措施（临时）">
            <div style={{ whiteSpace: 'pre-wrap' }}>{hazard.control_measures || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="纠正预防措施（永久）">
            <div style={{ whiteSpace: 'pre-wrap' }}>
              {hazard.corrective_preventive_measures || '-'}
            </div>
          </Descriptions.Item>
        </Descriptions>
      )}

      <Divider />

      {/* ── 操作按钮 ── */}
      <Space style={{ width: '100%', justifyContent: 'center' }} size="middle">
        <Button
          icon={editing ? <CheckCircleOutlined /> : <EditOutlined />}
          onClick={() => {
            if (editing) {
              // 退出编辑模式，放弃修改
              setEditing(false)
              setEdits({})
            } else {
              setEditing(true)
            }
          }}
        >
          {editing ? '取消修改' : '✏️ 修改'}
        </Button>
        <Button
          type="primary"
          size="large"
          icon={<CheckCircleOutlined />}
          onClick={handleConfirm}
          loading={confirming}
        >
          ✅ 确认入库
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={handleRerun}
          disabled={confirming}
        >
          🔄 重新分析
        </Button>
      </Space>
    </Card>
  )
}

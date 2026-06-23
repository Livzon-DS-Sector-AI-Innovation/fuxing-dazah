'use client'

import { useState } from 'react'
import {
  Card,
  Button,
  Typography,
  Alert,
  Select,
  Input,
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
  FileTextOutlined,
} from '@ant-design/icons'
import type { HazardReport, HazardLevel } from '@/types/safety'
import {
  HAZARD_TYPE_OPTIONS,
  HAZARD_LEVEL_OPTIONS,
  HAZARD_CATEGORY_OPTIONS,
} from '@/types/safety'

const { Text } = Typography
const { TextArea } = Input

const CATEGORY_LABELS = Object.fromEntries(
  HAZARD_CATEGORY_OPTIONS.map((o) => [o.value, o.label])
)

interface EditableFields {
  hazard_type: string
  hazard_level: string
  hazard_category: string
  description: string
  key_defect: string
  major_hazard_basis: string
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
      style={{
        borderRadius: 12,
        border: '1px solid #e5e3df',
        borderLeft: '4px solid #5645d4',
      }}
      styles={{ body: { padding: '20px 24px' } }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 20,
          paddingBottom: 16,
          borderBottom: '1px solid #ede9e4',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <RobotOutlined style={{ color: '#5645d4', fontSize: 18 }} />
          <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>AI 分析结果</span>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              padding: '2px 10px',
              borderRadius: 4,
              fontSize: 12,
              fontWeight: 600,
              color: '#391c57',
              background: '#e6e0f5',
            }}
          >
            编号：{hazard.hazard_no}
          </span>
        </div>
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 20, fontSize: 13, color: '#5d5b54' }}>
        请审核 AI 生成的隐患识别结果和整改建议，可点击"修改"进行人工调整
      </Text>

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
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 12,
        }}
      >
        <RobotOutlined style={{ color: '#5645d4', fontSize: 15 }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a' }}>
          AI 隐患识别结果
        </span>
        <span
          style={{
            display: 'inline-flex',
            padding: '2px 8px',
            borderRadius: 4,
            fontSize: 11,
            fontWeight: 600,
            color: '#391c57',
            background: '#e6e0f5',
          }}
        >
          Step 1
        </span>
      </div>

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
        <>
          <Row gutter={[16, 12]}>
            <Col span={8}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>隐患分类</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', minHeight: 40, display: 'flex', alignItems: 'center' }}>
                {hazard.hazard_type ? (
                  <span style={{ display: 'inline-flex', padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: '#391c57', background: '#e6e0f5' }}>{getTypeLabel(hazard.hazard_type)}</span>
                ) : <Text style={{ fontSize: 14, color: '#a4a097' }}>-</Text>}
              </div>
            </Col>
            <Col span={8}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>隐患等级</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', minHeight: 40, display: 'flex', alignItems: 'center' }}>
                {hazard.hazard_level ? (
                  <span style={{ display: 'inline-flex', padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: getLevelColor(hazard.hazard_level as HazardLevel) === 'red' ? '#e03131' : getLevelColor(hazard.hazard_level as HazardLevel) === 'orange' ? '#dd5b00' : '#5645d4', background: getLevelColor(hazard.hazard_level as HazardLevel) === 'red' ? '#fde0ec' : getLevelColor(hazard.hazard_level as HazardLevel) === 'orange' ? '#ffe8d4' : '#e6e0f5' }}>{getLevelLabel(hazard.hazard_level as HazardLevel)}</span>
                ) : <Text style={{ fontSize: 14, color: '#a4a097' }}>-</Text>}
              </div>
            </Col>
            <Col span={8}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>隐患类别</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', minHeight: 40, display: 'flex', alignItems: 'center' }}>
                {hazard.hazard_category ? (
                  <span style={{ display: 'inline-flex', padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: '#391c57', background: '#e6e0f5' }}>{CATEGORY_LABELS[hazard.hazard_category] || hazard.hazard_category}</span>
                ) : <Text style={{ fontSize: 14, color: '#a4a097' }}>-</Text>}
              </div>
            </Col>
          </Row>
          {hazard.key_defect && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>隐患重点</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: '#37352f' }}>{hazard.key_defect}</div>
            </div>
          )}
          {hazard.description && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>
                <ExclamationCircleOutlined style={{ color: '#d4b106', marginRight: 4 }} />
                隐患描述
              </div>
              <div style={{ border: '1px solid #ffe58f', borderRadius: 8, padding: '10px 14px', background: '#fffbe6', fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: '#37352f' }}>{hazard.description}</div>
            </div>
          )}
          {hazard.major_hazard_basis && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>判定依据</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: '#37352f' }}>{hazard.major_hazard_basis}</div>
            </div>
          )}
        </>
      )}

      {/* ── Step 2 结果：整改建议 ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 12,
          marginTop: 12,
        }}
      >
        <FileTextOutlined style={{ color: '#5645d4', fontSize: 15 }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a' }}>
          AI 整改建议
        </span>
        <span
          style={{
            display: 'inline-flex',
            padding: '2px 8px',
            borderRadius: 4,
            fontSize: 11,
            fontWeight: 600,
            color: '#391c57',
            background: '#e6e0f5',
          }}
        >
          Step 2
        </span>
      </div>

      {editing ? (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
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
        <>
          {hazard.corrective_preventive_measures ? (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 13, color: '#5d5b54', marginBottom: 6, fontWeight: 500 }}>纠正预防措施（永久）</div>
              <div style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '10px 14px', background: '#fafaf9', fontSize: 14, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: '#37352f' }}>{hazard.corrective_preventive_measures}</div>
            </div>
          ) : null}
          {!hazard.corrective_preventive_measures && (
            <Text style={{ fontSize: 14, color: '#a4a097' }}>暂无整改建议</Text>
          )}
        </>
      )}

      {/* ── 操作按钮 ── */}
      <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid #ede9e4', display: 'flex', justifyContent: 'center', gap: 16 }}>
        <Button
          icon={editing ? <CheckCircleOutlined /> : <EditOutlined />}
          onClick={() => {
            if (editing) {
              setEditing(false)
              setEdits({})
            } else {
              setEditing(true)
            }
          }}
        >
          {editing ? '取消修改' : '修改'}
        </Button>
        <Button
          type="primary"
          size="large"
          icon={<CheckCircleOutlined />}
          onClick={handleConfirm}
          loading={confirming}
          style={{ fontWeight: 600, borderRadius: 8 }}
        >
          确认入库
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={handleRerun}
          disabled={confirming}
        >
          重新分析
        </Button>
      </div>
    </Card>
  )
}

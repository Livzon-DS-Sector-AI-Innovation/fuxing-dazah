'use client'

import { Descriptions, Divider, Empty, Modal, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import type { KeyRiskOperationReport } from '@/types/safety'
import { KEY_RISK_APPLY_STATUS_CONFIG } from '@/types/safety'

const { Text } = Typography

interface Props {
  open: boolean
  item: KeyRiskOperationReport | null
  onClose: () => void
}

function fmt(dt?: string): string {
  return dt ? dayjs(dt).format('YYYY-MM-DD HH:mm') : '—'
}

function StatusTag({ status }: { status?: string }) {
  if (!status) return <Text type="secondary">—</Text>
  const cfg = KEY_RISK_APPLY_STATUS_CONFIG[status] || { label: status, color: '#787671', bg: '#f0eeec' }
  return (
    <Tag style={{ color: cfg.color, backgroundColor: cfg.bg, border: 'none', borderRadius: 6, fontWeight: 600 }}>
      {cfg.label}
    </Tag>
  )
}

export default function KeyRiskOpsDetail({ open, item, onClose }: Props) {
  if (!item) return null
  const phases = [
    { key: 'phase_before' as const, label: '作业前' },
    { key: 'phase_ongoing' as const, label: '作业中' },
    { key: 'phase_after' as const, label: '作业后' },
  ]

  return (
    <Modal
      title={
        <span style={{ fontSize: 16, fontWeight: 600 }}>
          关键风险作业详情
          <Text style={{ fontSize: 12, color: '#787671', marginLeft: 8, fontFamily: 'monospace' }}>
            {item.report_no}
          </Text>
        </span>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={880}
    >
      {/* ── 审批信息 ── */}
      <Descriptions title="审批信息" column={3} size="small" bordered
        labelStyle={{ width: 110, fontWeight: 600, color: '#5d5b54' }}>
        <Descriptions.Item label="申请状态"><StatusTag status={item.apply_status} /></Descriptions.Item>
        <Descriptions.Item label="审批流程">{item.approval_flow || '—'}</Descriptions.Item>
        <Descriptions.Item label="审批节点">{item.approval_node || '—'}</Descriptions.Item>
        <Descriptions.Item label="当前处理人">{item.current_handler || '—'}</Descriptions.Item>
        <Descriptions.Item label="发起人">{item.initiator_name || '—'}</Descriptions.Item>
        <Descriptions.Item label="发起部门">{item.initiator_department || '—'}</Descriptions.Item>
        <Descriptions.Item label="发起时间">{fmt(item.submitted_at)}</Descriptions.Item>
        <Descriptions.Item label="完成时间">{fmt(item.completed_at)}</Descriptions.Item>
        <Descriptions.Item label="申请编号">
          {item.approval_no_url ? (
            <a href={item.approval_no_url} target="_blank" rel="noreferrer" style={{ color: '#0075de' }}>
              查看审批单据 ↗
            </a>
          ) : (item.report_no || '—')}
        </Descriptions.Item>
      </Descriptions>

      {/* ── 作业主信息 ── */}
      <Divider style={{ margin: '16px 0' }} />
      <Descriptions title="作业信息" column={3} size="small" bordered
        labelStyle={{ width: 110, fontWeight: 600, color: '#5d5b54' }}>
        <Descriptions.Item label="部门">{item.department || '—'}</Descriptions.Item>
        <Descriptions.Item label="区域">{item.area || '—'}</Descriptions.Item>
        <Descriptions.Item label="作业内容">{item.operation_content || '—'}</Descriptions.Item>
        <Descriptions.Item label="作业开始">{fmt(item.start_time)}</Descriptions.Item>
        <Descriptions.Item label="作业结束">{fmt(item.end_time)}</Descriptions.Item>
        <Descriptions.Item label="时长">{item.duration_hours != null ? `${item.duration_hours}h` : '—'}</Descriptions.Item>
        <Descriptions.Item label="现场作业监护人">{item.guardian || '—'}</Descriptions.Item>
        <Descriptions.Item label="现场监护人">{item.site_guardian || '—'}</Descriptions.Item>
        <Descriptions.Item label="部门安全员">{item.dept_safety_officer || '—'}</Descriptions.Item>
        <Descriptions.Item label="备注" span={3}>{item.notes || '—'}</Descriptions.Item>
      </Descriptions>

      {/* ── 安全措施 ── */}
      <Divider style={{ margin: '16px 0' }} />
      <Descriptions title="安全措施" column={1} size="small" bordered
        labelStyle={{ width: 120, fontWeight: 600, color: '#5d5b54' }}>
        <Descriptions.Item label="个人防护">{item.personal_protection || '—'}</Descriptions.Item>
        <Descriptions.Item label="准备措施">{item.preparation_measures || '—'}</Descriptions.Item>
        <Descriptions.Item label="操作注意事项">{item.operation_precautions || '—'}</Descriptions.Item>
        <Descriptions.Item label="应急措施">{item.emergency_measures || '—'}</Descriptions.Item>
      </Descriptions>

      {/* ── 附加作业块 ── */}
      {item.operations && item.operations.length > 0 && (
        <>
          <Divider style={{ margin: '16px 0' }} />
          <Text strong style={{ fontSize: 14 }}>附加作业</Text>
          {item.operations.map((op, i) => (
            <div key={i} style={{ marginTop: 8, borderRadius: 8, border: '1px solid #e5e3df', padding: '8px 12px' }}>
              <Text strong style={{ fontSize: 13, color: '#5645d4' }}>作业 {i + 2}</Text>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px 16px', marginTop: 6 }}>
                <div><Text type="secondary">部门:</Text> {op.department || '—'}</div>
                <div><Text type="secondary">区域:</Text> {op.area || '—'}</div>
                <div><Text type="secondary">作业内容:</Text> {op.operation_content || '—'}</div>
                <div><Text type="secondary">时间段:</Text> {op.time_slot || '—'}</div>
                <div><Text type="secondary">监护人:</Text> {op.guardian || '—'}</div>
              </div>
              {op.personal_protection && <div style={{ marginTop: 4 }}><Text type="secondary">个人防护:</Text> {op.personal_protection}</div>}
              {op.preparation_measures && <div style={{ marginTop: 4 }}><Text type="secondary">准备措施:</Text> {op.preparation_measures}</div>}
              {op.operation_precautions && <div style={{ marginTop: 4 }}><Text type="secondary">操作注意事项:</Text> {op.operation_precautions}</div>}
              {op.emergency_measures && <div style={{ marginTop: 4 }}><Text type="secondary">应急措施:</Text> {op.emergency_measures}</div>}
            </div>
          ))}
        </>
      )}

      {/* ── 三阶段现场确认 ── */}
      <Divider style={{ margin: '16px 0' }} />
      <Text strong style={{ fontSize: 14 }}>现场确认（三阶段）</Text>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 8 }}>
        {phases.map(({ key, label }) => {
          const p = item[key]
          if (!p) {
            return (
              <div key={key} style={{ borderRadius: 8, border: '1px solid #ede9e4', padding: 12, background: '#fafaf9' }}>
                <Text strong style={{ fontSize: 13 }}>{label}</Text>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未填写" style={{ margin: '12px 0' }} />
              </div>
            )
          }
          return (
            <div key={key} style={{ borderRadius: 8, border: '1px solid #e5e3df', padding: 12 }}>
              <Text strong style={{ fontSize: 13 }}>{label}</Text>
              <div style={{ fontSize: 12, color: '#5d5b54', marginTop: 8 }}>
                <div>日期: {p.date ? dayjs(p.date).format('YYYY-MM-DD HH:mm') : '—'}</div>
                {p.photo_url && (
                  <div style={{ marginTop: 4 }}>
                    <a href={p.photo_url} target="_blank" rel="noreferrer" style={{ color: '#0075de' }}>
                      现场确认照片 ↗
                    </a>
                  </div>
                )}
                <div style={{ marginTop: 4 }}>问题描述: {p.issue_desc || '无'}</div>
              </div>
            </div>
          )
        })}
      </div>
    </Modal>
  )
}

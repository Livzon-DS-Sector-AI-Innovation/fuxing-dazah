'use client'

// 转岗离岗申请详情 Drawer（OhApplicationDrawer）
// 打开时先展示行内数据，后台拉详情（diff_analyze_result 展开）覆盖。
// 固定顺序：① 申请信息 Descriptions ② 审批节点 Timeline ③ OhTransferDiffCard ④ 重新分析按钮。

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Popconfirm,
  Space,
  Timeline,
} from 'antd'
import { RocketOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { analyzeOhApplication, getOhApplication } from '@/actions/safety'
import type { OhExamApplication } from '@/types/safety'
import {
  CARD_STYLE,
  OH_APPLICATION_STATUS_UI,
  OH_TRANSFER_TYPE_UI,
  T,
  UI,
} from './ohConstants'
import OhTransferDiffCard from './OhTransferDiffCard'

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function fmtDate(v?: string): string {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : ''
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  )
}

interface OhApplicationDrawerProps {
  open: boolean
  onClose: () => void
  application: OhExamApplication | null
  onRefresh: () => void
}

export default function OhApplicationDrawer({
  open,
  onClose,
  application,
  onRefresh,
}: OhApplicationDrawerProps) {
  const { message } = App.useApp()
  const [detail, setDetail] = useState<OhExamApplication | null>(application)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const res = await getOhApplication(id)
      if (res.code === 200 && res.data) {
        setDetail(res.data)
      } else {
        message.error(res.message || '加载详情失败')
      }
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    if (open && application) {
      setDetail(application)
      loadDetail(application.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, application?.id])

  const handleAnalyze = async () => {
    if (!detail) return
    setAnalyzing(true)
    try {
      const res = await analyzeOhApplication(detail.id)
      if (res.code === 200) {
        message.success('已触发差异分析')
        loadDetail(detail.id)
      } else {
        message.error(res.message || '分析失败')
      }
    } finally {
      setAnalyzing(false)
    }
  }

  if (!detail) {
    return <Drawer open={open} onClose={onClose} title="转岗离岗申请详情" width={800}><Empty description="暂无数据" /></Drawer>
  }

  const isTransfer = detail.transfer_type === 'transfer'
  const targetDate = isTransfer ? detail.transfer_date : detail.leave_date

  // 审批 Timeline（后端提供审批流程名/当前节点/处理人；节点数组按可用字段派生）
  const timelineItems: Array<{ color?: string; children: React.ReactNode }> = [
    {
      color: 'green' as const,
      children: (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>发起申请{detail.applicant_name ? `（${detail.applicant_name}）` : ''}</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 2 }}>
            {detail.initiator_name ? `${detail.initiator_name} · ` : ''}
            {fmtDate(detail.submitted_at) || fmtDate(detail.apply_date) || '—'}
          </div>
        </div>
      ),
    },
  ]
  if (detail.approval_flow) {
    timelineItems.push({
      color: detail.apply_status === '已通过' ? 'green' as const : 'blue' as const,
      children: (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>审批流程：{detail.approval_flow}</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 2 }}>
            当前节点：{detail.approval_node || '—'}
            {detail.current_handler ? ` ｜ 处理人：${detail.current_handler}` : ''}
          </div>
        </div>
      ),
    })
  }
  if (detail.completed_at) {
    timelineItems.push({
      color: 'green' as const,
      children: (
        <div>
          <div style={{ fontWeight: 600, fontSize: 13 }}>审批完成</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 2 }}>{fmtDate(detail.completed_at)}</div>
        </div>
      ),
    })
  }

  return (
    <Drawer
      title={detail.application_no ? `申请 ${detail.application_no}` : '转岗离岗申请详情'}
      open={open}
      onClose={onClose}
      width={800}
      loading={loading}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {/* ① 申请信息 */}
        <SectionCard title="申请信息">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="申请编号"><b>{detail.application_no || '-'}</b></Descriptions.Item>
            <Descriptions.Item label="状态"><Pill status={detail.apply_status} map={OH_APPLICATION_STATUS_UI} /></Descriptions.Item>
            <Descriptions.Item label="姓名">{detail.employee_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="类型"><Pill status={detail.transfer_type} map={OH_TRANSFER_TYPE_UI} /></Descriptions.Item>
            <Descriptions.Item label="原部门">{detail.department || '-'}</Descriptions.Item>
            <Descriptions.Item label="原岗位">{detail.position || '-'}</Descriptions.Item>
            <Descriptions.Item label="转入部门">{detail.new_department || (isTransfer ? '-' : '离岗')}</Descriptions.Item>
            <Descriptions.Item label="转入岗位">{detail.new_position || (isTransfer ? '-' : '离岗')}</Descriptions.Item>
            <Descriptions.Item label={isTransfer ? '转岗日期' : '离岗日期'}>{fmtDate(targetDate) || '-'}</Descriptions.Item>
            <Descriptions.Item label="部门安全员">{detail.dept_safety_officer || '-'}</Descriptions.Item>
            <Descriptions.Item label="当前处理人" span={2}>{detail.current_handler || '-'}</Descriptions.Item>
          </Descriptions>
        </SectionCard>

        {/* ② 审批节点 */}
        <SectionCard title="审批节点">
          <Timeline items={timelineItems} />
        </SectionCard>

        {/* ③ 差异分析卡片 */}
        <OhTransferDiffCard application={detail} onRefresh={() => loadDetail(detail.id)} />

        {/* ④ 重新分析（仅未完成分析时显示主按钮；卡片内已有 failed 重试入口） */}
        {detail.diff_analyze_status !== 'analyzed' && (
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Popconfirm
              title="重新分析"
              description="重新调用 AI 进行转岗危害差异分析"
              okText="确认" cancelText="取消"
              onConfirm={handleAnalyze}
            >
              <Button type="primary" icon={<RocketOutlined />} loading={analyzing}>重新分析</Button>
            </Popconfirm>
          </div>
        )}
      </Space>
    </Drawer>
  )
}

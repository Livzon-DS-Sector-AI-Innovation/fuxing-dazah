'use client'

// 人员台账详情 Drawer（OhPersonDrawer）
// 打开时先展示行内数据，后台拉详情（体检记录链 + 异常随访）覆盖（异常态：失败保留旧数据）。
// 底部「同步总表」按钮 → syncOhPerson（confirm → loading → 成功 message + onSynced 刷新）。

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { getOhPerson, syncOhPerson } from '@/actions/safety'
import type { OhFollowup, OhHealthExam, OhPerson } from '@/types/safety'
import {
  OH_AI_CONCLUSION_UI,
  OH_EXAM_TYPE_UI,
  OH_FOLLOWUP_STATUS_UI,
  OH_PARSE_STATUS_UI,
  OH_WORK_STATUS_UI,
  T,
  UI,
  CARD_STYLE,
} from './ohConstants'
import { monoFont } from './shared-styles'

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function fmtDate(v?: string): string {
  return v ? dayjs(v).format('YYYY-MM-DD') : '-'
}

function fmtYears(v?: number): string {
  if (v === undefined || v === null) return '-'
  const y = Math.floor(v)
  const m = Math.round((v - y) * 12)
  if (y === 0 && m === 0) return '0 年'
  if (y === 0) return `${m} 个月`
  if (m === 0) return `${y} 年`
  return `${y} 年 ${m} 个月`
}

interface OhPersonDrawerProps {
  open: boolean
  onClose: () => void
  person: OhPerson | null
  onViewExams: (personName: string) => void
  onSynced: () => void
}

export default function OhPersonDrawer({
  open,
  onClose,
  person,
  onViewExams,
  onSynced,
}: OhPersonDrawerProps) {
  const { message } = App.useApp()
  const [detail, setDetail] = useState<OhPerson | null>(person)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const res = await getOhPerson(id)
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
    if (open && person) {
      setDetail(person)
      loadDetail(person.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, person?.id])

  const handleSync = async () => {
    if (!detail) return
    setSyncing(true)
    try {
      const res = await syncOhPerson(detail.id)
      if (res.code === 200) {
        message.success('已同步总表')
        onSynced()
        loadDetail(detail.id)
      } else {
        message.error(res.message || '同步失败')
      }
    } finally {
      setSyncing(false)
    }
  }

  const examColumns: ColumnsType<OhHealthExam> = [
    { title: '体检号', dataIndex: 'exam_no', key: 'exam_no', width: 150, render: (v: string) => <span style={monoFont}>{v || '-'}</span> },
    { title: '类型', dataIndex: 'exam_type', key: 'exam_type', width: 90, render: (v: string) => <Pill status={v} map={OH_EXAM_TYPE_UI} /> },
    { title: '日期', dataIndex: 'exam_date', key: 'exam_date', width: 110, render: (v: string) => fmtDate(v) },
    {
      title: 'AI 结论', key: 'conclusion', width: 100,
      render: (_: unknown, r: OhHealthExam) => <Pill status={r.override_conclusion ?? r.ai_conclusion} map={OH_AI_CONCLUSION_UI} />,
    },
    { title: '解析状态', dataIndex: 'ai_parse_status', key: 'parse', width: 90, render: (v: string) => <Pill status={v} map={OH_PARSE_STATUS_UI} /> },
  ]

  const followupColumns: ColumnsType<OhFollowup> = [
    { title: '异常指标', dataIndex: 'indicator_name', key: 'indicator_name', render: (v: string) => v || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Pill status={v} map={OH_FOLLOWUP_STATUS_UI} />,
    },
    { title: '建议复查日期', dataIndex: 'followup_date', key: 'followup_date', width: 130, render: (v: string) => fmtDate(v) },
  ]

  const exams = detail?.exams ?? []
  const followups = detail?.followups ?? []
  const hazards = detail?.hazard_factors ?? []

  return (
    <Drawer
      title={detail ? `${detail.name} — 人员详情` : '人员详情'}
      open={open}
      onClose={onClose}
      width={720}
      loading={loading}
      footer={
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button type="primary" icon={<ReloadOutlined />} loading={syncing} onClick={handleSync}>
            同步总表
          </Button>
        </div>
      }
    >
      {!detail ? (
        <Empty description="暂无数据" />
      ) : (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>基本信息</div>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="姓名"><b>{detail.name}</b></Descriptions.Item>
              <Descriptions.Item label="工号">{detail.employee_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="身份证号" span={2}>{detail.id_card_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="部门">{detail.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="岗位">{detail.position || '-'}</Descriptions.Item>
              <Descriptions.Item label="总工龄">{fmtYears(detail.total_work_years)}</Descriptions.Item>
              <Descriptions.Item label="接害工龄">{fmtYears(detail.hazard_exposure_years)}</Descriptions.Item>
              <Descriptions.Item label="在岗状态"><Pill status={detail.work_status} map={OH_WORK_STATUS_UI} /></Descriptions.Item>
              <Descriptions.Item label="部门安全员">{detail.safety_officer || '-'}</Descriptions.Item>
            </Descriptions>
          </div>

          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>接触危害因素</div>
            {hazards.length === 0 ? (
              <span style={{ color: UI.muted, fontSize: 13 }}>未登记</span>
            ) : (
              <Space size={[6, 6]} wrap>
                {hazards.map((h) => (
                  <Tag key={h} style={{ marginInlineEnd: 0, background: T.lavender, color: '#391c57', borderColor: 'transparent', borderRadius: 6 }}>{h}</Tag>
                ))}
              </Space>
            )}
          </div>

          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>
              体检记录链
              <span style={{ color: UI.muted, fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
                点击行跳转体检记录 Tab 预筛
              </span>
            </div>
            {exams.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无体检记录" />
            ) : (
              <Table<OhHealthExam>
                rowKey="id"
                size="small"
                columns={examColumns}
                dataSource={exams}
                pagination={false}
                onRow={(r) => ({
                  onClick: () => onViewExams(r.employee_name),
                })}
              />
            )}
          </div>

          <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>异常随访</div>
            {followups.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无异常随访" />
            ) : (
              <Table<OhFollowup>
                rowKey="id"
                size="small"
                columns={followupColumns}
                dataSource={followups}
                pagination={false}
              />
            )}
          </div>

          <Tooltip title="取最近一次体检回填人员汇总表并回写 Bitable">
            <span style={{ color: UI.muted, fontSize: 12 }}>同步总表：从该人员最近体检记录回填「最后体检结论/时间/记录链」并回写飞书</span>
          </Tooltip>
        </Space>
      )}
    </Drawer>
  )
}

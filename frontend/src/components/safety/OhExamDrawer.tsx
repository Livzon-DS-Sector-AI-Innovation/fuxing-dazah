'use client'

// 体检记录详情 Drawer（OhExamDrawer）
// 打开时先展示行内数据，后台拉详情（ai_parse_result 展开 + followups）覆盖。
// 固定顺序：① OhExamParseCard ② 异常指标 Table ③ 原始文本折叠 Panel
// ④ 基本信息 Descriptions ⑤ 关联随访列表 + 新建随访按钮。

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Table,
  Typography,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { getOhExam } from '@/actions/safety'
import type { OhAbnormalIndicator, OhFollowup, OhHealthExam } from '@/types/safety'
import {
  CARD_STYLE,
  OH_EXAM_TYPE_UI,
  OH_FOLLOWUP_STATUS_UI,
  OH_INDICATOR_CATEGORY_UI,
  OH_PARSE_STATUS_UI,
  OH_SEVERITY_UI,
  T,
  UI,
} from './ohConstants'
import { monoFont } from './shared-styles'
import OhExamParseCard from './OhExamParseCard'
import OhFollowupModal from './OhFollowupModal'

const { Paragraph } = Typography

function Pill({ status, map }: { status?: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function fmtDate(v?: string): string {
  return v ? dayjs(v).format('YYYY-MM-DD') : '-'
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  )
}

interface OhExamDrawerProps {
  open: boolean
  onClose: () => void
  exam: OhHealthExam | null
  onRefresh: () => void
}

export default function OhExamDrawer({ open, onClose, exam, onRefresh }: OhExamDrawerProps) {
  const { message } = App.useApp()
  const [detail, setDetail] = useState<OhHealthExam | null>(exam)
  const [loading, setLoading] = useState(false)
  const [followupOpen, setFollowupOpen] = useState(false)

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const res = await getOhExam(id)
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
    if (open && exam) {
      setDetail(exam)
      loadDetail(exam.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, exam?.id])

  const indicators: OhAbnormalIndicator[] = detail?.ai_parse_result?.abnormal_indicators ?? []
  const followups = detail?.followups ?? []
  const rawSections = [
    { label: '体检结果', text: detail?.exam_result },
    { label: '检查结论', text: detail?.exam_conclusion },
    { label: '处理意见', text: detail?.treatment_advice_raw },
  ].filter((s) => s.text)

  const indicatorColumns: ColumnsType<OhAbnormalIndicator> = [
    { title: '指标', dataIndex: 'name', key: 'name', width: 140, render: (v: string) => <b style={{ fontSize: 13 }}>{v}</b> },
    { title: '数值', dataIndex: 'value', key: 'value', width: 130 },
    { title: '参考范围', dataIndex: 'reference_range', key: 'reference_range', width: 130, render: (v: string | null | undefined) => v || '-' },
    { title: '类别', dataIndex: 'category', key: 'category', width: 80, render: (v: string) => <Pill status={v} map={OH_INDICATOR_CATEGORY_UI} /> },
    { title: '严重度', dataIndex: 'severity', key: 'severity', width: 80, render: (v: string) => <Pill status={v} map={OH_SEVERITY_UI} /> },
    { title: '随访建议', dataIndex: 'followup_suggestion', key: 'followup_suggestion', render: (v: string | null | undefined) => v || '-' },
  ]

  const followupColumns: ColumnsType<OhFollowup> = [
    { title: '异常指标', dataIndex: 'indicator_name', key: 'indicator_name', render: (v: string) => v || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (v: string) => <Pill status={v} map={OH_FOLLOWUP_STATUS_UI} />,
    },
    { title: '建议复查日期', dataIndex: 'followup_date', key: 'followup_date', width: 130, render: (v: string) => fmtDate(v) },
  ]

  return (
    <Drawer
      title={detail?.exam_no ? `体检记录 ${detail.exam_no}` : '体检记录详情'}
      open={open}
      onClose={onClose}
      width={800}
      loading={loading}
    >
      {!detail ? (
        <Empty description="暂无数据" />
      ) : (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {/* ① AI 解读卡片 */}
          <OhExamParseCard exam={detail} onRefresh={() => loadDetail(detail.id)} />

          {/* ② 异常指标 */}
          <SectionCard title="异常指标">
            {indicators.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无异常指标数据" />
            ) : (
              <Table<OhAbnormalIndicator>
                rowKey={(r, i) => `${r.name}-${i}`}
                size="small"
                columns={indicatorColumns}
                dataSource={indicators}
                pagination={false}
                scroll={{ x: 640 }}
              />
            )}
          </SectionCard>

          {/* ③ 原始文本 */}
          <SectionCard title="原始文本">
            {rawSections.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无原始文本" />
            ) : (
              <Collapse
                size="small"
                items={rawSections.map((s) => ({
                  key: s.label,
                  label: s.label,
                  children: (
                    <Paragraph style={{ fontSize: 13, color: T.charcoal, marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                      {s.text}
                    </Paragraph>
                  ),
                }))}
              />
            )}
          </SectionCard>

          {/* ④ 基本信息 */}
          <SectionCard title="基本信息">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="体检号"><span style={monoFont}>{detail.exam_no || '-'}</span></Descriptions.Item>
              <Descriptions.Item label="体检类型"><Pill status={detail.exam_type} map={OH_EXAM_TYPE_UI} /></Descriptions.Item>
              <Descriptions.Item label="体检机构">{detail.exam_agency || '-'}</Descriptions.Item>
              <Descriptions.Item label="报告日期">{fmtDate(detail.report_date)}</Descriptions.Item>
              <Descriptions.Item label="体检日期">{fmtDate(detail.exam_date)}</Descriptions.Item>
              <Descriptions.Item label="解析状态"><Pill status={detail.ai_parse_status} map={OH_PARSE_STATUS_UI} /></Descriptions.Item>
              <Descriptions.Item label="危害因素" span={2}>
                {detail.hazard_factors?.length ? detail.hazard_factors.join('、') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="登记时间">{fmtDate(detail.scheduled_date)}</Descriptions.Item>
              <Descriptions.Item label="已同步汇总表">{detail.synced_to_summary ? '是' : '否'}</Descriptions.Item>
            </Descriptions>
          </SectionCard>

          {/* ⑤ 关联随访 */}
          <SectionCard title="关联随访">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
              <Button size="small" type="primary" ghost icon={<PlusOutlined />} onClick={() => setFollowupOpen(true)}>
                新建随访
              </Button>
            </div>
            {followups.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联随访" />
            ) : (
              <Table<OhFollowup>
                rowKey="id"
                size="small"
                columns={followupColumns}
                dataSource={followups}
                pagination={false}
              />
            )}
          </SectionCard>
        </Space>
      )}

      <OhFollowupModal
        open={followupOpen}
        onClose={() => setFollowupOpen(false)}
        followup={null}
        preset={{
          person_name: detail?.employee_name,
          exam_id: detail?.id,
        }}
        onSaved={() => {
          setFollowupOpen(false)
          if (detail) loadDetail(detail.id)
        }}
      />
    </Drawer>
  )
}

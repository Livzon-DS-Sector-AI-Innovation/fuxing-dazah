'use client'

import { useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Progress, Select, Tag } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'

import { confirmURsAssessment, getURsReport, runURsAdaptation } from '@/actions/safety'
import type { URSReport } from '@/types/safety'
import { T } from '../shared-styles'
import { RISK_DIMENSION_KEYS, RISK_DIMENSION_LABELS, RISK_LEVEL_UI } from './ursConstants'

interface Props {
  recordId: string | null
  onClose: () => void
  onOpenReview?: (id: string) => void
}

export function URSRiskAssessmentDrawer({ recordId, onClose, onOpenReview }: Props) {
  const { message } = App.useApp()
  const [report, setReport] = useState<URSReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [acting, setActing] = useState(false)
  const [corrections, setCorrections] = useState<Record<string, string>>({})

  const load = async (id: string) => {
    setLoading(true)
    const res = await getURsReport(id)
    setLoading(false)
    if (res.code >= 200 && res.code < 300) setReport(res.data ?? null)
    else message.error(res.message || '加载失败')
  }

  useEffect(() => {
    if (recordId) load(recordId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId])

  const handleConfirm = async () => {
    if (!report) return
    setActing(true)
    const res = await confirmURsAssessment(report.id, {
      comment: '人工复核确认',
      corrections: Object.keys(corrections).length ? corrections : undefined,
    })
    setActing(false)
    if (res.code >= 200 && res.code < 300) {
      message.success('画像已确认')
      load(report.id)
    } else message.error(res.message || '确认失败')
  }

  const handleAdaptation = async () => {
    if (!report) return
    setActing(true)
    const res = await runURsAdaptation(report.id)
    setActing(false)
    if (res.code >= 200 && res.code < 300) {
      message.success('标准适配完成，AI 已预填审核结论')
      load(report.id)
    } else message.error(res.message || '适配失败')
  }

  if (!report) return <Drawer open={false} onClose={onClose} />

  const risk = report.overall_risk_level || 'low'
  const riskUi = RISK_LEVEL_UI[risk] ?? { label: risk, pill: undefined }
  const needReview = report.review_status === 'human_review'
  const canAdapt = report.review_status === 'assessment_confirmed'
  const adapted = report.review_status === 'adapting' || report.review_status === 'item_review'

  return (
    <Drawer title={`适用性评估：${report.equipment_name}`} width={620} open loading={loading} onClose={onClose}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 18, fontWeight: 700 }}>综合风险：<span style={riskUi.pill}>{riskUi.label}</span></span>
        <div style={{ flex: 1, maxWidth: 260 }}>
          <Progress percent={Math.round((report.ai_confidence ?? 0) * 100)} size="small" strokeColor={T.primary} />
        </div>
        <span style={{ fontSize: 12, color: T.steel }}>置信度</span>
      </div>

      {needReview && (
        <div style={{ background: '#ffe8d4', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: T.warning, marginBottom: 12 }}>
          ⚠️ 置信度不足，需人工复核。可调整各维度等级后点击「确认画像」（修正后自动重跑标准适配）。
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {RISK_DIMENSION_KEYS.map((key) => {
          const dim = report.risk_profile?.[key as keyof NonNullable<typeof report.risk_profile>] ?? { level: 'low', indicators: [], evidence: '' }
          const ui = RISK_LEVEL_UI[dim.level] ?? { label: dim.level, pill: undefined }
          const edited = needReview ? corrections[key] ?? dim.level : dim.level
          const editUi = RISK_LEVEL_UI[edited] ?? { label: edited, pill: undefined }
          return (
            <div key={key} style={{ background: '#f6f5f4', borderRadius: 8, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 600 }}>{RISK_DIMENSION_LABELS[key]}风险</span>
                <span style={editUi.pill}>{editUi.label}</span>
                {needReview && (
                  <Select
                    size="small" style={{ width: 110, marginLeft: 'auto' }}
                    value={edited}
                    onChange={(v) => setCorrections((prev) => ({ ...prev, [key]: v }))}
                    options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]}
                  />
                )}
              </div>
              {dim.indicators?.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  {dim.indicators.map((ind) => <Tag key={ind} style={{ fontSize: 12 }}>{ind}</Tag>)}
                </div>
              )}
              {dim.evidence && <div style={{ marginTop: 6, fontSize: 12, color: T.steel }}>依据：{dim.evidence}</div>}
            </div>
          )
        })}
      </div>

      <Descriptions size="small" column={1} style={{ marginTop: 16 }}>
        <Descriptions.Item label="综合定级理由">{report.risk_profile_reasoning || '—'}</Descriptions.Item>
        {report.ai_error_message && (
          <Descriptions.Item label="AI 错误"><span style={{ color: T.error }}>{report.ai_error_message}</span></Descriptions.Item>
        )}
      </Descriptions>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
        {needReview && (
          <Button type="primary" loading={acting} onClick={handleConfirm} style={{ background: T.primary, borderColor: T.primary }}>
            ✅ 确认画像
          </Button>
        )}
        {canAdapt && (
          <Button type="primary" icon={<ThunderboltOutlined />} loading={acting} onClick={handleAdaptation} style={{ background: T.primary, borderColor: T.primary }}>
            触发标准适配
          </Button>
        )}
        {adapted && onOpenReview && report.id && (
          <Button type="primary" onClick={() => onOpenReview(report.id!)} style={{ background: T.success, borderColor: T.success }}>
            进入逐条审核
          </Button>
        )}
      </div>
    </Drawer>
  )
}

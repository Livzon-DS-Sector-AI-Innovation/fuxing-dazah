'use client'

import { useEffect, useState } from 'react'
import { App, Button, Descriptions, Modal, Progress } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'

import { getURsReport } from '@/actions/safety'
import type { URSReport } from '@/types/safety'
import { T } from '../shared-styles'
import { RISK_LEVEL_UI, URS_STATUS_UI } from './ursConstants'
import { URSAppealModal } from './URSAppealModal'

interface Props {
  recordId: string | null
  onClose: () => void
  onAppeal?: (id: string) => void
}

export function URSConclusionModal({ recordId, onClose, onAppeal }: Props) {
  const { message } = App.useApp()
  const [report, setReport] = useState<URSReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [appealOpen, setAppealOpen] = useState(false)

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

  if (!report) return <Modal open={false} onCancel={onClose} />

  const riskUi = RISK_LEVEL_UI[report.overall_risk_level ?? 'low'] ?? { label: report.overall_risk_level ?? '—', pill: undefined }
  const statusUi = URS_STATUS_UI[report.review_status] ?? { label: report.review_status, pill: undefined }
  const approved = report.conclusion === 'approved'
  const score = report.score ?? 0
  const reqs = report.rectification_requirements ?? []

  return (
    <Modal title={`审核结论：${report.equipment_name}`} open={!!recordId} onCancel={onClose} width={640}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            {report.review_status === 'rejected' && (
              <Button onClick={() => setAppealOpen(true)} style={{ borderColor: T.primary, color: T.primary }}>
                提交申诉
              </Button>
            )}
            {onAppeal && report.review_status === 'appeal' && (
              <Button onClick={() => onAppeal(report.id)} style={{ borderColor: T.primary, color: T.primary }}>
                查看重评画像
              </Button>
            )}
          </div>
          <Button type="primary" onClick={onClose} style={{ background: T.primary, borderColor: T.primary }}>关闭</Button>
        </div>
      }>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 16 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 44, fontWeight: 800, color: approved ? T.success : T.error, lineHeight: 1 }}>{score}</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 4 }}>评分</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: T.primary, lineHeight: 1.2 }}>{report.grade || '—'}</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 4 }}>等级</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: approved ? T.success : T.error }}>{approved ? '✅ 通过' : '❌ 不通过'}</div>
          <div style={{ fontSize: 12, color: T.steel, marginTop: 4 }}>结论</div>
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ textAlign: 'right' }}>
          <div>综合风险 <span style={riskUi.pill}>{riskUi.label}</span></div>
          <div style={{ marginTop: 6 }}>状态 <span style={statusUi.pill}>{statusUi.label}</span></div>
        </div>
      </div>

      <Progress percent={score} strokeColor={approved ? T.success : T.error} format={(p) => `${p} 分`} />

      {report.review_result?.summary && (
        <div style={{ background: '#f6f5f4', borderRadius: 8, padding: 12, marginTop: 16, fontSize: 13, color: T.ink }}>
          {report.review_result.summary}
        </div>
      )}

      {reqs.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            <FileTextOutlined /> 整改要求（{reqs.length} 项）
          </div>
          {reqs.map((req, i) => (
            <div key={i} style={{ background: '#fff3f5', borderRadius: 8, padding: '8px 12px', marginBottom: 6, fontSize: 13 }}>
              <span style={{ fontWeight: 600 }}>{req.item_no}</span>　{req.requirement}
              {req.responsible && <span style={{ color: T.steel, marginLeft: 8 }}>责任人：{req.responsible}</span>}
            </div>
          ))}
        </div>
      )}

      {report.review_status === 'appeal' && report.appeal_result && (
        <Descriptions size="small" column={1} style={{ marginTop: 16 }} title="申诉重评">
          <Descriptions.Item label="申诉理由">{report.appeal_reason || '—'}</Descriptions.Item>
          <Descriptions.Item label="风险调整">{report.appeal_result.old_overall ?? '?'} → {report.appeal_result.reassessed_overall ?? '?'}</Descriptions.Item>
          <Descriptions.Item label="调整依据">{report.appeal_result.basis || '—'}</Descriptions.Item>
        </Descriptions>
      )}

      <URSAppealModal recordId={appealOpen ? report.id : null} onClose={() => setAppealOpen(false)} onSuccess={() => load(report.id)} />
    </Modal>
  )
}

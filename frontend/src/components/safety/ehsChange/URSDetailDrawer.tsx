'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { App, Button, Descriptions, Drawer, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DownloadOutlined, ThunderboltOutlined } from '@ant-design/icons'

import { exportURsReviewPdf, getURsItems, getURsReport } from '@/actions/safety'
import type { URSReport, URSStandardItem } from '@/types/safety'
import { T } from '../shared-styles'
import {
  APPLICABILITY_UI, CATEGORY_LABELS, ITEM_VERDICT_UI,
  RISK_DIMENSION_LABELS, RISK_LEVEL_UI, URS_STATUS_UI,
} from './ursConstants'

interface Props {
  recordId: string | null
  onClose: () => void
  onOpenAssess?: (id: string) => void
}

export function URSDetailDrawer({ recordId, onClose, onOpenAssess }: Props) {
  const { message } = App.useApp()
  const [report, setReport] = useState<URSReport | null>(null)
  const [items, setItems] = useState<URSStandardItem[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const recordIdRef = useRef(recordId)

  const load = async (id: string) => {
    setLoading(true)
    const [reportRes, itemsRes] = await Promise.all([getURsReport(id), getURsItems(id)])
    if (id !== recordIdRef.current) {
      setLoading(false) // 忽略过期响应（recordId 已切换）
      return
    }
    setLoading(false)
    if (reportRes.code >= 200 && reportRes.code < 300) setReport(reportRes.data ?? null)
    else message.error(reportRes.message || '加载失败')
    if (itemsRes.code >= 200 && itemsRes.code < 300) setItems(itemsRes.data ?? [])
    else message.error(itemsRes.message || '条款加载失败')
  }

  useEffect(() => {
    recordIdRef.current = recordId
    if (recordId) load(recordId)
    else {
      setReport(null)
      setItems([])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId])

  const statusUi = URS_STATUS_UI[report?.review_status ?? ''] ?? { label: report?.review_status ?? '—', pill: undefined }
  const inAssessFlow = report && ['assessing', 'assessment_confirmed', 'human_review', 'adapting', 'item_review'].includes(report.review_status)

  // ── 导出 PDF ──
  const downloadBase64 = (base64: string, filename: string, mimeType: string) => {
    const byteCharacters = atob(base64)
    const byteNumbers = new Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) byteNumbers[i] = byteCharacters.charCodeAt(i)
    const byteArray = new Uint8Array(byteNumbers)
    const blob = new Blob([byteArray], { type: mimeType })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  }

  const handleExportPdf = async () => {
    if (!report) return
    setExporting(true)
    try {
      const res = await exportURsReviewPdf(report.id)
      if (res.code !== 0 || !res.data) {
        message.error(res.message || 'PDF 导出失败')
        return
      }
      downloadBase64(res.data, `${report.urs_no}_URS审核报告.pdf`, 'application/pdf')
      message.success('PDF 导出成功')
    } catch {
      message.error('PDF 导出失败')
    } finally {
      setExporting(false)
    }
  }

  // ── 标准条款审核过程统计 ──
  const auditStat = useMemo(() => {
    const applicable = items.filter((i) => i.applicability !== 'not_applicable')
    const mandatory = items.filter((i) => i.applicability === 'mandatory').length
    const recommended = items.filter((i) => i.applicability === 'recommended').length
    const notApplicable = items.length - applicable.length
    const passed = applicable.filter((i) => i.review_status === 'passed').length
    const failed = applicable.filter((i) => i.review_status === 'failed').length
    const pending = applicable.filter((i) => !['passed', 'failed', 'skipped'].includes(i.review_status)).length
    const veto = items.filter((i) => i.is_veto)
    const vetoFailed = veto.filter((i) => i.review_status === 'failed').length
    const vetoPending = veto.filter((i) => i.review_status === 'pending').length
    return { mandatory, recommended, notApplicable, passed, failed, pending, vetoTotal: veto.length, vetoFailed, vetoPending }
  }, [items])

  const itemColumns: ColumnsType<URSStandardItem> = [
    {
      title: '条款', width: 170,
      render: (_, r) => (
        <div>
          <span style={{ fontWeight: 600 }}>{r.item_no}</span>
          {r.is_veto && <Tag color="red" style={{ marginLeft: 4, fontSize: 11 }}>否决</Tag>}
          <div style={{ fontSize: 11, color: T.steel, marginTop: 2 }}>
            {CATEGORY_LABELS[r.category] ?? r.category}
            {r.risk_dimension ? `｜${RISK_DIMENSION_LABELS[r.risk_dimension] ?? r.risk_dimension}` : ''}
          </div>
        </div>
      ),
    },
    {
      title: '标准条款', width: 250,
      render: (_, r) => (
        <div>
          <div style={{ fontSize: 13 }}>{r.standard_title}</div>
          {r.standard_ref && <div style={{ fontSize: 11, color: T.steel, marginTop: 2 }}>{r.standard_ref}</div>}
        </div>
      ),
    },
    {
      title: '适配', width: 170,
      render: (_, r) => {
        const ui = APPLICABILITY_UI[r.applicability] ?? { label: r.applicability, pill: undefined }
        return (
          <div>
            <span style={ui.pill}>{ui.label}</span>
            {r.applicability_reason && <div style={{ fontSize: 11, color: T.steel, marginTop: 2 }}>{r.applicability_reason}</div>}
          </div>
        )
      },
    },
    {
      title: 'AI 判定', width: 190,
      render: (_, r) => {
        // 不适用条款自动跳过（后端恒为 pending，此处以「跳过」展示）
        const status = r.applicability === 'not_applicable' ? 'skipped' : r.review_status
        const ui = ITEM_VERDICT_UI[status] ?? { label: status, pill: undefined }
        return (
          <div>
            <span style={ui.pill}>{ui.label}</span>
            {r.ai_suggestion && <div style={{ fontSize: 11, color: T.steel, marginTop: 2 }}>{r.ai_suggestion}</div>}
          </div>
        )
      },
    },
    {
      title: '审核意见', width: 210,
      render: (_, r) => (
        <div>
          {r.review_comment
            ? <div style={{ fontSize: 12 }}>{r.review_comment}</div>
            : <span style={{ color: '#bbb8b1', fontSize: 12 }}>—</span>}
          {r.rectification_required && <Tag color="orange" style={{ marginTop: 4, fontSize: 11 }}>需整改</Tag>}
        </div>
      ),
    },
  ]

  return (
    <Drawer
      title={`URS 详情：${report?.urs_no ?? ''}`}
      width={1040}
      open={!!recordId}
      loading={loading}
      onClose={onClose}
      extra={
        report ? (
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExportPdf}>
            导出 PDF
          </Button>
        ) : undefined
      }
    >
      {report && (
        <>
          <Descriptions size="small" column={1} bordered title="基本信息">
            <Descriptions.Item label="设备名称">{report.equipment_name}</Descriptions.Item>
            <Descriptions.Item label="设备类别">{report.equipment_category || '—'}</Descriptions.Item>
            <Descriptions.Item label="申请部门">{report.department || '—'}</Descriptions.Item>
            <Descriptions.Item label="申请人">{report.applicant_name || '—'}</Descriptions.Item>
            <Descriptions.Item label="采购用途">{report.procurement_purpose || '—'}</Descriptions.Item>
            <Descriptions.Item label="审核状态"><span style={statusUi.pill}>{statusUi.label}</span></Descriptions.Item>
            <Descriptions.Item label="URS 正文">{report.urs_content || '—'}</Descriptions.Item>
          </Descriptions>

          {report.risk_profile && (
            <Descriptions size="small" column={1} bordered title="五维风险画像" style={{ marginTop: 16 }}>
              {Object.entries(RISK_DIMENSION_LABELS).map(([key, label]) => {
                const dim = report.risk_profile?.[key as keyof NonNullable<typeof report.risk_profile>]
                if (!dim) return null
                const ui = RISK_LEVEL_UI[dim.level] ?? { label: dim.level, pill: undefined }
                return (
                  <Descriptions.Item key={key} label={`${label}风险`}>
                    <span style={ui.pill}>{ui.label}</span>
                    {dim.indicators?.length > 0 && dim.indicators.map((i) => <Tag key={i} style={{ marginLeft: 4, fontSize: 12 }}>{i}</Tag>)}
                    {dim.evidence && <div style={{ fontSize: 12, color: T.steel, marginTop: 2 }}>{dim.evidence}</div>}
                  </Descriptions.Item>
                )
              })}
              <Descriptions.Item label="综合风险">{report.overall_risk_level || '—'}</Descriptions.Item>
              <Descriptions.Item label="置信度">{report.ai_confidence != null ? `${Math.round(report.ai_confidence * 100)}%` : '—'}</Descriptions.Item>
              {report.risk_profile_reasoning && (
                <Descriptions.Item label="综合定级理由">{report.risk_profile_reasoning}</Descriptions.Item>
              )}
            </Descriptions>
          )}

          {report.conclusion && (
            <Descriptions size="small" column={1} bordered title="审核结论" style={{ marginTop: 16 }}>
              <Descriptions.Item label="评分">{report.score} 分（{report.grade} 级）</Descriptions.Item>
              <Descriptions.Item label="结论">
                {report.conclusion === 'approved' ? '✅ 通过' : '❌ 不通过'}
                {report.review_result?.veto_break ? <Tag color="red" style={{ marginLeft: 6, fontSize: 11 }}>一票否决</Tag> : null}
              </Descriptions.Item>
              {report.review_result?.summary && (
                <Descriptions.Item label="结论摘要">{report.review_result.summary}</Descriptions.Item>
              )}
              <Descriptions.Item label="整改要求">
                {(report.rectification_requirements ?? []).length
                  ? report.rectification_requirements!.map((r) => `${r.item_no} ${r.requirement}`).join('；')
                  : '无'}
              </Descriptions.Item>
            </Descriptions>
          )}

          <div style={{ marginTop: 16 }}>
            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 10 }}>标准条款审核过程</div>
            {items.length === 0 ? (
              <div style={{ background: '#f6f5f4', borderRadius: 8, padding: 12, fontSize: 12, color: T.steel }}>
                尚未进行标准适配，暂无逐条审核记录。
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 13, marginBottom: 10 }}>
                  <span>
                    强制 <b style={{ color: '#e03131' }}>{auditStat.mandatory}</b>
                    {' '}/ 建议 <b style={{ color: '#dd5b00' }}>{auditStat.recommended}</b>
                    {' '}/ 不适用 <b style={{ color: '#a4a097' }}>{auditStat.notApplicable}</b>
                  </span>
                  <span style={{ color: T.hairline }}>｜</span>
                  <span>
                    通过 <b style={{ color: T.success }}>{auditStat.passed}</b>
                    {' '}/ 不通过 <b style={{ color: T.error }}>{auditStat.failed}</b>
                    {' '}/ 待审 <b>{auditStat.pending}</b>
                  </span>
                  <span style={{ color: T.hairline }}>｜</span>
                  <span>
                    否决项 {auditStat.vetoTotal} 项：
                    {auditStat.vetoFailed > 0
                      ? <b style={{ color: T.error }}>{auditStat.vetoFailed} 项未通过（一票否决）</b>
                      : auditStat.vetoPending > 0
                        ? <b style={{ color: T.warning }}>{auditStat.vetoPending} 项待审</b>
                        : <b style={{ color: T.success }}>全部通过</b>}
                  </span>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  columns={itemColumns}
                  dataSource={items}
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                  onRow={(r) => ({
                    style: r.applicability === 'not_applicable' ? { opacity: 0.55, background: '#faf9f8' } : undefined,
                  })}
                />
              </>
            )}
          </div>

          {report.ai_error_message && (
            <div style={{ background: '#fde0ec', borderRadius: 8, padding: 10, marginTop: 16, fontSize: 12, color: T.error }}>
              AI 错误：{report.ai_error_message}
            </div>
          )}

          {inAssessFlow && onOpenAssess && (
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => onOpenAssess(report.id)} style={{ background: T.primary, borderColor: T.primary }}>
                查看评估/审核
              </Button>
            </div>
          )}
        </>
      )}
    </Drawer>
  )
}

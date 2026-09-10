'use client'

// AI 解读卡片（OhExamParseCard）— 对齐存量「AI智能解读」五段格式
// 状态分支：pending/parsing（等待 AI 解析 + 可手动触发）｜failed（error + 错误信息 + 重新解析）
// ｜parsed（完整五段卡片 + 三按钮）｜存量降级（仅 ai_interpretation 原文 pre-wrap + 「存量解读」Tag，
//   不展示结构化区块、不改写存量；保留重新解析入口）。

import { useState } from 'react'
import {
  App,
  Button,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { RobotOutlined, RocketOutlined, FileTextOutlined, FormOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { overrideOhExamConclusion, parseOhExam } from '@/actions/safety'
import type { OhHealthExam } from '@/types/safety'
import {
  OH_AI_CONCLUSION_FILTER,
  OH_AI_CONCLUSION_UI,
  OH_FITNESS_UI,
  OH_INDICATOR_CATEGORY_UI,
  OH_PARSE_STATUS_UI,
  OH_SEVERITY_UI,
  T,
  UI,
  CARD_STYLE,
} from './ohConstants'

const { Text, Paragraph } = Typography
const { TextArea } = Input

interface OhExamParseCardProps {
  exam: OhHealthExam
  onRefresh: () => void
}

export default function OhExamParseCard({ exam, onRefresh }: OhExamParseCardProps) {
  const { message } = App.useApp()
  const [parsing, setParsing] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideConclusion, setOverrideConclusion] = useState<string>('')
  const [overrideNotes, setOverrideNotes] = useState('')
  const [overriding, setOverriding] = useState(false)

  const result = exam.ai_parse_result
  const status = exam.ai_parse_status
  const isLegacy = !result && !!exam.ai_interpretation
  const conclusion = exam.override_conclusion ?? exam.ai_conclusion

  const handleParse = async () => {
    setParsing(true)
    try {
      const res = await parseOhExam(exam.id)
      if (res.code === 200) {
        message.success('已触发重新解析')
        onRefresh()
      } else {
        message.error(res.message || '解析失败')
      }
    } finally {
      setParsing(false)
    }
  }

  const handleOverride = async () => {
    if (!overrideConclusion) {
      message.warning('请选择覆盖结论')
      return
    }
    if (!overrideNotes.trim()) {
      message.warning('请填写覆盖理由')
      return
    }
    setOverriding(true)
    try {
      const res = await overrideOhExamConclusion(exam.id, {
        conclusion: overrideConclusion,
        notes: overrideNotes.trim(),
      })
      if (res.code === 200) {
        message.success('已覆盖结论')
        setOverrideOpen(false)
        setOverrideConclusion('')
        setOverrideNotes('')
        onRefresh()
      } else {
        message.error(res.message || '覆盖失败')
      }
    } finally {
      setOverriding(false)
    }
  }

  const rawSections = [
    { label: '体检结果', text: exam.exam_result },
    { label: '检查结论', text: exam.exam_conclusion },
    { label: '处理意见', text: exam.treatment_advice_raw },
  ].filter((s) => s.text)

  // ── 状态 Pill ──
  const statusPill = (() => {
    const ui = OH_PARSE_STATUS_UI[status]
    if (!ui) return null
    return <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
  })()

  // ── pending / parsing ──
  if ((status === 'pending' || status === 'parsing') && !result && !isLegacy) {
    return (
      <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
        <div style={{ height: 4, background: T.lavender }} />
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Space size={8}>
              <RobotOutlined style={{ color: T.primary }} />
              <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 智能解读</span>
            </Space>
            {statusPill}
          </div>
          <Text style={{ color: T.steel }}>等待 AI 解析{status === 'parsing' ? '中' : ''}，解析完成后自动展示五段解读结果。</Text>
          <div style={{ marginTop: 12 }}>
            <Button icon={<RocketOutlined />} loading={parsing} onClick={handleParse}>
              {status === 'parsing' ? '重新解析' : '开始解析'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // ── failed ──
  if (status === 'failed' && !result) {
    return (
      <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
        <div style={{ height: 4, background: T.rose }} />
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Space size={8}>
              <RobotOutlined style={{ color: T.error }} />
              <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 智能解读</span>
            </Space>
            {statusPill}
          </div>
          <Text style={{ color: T.error }}>AI 解析失败，可点击重新解析重试。</Text>
          {exam.ai_parse_error && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>失败原因</div>
              <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, lineHeight: 1.7, color: T.charcoal, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {exam.ai_parse_error}
              </div>
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <Button type="primary" icon={<RocketOutlined />} loading={parsing} onClick={handleParse}>重新解析</Button>
          </div>
        </div>
      </div>
    )
  }

  // ── 存量降级（仅 ai_interpretation 原文，无结构化 result；不改写）──
  if (isLegacy) {
    return (
      <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
        <div style={{ height: 4, background: T.lavender }} />
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
            <Space size={8}>
              <RobotOutlined style={{ color: T.primary }} />
              <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 智能解读</span>
              <Tag color="purple" style={{ marginInlineEnd: 0 }}>存量解读</Tag>
            </Space>
            {statusPill}
          </div>
          <Text style={{ color: T.steel, fontSize: 12 }}>员工：{exam.employee_name} ｜ 部门：{exam.department || '-'} ｜ 岗位：{exam.position || '-'}</Text>
          <div style={{ color: T.steel, fontSize: 12, marginTop: 2, marginBottom: 12 }}>
            体检日期：{exam.exam_date ? dayjs(exam.exam_date).format('YYYY-MM-DD') : '-'}
          </div>
          <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, lineHeight: 1.7, color: T.charcoal, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {exam.ai_interpretation}
          </div>
          <div style={{ marginTop: 12 }}>
            <Popconfirm title="重新解析" description="将重新调用 AI 结构化解析该体检报告（存量解读文本不改写）" okText="重新解析" cancelText="取消" onConfirm={handleParse}>
              <Button icon={<RocketOutlined />} loading={parsing}>重新解析</Button>
            </Popconfirm>
          </div>
        </div>
      </div>
    )
  }

  // ── parsed（结构化五段）──
  const indicators = result?.abnormal_indicators ?? []
  const recommendations = result?.recommendations ?? []
  const contraindicationFactors = exam.ai_contraindication_factors?.length
    ? exam.ai_contraindication_factors
    : (result?.contraindication_factors ?? [])

  return (
    <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
      <div style={{ height: 4, background: T.lavender }} />
      <div style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <Space size={8}>
            <RobotOutlined style={{ color: T.primary }} />
            <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>AI 智能解读</span>
            {exam.override_conclusion && (
              <Tooltip title={exam.ai_override_notes || '人工覆盖结论'}>
                <Tag color="orange" style={{ marginInlineEnd: 0 }}>人工已覆盖</Tag>
              </Tooltip>
            )}
          </Space>
          {statusPill}
        </div>

        <Text style={{ color: T.steel, fontSize: 12 }}>员工：{exam.employee_name} ｜ 部门：{exam.department || '-'} ｜ 岗位：{exam.position || '-'}</Text>
        <div style={{ color: T.steel, fontSize: 12, marginTop: 2, marginBottom: 14 }}>
          体检日期：{exam.exam_date ? dayjs(exam.exam_date).format('YYYY-MM-DD') : '-'}
        </div>

        {/* 【异常指标】 */}
        <SectionTitle>异常指标</SectionTitle>
        {indicators.length === 0 ? (
          <Text style={{ color: T.success, fontSize: 13 }}>未见明显异常</Text>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {indicators.map((ind, i) => (
              <div key={`${ind.name}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: UI.stone }}>{i + 1}.</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: UI.ink }}>{ind.name}</span>
                <span style={{ fontSize: 13, color: T.charcoal }}>{ind.value}</span>
                {ind.reference_range && <span style={{ fontSize: 12, color: UI.muted }}>（参考 {ind.reference_range}）</span>}
                {ind.severity && <MiniPill map={OH_SEVERITY_UI} status={ind.severity} />}
                {ind.category && <MiniPill map={OH_INDICATOR_CATEGORY_UI} status={ind.category} />}
                {ind.followup_suggestion && <span style={{ fontSize: 12, color: T.warning }}>{ind.followup_suggestion}</span>}
              </div>
            ))}
          </div>
        )}

        {/* 【岗位关联分析】 */}
        <SectionTitle>岗位关联分析</SectionTitle>
        {result?.contraindication_statement ? (
          <Paragraph style={{ fontSize: 13, color: T.charcoal, marginBottom: 0 }}>{result.contraindication_statement}</Paragraph>
        ) : (
          <Text style={{ color: UI.muted, fontSize: 13 }}>未获取岗位危害因素信息</Text>
        )}

        {/* 【健康建议】 */}
        <SectionTitle>健康建议</SectionTitle>
        {recommendations.length === 0 ? (
          <Text style={{ color: UI.muted, fontSize: 13 }}>无</Text>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {recommendations.map((rec, i) => (
              <div key={i} style={{ fontSize: 13, color: T.charcoal, lineHeight: 1.7 }}>
                {i + 1}. {rec}
              </div>
            ))}
          </div>
        )}

        {/* 【结论】 */}
        <SectionTitle>结论</SectionTitle>
        <Space size={8} wrap style={{ marginBottom: 14 }}>
          {conclusion && <Pill status={conclusion} map={OH_AI_CONCLUSION_UI} />}
          {result?.fitness && <Pill status={result.fitness} map={OH_FITNESS_UI} />}
          {contraindicationFactors.map((f) => (
            <Tag key={f} color="red" style={{ marginInlineEnd: 0 }}>{f}</Tag>
          ))}
        </Space>

        {/* 操作行 */}
        <div style={{ borderTop: `1px solid ${T.hairline}`, paddingTop: 14, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Button size="small" icon={<FileTextOutlined />} onClick={() => setShowRaw((s) => !s)}>
            查看原始文本
          </Button>
          <Popconfirm title="重新解析" description="将重新调用 AI 解析该体检报告" okText="重新解析" cancelText="取消" onConfirm={handleParse}>
            <Button size="small" icon={<RocketOutlined />} loading={parsing}>重新解析</Button>
          </Popconfirm>
          <Button size="small" icon={<FormOutlined />} onClick={() => setOverrideOpen(true)}>人工覆盖结论</Button>
        </div>

        {showRaw && (
          <div style={{ marginTop: 14 }}>
            {rawSections.length === 0 ? (
              <Text style={{ color: UI.muted, fontSize: 13 }}>无原始文本</Text>
            ) : (
              rawSections.map((s) => (
                <div key={s.label} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: T.slate, marginBottom: 4 }}>{s.label}</div>
                  <Paragraph
                    style={{ fontSize: 13, color: T.charcoal, marginBottom: 0, background: T.surface, padding: '8px 12px', borderRadius: 8 }}
                    ellipsis={{ rows: 3, expandable: true, symbol: (expanded) => (expanded ? '收起' : '展开') }}
                  >
                    {s.text}
                  </Paragraph>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* 人工覆盖结论 Modal */}
      <Modal
        title="人工覆盖 AI 结论"
        open={overrideOpen}
        onCancel={() => setOverrideOpen(false)}
        onOk={handleOverride}
        confirmLoading={overriding}
        okText="确认覆盖"
        cancelText="取消"
        width={520}
        destroyOnHidden
      >
        <div style={{ marginBottom: 12, fontSize: 13, color: T.steel }}>
          覆盖后该体检记录以人工结论为准，并留痕覆盖备注（联动人员台账最后体检结论）。
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>结论分类</div>
        <Select
          value={overrideConclusion || undefined}
          onChange={setOverrideConclusion}
          options={OH_AI_CONCLUSION_FILTER.filter((o) => o.value !== '')}
          placeholder="选择覆盖结论"
          style={{ width: '100%', marginBottom: 12 }}
        />
        <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>覆盖理由（留痕）</div>
        <TextArea
          rows={3}
          value={overrideNotes}
          onChange={(e) => setOverrideNotes(e.target.value)}
          placeholder="请填写覆盖理由"
        />
      </Modal>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>
      【{children}】
    </div>
  )
}

function Pill({ status, map }: { status: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  return <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function MiniPill({ status, map }: { status: string; map: Record<string, { label: string; color: string; bg: string }> }) {
  const ui = map[status]
  if (!ui) return null
  return <span style={{ fontSize: 12, padding: '1px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

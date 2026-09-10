'use client'

/**
 * EHS 变更管理 共享组件（申请/验收两页复用）
 * 视觉统一使用 DESIGN tokens（shared-styles T / statusPill）。
 * 详情页：隐患式纵轴阶段布局（StageDot → StageCard → StageHeader → FieldLabel/FieldTile），
 *         按流程阶段顺序展开，字段口径与《EHS变更多维表格字段清单》一致。
 */
import { useState } from 'react'
import {
  Button,
  Card,
  Col,
  Row,
  Tag,
  Typography,
} from 'antd'
import { FileTextOutlined, RobotOutlined, RocketOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { runEhsAiReview } from '@/actions/safety'
import type { EhsChange, EhsChangeTableId } from '@/types/safety'
import { T } from '../shared-styles'
import {
  AI_CONCLUSION_UI,
  CHANGE_DURATION_LABEL,
  CHANGE_GRADE_UI,
  CHANGE_TYPE_LABEL,
  getAiConclusion,
} from './ehsChangeConstants'

const { Text, Paragraph } = Typography

// 卡片样式（DESIGN：12px 圆角 + hairline 描边）
export const CARD_STYLE: React.CSSProperties = {
  background: '#fff',
  border: `1px solid ${T.hairline}`,
  borderRadius: 12,
}

// ═══════════════════════════════════════════════════════════════
// 迷你标签
// ═══════════════════════════════════════════════════════════════

export function SourcePill({ source }: { source?: string }) {
  return <span style={{ color: source === 'bitable' ? '#0075de' : T.slate, fontWeight: 600 }}>{source === 'bitable' ? '飞书' : '平台'}</span>
}

export function StatusPill({ status }: { status: string }) {
  const color: Record<string, [string, string]> = {
    draft: ['#787671', '#f0eeec'],
    under_review: ['#dd5b00', '#ffe8d4'],
    approved: ['#1aae39', '#d9f3e1'],
    rejected: ['#e03131', '#fde0ec'],
    withdrawn: ['#787671', '#f0eeec'],
    cancelled: ['#a4a097', '#f0eeec'],
    terminated: ['#787671', '#f0eeec'],
    in_progress: ['#0075de', '#dcecfa'],
    commissioned: ['#5645d4', '#e6e0f5'],
    closed: ['#787671', '#f0eeec'],
  }
  const label: Record<string, string> = {
    draft: '草稿', under_review: '审批中', approved: '已通过', rejected: '已拒绝',
    withdrawn: '已撤回', cancelled: '已取消', terminated: '已终止',
    in_progress: '实施中', commissioned: '已投用', closed: '已关闭',
  }
  const [c, bg] = color[status] ?? color.closed
  return <span style={{ display: 'inline-flex', padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: c, background: bg }}>{label[status] ?? status}</span>
}

export function AiConclusionPill({ change }: { change: EhsChange }) {
  const c = getAiConclusion(change)
  if (!c) return <Text style={{ color: T.steel, fontSize: 12 }}>—</Text>
  return <span style={AI_CONCLUSION_UI[c]}>{c}</span>
}

export function GradePill({ grade }: { grade?: string }) {
  const ui = CHANGE_GRADE_UI[grade ?? '']
  if (!ui) return <Text style={{ color: T.steel, fontSize: 12 }}>—</Text>
  return <span style={{ display: 'inline-flex', padding: '2px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, color: ui.pill.color as string, background: ui.pill.background as string }}>{ui.label}</span>
}

// ═══════════════════════════════════════════════════════════════
// KPI 统计卡（自绘，对齐 AI 审计 KpiCard 风格）
// ═══════════════════════════════════════════════════════════════

export function KpiCard({
  label,
  value,
  caption,
  active,
  color,
  bg,
  onClick,
}: {
  label: string
  value: number | string
  caption?: string
  active?: boolean
  color?: string
  bg?: string
  onClick?: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        ...CARD_STYLE,
        flex: 1,
        minWidth: 0,
        padding: '14px 16px',
        background: bg ?? (active ? T.gray : T.canvas),
        cursor: onClick ? 'pointer' : undefined,
        transition: 'background .15s',
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: T.muted }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.3, marginTop: 4, color: color ?? T.ink, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      <div style={{ fontSize: 12, color: T.steel, marginTop: 2, minHeight: 18 }}>{caption ?? ''}</div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 详情页：纵轴阶段布局（参考隐患详情 hazard/[id]/page.tsx）
// ═══════════════════════════════════════════════════════════════

function StageDot({ num, active }: { num: number; active?: boolean }) {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        fontWeight: 600,
        color: active ? '#fff' : T.muted,
        background: active ? T.primary : T.gray,
        border: `1px solid ${active ? T.primary : T.hairline}`,
        flexShrink: 0,
      }}
    >
      {num}
    </div>
  )
}

function StageConnector() {
  return <div style={{ width: 2, flex: 1, minHeight: 16, background: T.hairlineSoft, margin: '4px auto' }} />
}

function StageCard({ accent, children }: { accent?: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        ...CARD_STYLE,
        padding: '16px 20px',
        borderLeft: `4px solid ${accent ?? T.primary}`,
      }}
    >
      {children}
    </div>
  )
}

function StageHeader({ icon, title, extra }: { icon: React.ReactNode; title: string; extra?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: T.primary, fontSize: 18, display: 'inline-flex' }}>{icon}</span>
        <span style={{ fontSize: 15, fontWeight: 600, color: T.ink }}>{title}</span>
      </div>
      {extra}
    </div>
  )
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>{children}</div>
}

function FieldTile({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '10px 14px', fontSize: 13, color: T.charcoal, minHeight: 38, wordBreak: 'break-all' }}>
      {children ?? <span style={{ color: T.muted }}>—</span>}
    </div>
  )
}

function TextBlock({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, lineHeight: 1.7, color: T.charcoal, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {children ?? <span style={{ color: T.muted }}>—</span>}
    </div>
  )
}

function fmtDate(v?: string): string {
  return v ? new Date(v).toLocaleDateString('zh-CN') : ''
}

// ═══════════════════════════════════════════════════════════════
// 详情主组件（按 table 渲染审批/验收阶段）
// ═══════════════════════════════════════════════════════════════

export function EhsChangeDetail({
  change,
  onRefresh,
  table,
}: {
  change: EhsChange
  onRefresh: () => void
  table: EhsChangeTableId
}) {
  const isApproval = table === 'approval'
  const extra = change.bt_extra

  // ── ① 基础信息字段 ──
  const basicFields = isApproval
    ? [
        { label: '申请编号', value: change.change_no },
        { label: '变更名称', value: change.title },
        { label: '变更申请编号', value: change.bt_change_no },
        { label: 'GMP变更编号', value: extra?.gmp_change_no },
        { label: '变更发起人', value: change.applicant_name },
        { label: '变更申请部门', value: change.department },
        { label: '变更分类', value: change.change_type ? CHANGE_TYPE_LABEL[change.change_type] || change.change_type : '' },
        { label: '变更级别', node: <GradePill grade={change.change_grade} /> },
        { label: '变更时效', value: change.change_duration ? CHANGE_DURATION_LABEL[change.change_duration] || change.change_duration : '' },
        { label: '预计实施日期', value: fmtDate(change.expected_start) },
      ]
    : [
        { label: '申请编号', value: change.change_no },
        { label: '变更编号', value: change.bt_change_no },
        { label: '变更名称', value: change.title },
        { label: '发起人', value: change.applicant_name },
        { label: '发起人部门', value: change.department },
        { label: '变更级别', node: <GradePill grade={change.change_grade} /> },
      ]

  // ── ② 内容字段（长文本） ──
  const contentFields = isApproval
    ? [
        { label: '申请变更原因', value: change.description },
        { label: '变更计划内容', value: change.bt_plan_content },
        { label: '预计效果', value: change.expected_effect },
        { label: '需更新的文件资料', value: change.documents_to_update?.length ? change.documents_to_update.map((d) => d.name).join('；') : '' },
        { label: '变更风险评估及建议措施', value: change.bt_risk_measures },
      ]
    : [
        { label: '验收日期', node: <span>{fmtDate(extra?.acceptance_date)}</span> },
        { label: '验收意见', value: change.bt_acceptance_comment },
      ]

  // ── 审批状态 ──
  const statusFields = isApproval
    ? [
        { label: '申请状态', node: <StatusPill status={change.status} /> },
        { label: '变更状态', value: change.bt_change_status },
      ]
    : [
        { label: '申请状态', node: <StatusPill status={change.status} /> },
        { label: '审批流程', value: extra?.approval_flow },
      ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* 元信息：仅查看飞书原文（功能链接，非字段） */}
      {extra?.feishu_url && (
        <div style={{ padding: '4px 0 16px' }}>
          <a href={extra.feishu_url} target="_blank" rel="noreferrer" style={{ color: '#0075de', fontSize: 13 }}>
            查看飞书原文 ↗
          </a>
        </div>
      )}

      {/* ── ① 基础信息 ── */}
      <div style={{ display: 'flex', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <StageDot num={1} active />
          <StageConnector />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <StageCard accent={isApproval ? T.primary : T.primary}>
            <StageHeader icon={<FileTextOutlined />} title="基础信息" />
            <Row gutter={[16, 12]}>
              {basicFields.map((f) => (
                <Col span={8} key={f.label}>
                  <FieldLabel>{f.label}</FieldLabel>
                  <FieldTile>{f.node ?? f.value}</FieldTile>
                </Col>
              ))}
            </Row>
          </StageCard>
        </div>
      </div>

      {/* ── ② 内容 ── */}
      <div style={{ display: 'flex', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <StageDot num={2} />
          <StageConnector />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <StageCard accent={T.slate}>
            <StageHeader icon={<UnorderedListOutlined />} title={isApproval ? '变更内容' : '验收内容'} />
            {contentFields.map((f) => (
              <div key={f.label} style={{ marginBottom: 14 }}>
                <FieldLabel>{f.label}</FieldLabel>
                {f.node ? <FieldTile>{f.node}</FieldTile> : <TextBlock>{f.value}</TextBlock>}
              </div>
            ))}
            {!isApproval && (
              <div>
                <FieldLabel>关联审批</FieldLabel>
                <FieldTile>
                  {extra?.related_approval ? extra.related_approval : null}
                </FieldTile>
              </div>
            )}
          </StageCard>
        </div>
      </div>

      {/* ── ③ AI 审核（审批） / ③ 审批状态（验收） ── */}
      {isApproval ? (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <StageDot num={3} />
            <StageConnector />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <StageCard accent={T.primary}>
              <StageHeader icon={<RobotOutlined />} title="AI 审核" />
              <AiReviewTab change={change} onRefresh={onRefresh} />
            </StageCard>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <StageDot num={2} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <StageCard accent={T.slate}>
              <StageHeader icon={<UnorderedListOutlined />} title="审批状态" />
              <Row gutter={[16, 12]}>
                {statusFields.map((f) => (
                  <Col span={8} key={f.label}>
                    <FieldLabel>{f.label}</FieldLabel>
                    <FieldTile>{f.node ?? f.value}</FieldTile>
                  </Col>
                ))}
              </Row>
            </StageCard>
          </div>
        </div>
      )}

      {/* ── ④ 审批状态（审批表） ── */}
      {isApproval && (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <StageDot num={4} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <StageCard accent={T.slate}>
              <StageHeader icon={<UnorderedListOutlined />} title="审批状态" />
              <Row gutter={[16, 12]}>
                {statusFields.map((f) => (
                  <Col span={8} key={f.label}>
                    <FieldLabel>{f.label}</FieldLabel>
                    <FieldTile>{f.node ?? f.value}</FieldTile>
                  </Col>
                ))}
              </Row>
            </StageCard>
          </div>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// AI 审核区块（审批阶段 ③）
// ═══════════════════════════════════════════════════════════════

type AiReviewDimKey = 'reason' | 'plan' | 'effect' | 'risk'

export function AiReviewTab({ change, onRefresh }: { change: EhsChange; onRefresh: () => void }) {
  const r = change.ai_review_result
  const [reviewing, setReviewing] = useState(false)
  const dims: { key: AiReviewDimKey; label: string }[] = [
    { key: 'reason', label: '申请变更原因' },
    { key: 'plan', label: '变更计划内容' },
    { key: 'effect', label: '预计效果' },
    { key: 'risk', label: '变更风险评估及建议措施' },
  ]

  const canReview = change.source === 'bitable' && change.feishu_table_id === 'approval' && change.ai_review_status !== 'completed'

  const handleReview = async () => {
    setReviewing(true)
    try {
      const res = await runEhsAiReview(change.id)
      if (res.code === 200) {
        onRefresh()
      }
    } finally {
      setReviewing(false)
    }
  }

  const hasResult = r && dims.some((d) => r[d.key]?.conclusion || r[d.key]?.report)

  if (!hasResult) {
    return (
      <div>
        {change.ai_review_status === 'failed' ? (
          <>
            <Text style={{ color: T.error }}>AI 审核失败，可点击重新审核。</Text>
            {change.ai_error_message && (
              <div style={{ marginTop: 10 }}>
                <FieldLabel>失败原因</FieldLabel>
                <TextBlock>{change.ai_error_message}</TextBlock>
              </div>
            )}
          </>
        ) : (
          <Text style={{ color: T.steel }}>
            暂无 AI 审核结果。由平台调用 AI 生成 4 维度审核结论并回填飞书多维表格。
          </Text>
        )}
        {canReview && (
          <div style={{ marginTop: 12 }}>
            <Button type="primary" icon={<RocketOutlined />} loading={reviewing} onClick={handleReview}>
              触发AI审核
            </Button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {canReview && (
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button type="primary" ghost icon={<RocketOutlined />} loading={reviewing} onClick={handleReview}>
            重新审核
          </Button>
        </div>
      )}
      {dims.map((d) => {
        const dim = r[d.key]
        if (!dim || (!dim.conclusion && !dim.report)) return null
        return (
          <div key={d.key}>
            <FieldLabel>{d.label}</FieldLabel>
            <div style={{ marginBottom: 8 }}>
              {dim.conclusion
                ? <span style={AI_CONCLUSION_UI[dim.conclusion]}>{dim.conclusion}</span>
                : <Tag>未审核</Tag>}
            </div>
            {dim.report && (
              <TextBlock>{dim.report}</TextBlock>
            )}
          </div>
        )
      })}
      {r.pre_review && (
        <div>
          <FieldLabel>AI预审意见</FieldLabel>
          <TextBlock>{r.pre_review}</TextBlock>
        </div>
      )}
      {r.regulations && r.regulations.length > 0 && (
        <div>
          <FieldLabel>审核依据（法规）</FieldLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {r.regulations.map((reg, i) => (
              <div key={i} style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '8px 12px', fontSize: 12, color: T.charcoal }}>
                <span style={{ fontWeight: 600 }}>{reg.doc_title || '未知法规'}</span>
                {reg.article_ref && <span style={{ color: T.steel }}> — {reg.article_ref}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

'use client'

// 转岗危害差异分析卡片（OhTransferDiffCard）— 对标 ehsChange/shared.tsx::AiReviewTab
// 分支：diff 未触发 → muted「审批通过后自动触发差异分析」；
//      failed → error + 错误信息 + 重新分析（对标 AiReviewTab failed 分支）；
//      analyzed → 完整卡片（新增/移除危害 Tag、PPE 小表、重点复查项、needs_exam 大 Pill、健康建议、摘要）。

import { useState } from 'react'
import {
  Alert,
  App,
  Button,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { RobotOutlined, RocketOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { analyzeOhApplication } from '@/actions/safety'
import type { OhExamApplication, OhTransferDiffOutput } from '@/types/safety'
import {
  CARD_STYLE,
  OH_DIFF_STATUS_UI,
  OH_EXAM_TYPE_UI,
  T,
  UI,
} from './ohConstants'

const { Text } = Typography

function DiffStatusPill({ status }: { status?: string }) {
  if (!status) return null
  const ui = OH_DIFF_STATUS_UI[status]
  if (!ui) return null
  return <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function TextBlock({ children }: { children?: React.ReactNode }) {
  return (
    <div style={{ background: T.surface, border: `1px solid ${T.hairline}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, lineHeight: 1.7, color: T.charcoal, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
      {children ?? <span style={{ color: T.muted }}>—</span>}
    </div>
  )
}

interface OhTransferDiffCardProps {
  application: OhExamApplication
  onRefresh: () => void
}

export default function OhTransferDiffCard({ application, onRefresh }: OhTransferDiffCardProps) {
  const { message } = App.useApp()
  const [analyzing, setAnalyzing] = useState(false)

  const status = application.diff_analyze_status
  const result: OhTransferDiffOutput | null = application.diff_analyze_result ?? null

  const handleAnalyze = async () => {
    setAnalyzing(true)
    try {
      const res = await analyzeOhApplication(application.id)
      if (res.code === 200) {
        message.success('已触发差异分析')
        onRefresh()
      } else {
        message.error(res.message || '分析失败')
      }
    } finally {
      setAnalyzing(false)
    }
  }

  // ── 未触发 / 审批未通过 ──
  if (!result && status !== 'failed') {
    return (
      <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
        <div style={{ height: 4, background: T.gray }} />
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Space size={8}>
              <RobotOutlined style={{ color: T.primary }} />
              <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>转岗危害差异分析</span>
            </Space>
            <DiffStatusPill status={status} />
          </div>
          {status === 'parsing' ? (
            <Text style={{ color: T.steel }}>AI 差异分析进行中，请稍后刷新查看结果。</Text>
          ) : (
            <Text style={{ color: T.steel }}>审批通过后自动触发差异分析，或点击下方按钮手动分析。</Text>
          )}
          <div style={{ marginTop: 12 }}>
            <Button icon={<RocketOutlined />} loading={analyzing} onClick={handleAnalyze}>
              {status === 'parsing' ? '重新分析' : '触发分析'}
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // ── failed ──
  if (!result && status === 'failed') {
    return (
      <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
        <div style={{ height: 4, background: T.rose }} />
        <div style={{ padding: '16px 20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Space size={8}>
              <RobotOutlined style={{ color: T.error }} />
              <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>转岗危害差异分析</span>
            </Space>
            <DiffStatusPill status={status} />
          </div>
          <Text style={{ color: T.error }}>差异分析失败，可点击重新分析重试。</Text>
          {application.diff_analyze_error && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.slate, marginBottom: 6 }}>失败原因</div>
              <TextBlock>{application.diff_analyze_error}</TextBlock>
            </div>
          )}
          <div style={{ marginTop: 12 }}>
            <Button type="primary" icon={<RocketOutlined />} loading={analyzing} onClick={handleAnalyze}>重新分析</Button>
          </div>
        </div>
      </div>
    )
  }

  // ── analyzed（完整卡片）──
  const added = result?.added_hazards ?? []
  const removed = result?.removed_hazards ?? []
  const ppeRows = result?.new_ppe_required ?? []
  const keyItems = result?.key_followup_items ?? []
  const needsExam = result?.needs_exam ?? application.needs_exam

  const ppeColumns: ColumnsType<{ factor: string; ppe: string }> = [
    { title: '危害因素', dataIndex: 'factor', key: 'factor', width: 200 },
    { title: '呼吸防护用品', dataIndex: 'ppe', key: 'ppe' },
  ]

  return (
    <div style={{ ...CARD_STYLE, overflow: 'hidden' }}>
      <div style={{ height: 4, background: T.lavender }} />
      <div style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <Space size={8}>
            <RobotOutlined style={{ color: T.primary }} />
            <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>转岗危害差异分析</span>
          </Space>
          <DiffStatusPill status={status} />
        </div>

        <Text style={{ color: T.steel, fontSize: 13 }}>
          原岗位：{application.position || '-'} → 转入岗位：{application.new_position || '-'}
        </Text>

        {/* 【新增危害】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【新增危害】</div>
        {added.length === 0 ? (
          <Text style={{ color: T.success, fontSize: 13 }}>无新增</Text>
        ) : (
          <Space size={[6, 6]} wrap>
            {added.map((h) => (
              <Tag key={h} color="warning" style={{ marginInlineEnd: 0 }}>{h}</Tag>
            ))}
          </Space>
        )}

        {/* 【移除危害】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【移除危害】</div>
        {removed.length === 0 ? (
          <Text style={{ color: UI.muted, fontSize: 13 }}>无移除</Text>
        ) : (
          <Space size={[6, 6]} wrap>
            {removed.map((h) => (
              <Tag key={h} style={{ marginInlineEnd: 0, background: T.gray, color: T.steel, borderColor: 'transparent' }}>{h}</Tag>
            ))}
          </Space>
        )}

        {/* 【新增 PPE 要求】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【新增 PPE 要求】</div>
        {ppeRows.length === 0 ? (
          <Text style={{ color: UI.muted, fontSize: 13 }}>无新增 PPE 要求</Text>
        ) : (
          <Table<{ factor: string; ppe: string }>
            rowKey="factor"
            size="small"
            columns={ppeColumns}
            dataSource={ppeRows}
            pagination={false}
          />
        )}

        {/* 【重点复查项】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【重点复查项】</div>
        {keyItems.length === 0 ? (
          <Text style={{ color: UI.muted, fontSize: 13 }}>无</Text>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {keyItems.map((item, i) => (
              <div key={i} style={{ fontSize: 13, color: T.charcoal, lineHeight: 1.7 }}>{i + 1}. {item}</div>
            ))}
          </div>
        )}

        {/* 【是否需体检】大 Pill */}
        <div style={{ margin: '16px 0' }}>
          {needsExam ? (
            <span style={{ fontSize: 15, padding: '6px 16px', borderRadius: 6, color: T.warning, background: T.peach, fontWeight: 700 }}>
              需要体检{result?.exam_type_suggestion
                ? `（${OH_EXAM_TYPE_UI[result.exam_type_suggestion]?.label ?? (application.exam_suggestion || '转岗')}）`
                : ''}
            </span>
          ) : (
            <span style={{ fontSize: 15, padding: '6px 16px', borderRadius: 6, color: T.success, background: T.mint, fontWeight: 700 }}>无需体检</span>
          )}
        </div>

        {/* 【健康建议】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【健康建议】</div>
        <TextBlock>{result?.health_advice}</TextBlock>

        {/* 【摘要】 */}
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, margin: '16px 0 8px' }}>【摘要】</div>
        <TextBlock>{result?.summary ?? application.diff_summary}</TextBlock>

        {/* 已自动创建体检登记提示 */}
        {needsExam && application.created_exam_id && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 14 }}
            message={`已自动创建体检登记（体检记录 ID：${application.created_exam_id}，流程状态=未体检）`}
          />
        )}

        {/* 操作行 */}
        <div style={{ borderTop: `1px solid ${T.hairline}`, paddingTop: 14, marginTop: 16 }}>
          <Button size="small" icon={<RocketOutlined />} loading={analyzing} onClick={handleAnalyze}>重新分析</Button>
        </div>
      </div>
    </div>
  )
}

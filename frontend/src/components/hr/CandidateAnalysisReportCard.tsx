'use client'

import { Descriptions, Tag, Typography } from 'antd'

const RECOMMEND_COLOR: Record<string, string> = {
  强烈推荐: 'success',
  推荐: 'processing',
  待定: 'warning',
  不推荐: 'error',
}

interface Dimension {
  name: string
  score?: number
  star?: number
  assessment?: string
}

interface Props {
  report: {
    id: string
    interview_id: string
    dimensions?: Dimension[] | null
    strengths?: string[] | null
    risks?: string[] | null
    total_score?: number | null
    recommend_level?: string | null
    interview_suggestions?: string[] | null
    training_suggestions?: string[] | null
    raw_text?: string | null
    generated_at?: string | null
  }
}

export default function CandidateAnalysisReportCard({ report }: Props) {
  return (
    <div className="space-y-3 text-[13px]">
      <div className="flex items-center gap-3 flex-wrap">
        {report.total_score != null && (
          <Typography.Text strong style={{ fontSize: 18 }}>
            综合胜任度：{report.total_score} 分
          </Typography.Text>
        )}
        {report.recommend_level && (
          <Tag color={RECOMMEND_COLOR[report.recommend_level] || 'default'}>
            {report.recommend_level}
          </Tag>
        )}
        {report.generated_at && (
          <Typography.Text type="secondary">
            {new Date(report.generated_at).toLocaleString()}
          </Typography.Text>
        )}
      </div>

      {report.dimensions && report.dimensions.length > 0 && (
        <Descriptions column={1} size="small" bordered>
          {report.dimensions.map((d) => (
            <Descriptions.Item
              key={d.name}
              label={`${d.name} ${d.star ? '⭐'.repeat(Math.min(d.star, 5)) : ''}`}
            >
              {d.score != null ? `${d.score}/100 · ` : ''}
              {d.assessment || ''}
            </Descriptions.Item>
          ))}
        </Descriptions>
      )}

      {report.raw_text && (
        <Typography.Paragraph className="!mb-1">{report.raw_text}</Typography.Paragraph>
      )}

      {report.strengths && report.strengths.length > 0 && (
        <div>
          <Typography.Text strong>核心优势</Typography.Text>
          <ul className="mt-1 space-y-0.5">
            {report.strengths.map((s, i) => <li key={i}>✅ {s}</li>)}
          </ul>
        </div>
      )}
      {report.risks && report.risks.length > 0 && (
        <div>
          <Typography.Text strong>潜在风险</Typography.Text>
          <ul className="mt-1 space-y-0.5">
            {report.risks.map((s, i) => <li key={i}>⚠️ {s}</li>)}
          </ul>
        </div>
      )}
      {report.interview_suggestions && report.interview_suggestions.length > 0 && (
        <div>
          <Typography.Text strong>面试建议（已联动到面试备注）</Typography.Text>
          <ul className="mt-1 space-y-0.5">
            {report.interview_suggestions.map((s, i) => <li key={i}>{i + 1}. {s}</li>)}
          </ul>
        </div>
      )}
      {report.training_suggestions && report.training_suggestions.length > 0 && (
        <div>
          <Typography.Text strong>录用后培养建议</Typography.Text>
          <ul className="mt-1 space-y-0.5">
            {report.training_suggestions.map((s, i) => <li key={i}>{i + 1}. {s}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

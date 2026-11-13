'use client'

import { Button, Descriptions, Tag, Typography } from 'antd'
import { PrinterOutlined } from '@ant-design/icons'

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

interface BasicInfoItem {
  label: string
  value: string
}

interface Props {
  candidateName?: string
  candidatePosition?: string
  report: {
    id: string
    interview_id: string
    basic_info?: BasicInfoItem[] | null
    jd_review?: string | null
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

/** 区块标题（一、二、三……），对齐参考报告的章节结构 */
function SectionTitle({ text }: { text: string }) {
  return (
    <div className="text-sm font-semibold text-[var(--color-charcoal)] border-l-2 border-[var(--color-primary)] pl-2">
      {text}
    </div>
  )
}

export default function CandidateAnalysisReportCard({ candidateName, candidatePosition, report }: Props) {
  return (
    <div className="space-y-4 text-[13px]">
      {/* 报告头：分析对象 / 岗位 / 日期 / 资料来源 */}
      <div className="rounded-lg bg-[var(--color-surface-soft)] border border-[var(--color-hairline-soft)] px-4 py-2.5 flex items-center gap-x-4 gap-y-1 flex-wrap text-xs text-[var(--color-slate)]">
        {candidateName && <span>分析对象：<b className="text-[var(--color-charcoal)]">{candidateName}</b></span>}
        {candidatePosition && <span>应聘岗位：<b className="text-[var(--color-charcoal)]">{candidatePosition}</b></span>}
        {report.generated_at && (
          <span>分析日期：{new Date(report.generated_at).toLocaleString()}</span>
        )}
        <span>资料来源：简历 + 岗位JD + 面试记录</span>
        <Button size="small" icon={<PrinterOutlined />} className="ml-auto"
          onClick={() => window.print()}>打印/导出报告</Button>
      </div>

      {/* 一、候选人基本信息（旧报告无此字段则跳过） */}
      {report.basic_info && report.basic_info.length > 0 && (
        <div className="space-y-2">
          <SectionTitle text="一、候选人基本信息" />
          <Descriptions
            column={{ xs: 1, sm: 2, md: 3 }}
            size="small"
            bordered
            labelStyle={{ width: 110 }}
          >
            {report.basic_info.map((it) => (
              <Descriptions.Item key={it.label} label={it.label}>{it.value}</Descriptions.Item>
            ))}
          </Descriptions>
        </div>
      )}

      {/* 二、岗位要求回顾（旧报告无此字段则跳过） */}
      {report.jd_review && (
        <div className="space-y-2">
          <SectionTitle text="二、岗位要求回顾" />
          <div className="whitespace-pre-wrap bg-[var(--color-surface-soft)] border border-[var(--color-hairline-soft)] rounded-md px-3 py-2 leading-relaxed">
            {report.jd_review}
          </div>
        </div>
      )}

      {/* 三、胜任度多维评估 */}
      {report.dimensions && report.dimensions.length > 0 && (
        <div className="space-y-2">
          <SectionTitle text="三、岗位胜任度多维评估" />
          <Descriptions column={1} size="small" bordered>
            {report.dimensions.map((d) => (
              <Descriptions.Item
                key={d.name}
                label={`${d.name} ${d.star ? '⭐'.repeat(Math.min(d.star, 5)) : ''}`}
              >
                {d.score != null && (
                  <span className="font-medium" style={{
                    color: d.score >= 80 ? '#1aae39' : d.score >= 60 ? '#0075de' : d.score >= 40 ? '#dd5b00' : '#e03131',
                  }}>{d.score}分 </span>
                )}
                {d.assessment || ''}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </div>
      )}

      {/* 四、优势与风险（双栏） */}
      {(report.strengths?.length || 0) + (report.risks?.length || 0) > 0 && (
        <div className="space-y-2">
          <SectionTitle text="四、优势与风险分析" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {report.strengths && report.strengths.length > 0 && (
              <div className="rounded-md border border-[#b7ebc4] bg-[#f0faf2] p-3">
                <div className="text-sm font-medium text-[#1a7a36] mb-1.5">✅ 核心优势</div>
                <ul className="space-y-1.5 leading-relaxed">
                  {report.strengths.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
            {report.risks && report.risks.length > 0 && (
              <div className="rounded-md border border-[#ffd8d2] bg-[#fff5f2] p-3">
                <div className="text-sm font-medium text-[#c2492a] mb-1.5">⚠️ 潜在风险</div>
                <ul className="space-y-1.5 leading-relaxed">
                  {report.risks.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 五、综合评价与建议 */}
      <div className="space-y-2">
        <SectionTitle text="五、综合评价与建议" />
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
        </div>
        {report.raw_text && (
          <Typography.Paragraph className="!mb-1">{report.raw_text}</Typography.Paragraph>
        )}
        {report.interview_suggestions && report.interview_suggestions.length > 0 && (
          <div>
            <Typography.Text strong>下一轮面试建议（已联动到面试备注）</Typography.Text>
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
    </div>
  )
}

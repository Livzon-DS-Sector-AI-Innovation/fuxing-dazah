'use client'

import { Button, Card, Progress, Tag, Tooltip } from 'antd'
import { RobotOutlined, ReloadOutlined } from '@ant-design/icons'
import type { AiEvaluation } from '@/types/hr'

interface AIScoreCardProps {
  evaluation: AiEvaluation
  onReEvaluate?: () => void
  loading?: boolean
}

const SCORE_CONFIG: { key: keyof AiEvaluation; label: string; color: string }[] = [
  { key: 'jd_match_score', label: 'JD匹配度', color: '#1677ff' },
  { key: 'professional_score', label: '专业能力', color: '#52c41a' },
  { key: 'communication_score', label: '沟通表达', color: '#fa8c16' },
  { key: 'learning_score', label: '学习能力', color: '#722ed1' },
  { key: 'stability_score', label: '稳定性', color: '#13c2c2' },
]

function scorePercent(v: number | undefined): number {
  return v != null ? Math.round(v * 10) : 0
}

function scoreColor(v: number | undefined): string {
  if (v == null) return '#d9d9d9'
  if (v >= 8) return '#52c41a'
  if (v >= 6) return '#1677ff'
  if (v >= 4) return '#fa8c16'
  return '#ff4d4f'
}

export default function AIScoreCard({ evaluation, onReEvaluate, loading }: AIScoreCardProps) {
  return (
    <Card
      size="small"
      title={
        <div className="flex items-center gap-2">
          <RobotOutlined className="text-blue-500" />
          <span>AI 评估结果</span>
          {evaluation.overall_score != null && (
            <Tag color={scoreColor(evaluation.overall_score)}>
              综合 {evaluation.overall_score?.toFixed(1)}
            </Tag>
          )}
        </div>
      }
      extra={
        onReEvaluate && (
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onReEvaluate}>
            重新评估
          </Button>
        )
      }
      className="bg-gradient-to-r from-blue-50/50 to-white"
    >
      {/* 五维评分条 */}
      <div className="space-y-2 mb-4">
        {SCORE_CONFIG.map(({ key, label, color }) => {
          const val = evaluation[key] as number | undefined
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-16 shrink-0">{label}</span>
              <Progress
                percent={scorePercent(val)}
                size="small"
                strokeColor={color}
                showInfo={false}
                style={{ flex: 1 }}
              />
              <Tooltip title={val != null ? `${val}/10` : '未评估'}>
                <span className="text-xs font-medium w-8 text-right" style={{ color: scoreColor(val) }}>
                  {val != null ? val.toFixed(1) : '-'}
                </span>
              </Tooltip>
            </div>
          )
        })}
      </div>

      {/* 综合评价 */}
      {evaluation.strengths && (
        <div className="mb-2">
          <div className="text-xs font-medium text-green-600 mb-1">优势</div>
          <div className="text-xs text-gray-600 whitespace-pre-line">{evaluation.strengths}</div>
        </div>
      )}

      {evaluation.weaknesses && (
        <div className="mb-2">
          <div className="text-xs font-medium text-orange-600 mb-1">不足</div>
          <div className="text-xs text-gray-600 whitespace-pre-line">{evaluation.weaknesses}</div>
        </div>
      )}

      {evaluation.ai_summary && (
        <div className="mb-2">
          <div className="text-xs font-medium text-blue-600 mb-1">综合评价</div>
          <div className="text-xs text-gray-700 whitespace-pre-line">{evaluation.ai_summary}</div>
        </div>
      )}

      {evaluation.risk_flags && evaluation.risk_flags !== '无' && (
        <div>
          <div className="text-xs font-medium text-red-600 mb-1">风险提示</div>
          <div className="text-xs text-red-500">{evaluation.risk_flags}</div>
        </div>
      )}

      {/* 评估时间 */}
      {evaluation.evaluated_at && (
        <div className="text-[10px] text-gray-400 mt-2 text-right">
          评估时间：{new Date(evaluation.evaluated_at).toLocaleString('zh-CN')}
        </div>
      )}
    </Card>
  )
}

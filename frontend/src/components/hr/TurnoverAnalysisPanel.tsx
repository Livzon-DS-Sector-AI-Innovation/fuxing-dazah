'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { Button, Alert, Divider } from 'antd'
import { BulbOutlined, ReloadOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { fetchTurnoverAnalysis } from '@/lib/api/hr'
import type { TurnoverAnalysisResponse } from '@/types/hr'

type Stage = 'idle' | 'extracting' | 'thinking' | 'streaming' | 'done' | 'error'

const THINKING_STEPS = [
  '智能检索数据中',
  '阿米巴经营智能体分析中',
  '精益生产智能体分析中',
  '质量管理智能体分析中',
]

export default function TurnoverAnalysisPanel() {
  const [stage, setStage] = useState<Stage>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const [result, setResult] = useState<TurnoverAnalysisResponse | null>(null)
  const [displayedText, setDisplayedText] = useState('')
  const [stepIndex, setStepIndex] = useState(0)
  const [noTransition, setNoTransition] = useState(false)

  const fullMarkdown = useMemo(() => {
    if (!result) return ''
    const lines = [
      `## AI分析`,
      '',
      result.data.ai_summary,
      '',
      ...result.data.ai_suggestions.flatMap((s, i) => [
        `### 建议${i + 1}`,
        s.suggestion,
        '',
        `**依据${i + 1}：**${s.evidence}`,
        '',
      ]),
    ]
    return lines.join('\n')
  }, [result])

  useEffect(() => {
    if (stage !== 'streaming' || !fullMarkdown) return

    let i = 0
    const timer = setInterval(() => {
      setDisplayedText(fullMarkdown.slice(0, i))
      i++
      if (i > fullMarkdown.length) {
        clearInterval(timer)
        setStage('done')
      }
    }, 30)

    return () => clearInterval(timer)
  }, [stage, fullMarkdown])

  useEffect(() => {
    if (stage !== 'extracting' && stage !== 'thinking') {
      setStepIndex(0)
      setNoTransition(false)
      return
    }
    const timer = setInterval(() => {
      setStepIndex((prev) => {
        const next = prev + 1
        if (next >= THINKING_STEPS.length) {
          setTimeout(() => {
            setNoTransition(true)
            setStepIndex(0)
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                setNoTransition(false)
              })
            })
          }, 500)
        }
        return next
      })
    }, 3000)
    return () => clearInterval(timer)
  }, [stage])

  const handleAnalyze = useCallback(async () => {
    setStage('extracting')
    setDisplayedText('')
    setErrorMsg('')
    setResult(null)

    try {
      const data = await fetchTurnoverAnalysis()
      setResult(data)

      setStage('thinking')
      await new Promise((r) => setTimeout(r, 1500))

      setStage('streaming')
    } catch (err: any) {
      setErrorMsg(err.message || '分析失败，请稍后重试')
      setStage('error')
    }
  }, [])

  const handleRetry = () => {
    setDisplayedText('')
    setErrorMsg('')
    setResult(null)
    handleAnalyze()
  }

  const isAnalyzing = stage === 'extracting' || stage === 'thinking' || stage === 'streaming'

  return (
    <div className="bg-white rounded-lg border border-[var(--color-hairline)] p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-[var(--color-charcoal)]">
            人员流动智能分析
          </h3>
          <p className="text-sm text-[var(--color-slate)] mt-1">
            基于最近6个月人事数据，AI生成管理建议
          </p>
        </div>
        <Button
          type="primary"
          icon={<BulbOutlined />}
          onClick={handleAnalyze}
          loading={isAnalyzing}
          disabled={isAnalyzing}
        >
          智能分析
        </Button>
      </div>

      {/* Content area */}
      {stage !== 'idle' && (
        <div className="mt-4 pt-4 border-t border-[var(--color-hairline-soft)]">
          {(stage === 'extracting' || stage === 'thinking') && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div
                className="w-10 h-10 rounded-full animate-spin"
                style={{
                  background: 'conic-gradient(from 0deg, #5645d4, #8b7cf7, #a78bfa, #5645d4)',
                  mask: 'radial-gradient(transparent 55%, black 56%)',
                  WebkitMask: 'radial-gradient(transparent 55%, black 56%)',
                }}
              />
              <div className="text-base font-medium text-[var(--color-charcoal)]">
                DeepThinking
              </div>
              <div className="relative h-6 w-full overflow-hidden">
                {[...THINKING_STEPS, ...THINKING_STEPS].map((step, i) => (
                  <div
                    key={i}
                    className={`absolute inset-x-0 h-6 flex items-center justify-center text-sm text-[var(--color-slate)] ${noTransition ? '' : 'transition-transform duration-500 ease-in-out'}`}
                    style={{ transform: `translateY(${(i - stepIndex) * 100}%)` }}
                  >
                    {step}
                  </div>
                ))}
              </div>
            </div>
          )}

          {(stage === 'streaming' || stage === 'done') && result && (
            <div className="space-y-4">
              {/* Data summary card */}
              <div className="bg-[var(--color-surface)] rounded-lg p-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-[var(--color-slate)]">统计周期</span>
                  <span className="font-medium">
                    {result.data.raw_data.period_start} 至 {result.data.raw_data.period_end}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-[var(--color-slate)]">入职人数</span>
                  <span className="font-medium text-[var(--color-success)]">
                    {result.data.raw_data.onboarding_count} 人
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-[var(--color-slate)]">离职人数</span>
                  <span className="font-medium text-[var(--color-error)]">
                    {result.data.raw_data.departure_count} 人
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-[var(--color-slate)]">人员流失率</span>
                  <span className="font-medium">
                    {result.data.metrics.turnover_rate}%
                  </span>
                </div>
                {Object.keys(result.data.raw_data.departure_by_reason).length > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-[var(--color-slate)]">离职原因分布</span>
                    <span className="font-medium text-right max-w-[70%]">
                      {Object.entries(result.data.raw_data.departure_by_reason)
                        .map(([k, v]) => `${k}(${v})`)
                        .join('、')}
                    </span>
                  </div>
                )}
              </div>

              <Divider />

              {/* AI analysis with typewriter effect */}
              <div className="text-sm leading-relaxed">
                <ReactMarkdown
                  components={{
                    h2: ({ children }) => (
                      <h2 className="text-lg font-semibold text-[var(--color-charcoal)] mt-4 mb-2">
                        {children}
                      </h2>
                    ),
                    h3: ({ children }) => (
                      <h3 className="text-base font-semibold text-[var(--color-charcoal)] mt-3 mb-1">
                        {children}
                      </h3>
                    ),
                    p: ({ children }) => (
                      <p className="text-sm text-[var(--color-ink)] leading-relaxed mb-2">
                        {children}
                      </p>
                    ),
                    strong: ({ children }) => (
                      <strong className="font-semibold text-[var(--color-charcoal)]">
                        {children}
                      </strong>
                    ),
                  }}
                >
                  {displayedText + (stage === 'streaming' ? '▌' : '')}
                </ReactMarkdown>
              </div>

              {stage === 'done' && (
                <div className="pt-2">
                  <Button icon={<ReloadOutlined />} onClick={handleRetry}>
                    重新分析
                  </Button>
                </div>
              )}
            </div>
          )}

          {stage === 'error' && (
            <Alert
              message="分析失败"
              description={errorMsg}
              type="error"
              showIcon
              action={
                <Button size="small" danger onClick={handleRetry}>
                  重试
                </Button>
              }
            />
          )}
        </div>
      )}
    </div>
  )
}

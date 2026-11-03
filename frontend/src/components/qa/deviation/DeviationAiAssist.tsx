'use client'

import { useState, type CSSProperties } from 'react'
import { Alert, App, Button, Checkbox, Modal, Tag } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import type { FormInstance } from 'antd'
import { deviationAiAssist } from '@/actions/qa-deviation'
import {
  DEVIATION_ITEM_CATEGORY_LABEL,
  type DeviationAiAssistInput,
  type DeviationAiAssistKind,
  type DeviationAiAssistResult,
  type DeviationItem,
  type WhyStep,
} from '@/types/qa-deviation'
import { actionError } from './shared'

/** AI 建议组件的识别色（沿用全站 AI 面板紫色系）。 */
const AI_COLOR = '#5645d4'

const M1E_LABELS: Record<string, string> = {
  personnel: '人员',
  machine: '设备 / 仪器',
  material: '物料',
  method: '方法 / 程序',
  environment: '环境',
  other: '其他',
}

/** 「采纳」回调收到的载荷：已按勾选过滤、可直接写回表单的建议。 */
export type DeviationAiAdoptPayload =
  | { kind: 'describe'; description: string | null; items: DeviationItem[] }
  | { kind: 'm1e'; inserts: Partial<Record<string, string[]>> }
  | { kind: 'why'; steps: WhyStep[] }
  | { kind: 'hypothesis'; tests: Array<{ hypothesis: string; sample: string | null; protocol: string | null; expected: string | null }> }

/** 偏差 AI 辅助按钮 + 结果审核弹窗：AI 只产建议，采纳动作由调用方写回表单。 */
export function DeviationAiAssistButton({
  kind,
  label,
  buildInput,
  onAdopt,
}: {
  kind: DeviationAiAssistKind
  label: string
  /** 点击时构造请求（从 form 实例取当前草稿值，未保存内容也参与辅助）。 */
  buildInput: () => DeviationAiAssistInput
  /** 采纳建议时回调；载荷已按勾选过滤。 */
  onAdopt: (payload: DeviationAiAdoptPayload) => void
}) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<DeviationAiAssistResult | null>(null)
  // 勾选键规则：`item-0` / `personnel-2` / `step-1` / `hyp-0`。
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [adoptDescription, setAdoptDescription] = useState(true)

  const run = async () => {
    const input = buildInput()
    if (input.description.trim().length < 10) {
      message.warning('请先填写偏差描述（至少 10 个字）再使用 AI 辅助')
      return
    }
    setLoading(true)
    try {
      const response = await deviationAiAssist(input)
      if (!response.success) {
        message.warning(actionError(response))
        return
      }
      const data = response.data
      if (!data) {
        message.warning('AI 未返回建议，请重试')
        return
      }
      setResult(data)
      const defaults: Record<string, boolean> = {}
      if (data.kind === 'describe') {
        ;(data.items ?? []).forEach((_, index) => { defaults[`item-${index}`] = true })
        setAdoptDescription(true)
      } else if (data.kind === 'm1e') {
        Object.entries(data.checklists ?? {}).forEach(([key, questions]) =>
          (questions ?? []).forEach((_, index) => { defaults[`${key}-${index}`] = true }),
        )
      } else if (data.kind === 'why') {
        ;(data.steps ?? []).forEach((_, index) => { defaults[`step-${index}`] = true })
      } else {
        ;(data.hypotheses ?? []).forEach((_, index) => { defaults[`hyp-${index}`] = true })
      }
      setSelected(defaults)
      setOpen(true)
    } finally {
      setLoading(false)
    }
  }

  const toggle = (key: string) => {
    setSelected((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const adopt = () => {
    if (!result) return
    if (result.kind === 'describe') {
      const items = (result.items ?? [])
        .filter((_, index) => selected[`item-${index}`])
        .map((item) => ({ category: item.category, name: item.name, batch_no: item.batch_no ?? null }))
      if (!adoptDescription && items.length === 0) {
        message.warning('请至少勾选一项要采纳的内容')
        return
      }
      onAdopt({
        kind: 'describe',
        description: adoptDescription ? result.description ?? null : null,
        items,
      })
    } else if (result.kind === 'm1e') {
      const inserts: Partial<Record<string, string[]>> = {}
      Object.entries(result.checklists ?? {}).forEach(([key, questions]) => {
        const picked = (questions ?? []).filter((_, index) => selected[`${key}-${index}`])
        if (picked.length) inserts[key] = picked
      })
      if (Object.keys(inserts).length === 0) {
        message.warning('请至少勾选一个要插入的问题')
        return
      }
      onAdopt({ kind: 'm1e', inserts })
    } else if (result.kind === 'why') {
      const steps = (result.steps ?? []).filter((_, index) => selected[`step-${index}`])
      if (steps.length === 0) {
        message.warning('请至少勾选一步追问')
        return
      }
      onAdopt({ kind: 'why', steps })
    } else {
      const tests = (result.hypotheses ?? [])
        .filter((_, index) => selected[`hyp-${index}`])
        .map((item) => ({
          hypothesis: item.hypothesis,
          sample: item.sample ?? null,
          protocol: item.protocol ?? null,
          expected: item.expected ?? null,
        }))
      if (tests.length === 0) {
        message.warning('请至少勾选一条假设')
        return
      }
      onAdopt({ kind: 'hypothesis', tests })
    }
    setOpen(false)
    message.success('已填入 AI 建议，请检查后保存')
  }

  const modalTitle =
    kind === 'describe' ? 'AI 描述规范化建议'
    : kind === 'm1e' ? 'AI 调查问题清单'
    : kind === 'why' ? 'AI 5Why 追问建议'
    : 'AI 假设性检验草案'

  return (
    <>
      <Button
        type="text"
        size="small"
        icon={<RobotOutlined style={{ color: AI_COLOR }} />}
        loading={loading}
        onClick={() => void run()}
        style={{ color: AI_COLOR, paddingInline: 4 }}
      >
        {loading ? 'AI 生成中…' : label}
      </Button>
      <Modal
        open={open}
        title={<span><RobotOutlined style={{ color: AI_COLOR, marginRight: 8 }} />{modalTitle}</span>}
        width={720}
        okText="采纳所选"
        cancelText="取消"
        onOk={adopt}
        onCancel={() => setOpen(false)}
      >
        <Alert
          type="info"
          showIcon
          title="AI 建议仅供参考，请审核后采纳；正式保存仍按原流程执行。"
          style={{ marginBottom: 12 }}
        />
        {result?.kind === 'describe' && (
          <DescribePanel result={result} selected={selected} toggle={toggle} adoptDescription={adoptDescription} onToggleDescription={setAdoptDescription} />
        )}
        {result?.kind === 'm1e' && <M1ePanel result={result} selected={selected} toggle={toggle} />}
        {result?.kind === 'why' && <WhyPanel result={result} selected={selected} toggle={toggle} />}
        {result?.kind === 'hypothesis' && <HypothesisPanel result={result} selected={selected} toggle={toggle} />}
      </Modal>
    </>
  )
}

const blockStyle: CSSProperties = {
  border: '1px solid #e5e3df',
  borderRadius: 8,
  background: '#fafaf9',
  padding: '10px 12px',
  fontSize: 13,
  whiteSpace: 'pre-wrap',
  lineHeight: 1.7,
}

function DescribePanel({
  result,
  selected,
  toggle,
  adoptDescription,
  onToggleDescription,
}: {
  result: DeviationAiAssistResult
  selected: Record<string, boolean>
  toggle: (key: string) => void
  adoptDescription: boolean
  onToggleDescription: (value: boolean) => void
}) {
  const missing = result.missing_elements ?? []
  const items = result.items ?? []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Checkbox checked={adoptDescription} onChange={(e) => onToggleDescription(e.target.checked)}>
          用规范化描述替换原描述
        </Checkbox>
        <div style={blockStyle}>{result.description}</div>
      </div>
      {missing.length > 0 && (
        <Alert type="warning" showIcon title={`原描述疑似缺失以下要素：${missing.join('、')}`} />
      )}
      {items.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>识别的涉及对象</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {items.map((item, index) => (
              <div key={`item-${index}`} style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '8px 12px', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <Checkbox aria-label={`采纳 ${item.name}`} checked={Boolean(selected[`item-${index}`])} onChange={() => toggle(`item-${index}`)} style={{ marginTop: 2 }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Tag style={{ marginInlineEnd: 0 }}>{DEVIATION_ITEM_CATEGORY_LABEL[item.category]}</Tag>
                    <span style={{ fontWeight: 600 }}>{item.name}</span>
                    {item.batch_no && <span style={{ color: '#787671' }}>批号 {item.batch_no}</span>}
                    {item.match && (
                      <Tag color="success" style={{ marginInlineEnd: 0 }}>
                        主数据 {item.match.code} · {Math.round(item.match.confidence * 100)}%
                      </Tag>
                    )}
                  </div>
                  {item.evidence && <div style={{ color: '#787671', fontSize: 12 }}>依据：{item.evidence}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function M1ePanel({
  result,
  selected,
  toggle,
}: {
  result: DeviationAiAssistResult
  selected: Record<string, boolean>
  toggle: (key: string) => void
}) {
  const checklists = result.checklists ?? {}
  const keys = Object.keys(checklists).filter((key) => (checklists[key as keyof typeof checklists] ?? []).length > 0)
  if (keys.length === 0) {
    return <Alert type="info" title="AI 未生成调查问题，请补充描述后重试。" />
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ color: '#787671', fontSize: 12 }}>勾选的问题将以清单形式追加到对应「人机料法环」输入框末尾，不覆盖已填写内容。</div>
      {keys.map((key) => (
        <div key={key} style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '8px 12px' }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{M1E_LABELS[key] ?? key}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {(checklists[key as keyof typeof checklists] ?? []).map((question, index) => (
              <Checkbox key={`${key}-${index}`} checked={Boolean(selected[`${key}-${index}`])} onChange={() => toggle(`${key}-${index}`)}>
                {question}
              </Checkbox>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function WhyPanel({
  result,
  selected,
  toggle,
}: {
  result: DeviationAiAssistResult
  selected: Record<string, boolean>
  toggle: (key: string) => void
}) {
  const steps = result.steps ?? []
  if (steps.length === 0) {
    return <Alert type="info" title="AI 未生成追问建议，请补充直接原因后重试。" />
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ color: '#787671', fontSize: 12 }}>勾选的步骤将填入 5Why 链中未完成的行（问题或回答为空），已完整的行保持不变。</div>
      {steps.map((step, index) => (
        <div key={`step-${index}`} style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '8px 12px', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Checkbox aria-label={step.question} checked={Boolean(selected[`step-${index}`])} onChange={() => toggle(`step-${index}`)} style={{ marginTop: 2 }} />
          <div>
            <div style={{ fontWeight: 600 }}>{index + 1}. {step.question}</div>
            <div style={{ color: '#37352f', fontSize: 13, whiteSpace: 'pre-wrap' }}>{step.answer}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function HypothesisPanel({
  result,
  selected,
  toggle,
}: {
  result: DeviationAiAssistResult
  selected: Record<string, boolean>
  toggle: (key: string) => void
}) {
  const hypotheses = result.hypotheses ?? []
  if (hypotheses.length === 0) {
    return <Alert type="info" title="AI 未生成假设草案，请补充调查内容后重试。" />
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ color: '#787671', fontSize: 12 }}>勾选的假设将追加为新的假设性检验记录，检验结果与结论仍需人工填写。</div>
      {hypotheses.map((item, index) => (
        <div key={`hyp-${index}`} style={{ border: '1px solid #e5e3df', borderRadius: 8, padding: '8px 12px', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <Checkbox aria-label={item.hypothesis} checked={Boolean(selected[`hyp-${index}`])} onChange={() => toggle(`hyp-${index}`)} style={{ marginTop: 2 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ fontWeight: 600 }}>{item.hypothesis}</div>
            {item.sample && <div style={{ fontSize: 13, color: '#787671' }}>样品：{item.sample}</div>}
            {item.protocol && <div style={{ fontSize: 13, color: '#787671' }}>方案：{item.protocol}</div>}
            {item.expected && <div style={{ fontSize: 13, color: '#787671' }}>预期：{item.expected}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 把 AI 建议的 m1e 问题清单追加到对应字段的现有文本之后（不覆盖、不重复追加）。 */
export function appendM1eQuestions(
  form: FormInstance,
  inserts: Partial<Record<string, string[]>>,
): void {
  Object.entries(inserts).forEach(([key, questions]) => {
    if (!questions?.length) return
    const field = `m1e_${key}`
    const current = (form.getFieldValue(field) as string | undefined) ?? ''
    const lines = current.split('\n')
    // 重新生成时按「去掉序号后的整行」去重，避免同一问题追加两遍。
    const existing = new Set(lines.map((line) => line.replace(/^\d+\.\s*/, '').trim()).filter(Boolean))
    const fresh = questions.filter((question) => !existing.has(question.trim()))
    if (!fresh.length) return
    const start = Math.max(0, ...lines.map((line) => Number(line.match(/^(\d+)\.\s/)?.[1] ?? 0))) + 1
    const block = fresh.map((question, index) => `${start + index}. ${question}`).join('\n')
    const next = current.trim() ? `${current.trimEnd()}\n${block}` : block
    form.setFieldValue(field, next.slice(0, 8000))
  })
}

/** 把 AI 建议的追问链填入 why_chain 中空行，不足追加；已填行与重复问题保持不变。 */
export function fillWhySteps(form: FormInstance, steps: WhyStep[]): void {
  const chain: Array<Partial<WhyStep>> = (form.getFieldValue('why_chain') as Array<Partial<WhyStep>> | undefined) ?? []
  const merged = [...chain]
  for (const step of steps) {
    if (merged.some((row) => row.question?.trim() === step.question.trim())) continue
    const blankIndex = merged.findIndex((row) => !row.question?.trim() || !row.answer?.trim())
    if (blankIndex >= 0) {
      merged[blankIndex] = { question: step.question, answer: step.answer }
    } else if (merged.length < 20) {
      merged.push({ question: step.question, answer: step.answer })
    }
  }
  form.setFieldValue('why_chain', merged.slice(0, 20))
}

/** 把 AI 假设草案追加为新的假设性检验行；重复生成时跳过已有假设。 */
export function appendHypothesisTests(
  form: FormInstance,
  tests: Array<{ hypothesis: string; sample: string | null; protocol: string | null; expected: string | null }>,
): void {
  const current = (form.getFieldValue('hypothesis_tests') as Array<Record<string, unknown>> | undefined) ?? []
  const existing = new Set(current.map((row) => String(row.hypothesis ?? '').trim()))
  const rows = tests
    .filter((test) => !existing.has(test.hypothesis.trim()))
    .map((test) => ({
      hypothesis: test.hypothesis,
      sample: test.sample ?? undefined,
      protocol: test.protocol ?? undefined,
      expected: test.expected ?? undefined,
    }))
  if (!rows.length) return
  form.setFieldValue('hypothesis_tests', [...current, ...rows].slice(0, 50))
}

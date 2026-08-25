'use client'

// 通用步骤向导：动态渲染工具声明的输入，逐步执行，展示结果。
// 步骤导航为自定义「步骤轨道」：序号圆点 + 步骤名，完成态填充工具识别色，
// 已完成步骤可点击回退重跑；编号承载真实流程顺序。
// 状态全在客户端；execution_id 写入 URL query 供刷新恢复（页面级，不重建会话）。
// 表单用 antd Form（项目实际惯例，未安装 react-hook-form）。

import { Fragment, useState } from 'react'
import Link from 'next/link'
import { Alert, Button, Checkbox, Form, Input, InputNumber, Select, Upload } from 'antd'
import { ArrowLeftOutlined, CheckOutlined, DownloadOutlined, InboxOutlined, SettingOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd'

import { runToolStep } from '@/actions/toolbox'
import { fetchFileDownload } from '@/lib/api/toolbox'
import type { StepRunData, ToolInfo } from '@/types/toolbox'
import { toolTint } from './toolTint'

const { TextArea } = Input
type ToolInput = ToolInfo['steps'][number]['inputs'][number]


function resultUrl(fileId: string, executionId: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  return `${base}/api/v1/toolbox/executions/${executionId}/files/${fileId}`
}

/** 结果区渲染约定：text → 文本块；rows+columns → 表格；csv_file/含 file_id → 下载按钮（两者同框渲染不互斥）；其余 → 键值。 */
function ResultView({ data, executionId }: { data: Record<string, unknown>; executionId: string }) {
  if (data.text != null) {
    return <pre className="whitespace-pre-wrap rounded-lg bg-[var(--color-surface)] p-4 text-[13px] leading-relaxed text-[var(--color-charcoal)]">{String(data.text)}</pre>
  }
  const fileRefs = Object.entries(data).filter(
    ([, v]) => typeof v === 'object' && v !== null && (v as Record<string, unknown>).file_id,
  )
  const hasTable = Array.isArray(data.rows) && Array.isArray(data.columns)
  if (!hasTable && fileRefs.length === 0) {
    return (
      <dl className="space-y-1 rounded-lg bg-[var(--color-surface)] p-4 text-[13px]">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <dt className="shrink-0 font-medium text-[var(--color-charcoal)]">{k}</dt>
            <dd className="text-[var(--color-slate)] break-all">{JSON.stringify(v)}</dd>
          </div>
        ))}
      </dl>
    )
  }
  const columns = data.columns as string[]
  const rows = data.rows as unknown[][]
  return (
    <div className="space-y-4">
      {hasTable && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-hairline)]">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-[var(--color-surface)]">
                {columns.map((c) => (
                  <th key={c} className="px-3 py-2 text-left font-medium text-[var(--color-charcoal)]">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-t border-[var(--color-hairline-soft)]">
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-2 text-[var(--color-slate)]">{String(cell ?? '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {fileRefs.length > 0 && (
        <div className="space-y-2">
          {fileRefs.map(([key, v]) => {
            const ref = v as { file_id: string; filename?: string }
            return (
              <Button
                key={key}
                icon={<DownloadOutlined />}
                onClick={async () => {
                  const blob = await fetchFileDownload(resultUrl(ref.file_id, executionId))
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = ref.filename || '下载文件'
                  a.click()
                  setTimeout(() => URL.revokeObjectURL(url), 1000)
                }}
              >
                下载 {ref.filename || key}
              </Button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function ToolRunner({
  tool,
  initialExecutionId,
  initialOutputs = {},
  initialFileIds = {},
}: {
  tool: ToolInfo
  initialExecutionId?: string | null
  initialOutputs?: Record<string, Record<string, unknown>>
  initialFileIds?: Record<string, string[]>
}) {
  const [stepIndex, setStepIndex] = useState(0)
  const [executionId, setExecutionId] = useState<string | null>(initialExecutionId ?? null)
  // 刷新恢复：outputs → StepRunData；file_ids 从 initialFileIds 按 input_key 回填，
  // 其余步骤的 file_ids 一律来自当次执行结果（避免 stale 引用复活）
  const [stepResults, setStepResults] = useState<Record<string, StepRunData>>(() => {
    const map: Record<string, StepRunData> = {}
    for (const [sid, data] of Object.entries(initialOutputs)) {
      const fileIds: Record<string, string[]> = {}
      for (const inp of tool.steps.find((s) => s.id === sid)?.inputs ?? []) {
        if (inp.type === 'file' && !inp.from_step && initialFileIds[inp.key]) {
          fileIds[inp.key] = initialFileIds[inp.key]
        }
      }
      map[sid] = { execution_id: initialExecutionId ?? '', data, file_ids: fileIds }
    }
    return map
  })
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()

  const step = tool.steps[stepIndex]
  const currentResult = stepResults[step.id]
  const isLast = stepIndex === tool.steps.length - 1

  // 工具识别色：由工具 id 稳定映射，卡片与执行页同色
  const { ink: tintInk } = toolTint(tool.id)

  /** from_step 文件引用解析：只取引用步骤当次执行的 file_ids（刷新恢复时已由 initialFileIds 回填）。 */
  const resolveFileIds = (inp: ToolInput): string[] =>
    stepResults[inp.from_step!]?.file_ids?.[inp.from_key!] ?? []

  // 步骤点击：回退时清空该步及其后结果（重跑）
  const handleStepClick = (idx: number) => {
    if (running) return
    if (idx >= stepIndex || !executionId) return
    setStepIndex(idx)
    setStepResults((prev) => {
      const kept: Record<string, StepRunData> = {}
      for (let i = 0; i < idx; i++) {
        const sid = tool.steps[i].id
        if (prev[sid]) kept[sid] = prev[sid]
      }
      return kept
    })
    form.resetFields()
    setError(null)
  }

  const onFinish = async (values: Record<string, unknown>) => {
    if (running) return
    setRunning(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.set('tool_id', tool.id)
      fd.set('step_id', step.id)
      if (executionId) fd.set('execution_id', executionId)
      const params: Record<string, unknown> = {}
      for (const inp of step.inputs) {
        if (inp.type === 'file') {
          if (inp.from_step && inp.from_key) {
            const fids = resolveFileIds(inp)
            if (fids.length > 0) params[inp.key] = { file_ids: fids }
            continue
          }
          const files = (values[inp.key] as UploadFile[] | undefined) ?? []
          for (const f of files) {
            if (f.originFileObj) fd.append(inp.key, f.originFileObj, f.name)
          }
        } else if (inp.type === 'boolean') {
          params[inp.key] = Boolean(values[inp.key])
        } else {
          const v = values[inp.key]
          if (v !== undefined && v !== null && v !== '') params[inp.key] = v
        }
      }
      fd.set('params', JSON.stringify(params))
      const result = await runToolStep(fd)
      setExecutionId(result.execution_id)
      // 直接改写 URL 持久化 execution，不触发 Next.js 导航与服务端重渲染
      window.history.replaceState(null, '', `/toolbox/${tool.id}?execution=${result.execution_id}`)
      setStepResults((prev) => ({ ...prev, [step.id]: result }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '执行失败')
    } finally {
      setRunning(false)
    }
  }

  const renderInput = (inp: ToolInput) => {
    const rules = inp.required && !(inp.type === 'file' && inp.from_step)
      ? [{ required: true, message: `${inp.type === 'file' ? '请上传' : '请填写'}${inp.label}` }]
      : undefined
    const label = (
      <span>
        {inp.label}
        {inp.required && <span className="ml-1 text-[var(--color-semantic-error)]">*</span>}
      </span>
    )
    if (inp.type === 'file') {
      if (inp.from_step && inp.from_key) {
        return (
          <div className="text-[13px] text-[var(--color-slate)]">
            已引用「{tool.steps.find((s) => s.id === inp.from_step)?.name}」步骤上传的文件
            {resolveFileIds(inp).length > 0 ? '' : '（请先完成该步骤）'}
          </div>
        )
      }
      return (
        <Form.Item name={inp.key} label={label} rules={rules} valuePropName="fileList" getValueFromEvent={(e) => e?.fileList ?? []}>
          <Upload.Dragger multiple={inp.multiple} accept={inp.accept ?? undefined} beforeUpload={() => false}>
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">点击或拖拽上传{inp.multiple ? '（可多选）' : ''}</p>
            {inp.accept && <p className="ant-upload-hint">支持格式：{inp.accept}</p>}
          </Upload.Dragger>
        </Form.Item>
      )
    }
    if (inp.type === 'textarea') {
      return (
        <Form.Item name={inp.key} label={label} rules={rules}>
          <TextArea rows={6} placeholder={inp.placeholder ?? undefined} />
        </Form.Item>
      )
    }
    if (inp.type === 'boolean') {
      return (
        <Form.Item name={inp.key} valuePropName="checked">
          <Checkbox>{inp.label}</Checkbox>
        </Form.Item>
      )
    }
    if (inp.type === 'number') {
      return (
        <Form.Item name={inp.key} label={label} rules={rules}>
          <InputNumber style={{ width: 200 }} />
        </Form.Item>
      )
    }
    if (inp.type === 'select') {
      return (
        <Form.Item name={inp.key} label={label} rules={rules}>
          <Select style={{ width: 240 }} options={(inp.options ?? []).map((o) => ({ label: o, value: o }))} />
        </Form.Item>
      )
    }
    return (
      <Form.Item name={inp.key} label={label} rules={rules}>
        <Input placeholder={inp.placeholder ?? undefined} />
      </Form.Item>
    )
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <Link
        href="/toolbox"
        className="inline-flex items-center gap-1 text-[13px] text-[var(--color-slate)] hover:text-[var(--color-primary)] transition-colors"
      >
        <ArrowLeftOutlined />
        返回工具箱
      </Link>
      <div className="mt-3 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-semibold text-[var(--color-charcoal)]">{tool.name}</h1>
          <p className="mt-1 text-[13px] text-[var(--color-slate)]">{tool.description}</p>
        </div>
        {tool.config_schema.length > 0 && (
          <Link
            href={`/toolbox/config/${tool.id}`}
            className="mt-1 inline-flex shrink-0 items-center gap-1 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-[13px] text-[var(--color-charcoal)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] transition-colors"
          >
            <SettingOutlined />
            配置
          </Link>
        )}
      </div>

      {/* 步骤轨道：编号承载真实流程顺序；完成态填充工具识别色，当前步骤 tint 描边 */}
      <div className="mt-6 flex items-center gap-0 overflow-x-auto pb-1">
        {tool.steps.map((s, i) => {
          const done = Boolean(stepResults[s.id])
          const current = i === stepIndex
          return (
            <Fragment key={s.id}>
              {i > 0 && <span className="mx-2 h-px w-8 shrink-0 bg-[var(--color-hairline-strong)]" />}
              <button
                type="button"
                onClick={() => handleStepClick(i)}
                disabled={!done || current || running}
                className={`flex shrink-0 items-center gap-2 rounded-full py-1 pr-3 transition-colors ${
                  current ? '' : done ? 'cursor-pointer hover:bg-[var(--color-surface)]' : 'cursor-default'
                }`}
              >
                <span
                  className="flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-semibold"
                  style={
                    done
                      ? { background: tintInk, color: '#ffffff' }
                      : current
                        ? { border: `2px solid ${tintInk}`, color: tintInk }
                        : { border: '2px solid var(--color-hairline-strong)', color: 'var(--color-stone)' }
                  }
                >
                  {done ? <CheckOutlined style={{ fontSize: 11 }} /> : i + 1}
                </span>
                <span
                  className={`text-[13px] ${
                    current ? 'font-semibold text-[var(--color-charcoal)]' : done ? 'text-[var(--color-slate)]' : 'text-[var(--color-stone)]'
                  }`}
                >
                  {s.name}
                </span>
              </button>
            </Fragment>
          )
        })}
      </div>

      <div className="mt-5 rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-6">
        <h2 className="text-[15px] font-semibold text-[var(--color-charcoal)]">
          步骤 {stepIndex + 1}：{step.name}
        </h2>
        <p className="mt-1 text-[13px] text-[var(--color-slate)]">{step.description}</p>
        {error && <Alert className="mt-4" type="error" title={error} showIcon />}
        <Form form={form} className="mt-4" layout="vertical" onFinish={onFinish}>
          {step.inputs.map((inp) => <Fragment key={inp.key}>{renderInput(inp)}</Fragment>)}
          <div className="flex gap-3">
            <Button type="primary" htmlType="submit" loading={running}>
              {currentResult ? '重新执行' : '执行'}
            </Button>
            {currentResult && !isLast && (
              <Button
                onClick={() => {
                  setStepIndex((i) => i + 1)
                  form.resetFields()
                  setError(null)
                }}
              >
                下一步
              </Button>
            )}
          </div>
        </Form>
        {currentResult && (
          <div className="mt-6">
            <h3 className="mb-2 text-[13px] font-semibold text-[var(--color-charcoal)]">本步结果</h3>
            <ResultView data={currentResult.data} executionId={currentResult.execution_id} />
          </div>
        )}
      </div>
    </div>
  )
}

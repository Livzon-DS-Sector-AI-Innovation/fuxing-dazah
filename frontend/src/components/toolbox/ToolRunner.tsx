'use client'

// 通用步骤向导：动态渲染工具声明的输入，逐步执行，展示结果。
// 表单布局：文件输入聚合成「材料槽」区——tint 虚线插槽，上传后实色填充（本页签名元素）；
// 非文件输入为参数区，show_when 声明驱动条件显示（如核对方式切换月份/日期字段），
// month/date 类型渲染 DatePicker，提交时格式化为字符串，后端 params 结构不变。
// 步骤导航为自定义「步骤轨道」：序号圆点 + 步骤名，完成态填充工具识别色，
// 已完成步骤可点击回退重跑；编号承载真实流程顺序。
// 状态全在客户端；execution_id 写入 URL query 供刷新恢复（页面级，不重建会话）。
// 表单用 antd Form（项目实际惯例，未安装 react-hook-form）。

import { Fragment, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Alert,
  Button,
  Checkbox,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
  Upload,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  DownloadOutlined,
  FileTextOutlined,
  InboxOutlined,
  SettingOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { FormInstance, UploadFile } from 'antd'
import type { Dayjs } from 'dayjs'

import { runToolStep } from '@/actions/toolbox'
import { fetchFileDownload } from '@/lib/api/toolbox'
import type { StepRunData, ToolInfo } from '@/types/toolbox'
import { toolTint } from './toolTint'

const { TextArea } = Input
type ToolInput = ToolInfo['steps'][number]['inputs'][number]

/** 结果区数字字段的中文标签；key 不在表内则不渲染统计条。 */
const STAT_LABELS: Record<string, string> = {
  anomaly_count: '人存在异常记录',
  remaining: '人仍有异常',
  written: '条记录已写入',
  deleted: '条旧记录已清除',
}

function resultUrl(fileId: string, executionId: string) {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  return `${base}/api/v1/toolbox/executions/${executionId}/files/${fileId}`
}

/** 分区小标题：短横线 + 微标签。 */
function SectionLabel({ children }: { children: string }) {
  return (
    <span className="flex items-center gap-2">
      <span className="h-px w-3 bg-[var(--color-hairline-strong)]" />
      <span className="text-[11px] font-semibold tracking-[1px] text-[var(--color-steel)]">{children}</span>
    </span>
  )
}

/** 统计条：结果中的数字字段（有中文标签的）渲染成 tint 大数字卡。 */
function StatStrip({ data, tintBg, tintInk }: { data: Record<string, unknown>; tintBg: string; tintInk: string }) {
  const stats = Object.entries(data).filter(([k, v]) => typeof v === 'number' && STAT_LABELS[k])
  if (stats.length === 0) return null
  return (
    <div className="mb-4 flex flex-wrap gap-3">
      {stats.map(([k, v]) => (
        <div key={k} className="flex items-baseline gap-2 rounded-lg px-4 py-3" style={{ background: tintBg }}>
          <span className="text-[24px] font-semibold leading-none" style={{ color: tintInk }}>{String(v)}</span>
          <span className="text-[13px]" style={{ color: tintInk }}>{STAT_LABELS[k]}</span>
        </div>
      ))}
    </div>
  )
}

/** 结果区渲染约定：text → 文本块；rows+columns → 表格；csv_file/含 file_id → 下载按钮（两者同框渲染不互斥）；其余 → 键值。 */
function ResultView({
  data,
  executionId,
  tintBg,
  tintInk,
}: {
  data: Record<string, unknown>
  executionId: string
  tintBg: string
  tintInk: string
}) {
  const fileRefs = Object.entries(data).filter(
    ([, v]) => typeof v === 'object' && v !== null && (v as Record<string, unknown>).file_id,
  )
  const hasTable = Array.isArray(data.rows) && Array.isArray(data.columns)
  let body: React.ReactNode
  if (data.text != null) {
    body = <pre className="whitespace-pre-wrap rounded-lg bg-[var(--color-surface)] p-4 text-[13px] leading-relaxed text-[var(--color-charcoal)]">{String(data.text)}</pre>
  } else if (!hasTable && fileRefs.length === 0) {
    body = (
      <dl className="space-y-1 rounded-lg bg-[var(--color-surface)] p-4 text-[13px]">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <dt className="shrink-0 font-medium text-[var(--color-charcoal)]">{k}</dt>
            <dd className="text-[var(--color-slate)] break-all">{JSON.stringify(v)}</dd>
          </div>
        ))}
      </dl>
    )
  } else {
    const columns = data.columns as string[]
    const rows = data.rows as unknown[][]
    body = (
      <Fragment>
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
      </Fragment>
    )
  }
  return (
    <div className="space-y-4">
      <StatStrip data={data} tintBg={tintBg} tintInk={tintInk} />
      {body}
    </div>
  )
}

/** 材料槽：文件输入的签名式上传格。空槽为 tint 虚线插槽，上传后实色填充并展示文件名。 */
function MaterialSlot({
  input,
  files,
  tintBg,
  tintInk,
  form,
}: {
  input: ToolInput
  files: UploadFile[]
  tintBg: string
  tintInk: string
  form: FormInstance
}) {
  const filled = files.length > 0
  const removeFile = (e: React.MouseEvent, uid: string) => {
    e.stopPropagation()
    form.setFieldValue(input.key, files.filter((f) => f.uid !== uid))
  }
  return (
    <Form.Item
      name={input.key}
      valuePropName="fileList"
      getValueFromEvent={(e) => e?.fileList ?? []}
      rules={
        input.required
          ? [
              {
                // 用 validator 而非 required：空数组也是 truthy，required 规则拦不住「选过再删光」
                validator: (_: unknown, value: UploadFile[] | undefined) =>
                  value && value.length > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error(`请上传${input.label}`)),
              },
            ]
          : undefined
      }
    >
      <Upload.Dragger
        multiple={input.multiple}
        accept={input.accept ?? undefined}
        beforeUpload={() => false}
        showUploadList={false}
        className="[&_.ant-upload-drag]:border-transparent! [&_.ant-upload-drag]:bg-transparent! [&_.ant-upload-drag:hover]:border-transparent! [&_.ant-upload-drag.ant-upload-drag-hover]:border-transparent! [&_.ant-upload-btn]:p-0!"
      >
        <div
          className="rounded-xl border border-dashed px-4 text-center transition-colors"
          style={{ background: filled ? tintBg : 'transparent', borderColor: filled ? 'transparent' : `${tintInk}40` }}
        >
          {filled ? (
            <div className="space-y-1 py-2">
              {files.map((f) => (
                <div key={f.uid} className="flex items-center justify-center gap-2">
                  <FileTextOutlined style={{ color: tintInk }} />
                  <span className="max-w-[75%] truncate text-[13px] font-medium" style={{ color: tintInk }}>
                    {f.name}
                  </span>
                  <button
                    type="button"
                    aria-label={`移除 ${f.name}`}
                    onClick={(e) => removeFile(e, f.uid)}
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px]"
                    style={{ background: tintInk, color: '#fff' }}
                  >
                    <CloseOutlined />
                  </button>
                </div>
              ))}
              <p className="text-[12px]" style={{ color: tintInk, opacity: 0.7 }}>
                点击更换文件
              </p>
            </div>
          ) : (
            <div className="py-4">
              <InboxOutlined className="text-[20px]" style={{ color: tintInk }} />
              <p className="mt-2 text-[13px] font-medium" style={{ color: tintInk }}>
                {input.label}
                {input.required && <span className="ml-0.5 text-[var(--color-semantic-error)]">*</span>}
              </p>
              <p className="mt-1 text-[12px]" style={{ color: tintInk, opacity: 0.7 }}>点击或拖拽上传</p>
              {input.accept && (
                <p className="mt-1 text-[11px]" style={{ color: tintInk, opacity: 0.5 }}>
                  {input.accept.split(',').map((s) => s.trim().replace(/^\./, '')).join(' / ')}
                </p>
              )}
            </div>
          )}
        </div>
      </Upload.Dragger>
    </Form.Item>
  )
}

/** 引用材料：展示从上游步骤引用的文件（只读，本步骤不重新上传）。 */
function ReferenceMaterial({
  input,
  filename,
  fromStepName,
  resolved,
  tintBg,
  tintInk,
}: {
  input: ToolInput
  filename?: string
  fromStepName: string
  resolved: boolean
  tintBg: string
  tintInk: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-3 py-2.5" style={{ background: tintBg }}>
      <FileTextOutlined style={{ color: tintInk }} />
      <span className="text-[13px] font-medium" style={{ color: tintInk }}>{input.label}</span>
      {filename && <span className="text-[13px]" style={{ color: tintInk }}>{filename}</span>}
      <span className="text-[12px]" style={{ color: tintInk, opacity: 0.7 }}>
        来自「{fromStepName}」{resolved ? '' : '（请先完成该步骤）'}
      </span>
    </div>
  )
}

export function ToolRunner({
  tool,
  initialExecutionId,
  initialOutputs = {},
  initialFileIds = {},
  initialFileNames = {},
  initialWarning = null,
}: {
  tool: ToolInfo
  initialExecutionId?: string | null
  initialOutputs?: Record<string, Record<string, unknown>>
  initialFileIds?: Record<string, string[]>
  initialFileNames?: Record<string, string>
  initialWarning?: string | null
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
  // 上传文件名（input_key → 文件名）：本 session 执行时记录，下游步骤引用芯片展示；刷新恢复时由 initialFileNames 提供
  const [uploadedNames, setUploadedNames] = useState<Record<string, string>>(initialFileNames)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 非致命提示：恢复失败（initialWarning）与执行成功但记录落库失败（result.warning）
  const [warning, setWarning] = useState<string | null>(initialWarning ?? null)
  const [form] = Form.useForm()

  const step = tool.steps[stepIndex]
  const currentResult = stepResults[step.id]
  const isLast = stepIndex === tool.steps.length - 1

  // 工具识别色：由工具 id 稳定映射，卡片与执行页同色
  const { bg: tintBg, ink: tintInk } = toolTint(tool.id)

  // 全量表单值：驱动 show_when 条件显示（字段少，整表 watch 足够）
  const watched = Form.useWatch([], form)

  /** show_when 判定：声明 (key, value) 命中（或未声明）时该输入可见。 */
  const visibleOf = (inp: ToolInput, vals: Record<string, unknown> | undefined) =>
    !inp.show_when || String(vals?.[inp.show_when[0]] ?? '') === inp.show_when[1]

  // 声明 default → initialValues（resetFields 后也回到默认值，如核对方式默认「按月核对」）
  const initialValues = useMemo(() => {
    const map: Record<string, unknown> = {}
    for (const s of tool.steps) {
      for (const inp of s.inputs) {
        if (inp.default !== undefined && inp.default !== null) map[inp.key] = inp.default
      }
    }
    return map
  }, [tool])

  // watched 首帧为 undefined（Form 未挂载），用 initialValues 兜底避免日期字段闪现
  const visibleInputs = step.inputs.filter((inp) => visibleOf(inp, watched ?? initialValues))
  const fileInputs = step.inputs.filter((inp) => inp.type === 'file' && !inp.from_step)
  const refInputs = step.inputs.filter((inp) => inp.type === 'file' && inp.from_step)
  const paramInputs = visibleInputs.filter((inp) => inp.type !== 'file')

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
    setWarning(null)
  }

  const onFinish = async (values: Record<string, unknown>) => {
    if (running) return
    setRunning(true)
    setError(null)
    setWarning(null)
    try {
      const fd = new FormData()
      fd.set('tool_id', tool.id)
      fd.set('step_id', step.id)
      if (executionId) fd.set('execution_id', executionId)
      const params: Record<string, unknown> = {}
      for (const inp of step.inputs) {
        if (!visibleOf(inp, values)) continue // 隐藏字段不提交，避免切换核对方式后残留旧值
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
        } else if (inp.type === 'month' || inp.type === 'date') {
          const v = values[inp.key] as Dayjs | undefined
          if (v) params[inp.key] = inp.type === 'month' ? v.format('YYYY-MM') : v.format('YYYY-MM-DD')
        } else {
          const v = values[inp.key]
          if (v !== undefined && v !== null && v !== '') params[inp.key] = v
        }
      }
      fd.set('params', JSON.stringify(params))
      const result = await runToolStep(fd)
      setExecutionId(result.execution_id)
      setWarning(result.warning ?? null)
      // 直接改写 URL 持久化 execution，不触发 Next.js 导航与服务端重渲染
      window.history.replaceState(null, '', `/toolbox/${tool.id}?execution=${result.execution_id}`)
      setStepResults((prev) => ({ ...prev, [step.id]: result }))
      // 记录本步上传的文件名，供下游步骤引用芯片展示
      const names: Record<string, string> = {}
      for (const inp of fileInputs) {
        const files = (values[inp.key] as UploadFile[] | undefined) ?? []
        if (files.length > 0) names[inp.key] = files.map((f) => f.name).join('、')
      }
      if (Object.keys(names).length > 0) setUploadedNames((prev) => ({ ...prev, ...names }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '执行失败')
    } finally {
      setRunning(false)
    }
  }

  const labelOf = (inp: ToolInput) => (
    <span>
      {inp.label}
      {inp.required && <span className="ml-1 text-[var(--color-semantic-error)]">*</span>}
    </span>
  )
  const verbOf = (inp: ToolInput) =>
    inp.type === 'select' || inp.type === 'month' || inp.type === 'date' ? '选择' : '填写'

  const renderParam = (inp: ToolInput) => {
    const rules = inp.required ? [{ required: true, message: `请${verbOf(inp)}${inp.label}` }] : undefined
    if (inp.type === 'select' && (inp.options?.length ?? 0) <= 3) {
      // 少量选项用 Segmented 分段控件（整行展示，切换直观）
      return (
        <Form.Item className="sm:col-span-2" name={inp.key} label={labelOf(inp)} rules={rules}>
          <Segmented block options={inp.options ?? []} />
        </Form.Item>
      )
    }
    if (inp.type === 'select') {
      return (
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules}>
          <Select style={{ width: 240 }} options={(inp.options ?? []).map((o) => ({ label: o, value: o }))} />
        </Form.Item>
      )
    }
    if (inp.type === 'month' || inp.type === 'date') {
      return (
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules}>
          <DatePicker
            picker={inp.type === 'month' ? 'month' : undefined}
            format={inp.type === 'month' ? 'YYYY-MM' : 'YYYY-MM-DD'}
            placeholder={inp.placeholder ?? undefined}
            className="w-full"
          />
        </Form.Item>
      )
    }
    if (inp.type === 'textarea') {
      return (
        <Form.Item className="sm:col-span-2" name={inp.key} label={labelOf(inp)} rules={rules}>
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
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules}>
          <InputNumber style={{ width: '100%' }} />
        </Form.Item>
      )
    }
    return (
      <Form.Item name={inp.key} label={labelOf(inp)} rules={rules}>
        <Input placeholder={inp.placeholder ?? undefined} />
      </Form.Item>
    )
  }

  // 材料槽网格随文件数自适应：1 个居中窄槽、2/3 个并排
  const fileGridCls =
    fileInputs.length === 1
      ? 'max-w-sm'
      : fileInputs.length === 2
        ? 'sm:grid-cols-2'
        : 'sm:grid-cols-3'

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
        {tool.config_schema.length > 0 && tool.can_config && (
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
        {warning && <Alert className="mt-4" type="warning" title={warning} showIcon />}
        <Form form={form} className="mt-4" layout="vertical" initialValues={initialValues} onFinish={onFinish}>
          {fileInputs.length > 0 && (
            <section>
              <SectionLabel>上传材料</SectionLabel>
              <div className={`mt-3 grid grid-cols-1 gap-3 ${fileGridCls}`}>
                {fileInputs.map((inp) => (
                  <MaterialSlot
                    key={inp.key}
                    input={inp}
                    files={(watched?.[inp.key] as UploadFile[] | undefined) ?? []}
                    tintBg={tintBg}
                    tintInk={tintInk}
                    form={form}
                  />
                ))}
              </div>
            </section>
          )}
          {refInputs.length > 0 && (
            <section className="mt-5 max-w-xl">
              <SectionLabel>引用材料</SectionLabel>
              <div className="mt-3 space-y-2">
                {refInputs.map((inp) => (
                  <ReferenceMaterial
                    key={inp.key}
                    input={inp}
                    filename={uploadedNames[inp.key]}
                    fromStepName={tool.steps.find((s) => s.id === inp.from_step)?.name ?? inp.from_step ?? ''}
                    resolved={resolveFileIds(inp).length > 0}
                    tintBg={tintBg}
                    tintInk={tintInk}
                  />
                ))}
              </div>
            </section>
          )}
          {paramInputs.length > 0 && (
            <section className="mt-5 max-w-xl">
              <SectionLabel>参数</SectionLabel>
              <div className="mt-3 grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {paramInputs.map((inp) => (
                  <Fragment key={inp.key}>{renderParam(inp)}</Fragment>
                ))}
              </div>
            </section>
          )}
          {step.inputs.length === 0 && (
            <div className="mt-5 flex max-w-xl items-start gap-2.5 rounded-lg px-4 py-3" style={{ background: tintBg }}>
              <WarningOutlined className="mt-0.5" style={{ color: tintInk }} />
              <p className="text-[13px] leading-relaxed" style={{ color: tintInk }}>{step.description}</p>
            </div>
          )}
          <div className="mt-6 flex gap-3">
            <Button type="primary" htmlType="submit" loading={running}>
              {step.inputs.length === 0
                ? currentResult
                  ? `重新${step.name}`
                  : step.name
                : currentResult
                  ? '重新执行'
                  : '执行'}
            </Button>
            {currentResult && !isLast && (
              <Button
                onClick={() => {
                  setStepIndex((i) => i + 1)
                  form.resetFields()
                  setError(null)
                  setWarning(null)
                }}
              >
                下一步
              </Button>
            )}
          </div>
        </Form>
        {currentResult && (
          <div className="mt-6 border-t border-[var(--color-hairline-soft)] pt-5">
            <h3 className="mb-3 text-[13px] font-semibold text-[var(--color-charcoal)]">本步结果</h3>
            <ResultView data={currentResult.data} executionId={currentResult.execution_id} tintBg={tintBg} tintInk={tintInk} />
          </div>
        )}
      </div>
    </div>
  )
}

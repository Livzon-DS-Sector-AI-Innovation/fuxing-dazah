'use client'

// 通用步骤向导：动态渲染工具声明的输入，逐步执行，展示结果。
// 页面骨架：顶栏（返回/配置，工具身份已在首页卡片展示不再重复）
// → 最近执行（白底卡片 + 状态徽标）→ 步骤轨道 → 工作卡（页面阴影锚点，眉标步骤头 + 分区表单）。
// 表单布局：文件输入聚合成「材料槽」区——tint 虚线插槽，上传后实色填充（本页签名元素）；
// 非文件输入为参数区，show_when 声明驱动条件显示（如核对方式切换月份/日期字段），
// month/date 类型渲染 DatePicker，提交时格式化为字符串，后端 params 结构不变。
// 步骤导航为自定义「步骤轨道」：序号圆点 + 步骤名，完成态填充工具识别色，
// 已完成步骤可点击回退重跑；编号承载真实流程顺序。
// 状态全在客户端；execution_id 写入 URL query 供刷新恢复（页面级，不重建会话）。
// 后台执行工具（background）：run 返回 running 后每 1.5s 轮询会话状态，
// 渲染 tint 进度条，done/failed 时落结果或报错；刷新时若任务仍在跑则恢复轮询。
// 表单用 antd Form（项目实际惯例，未安装 react-hook form）。

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  Alert,
  Button,
  Checkbox,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Progress,
  Segmented,
  Select,
  Upload,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  DownloadOutlined,
  FileTextOutlined,
  InboxOutlined,
  RightOutlined,
  SettingOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import type { FormInstance, UploadFile } from 'antd'
import type { Dayjs } from 'dayjs'

import { runToolStep } from '@/actions/toolbox'
import { fetchExecutionState, fetchFileDownload } from '@/lib/api/toolbox'
import type { ExecutionInfo, ExecutionSummaryInfo, StepProgress, StepRunData, ToolInfo } from '@/types/toolbox'
import { toolTint } from './toolTint'
import { MarkdownView } from './MarkdownView'

const { TextArea } = Input
type ToolInput = ToolInfo['steps'][number]['inputs'][number]

/** 后台执行轮询间隔与容错上限。 */
const POLL_INTERVAL_MS = 1500
const POLL_MAX_NETWORK_FAILURES = 5

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

/** select 选项归一化：字符串（显示=提交值）或 {value, label}（中文显示、提交枚举值）。 */
function optionItems(inp: ToolInput): { label: string; value: string }[] {
  return (inp.options ?? []).map((o) => (typeof o === 'string' ? { label: o, value: o } : o))
}

/** 分区微标签：小号加宽字距，编辑感分区（DESIGN.md micro-uppercase 节奏）。 */
function SectionLabel({ children }: { children: string }) {
  return (
    <p className="m-0 text-[12px] font-semibold tracking-[0.15em] text-[var(--color-steel)]">{children}</p>
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

/** 结果区下载按钮：含 file_id 的对象 → 下载按钮（横排并排展示）。 */
function DownloadButtons({
  refs,
  executionId,
}: {
  refs: [string, unknown][]
  executionId: string
}) {
  return (
    <div className="flex flex-wrap gap-3">
      {refs.map(([key, v]) => {
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
  )
}

/** 结果区渲染约定：text → 文本块；键名以 _md 结尾 → Markdown 渲染；
 * rows+columns → 表格；含 file_id 的对象 → 下载按钮（多形态同框渲染不互斥）；其余 → 键值。 */
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
  const mdEntries = Object.entries(data).filter(
    ([k, v]) => k.endsWith('_md') && typeof v === 'string' && v,
  )
  const hasTable = Array.isArray(data.rows) && Array.isArray(data.columns)
  let body: React.ReactNode
  if (data.text != null) {
    body = <pre className="m-0 whitespace-pre-wrap rounded-lg bg-[var(--color-surface)] p-4 text-[14px] leading-relaxed text-[var(--color-charcoal)]">{String(data.text)}</pre>
  } else if (mdEntries.length > 0) {
    body = (
      <div className="space-y-4">
        {mdEntries.map(([k, v]) => (
          <MarkdownView key={k} text={String(v)} />
        ))}
        {fileRefs.length > 0 && <DownloadButtons refs={fileRefs} executionId={executionId} />}
      </div>
    )
  } else if (!hasTable && fileRefs.length === 0) {
    body = (
      <dl className="m-0 space-y-1 rounded-lg bg-[var(--color-surface)] p-4 text-[14px]">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <dt className="shrink-0 font-medium text-[var(--color-charcoal)]">{k}</dt>
            <dd className="m-0 text-[var(--color-slate)] break-all">{JSON.stringify(v)}</dd>
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
        {fileRefs.length > 0 && <DownloadButtons refs={fileRefs} executionId={executionId} />}
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
        // 单文件输入：maxCount=1 时新上传的文件自动替换旧文件（点选与拖拽均生效）
        maxCount={input.multiple ? undefined : 1}
        accept={input.accept ?? undefined}
        beforeUpload={() => false}
        showUploadList={false}
        className="[&_.ant-upload-drag]:border-transparent! [&_.ant-upload-drag]:bg-transparent! [&_.ant-upload-drag:hover]:border-transparent! [&_.ant-upload-drag.ant-upload-drag-hover]:border-transparent! [&_.ant-upload-btn]:p-0!"
      >
        <div
          className="rounded-xl border border-dashed px-4 text-center transition-colors"
          style={{
            background: filled ? tintBg : 'var(--color-surface-soft)',
            borderColor: filled ? 'transparent' : `${tintInk}40`,
          }}
        >
          {filled ? (
            <div className="space-y-1 py-2.5">
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
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] transition-opacity hover:opacity-80"
                    style={{ background: tintInk, color: '#fff' }}
                  >
                    <CloseOutlined />
                  </button>
                </div>
              ))}
              <p className="m-0 text-[12px]" style={{ color: tintInk, opacity: 0.7 }}>
                点击更换文件
              </p>
            </div>
          ) : (
            <div className="py-5">
              <InboxOutlined className="text-[20px]" style={{ color: tintInk }} />
              <p className="m-0 mt-2 text-[13px] font-medium" style={{ color: tintInk }}>
                {input.label}
                {input.required && <span className="ml-0.5 text-[var(--color-error)]">*</span>}
              </p>
              <p className="m-0 mt-1 text-[12px]" style={{ color: tintInk, opacity: 0.7 }}>点击或拖拽上传</p>
              {input.accept && (
                <p className="m-0 mt-1 text-[11px]" style={{ color: tintInk, opacity: 0.5 }}>
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
  initialProgress,
  recentExecutions = [],
}: {
  tool: ToolInfo
  initialExecutionId?: string | null
  initialOutputs?: Record<string, Record<string, unknown>>
  initialFileIds?: Record<string, string[]>
  initialFileNames?: Record<string, string>
  initialWarning?: string | null
  initialProgress?: Record<string, StepProgress>
  recentExecutions?: ExecutionSummaryInfo[]
}) {
  const router = useRouter()
  // 恢复时仍在后台执行的步骤（progress=running）：定位到该步骤并继续轮询
  const [resumedStepId] = useState(() => {
    if (!initialExecutionId || !initialProgress) return null
    return tool.steps.find((s) => initialProgress[s.id]?.status === 'running')?.id ?? null
  })
  const [stepIndex, setStepIndex] = useState(() => {
    const idx = resumedStepId ? tool.steps.findIndex((s) => s.id === resumedStepId) : -1
    return idx >= 0 ? idx : 0
  })
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
  const [running, setRunning] = useState(() => Boolean(resumedStepId))
  // 恢复到 failed 会话（用户经「查看结果」回来）：直接展示失败原因，不回到空表单
  const [error, setError] = useState<string | null>(() => {
    if (!initialProgress) return null
    const failed = Object.values(initialProgress).find((p) => p.status === 'failed')
    return failed ? failed.error || '执行失败' : null
  })
  // 非致命提示：恢复失败（initialWarning）与执行成功但记录落库失败（result.warning）
  const [warning, setWarning] = useState<string | null>(initialWarning ?? null)
  // 后台执行进度（percent + 阶段消息），渲染 tint 进度条；非后台工具恒为 null
  const [progress, setProgress] = useState<{ percent: number; message: string } | null>(() => {
    if (!resumedStepId || !initialProgress) return null
    const p = initialProgress[resumedStepId]
    return p ? { percent: p.percent, message: p.message } : null
  })
  const [form] = Form.useForm()

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 停止标志与挂载标志：tick 在 await 期间可能遇到 stopPolling/卸载，
  // 请求返回后不得再武装新 timer（否则轮询泄漏，每 1.5s 空转请求）
  const pollStoppedRef = useRef(false)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const stopPolling = useCallback(() => {
    pollStoppedRef.current = true
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  /** 轮询后台执行：running 更新进度条；done 落结果；failed 报错；网络抖动有限容错。 */
  const pollExecution = useCallback((execId: string, stepId: string) => {
    let networkFailures = 0
    pollStoppedRef.current = false
    /** 本步上传文件的 file_ids：从会话 files 按 input_key 归组（与刷新恢复路径同源）。 */
    const fileIdsOf = (info: ExecutionInfo): Record<string, string[]> => {
      const map: Record<string, string[]> = {}
      for (const inp of tool.steps.find((s) => s.id === stepId)?.inputs ?? []) {
        if (inp.type !== 'file' || inp.from_step) continue
        const fids = Object.entries(info.files)
          .filter(([, meta]) => meta.input_key === inp.key)
          .map(([fid]) => fid)
        if (fids.length > 0) map[inp.key] = fids
      }
      return map
    }
    const finishWith = (
      data: Record<string, unknown> | null,
      fileIds: Record<string, string[]> = {},
      errorMessage?: string,
    ) => {
      stopPolling()
      setProgress(null)
      if (data !== null) {
        setStepResults((prev) => ({
          ...prev,
          [stepId]: { execution_id: execId, data, file_ids: fileIds },
        }))
      }
      if (errorMessage) setError(errorMessage)
      setRunning(false)
    }
    const tick = async () => {
      if (pollStoppedRef.current || !mountedRef.current) return
      try {
        const info = await fetchExecutionState(execId)
        if (pollStoppedRef.current || !mountedRef.current) return
        networkFailures = 0
        const p = info.progress?.[stepId]
        const output = info.outputs[stepId]
        if (p?.status === 'done' || (!p && output)) {
          finishWith(output ?? {}, fileIdsOf(info))
        } else if (p?.status === 'failed') {
          finishWith(null, {}, p.error || '执行失败')
        } else {
          if (p) setProgress({ percent: p.percent, message: p.message })
          pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS)
        }
      } catch (e) {
        if (pollStoppedRef.current || !mountedRef.current) return
        const status = (e as { status?: number } | null)?.status
        if (status === 401 || status === 403) {
          // 登录失效/被移出授权名单：轮询没有恢复可能，直接终止并提示
          finishWith(null, {}, e instanceof Error ? e.message : '执行状态获取失败')
          return
        }
        networkFailures += 1
        if (networkFailures >= POLL_MAX_NETWORK_FAILURES) {
          finishWith(null, {}, '执行状态获取失败：网络异常，请稍后刷新页面查看结果')
          return
        }
        pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS)
      }
    }
    if (mountedRef.current) pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS)
  }, [stopPolling, tool])

  // 恢复仍在执行的后台任务轮询；卸载时停表（setState 均发生在 timer 回调，事件驱动）
  useEffect(() => {
    if (resumedStepId && initialExecutionId) {
      pollExecution(initialExecutionId, resumedStepId)
    }
    return stopPolling
  }, [resumedStepId, initialExecutionId, pollExecution, stopPolling])

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
    stopPolling()
    setProgress(null)
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
    setProgress(null)
    let backgroundStarted = false
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
      // 记录本步上传的文件名，供下游步骤引用芯片展示
      const names: Record<string, string> = {}
      for (const inp of fileInputs) {
        const files = (values[inp.key] as UploadFile[] | undefined) ?? []
        if (files.length > 0) names[inp.key] = files.map((f) => f.name).join('、')
      }
      if (Object.keys(names).length > 0) setUploadedNames((prev) => ({ ...prev, ...names }))
      if (result.status === 'running') {
        // 后台执行：保持 running 渲染进度条，轮询会话直到完成
        backgroundStarted = true
        setProgress({ percent: 0, message: '任务已启动，正在准备…' })
        pollExecution(result.execution_id, step.id)
        return
      }
      setStepResults((prev) => ({ ...prev, [step.id]: result }))
    } catch (e) {
      setError(e instanceof Error ? e.message : '执行失败')
    } finally {
      if (!backgroundStarted) setRunning(false)
    }
  }

  const labelOf = (inp: ToolInput) => (
    <span>
      {inp.label}
      {inp.required && <span className="ml-1 text-[var(--color-error)]">*</span>}
    </span>
  )
  const verbOf = (inp: ToolInput) =>
    inp.type === 'select' || inp.type === 'month' || inp.type === 'date' ? '选择' : '填写'

  const renderParam = (inp: ToolInput) => {
    const rules = inp.required ? [{ required: true, message: `请${verbOf(inp)}${inp.label}` }] : undefined
    const tooltip = inp.help ?? undefined
    if (inp.type === 'select' && (inp.options?.length ?? 0) <= 3) {
      // 少量选项用 Segmented 分段控件（整行展示，切换直观）
      return (
        <Form.Item className="sm:col-span-2" name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
          <Segmented block options={optionItems(inp)} />
        </Form.Item>
      )
    }
    if (inp.type === 'select') {
      return (
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
          <Select style={{ width: 240 }} options={optionItems(inp)} />
        </Form.Item>
      )
    }
    if (inp.type === 'month' || inp.type === 'date') {
      return (
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
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
        <Form.Item className="sm:col-span-2" name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
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
        <Form.Item name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
          <InputNumber style={{ width: '100%' }} />
        </Form.Item>
      )
    }
    return (
      <Form.Item name={inp.key} label={labelOf(inp)} rules={rules} tooltip={tooltip}>
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
      {/* 页头工具条：返回与配置置于内容之上 */}
      <div className="flex items-center justify-between gap-3">
        <Link
          href="/toolbox"
          className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--color-steel)] transition-colors hover:text-[var(--color-primary)]"
        >
          <ArrowLeftOutlined />
          返回工具箱
        </Link>
        {tool.config_schema.length > 0 && tool.can_config && (
          <Link
            href={`/toolbox/config/${tool.id}`}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-[13px] font-medium text-[var(--color-charcoal)] transition-colors hover:border-[var(--color-stone)] hover:text-[var(--color-ink)]"
          >
            <SettingOutlined />
            配置
          </Link>
        )}
      </div>

      {/* 工具身份已在首页卡片展示，执行页不再重复（名称/描述/步数），顶栏即页头 */}

      {/* 恢复提示：后台任务不随页面离开而终止，重进工具页时给出找回入口。
          仅在尚未进入任何会话时显示（已恢复/已开跑则当前视图即任务本身）。
          分区标签置于卡头、与行内状态图标共用同一条左线（24px，同工作卡内边距），
          避免标签悬在卡外形成第二条左线。 */}
      {recentExecutions.length > 0 && !executionId && (
        <section className="mt-7">
          <div className="overflow-hidden rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] shadow-[rgba(15,15,15,0.04)_0px_1px_2px_0px]">
            <div className="px-6 pt-4">
              <SectionLabel>最近执行</SectionLabel>
            </div>
            <ul className="m-0 mt-2.5 divide-y divide-[var(--color-hairline-soft)]">
              {recentExecutions.map((e) => {
                const href = `/toolbox/${tool.id}?execution=${e.execution_id}`
                const running = e.status === 'running'
                const failed = !running && e.status === 'failed'
                // 手动格式化（不用 toLocaleString，避免 SSR/客户端 Intl 差异导致 hydration mismatch）
                const dt = new Date(e.created_at * 1000)
                const pad = (n: number) => String(n).padStart(2, '0')
                const time = `${pad(dt.getMonth() + 1)}/${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`
                const title = running ? `任务正在执行（${e.percent}%）` : failed ? '上次执行失败' : '上次执行已完成'
                const subtitle = running ? e.message || '任务已启动' : failed ? e.error || '执行失败' : time
                return (
                  <li
                    key={e.execution_id}
                    className="flex h-[52px] items-center gap-3 px-6"
                    style={running ? { background: tintBg } : undefined}
                  >
                    <span
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[13px]"
                      style={{
                        background: running
                          ? 'rgba(255, 255, 255, 0.55)'
                          : failed
                            ? 'rgba(224, 49, 49, 0.10)'
                            : 'rgba(26, 174, 57, 0.10)',
                        color: running ? tintInk : failed ? 'var(--color-error)' : 'var(--color-success)',
                      }}
                    >
                      {running ? <ClockCircleOutlined spin /> : failed ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
                    </span>
                    <p className="m-0 min-w-0 flex-1 truncate text-[13px] leading-5">
                      <span
                        className="font-medium"
                        style={{ color: running ? tintInk : 'var(--color-charcoal)' }}
                      >
                        {title}
                      </span>
                      <span
                        className="ml-2"
                        style={{ color: running ? tintInk : 'var(--color-stone)', opacity: running ? 0.75 : 1 }}
                      >
                        {subtitle}
                      </span>
                    </p>
                    {running ? (
                      // tint 墨色实心：与步骤轨道完成态圆点同色语言，突出唯一需要关注的动作
                      <button
                        type="button"
                        onClick={() => router.push(href)}
                        className="shrink-0 rounded-md px-3 py-1 text-[12px] font-medium leading-5 text-white transition-opacity active:opacity-80"
                        style={{ background: tintInk }}
                      >
                        继续查看
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => router.push(href)}
                        className="inline-flex shrink-0 items-center gap-1 text-[13px] font-medium leading-5 text-[var(--color-charcoal)] transition-colors hover:text-[var(--color-primary)]"
                      >
                        查看结果
                        <RightOutlined style={{ fontSize: 10 }} />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        </section>
      )}

      {/* 步骤轨道：编号承载真实流程顺序；完成态填充工具识别色，当前步骤 tint 底 + 描边，
          连接线在前序步骤完成后染上 tint，进度一眼可读 */}
      <div className="mt-7 flex items-center gap-0 overflow-x-auto pb-1">
        {tool.steps.map((s, i) => {
          const done = Boolean(stepResults[s.id])
          const current = i === stepIndex
          const prevDone = i > 0 && Boolean(stepResults[tool.steps[i - 1].id])
          return (
            <Fragment key={s.id}>
              {i > 0 && (
                <span
                  className="mx-3 h-px w-8 shrink-0"
                  style={{ background: prevDone ? `${tintInk}59` : 'var(--color-hairline-strong)' }}
                />
              )}
              <button
                type="button"
                onClick={() => handleStepClick(i)}
                disabled={!done || current || running}
                className={`flex shrink-0 items-center gap-2 rounded-full py-1 pr-3 transition-colors ${
                  current ? '' : done ? 'cursor-pointer hover:bg-[var(--color-surface)]' : 'cursor-default'
                }`}
              >
                <span
                  className="flex h-7 w-7 items-center justify-center rounded-full text-[13px] font-semibold"
                  style={
                    done
                      ? { background: tintInk, color: '#ffffff' }
                      : current
                        ? { border: `2px solid ${tintInk}`, color: tintInk, background: tintBg }
                        : { border: '2px solid var(--color-hairline-strong)', color: 'var(--color-stone)' }
                  }
                >
                  {done ? <CheckOutlined style={{ fontSize: 12 }} /> : i + 1}
                </span>
                <span
                  className={`text-[14px] ${
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

      <div className="mt-4 rounded-xl border border-[var(--color-hairline)] bg-[var(--color-canvas)] p-6 shadow-[rgba(15,15,15,0.04)_0px_1px_2px_0px,rgba(15,15,15,0.05)_0px_6px_16px_0px]">
        {/* 步骤头：眉标 + 标题 + 描述同一条左线，与卡内分区标签对齐 */}
        <div className="border-b border-[var(--color-hairline-soft)] pb-4">
          <p className="m-0 text-[12px] font-semibold tracking-[0.08em]" style={{ color: tintInk }}>
            步骤 {stepIndex + 1}
          </p>
          <h2 className="m-0 mt-1 text-[18px] font-semibold leading-snug text-[var(--color-charcoal)]">{step.name}</h2>
          <p className="m-0 mt-1 text-[14px] leading-relaxed text-[var(--color-slate)]">{step.description}</p>
        </div>
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
            <div className="mt-5 flex max-w-xl items-start gap-3 rounded-lg px-4 py-3.5" style={{ background: tintBg }}>
              <span
                className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/60"
                style={{ color: tintInk }}
              >
                <WarningOutlined style={{ fontSize: 11 }} />
              </span>
              <p className="m-0 text-[13px] leading-relaxed" style={{ color: tintInk }}>{step.description}</p>
            </div>
          )}
          <div className="mt-6 flex items-center gap-3">
            <Button type="primary" size="large" htmlType="submit" loading={running} className="min-w-[128px]">
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
                size="large"
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
        {progress && running && (
          <div className="mt-5 rounded-lg px-4 py-3" style={{ background: tintBg }}>
            <div className="flex items-center justify-between gap-3">
              <span className="truncate text-[13px] font-medium" style={{ color: tintInk }}>
                {progress.message}
              </span>
              <span className="shrink-0 text-[12px] tabular-nums" style={{ color: tintInk, opacity: 0.7 }}>
                {progress.percent}%
              </span>
            </div>
            <Progress
              percent={progress.percent}
              showInfo={false}
              strokeColor={tintInk}
              railColor="rgba(0, 0, 0, 0.08)"
              className="mt-1 [&_.ant-progress-inner]:h-1.5"
            />
          </div>
        )}
        {currentResult && (
          <div className="mt-6 border-t border-[var(--color-hairline-soft)] pt-5">
            <div className="mb-3 flex items-center gap-2">
              <span
                className="flex h-5 w-5 items-center justify-center rounded-full"
                style={{ background: 'rgba(26, 174, 57, 0.10)', color: 'var(--color-success)' }}
              >
                <CheckCircleOutlined style={{ fontSize: 12 }} />
              </span>
              <h3 className="text-[14px] font-semibold text-[var(--color-charcoal)]">执行结果</h3>
            </div>
            <ResultView data={currentResult.data} executionId={currentResult.execution_id} tintBg={tintBg} tintInk={tintInk} />
          </div>
        )}
      </div>
    </div>
  )
}

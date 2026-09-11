// 工具箱执行页：服务端拉取工具元数据（含 URL 中的 execution 恢复）

import { apiGet } from '@/lib/http-client'

import { ToolRunner } from '@/components/toolbox'
import type { ExecutionInfo, ExecutionSummaryInfo, StepProgress, ToolInfo } from '@/types/toolbox'

export const dynamic = 'force-dynamic'

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

export default async function ToolPage({
  params,
  searchParams,
}: {
  params: Promise<{ toolId: string }>
  searchParams: Promise<{ execution?: string }>
}) {
  const { toolId } = await params
  const { execution } = await searchParams

  let tools: ToolInfo[] = []
  let loadError: string | null = null
  try {
    tools = await apiGet<ToolInfo[]>(`${API_BASE}/api/v1/toolbox/tools`, {
      cache: 'no-store',
    })
  } catch (e) {
    loadError = e instanceof Error ? e.message : '页面数据加载失败'
  }
  if (loadError) {
    return (
      <p className="p-6 text-[15px] text-[var(--color-stone)]">
        页面数据加载失败：{loadError}，请稍后重试或联系管理员
      </p>
    )
  }
  const tool = tools.find((t) => t.id === toolId)

  if (!tool) {
    return <p className="p-6 text-[var(--color-stone)]">工具不存在</p>
  }
  if (!tool.can_use) {
    return (
      <p className="p-6 text-[15px] text-[var(--color-stone)]">
        没有使用该工具的权限，请联系管理员
      </p>
    )
  }

  let initialExecutionId: string | null = execution ?? null
  let restoreNotice: string | null = null
  let initialOutputs: Record<string, Record<string, unknown>> = {}
  let initialProgress: Record<string, StepProgress> | undefined
  const initialFileIds: Record<string, string[]> = {}
  const initialFileNames: Record<string, string> = {}
  if (execution) {
    try {
      const einfo: ExecutionInfo = await apiGet<ExecutionInfo>(
        `${API_BASE}/api/v1/toolbox/executions/${execution}`,
        { cache: 'no-store' },
      )
      initialOutputs = einfo.outputs
      // 后台执行任务的进度：任务仍在跑时 ToolRunner 据此恢复轮询
      initialProgress = einfo.progress
      // files: {file_id: {input_key, filename}} → {input_key: file_id[]}（后出现者排在后面）
      for (const [fid, meta] of Object.entries(einfo.files)) {
        ;(initialFileIds[meta.input_key] ??= []).push(fid)
        // 文件名供执行页「引用材料」芯片展示
        const cur = initialFileNames[meta.input_key]
        initialFileNames[meta.input_key] = cur ? `${cur}、${meta.filename}` : meta.filename
      }
    } catch (e) {
      // 恢复失败不再静默：404（会话过期/被清理）丢弃 execution 从头开始；
      // 5xx/网络错误保留 execution，仅提示（后端恢复后会话可能仍在）
      const status = (e as { status?: number } | null)?.status
      restoreNotice =
        status === 404
          ? '该执行会话已过期或不存在，历史步骤结果无法恢复，请重新开始执行'
          : '历史执行结果加载失败，请稍后重试或联系管理员'
      if (status === 404) initialExecutionId = null
    }
  }

  // 恢复提示：用户中途离开后任务仍在后台执行，重进工具页时给出「继续查看」入口。
  // 仅后台工具、且 URL 未指定 execution 时拉取（已恢复到具体会话则无需提示）。
  let recentExecutions: ExecutionSummaryInfo[] = []
  if (!execution && tool.background) {
    try {
      const mine = await apiGet<ExecutionSummaryInfo[]>(
        `${API_BASE}/api/v1/toolbox/executions`,
        { cache: 'no-store' },
      )
      const ofTool = mine.filter((e) => e.tool_id === toolId)
      const running = ofTool.filter((e) => e.status === 'running')
      // 已完成只留最新一条：更早的历史结果价值有限，两条重复的「已完成」只会成为噪音
      const latestFinished = ofTool
        .filter((e) => e.status !== 'running')
        .sort((a, b) => b.created_at - a.created_at)
        .slice(0, 1)
      recentExecutions = [...running, ...latestFinished]
    } catch {
      // 提示条是辅助能力：拉取失败不打断页面
    }
  }

  return (
    <ToolRunner
      // key 绑定 execution：软导航（提示条「继续查看」的 router.push）只重渲染
      // 不重挂载，useState 初始化函数不会重跑、恢复逻辑不生效；key 变化强制重挂载
      key={execution ?? 'fresh'}
      tool={tool}
      initialExecutionId={initialExecutionId}
      initialOutputs={initialOutputs}
      initialFileIds={initialFileIds}
      initialFileNames={initialFileNames}
      initialWarning={restoreNotice}
      initialProgress={initialProgress}
      recentExecutions={recentExecutions}
    />
  )
}

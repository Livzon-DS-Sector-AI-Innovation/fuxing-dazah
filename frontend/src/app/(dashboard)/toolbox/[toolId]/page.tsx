// 工具箱执行页：服务端拉取工具元数据（含 URL 中的 execution 恢复）

import { apiGet } from '@/lib/http-client'

import { ToolRunner } from '@/components/toolbox'
import type { ExecutionInfo, ToolInfo } from '@/types/toolbox'

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
  const initialFileIds: Record<string, string[]> = {}
  const initialFileNames: Record<string, string> = {}
  if (execution) {
    try {
      const einfo: ExecutionInfo = await apiGet<ExecutionInfo>(
        `${API_BASE}/api/v1/toolbox/executions/${execution}`,
        { cache: 'no-store' },
      )
      initialOutputs = einfo.outputs
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

  return (
    <ToolRunner
      tool={tool}
      initialExecutionId={initialExecutionId}
      initialOutputs={initialOutputs}
      initialFileIds={initialFileIds}
      initialFileNames={initialFileNames}
      initialWarning={restoreNotice}
    />
  )
}

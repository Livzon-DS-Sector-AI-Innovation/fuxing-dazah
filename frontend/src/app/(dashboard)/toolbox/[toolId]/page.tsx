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

  const tools: ToolInfo[] = await apiGet<ToolInfo[]>(`${API_BASE}/api/v1/toolbox/tools`, {
    cache: 'no-store',
  }).catch(() => [])
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
    } catch {
      initialOutputs = {}
    }
  }

  return (
    <ToolRunner
      tool={tool}
      initialExecutionId={execution ?? null}
      initialOutputs={initialOutputs}
      initialFileIds={initialFileIds}
      initialFileNames={initialFileNames}
    />
  )
}

// 工具配置页：按工具声明的 config_schema 动态渲染配置表单

import { apiGet } from '@/lib/http-client'

import { ToolConfigForm } from '@/components/toolbox'
import type { ToolConfig, ToolInfo } from '@/types/toolbox'

export const dynamic = 'force-dynamic'

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

export default async function ToolConfigPage({
  params,
}: {
  params: Promise<{ toolId: string }>
}) {
  const { toolId } = await params

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
  if (tool.config_schema.length === 0) {
    return <p className="p-6 text-[var(--color-stone)]">该工具没有可配置项</p>
  }
  if (!tool.can_config) {
    return <p className="p-6 text-[var(--color-stone)]">没有修改该工具配置的权限</p>
  }

  let config: ToolConfig | null = null
  try {
    config = await apiGet<ToolConfig>(`${API_BASE}/api/v1/toolbox/tools/${toolId}/config`, {
      cache: 'no-store',
    })
  } catch (e) {
    // 404 = 尚未配置：显示空表单供管理员首次填写；其他错误才报加载失败
    if ((e as { status?: number }).status !== 404) {
      loadError = e instanceof Error ? e.message : '页面数据加载失败'
    }
  }
  if (loadError) {
    return (
      <p className="p-6 text-[15px] text-[var(--color-stone)]">
        页面数据加载失败：{loadError}，请稍后重试或联系管理员
      </p>
    )
  }

  return (
    <ToolConfigForm
      toolId={tool.id}
      toolName={tool.name}
      schema={tool.config_schema}
      initial={config}
    />
  )
}

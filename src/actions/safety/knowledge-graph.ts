'use server'

import { revalidatePath } from 'next/cache'

import { getAuthHeaders } from '@/lib/auth'
import { fetchApi } from './_helpers'
import { buildQueryString } from './_utils'
import type {
  FullGraphData,
  GraphEdge,
  GraphExpandParams,
  GraphGenerateRequest,
  GraphGenerateResult,
  GraphNode,
  GraphQueryParams,
} from '@/types/safety'

/** 获取完整图谱数据（节点 + 边），供 React Flow 渲染 */
export async function getFullGraph(params?: GraphQueryParams): Promise<FullGraphData> {
  const qs = buildQueryString(params || {})
  const res = await fetchApi<FullGraphData>(
    `/safety/knowledge-graph/full-graph${qs}`,
    { method: 'GET', headers: await getAuthHeaders() },
  )
  return res.data
}

/** 获取图谱节点列表 */
export async function getGraphNodes(params?: GraphQueryParams): Promise<GraphNode[]> {
  const qs = buildQueryString(params || {})
  const res = await fetchApi<GraphNode[]>(
    `/safety/knowledge-graph/nodes${qs}`,
    { method: 'GET', headers: await getAuthHeaders() },
  )
  return res.data
}

/** 获取图谱边列表 */
export async function getGraphEdges(params?: GraphQueryParams): Promise<GraphEdge[]> {
  const qs = buildQueryString(params || {})
  const res = await fetchApi<GraphEdge[]>(
    `/safety/knowledge-graph/edges${qs}`,
    { method: 'GET', headers: await getAuthHeaders() },
  )
  return res.data
}

/** 搜索图谱节点 */
export async function searchGraphNodes(query: string, nodeTypes?: string): Promise<GraphNode[]> {
  const qs = buildQueryString({ query, node_types: nodeTypes })
  const res = await fetchApi<GraphNode[]>(
    `/safety/knowledge-graph/search${qs}`,
    { method: 'GET', headers: await getAuthHeaders() },
  )
  return res.data
}

/** 从节点展开 N-hop 邻居子图 */
export async function expandGraphNode(params: GraphExpandParams): Promise<FullGraphData> {
  const qs = buildQueryString(params)
  const res = await fetchApi<FullGraphData>(
    `/safety/knowledge-graph/expand${qs}`,
    { method: 'GET', headers: await getAuthHeaders() },
  )
  return res.data
}

/** 触发 AI 图谱生成 */
export async function triggerGraphGeneration(data?: GraphGenerateRequest): Promise<GraphGenerateResult> {
  const res = await fetchApi<GraphGenerateResult>(
    `/safety/knowledge-graph/generate`,
    {
      method: 'POST',
      headers: {
        ...(await getAuthHeaders()),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data || {}),
    },
  )
  revalidatePath('/safety/knowledge-base/graph')
  return res.data
}

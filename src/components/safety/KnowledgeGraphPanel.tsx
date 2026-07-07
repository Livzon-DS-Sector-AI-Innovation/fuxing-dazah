'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  MarkerType,
  BackgroundVariant,
  Panel,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { App, Space } from 'antd'
import {
  ReloadOutlined,
} from '@ant-design/icons'
import dagre from 'dagre'

import type { GraphNode, GraphEdge as GraphEdgeData } from '@/types/safety'
import {
  getFullGraph,
  expandGraphNode,
} from '@/actions/safety/knowledge-graph'
import { useKnowledgeGraphStore } from '@/stores/safety/knowledgeGraphStore'
import {
  NODE_TYPE_STYLE,
  RELATION_TYPE_STYLE,
  AI_GENERATED_OPACITY,
  HUMAN_CONFIRMED_OPACITY,
  DEFAULT_NODE_STYLE,
} from './graphConstants'
import KnowledgeGraphToolbar from './KnowledgeGraphToolbar'
import KnowledgeGraphDetail from './KnowledgeGraphDetail'
import KnowledgeGraphLegend from './KnowledgeGraphLegend'

// ── 布局配置 ──────────────────────────────────────────────

const SUB_DAGRE_CONFIG = {
  rankdir: 'TB',        // 聚类内部：分类在上，实体在下
  nodesep: 30,
  ranksep: 50,
  marginx: 15,
  marginy: 15,
}

const NODE_DIMS: Record<string, { w: number; h: number }> = {
  category: { w: 140, h: 34 },
  entity:   { w: 170, h: 34 },
  concept:  { w: 150, h: 34 },
  document: { w: 190, h: 34 },
  clause:   { w: 150, h: 30 },
}

const GRID_W = 340   // 网格列宽
const GRID_H = 250   // 网格行高
const GRID_COLS = 5  // 每行 5 个聚类

function nodeDims(nodeType: string) {
  return NODE_DIMS[nodeType] || { w: 160, h: 34 }
}

/** 按聚类分组 + dagre 布局 + 网格排列 */
function layoutGraph(flowNodes: Node[], flowEdges: Edge[]): Node[] {
  if (flowNodes.length === 0) return []

  // 1. 识别边的关系类型（从 data 或 label 判断）
  const getRelType = (e: Edge): string =>
    (e.data as any)?.relationType || (e as any).relationType || ''

  // 2. 找 belongs_to 边 → entity → category 映射
  const entityCat = new Map<string, string>()
  for (const e of flowEdges) {
    if (getRelType(e) === 'belongs_to') {
      entityCat.set(e.source, e.target)
    }
  }

  // 3. 分组：每个 category + 归属它的 entity
  type Cluster = { catId: string; entityIds: string[] }
  const clusters: Cluster[] = []
  const catHasCluster = new Set<string>()
  const entityClustered = new Set<string>()

  for (const n of flowNodes) {
    const nt = (n.data?.nodeType as string) || ''
    if (nt === 'category' && !catHasCluster.has(n.id)) {
      clusters.push({ catId: n.id, entityIds: [] })
      catHasCluster.add(n.id)
    }
  }

  for (const n of flowNodes) {
    const nt = (n.data?.nodeType as string) || ''
    if (nt === 'category') continue
    const catId = entityCat.get(n.id)
    const cluster = clusters.find(c => c.catId === catId)
    if (cluster) {
      cluster.entityIds.push(n.id)
      entityClustered.add(n.id)
    }
  }

  // 无归属实体单独成组（每个一行）
  const orphans = flowNodes.filter(
    n => !entityClustered.has(n.id) && !catHasCluster.has(n.id)
  )

  // 4. 对每个聚类运行 dagre TB 布局
  const nodeMap = new Map(flowNodes.map(n => [n.id, n]))
  const positions = new Map<string, { x: number; y: number }>()

  function layoutSubgraph(nodeIds: string[], offsetX: number, offsetY: number) {
    const g = new dagre.graphlib.Graph()
    g.setDefaultEdgeLabel(() => ({}))
    g.setGraph(SUB_DAGRE_CONFIG)

    const idSet = new Set(nodeIds)
    for (const id of nodeIds) {
      const n = nodeMap.get(id)
      if (!n) continue
      const d = nodeDims((n.data?.nodeType as string) || 'entity')
      g.setNode(id, { width: d.w, height: d.h })
    }
    for (const e of flowEdges) {
      if (idSet.has(e.source) && idSet.has(e.target)) {
        g.setEdge(e.source, e.target)
      }
    }
    dagre.layout(g)

    // 找子图左上角
    let minX = Infinity, minY = Infinity
    for (const id of nodeIds) {
      const pos = g.node(id)
      const d = nodeDims((nodeMap.get(id)?.data?.nodeType as string) || 'entity')
      if (pos) {
        minX = Math.min(minX, pos.x - d.w / 2)
        minY = Math.min(minY, pos.y - d.h / 2)
      }
    }
    if (!isFinite(minX)) { minX = 0; minY = 0 }

    for (const id of nodeIds) {
      const pos = g.node(id)
      const d = nodeDims((nodeMap.get(id)?.data?.nodeType as string) || 'entity')
      if (pos) {
        positions.set(id, {
          x: pos.x - d.w / 2 - minX + offsetX,
          y: pos.y - d.h / 2 - minY + offsetY,
        })
      } else {
        positions.set(id, { x: offsetX + 40, y: offsetY + 20 })
      }
    }
  }

  let gridIdx = 0
  for (const cluster of clusters) {
    const col = gridIdx % GRID_COLS
    const row = Math.floor(gridIdx / GRID_COLS)
    layoutSubgraph([cluster.catId, ...cluster.entityIds], col * GRID_W + 30, row * GRID_H + 30)
    gridIdx++
  }

  // 孤儿节点：简单网格排列
  if (orphans.length > 0) {
    const startCol = gridIdx % GRID_COLS
    const startRow = Math.floor(gridIdx / GRID_COLS)
    orphans.forEach((n, i) => {
      const col = startCol + (i % 4)
      const row = startRow + Math.floor(i / 4)
      const d = nodeDims((n.data?.nodeType as string) || 'entity')
      positions.set(n.id, {
        x: col * GRID_W + 30 + (GRID_W - d.w) / 2,
        y: row * GRID_H + 30 + (GRID_H - d.h) / 2,
      })
    })
  }

  // 5. 输出
  return flowNodes.map(n => {
    const pos = positions.get(n.id) || { x: 0, y: 0 }
    return { ...n, position: pos }
  })
}

// ── 节点/边映射 ──────────────────────────────────────────

function mapNodeToFlowNode(n: GraphNode): Node {
  const style = NODE_TYPE_STYLE[n.node_type] || NODE_TYPE_STYLE.document
  const isAi = n.status === 'ai_generated'
  const opacity = isAi ? AI_GENERATED_OPACITY : HUMAN_CONFIRMED_OPACITY
  const dims = nodeDims(n.node_type)

  return {
    id: n.id,
    type: 'default',
    position: { x: 0, y: 0 },
    data: {
      label: (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          {style.icon && <style.icon style={{ fontSize: 13, color: style.color }} />}
          <span style={{ color: style.color, lineHeight: 1.2 }}>{n.name}</span>
        </div>
      ),
      nodeType: n.node_type,
      status: n.status,
      entityType: n.entity_type,
      summary: n.ai_summary,
    },
    style: {
      ...DEFAULT_NODE_STYLE,
      background: style.bg,
      borderColor: isAi ? `${style.color}66` : style.color,
      color: style.color,
      opacity,
      fontStyle: isAi ? 'italic' : 'normal',
      padding: '4px 10px',
      borderRadius: '6px',
      width: dims.w,
    },
    draggable: true,
  }
}

function mapEdgeToFlowEdge(e: GraphEdgeData): Edge {
  const style = RELATION_TYPE_STYLE[e.relation_type] || RELATION_TYPE_STYLE.related_to

  return {
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    type: 'smoothstep',
    animated: e.relation_type === 'cites',
    label: style.label,
    style: {
      stroke: style.color,
      strokeWidth: style.strokeWidth,
      strokeDasharray: style.strokeDasharray || undefined,
      opacity: e.status === 'human_deleted' ? 0.3 : 0.8,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: style.color,
      width: 14,
      height: 14,
    },
    data: {
      relationType: e.relation_type,
      description: e.description,
      evidence: e.evidence_text,
      confidence: e.confidence,
      status: e.status,
    },
  }
}

// ── 主组件 ──────────────────────────────────────────────

export default function KnowledgeGraphPanel() {
  const { message } = App.useApp()
  const store = useKnowledgeGraphStore()
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([])
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([])
  const rfInstance = useRef<any>(null)

  // 加载数据
  const loadGraph = useCallback(async () => {
    store.setLoading(true)
    try {
      const data = await getFullGraph({
        node_types: store.nodeTypeFilter || undefined,
        relation_types: store.relationTypeFilter || undefined,
        max_nodes: 500,
      })
      store.setGraphData(data)
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '加载图谱失败'
      store.setError(errMsg)
      message.error(`加载图谱数据失败: ${errMsg}`)
    } finally {
      store.setLoading(false)
    }
  }, [store.nodeTypeFilter, store.relationTypeFilter])

  useEffect(() => { loadGraph() }, [loadGraph])

  // 同步 store → React Flow（聚类布局），只保留 category + document 节点
  useEffect(() => {
    // 过滤：只保留分类节点 + 文档节点（entity_type=standard 的实体即法规文档）
    const filteredNodes = store.nodes.filter(
      n => n.node_type === 'category' || n.entity_type === 'standard'
    )
    const filteredNodeIds = new Set(filteredNodes.map(n => n.id))

    // 过滤边：两端都在保留节点中
    const filteredEdges = store.edges.filter(
      e => filteredNodeIds.has(e.source_node_id) && filteredNodeIds.has(e.target_node_id)
    )

    const mappedNodes = filteredNodes.map(mapNodeToFlowNode)
    const mappedEdges = filteredEdges.map(mapEdgeToFlowEdge)
    const laidOut = layoutGraph(mappedNodes, mappedEdges)
    setFlowNodes(laidOut)
    setFlowEdges(mappedEdges)
    setTimeout(() => {
      rfInstance.current?.fitView?.({ padding: 0.05, duration: 200 })
    }, 100)
  }, [store.nodes, store.edges])

  // 节点点击 → 展开邻居
  const onNodeClick = useCallback(
    async (_event: React.MouseEvent, node: Node) => {
      store.selectNode(node.id)
      try {
        const expanded = await expandGraphNode({ node_id: node.id, hops: 1, max_nodes: 30 })
        if (expanded.nodes.length > 0) {
          store.setGraphData(expanded)
          setTimeout(() => {
            rfInstance.current?.fitView?.({ padding: 0.1, duration: 300 })
          }, 50)
        }
      } catch { /* ignore */ }
    },
    [store],
  )

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => { store.selectEdge(edge.id) },
    [store],
  )

  const onPaneClick = useCallback(() => {
    store.selectNode(null)
    store.selectEdge(null)
  }, [store])

  const selectedNode = useMemo(
    () => store.nodes.find(n => n.id === store.selectedNodeId) || null,
    [store.nodes, store.selectedNodeId],
  )
  const selectedEdge = useMemo(
    () => store.edges.find(e => e.id === store.selectedEdgeId) || null,
    [store.edges, store.selectedEdgeId],
  )

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <KnowledgeGraphToolbar
        onRefresh={loadGraph}
        loading={store.loading}
        onFitView={() => rfInstance.current?.fitView?.({ padding: 0.1, duration: 300 })}
      />

      <Panel position="top-right">
        <KnowledgeGraphLegend />
      </Panel>

      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={onPaneClick}
        onInit={(inst) => { rfInstance.current = inst }}
        minZoom={0.05}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        style={{ background: 'var(--color-surface-soft, #fafaf9)' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e5e3df" />
        <Controls
          style={{ background: 'white', borderRadius: 8, boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}
        />
        <MiniMap
          style={{ background: 'var(--color-surface, #f6f5f4)', borderRadius: 8 }}
          maskColor="rgba(0,0,0,0.05)"
          nodeColor={(n) => {
            const nodeType = (n.data?.nodeType as string) || 'document'
            return NODE_TYPE_STYLE[nodeType as keyof typeof NODE_TYPE_STYLE]?.color || '#5645d4'
          }}
        />
      </ReactFlow>

      {(selectedNode || selectedEdge) && (
        <KnowledgeGraphDetail
          node={selectedNode}
          edge={selectedEdge}
          nodes={store.nodes}
          onClose={() => { store.selectNode(null); store.selectEdge(null) }}
          onNodeClick={(id) => { store.selectNode(id) }}
        />
      )}

      {store.loading && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)', background: 'white',
          padding: '24px 36px', borderRadius: 12,
          boxShadow: '0 4px 20px rgba(0,0,0,0.1)', zIndex: 10,
        }}>
          <Space>
            <ReloadOutlined spin />
            <span style={{ color: 'var(--color-slate, #5d5b54)' }}>加载图谱数据...</span>
          </Space>
        </div>
      )}

      {!store.loading && store.nodes.length === 0 && (
        <div style={{
          position: 'absolute', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)', textAlign: 'center', zIndex: 10,
        }}>
          <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }}>🗺️</div>
          <p style={{ color: 'var(--color-steel, #787671)', marginBottom: 16 }}>暂无图谱数据</p>
          <p style={{ color: 'var(--color-steel, #787671)', fontSize: 13 }}>
            图谱由 AI 随文档同步自动生成，请确认知识库中有已发布的法规文档
          </p>
        </div>
      )}
    </div>
  )
}

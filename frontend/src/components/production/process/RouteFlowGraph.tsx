'use client'

import { useMemo } from 'react'
import type { CSSProperties } from 'react'
import {
  Handle,
  MarkerType,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import {
  FlowGraph,
  MaterialNode,
  MATERIAL_INPUT,
  MATERIAL_OUTPUT,
  PROCESS_NODE_H,
  PROCESS_NODE_W,
  type MaterialNodeData,
} from '../shared/FlowGraph'
import { stageColor, stageTint } from '../shared/stageColor'
import styles from '../shared/FlowGraph.module.css'
import type { RouteEdge, RouteNode } from '@/types/production'

type ProcessNodeData = {
  name: string
  node_code: string
  stage_name: string | null
  fieldCount: number
}

function ProcessNode({ data, selected }: NodeProps) {
  const d = data as ProcessNodeData
  const accent = d.stage_name ? stageColor(d.stage_name) : '#a4a097'
  return (
    <div
      className={`${styles.processNode}${selected ? ` ${styles.processNodeSelected}` : ''}`}
      style={
        {
          width: PROCESS_NODE_W,
          height: PROCESS_NODE_H,
          '--stage-accent': accent,
          '--stage-tint': d.stage_name ? stageTint(d.stage_name) : '#f6f5f4',
        } as CSSProperties
      }
    >
      <Handle type="target" position={Position.Top} id="top" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} id="left-target" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Right} id="right-target" style={{ opacity: 0 }} />
      <span className={styles.processAccent} />
      <div className={styles.processBody}>
        <div className={styles.processTitle}>{d.name}</div>
        <div className={styles.processMeta}>
          <span className={styles.processCode}>{d.node_code}</span>
          {d.stage_name && <span className={styles.processStage}>{d.stage_name}</span>}
          <span className={styles.processFields}>{d.fieldCount} 字段</span>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Left} id="left-source" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="right-source" style={{ opacity: 0 }} />
    </div>
  )
}

const nodeTypes = {
  processNode: ProcessNode,
  [MATERIAL_INPUT]: MaterialNode,
  [MATERIAL_OUTPUT]: MaterialNode,
}

export function toRouteFlowElements(
  nodes: RouteNode[],
  edges: RouteEdge[],
): { rfNodes: Node[]; rfEdges: Edge[] } {
  const rfNodes: Node[] = nodes.map(n => ({
    id: n.id,
    type: 'processNode',
    position: { x: 0, y: 0 }, // layoutGraph 会覆盖
    data: {
      name: n.name,
      node_code: n.node_code,
      stage_name: n.stage_name,
      fieldCount: n.fields.length,
    },
  }))

  // ── 为有 intermediates 的工序生成物料节点 ──
  const materialEdges: Edge[] = []
  for (const n of nodes) {
    const intermediates = n.intermediates ?? []
    const inputs = intermediates.filter(i => i.direction === 'input')
    const outputs = intermediates.filter(i => i.direction === 'output')

    if (inputs.length > 0) {
      const inputNodeId = `${n.id}__material-input`
      rfNodes.push({
        id: inputNodeId,
        type: MATERIAL_INPUT,
        position: { x: 0, y: 0 },
        data: {
          parentNodeId: n.id,
          direction: 'input',
          materials: inputs.map(i => ({ name: i.intermediate_type_name || i.intermediate_type_id })),
        } satisfies MaterialNodeData,
      })
      materialEdges.push({
        id: `${n.id}__material-input-edge`,
        source: inputNodeId,
        target: n.id,
        sourceHandle: 'material-source',
        targetHandle: 'left-target',
        type: 'straight',
        style: { stroke: '#dd5b00', strokeDasharray: '4 3', strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#dd5b00' },
      })
    }

    if (outputs.length > 0) {
      const outputNodeId = `${n.id}__material-output`
      rfNodes.push({
        id: outputNodeId,
        type: MATERIAL_OUTPUT,
        position: { x: 0, y: 0 },
        data: {
          parentNodeId: n.id,
          direction: 'output',
          materials: outputs.map(i => ({ name: i.intermediate_type_name || i.intermediate_type_id })),
        } satisfies MaterialNodeData,
      })
      materialEdges.push({
        id: `${n.id}__material-output-edge`,
        source: n.id,
        target: outputNodeId,
        sourceHandle: 'right-source',
        targetHandle: 'material-target',
        type: 'straight',
        style: { stroke: '#1aae39', strokeDasharray: '4 3', strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: '#1aae39' },
      })
    }
  }

  const rfEdges: Edge[] = [
    ...edges.map(e => {
      const isRework = e.edge_type === 'rework'
      const isBoundary = e.is_batch_boundary
      const stroke = isRework
        ? '#dd5b00'
        : e.allow_overlap
          ? '#1aae39'
          : isBoundary
            ? '#5645d4'
            : '#cbc7c1'
      return {
        id: e.id,
        source: e.from_node_id,
        target: e.to_node_id,
        type: 'smoothstep',
        // 仅回流线保留流动动画：主线全部流动会淹没"异常路径"的信号
        animated: isRework,
        sourceHandle: isRework ? 'right-source' : 'bottom',
        targetHandle: isRework ? 'right-target' : 'top',
        pathOptions: isRework ? { borderRadius: 18, offset: 30 } : undefined,
        label: isRework ? '回流' : e.allow_overlap ? '流水线' : isBoundary ? '批次边界' : undefined,
        labelStyle: { fontSize: 10.5, fontWeight: 500, fill: stroke },
        labelBgStyle: { fill: '#ffffff', stroke, strokeWidth: 1 },
        labelBgPadding: [5, 3] as [number, number],
        labelBgBorderRadius: 7,
        style: isRework
          ? { stroke, strokeDasharray: '6 4', strokeWidth: 2 }
          : { stroke, strokeWidth: isBoundary || e.allow_overlap ? 2 : 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13, color: stroke },
      }
    }),
    ...materialEdges,
  ]

  return { rfNodes, rfEdges }
}

interface Props {
  nodes: RouteNode[]
  edges: RouteEdge[]
  onNodeClick?: (nodeId: string) => void
  height?: number | string
}

export function RouteFlowGraph({ nodes, edges, onNodeClick, height = 460 }: Props) {
  const { rfNodes, rfEdges } = useMemo(
    () => toRouteFlowElements(nodes, edges),
    [nodes, edges],
  )
  return (
    <FlowGraph
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick ? (id) => { if (!id.includes('__material-')) onNodeClick(id) } : undefined}
      height={height}
    />
  )
}

'use client'

import { Button, Descriptions, Space, Tag, Tooltip } from 'antd'
import { CloseOutlined, LinkOutlined } from '@ant-design/icons'
import type { GraphNode, GraphEdge as GraphEdgeData } from '@/types/safety'
import {
  NODE_TYPE_STYLE,
  RELATION_TYPE_STYLE,
  ENTITY_TYPE_STYLE,
  NODE_STATUS_LABEL,
  EDGE_STATUS_LABEL,
} from './graphConstants'
import type { GraphNodeType, GraphEntityType, GraphRelationType } from '@/types/safety'

interface DetailProps {
  node: GraphNode | null
  edge: GraphEdgeData | null
  nodes: GraphNode[]
  onClose: () => void
  onNodeClick: (nodeId: string) => void
}

export default function KnowledgeGraphDetail({
  node,
  edge,
  nodes,
  onClose,
  onNodeClick,
}: DetailProps) {
  if (!node && !edge) return null

  const nodeStyle = node ? NODE_TYPE_STYLE[node.node_type as GraphNodeType] : null
  const edgeStyle = edge ? RELATION_TYPE_STYLE[edge.relation_type as GraphRelationType] : null

  // 查找边的源/目标节点
  const sourceNode = edge ? nodes.find((n) => n.id === edge.source_node_id) : null
  const targetNode = edge ? nodes.find((n) => n.id === edge.target_node_id) : null

  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        right: 12,
        width: 320,
        maxHeight: 'calc(100% - 24px)',
        overflowY: 'auto',
        background: 'white',
        borderRadius: 12,
        boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
        zIndex: 10,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 16px',
          borderBottom: '1px solid var(--color-hairline-soft, #ede9e4)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {nodeStyle?.icon && <nodeStyle.icon style={{ fontSize: 16, color: nodeStyle.color }} />}
          {edgeStyle && (
            <LinkOutlined style={{ fontSize: 16, color: edgeStyle.color }} />
          )}
          <span style={{ fontWeight: 600, fontSize: 15, color: 'var(--color-ink-deep, #000)' }}>
            {node ? '节点详情' : '边详情'}
          </span>
        </div>
        <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
      </div>

      {/* Content */}
      <div style={{ padding: '14px 16px' }}>
        {/* Node detail */}
        {node && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{node.name}</div>
              <Space size={4} wrap>
                <Tag color={nodeStyle?.color} style={{ margin: 0 }}>
                  {nodeStyle?.label || node.node_type}
                </Tag>
                <Tag
                  color={node.status === 'human_confirmed' ? 'green' : 'default'}
                  style={{ margin: 0, opacity: node.status === 'ai_generated' ? 0.7 : 1 }}
                >
                  {NODE_STATUS_LABEL[node.status] || node.status}
                </Tag>
                {node.entity_type && (
                  <Tag
                    color={
                      ENTITY_TYPE_STYLE[node.entity_type as GraphEntityType]?.color
                    }
                    style={{ margin: 0 }}
                  >
                    {ENTITY_TYPE_STYLE[node.entity_type as GraphEntityType]?.label || node.entity_type}
                  </Tag>
                )}
              </Space>
            </div>

            {node.aliases && node.aliases.length > 0 && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  别名
                </div>
                <Space size={4} wrap>
                  {node.aliases.map((alias, i) => (
                    <Tag key={i} style={{ margin: 0, fontSize: 12 }}>
                      {alias}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}

            {node.ai_summary && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  AI 摘要
                </div>
                <p style={{ fontSize: 13, color: 'var(--color-charcoal, #37352f)', lineHeight: 1.5, margin: 0 }}>
                  {node.ai_summary}
                </p>
              </div>
            )}

            {node.confidence != null && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  AI 置信度
                </div>
                <div
                  style={{
                    height: 6,
                    borderRadius: 3,
                    background: 'var(--color-hairline, #e5e3df)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${(node.confidence * 100).toFixed(0)}%`,
                      background: node.confidence >= 0.8 ? 'var(--color-brand-green, #1aae39)' : 'var(--color-brand-orange, #dd5b00)',
                      borderRadius: 3,
                    }}
                  />
                </div>
              </div>
            )}
          </Space>
        )}

        {/* Edge detail */}
        {edge && (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <div>
              <Tag color={edgeStyle?.color} style={{ margin: 0, marginBottom: 8 }}>
                {edgeStyle?.label || edge.relation_type}
              </Tag>
              <Tag
                color={edge.status === 'human_confirmed' ? 'green' : 'default'}
                style={{ margin: 0 }}
              >
                {EDGE_STATUS_LABEL[edge.status] || edge.status}
              </Tag>
            </div>

            {/* 源/目标节点 (可点击) */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                源节点
              </div>
              {sourceNode ? (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: 'auto', fontWeight: 500 }}
                  onClick={() => onNodeClick(sourceNode.id)}
                >
                  {sourceNode.name}
                </Button>
              ) : (
                <span style={{ fontSize: 13, color: 'var(--color-muted, #bbb8b1)' }}>
                  {edge.source_node_id}
                </span>
              )}
            </div>

            <div>
              <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                目标节点
              </div>
              {targetNode ? (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: 'auto', fontWeight: 500 }}
                  onClick={() => onNodeClick(targetNode.id)}
                >
                  {targetNode.name}
                </Button>
              ) : (
                <span style={{ fontSize: 13, color: 'var(--color-muted, #bbb8b1)' }}>
                  {edge.target_node_id}
                </span>
              )}
            </div>

            {edge.description && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  关系说明
                </div>
                <p style={{ fontSize: 13, color: 'var(--color-charcoal, #37352f)', lineHeight: 1.5, margin: 0 }}>
                  {edge.description}
                </p>
              </div>
            )}

            {edge.evidence_text && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  原文证据
                </div>
                <p
                  style={{
                    fontSize: 12,
                    color: 'var(--color-slate, #5d5b54)',
                    lineHeight: 1.5,
                    margin: 0,
                    padding: '8px 10px',
                    background: 'var(--color-surface, #f6f5f4)',
                    borderRadius: 6,
                    fontStyle: 'italic',
                  }}
                >
                  {edge.evidence_text}
                </p>
              </div>
            )}

            {edge.confidence != null && (
              <div>
                <div style={{ fontSize: 12, color: 'var(--color-steel, #787671)', marginBottom: 4 }}>
                  AI 置信度
                </div>
                <div
                  style={{
                    height: 6,
                    borderRadius: 3,
                    background: 'var(--color-hairline, #e5e3df)',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${(edge.confidence * 100).toFixed(0)}%`,
                      background: edge.confidence >= 0.8 ? 'var(--color-brand-green, #1aae39)' : 'var(--color-brand-orange, #dd5b00)',
                      borderRadius: 3,
                    }}
                  />
                </div>
              </div>
            )}
          </Space>
        )}
      </div>
    </div>
  )
}

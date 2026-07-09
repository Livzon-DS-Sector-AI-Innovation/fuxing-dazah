'use client'

import { Button, Space, Tag } from 'antd'
import { CloseOutlined } from '@ant-design/icons'
import type { GraphNode, GraphEdge as GraphEdgeData } from '@/types/safety'
import {
  NODE_TYPE_STYLE,
  ENTITY_TYPE_STYLE,
  NODE_STATUS_LABEL,
  RELATION_TYPE_STYLE,
} from './graphConstants'
import type { GraphNodeType, GraphEntityType, GraphRelationType } from '@/types/safety'

interface DetailProps {
  node: GraphNode | null
  /** 子节点列表 (belongs_to 指向此节点) */
  childNodes?: GraphNode[]
  /** 父节点列表 (此节点 belongs_to 指向的) */
  parentNodes?: GraphNode[]
  /** 关联边 (非 belongs_to) */
  relatedEdges?: GraphEdgeData[]
  /** 全局节点 (用于解析关联边的另一端) */
  allNodes?: GraphNode[]
  onClose: () => void
  onNodeClick: (nodeId: string) => void
}

export default function KnowledgeGraphDetail({
  node,
  childNodes = [],
  parentNodes = [],
  relatedEdges = [],
  allNodes = [],
  onClose,
  onNodeClick,
}: DetailProps) {
  if (!node) return null

  const nodeStyle = NODE_TYPE_STYLE[node.node_type as GraphNodeType]
  const isAi = node.status === 'ai_generated'

  return (
    <div
      style={{
        width: 320,
        flexShrink: 0,
        borderLeft: '1px solid var(--color-hairline, #e5e3df)',
        background: 'var(--color-canvas, #ffffff)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
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
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {nodeStyle?.icon && (
            <nodeStyle.icon style={{ fontSize: 16, color: nodeStyle.color }} />
          )}
          <span
            style={{
              fontWeight: 600,
              fontSize: 15,
              color: 'var(--color-ink-deep, #000)',
            }}
          >
            节点详情
          </span>
        </div>
        <Button
          type="text"
          size="small"
          icon={<CloseOutlined />}
          onClick={onClose}
        />
      </div>

      {/* Content */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '14px 16px',
        }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {/* 名称 + 类型标签 */}
          <div>
            <div
              style={{
                fontWeight: 600,
                fontSize: 15,
                marginBottom: 4,
                fontStyle: isAi ? 'italic' : 'normal',
                opacity: isAi ? 0.8 : 1,
              }}
            >
              {node.name}
            </div>
            <Space size={4} wrap>
              <Tag color={nodeStyle?.color} style={{ margin: 0 }}>
                {nodeStyle?.label || node.node_type}
              </Tag>
              <Tag
                color={
                  node.status === 'human_confirmed' ? 'green' : 'default'
                }
                style={{ margin: 0 }}
              >
                {NODE_STATUS_LABEL[node.status] || node.status}
              </Tag>
              {node.entity_type && (
                <Tag
                  color={
                    ENTITY_TYPE_STYLE[node.entity_type as GraphEntityType]
                      ?.color
                  }
                  style={{ margin: 0 }}
                >
                  {ENTITY_TYPE_STYLE[node.entity_type as GraphEntityType]
                    ?.label || node.entity_type}
                </Tag>
              )}
            </Space>
          </div>

          {/* 父节点面包屑 */}
          {parentNodes.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
                所属分类
              </div>
              <Space size={4} wrap>
                {parentNodes.map((p) => (
                  <Button
                    key={p.id}
                    type="link"
                    size="small"
                    style={{ padding: 0, height: 'auto', fontSize: 13 }}
                    onClick={() => onNodeClick(p.id)}
                  >
                    {p.name}
                  </Button>
                ))}
              </Space>
            </div>
          )}

          {/* 别名 */}
          {node.aliases && node.aliases.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
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

          {/* AI 摘要 */}
          {node.ai_summary && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
                AI 摘要
              </div>
              <p
                style={{
                  fontSize: 13,
                  color: 'var(--color-charcoal, #37352f)',
                  lineHeight: 1.5,
                  margin: 0,
                }}
              >
                {node.ai_summary}
              </p>
            </div>
          )}

          {/* 置信度 */}
          {node.confidence != null && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
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
                    background:
                      node.confidence >= 0.8
                        ? 'var(--color-brand-green, #1aae39)'
                        : 'var(--color-brand-orange, #dd5b00)',
                    borderRadius: 3,
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--color-stone, #787671)',
                  marginTop: 2,
                }}
              >
                {(node.confidence * 100).toFixed(0)}%
              </span>
            </div>
          )}

          {/* 子节点列表 */}
          {childNodes.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
                子节点 ({childNodes.length})
              </div>
              <Space direction="vertical" size={2}>
                {childNodes.slice(0, 20).map((c) => (
                  <Button
                    key={c.id}
                    type="link"
                    size="small"
                    style={{
                      padding: 0,
                      height: 'auto',
                      fontSize: 13,
                      textAlign: 'left',
                      display: 'block',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    onClick={() => onNodeClick(c.id)}
                  >
                    {c.name}
                  </Button>
                ))}
                {childNodes.length > 20 && (
                  <span
                    style={{
                      fontSize: 12,
                      color: 'var(--color-stone, #787671)',
                    }}
                  >
                    ...还有 {childNodes.length - 20} 个
                  </span>
                )}
              </Space>
            </div>
          )}

          {/* 关联关系 */}
          {relatedEdges.length > 0 && (
            <div>
              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-steel, #787671)',
                  marginBottom: 4,
                }}
              >
                关联关系 ({relatedEdges.length})
              </div>
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                {relatedEdges.slice(0, 15).map((e) => {
                  const style =
                    RELATION_TYPE_STYLE[e.relation_type as GraphRelationType]
                  const otherId =
                    e.source_node_id === node.id
                      ? e.target_node_id
                      : e.source_node_id
                  const otherNode = allNodes.find((n) => n.id === otherId)

                  return (
                    <div
                      key={e.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: 12,
                      }}
                    >
                      <Tag
                        color={style?.color}
                        style={{ margin: 0, fontSize: 11, lineHeight: '18px' }}
                      >
                        {style?.label || e.relation_type}
                      </Tag>
                      {otherNode ? (
                        <Button
                          type="link"
                          size="small"
                          style={{
                            padding: 0,
                            height: 'auto',
                            fontSize: 12,
                            flex: 1,
                            minWidth: 0,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            textAlign: 'left',
                          }}
                          onClick={() => onNodeClick(otherNode.id)}
                        >
                          {otherNode.name}
                        </Button>
                      ) : (
                        <span
                          style={{
                            color: 'var(--color-muted, #bbb8b1)',
                            flex: 1,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {otherId}
                        </span>
                      )}
                    </div>
                  )
                })}
                {relatedEdges.length > 15 && (
                  <span
                    style={{
                      fontSize: 12,
                      color: 'var(--color-stone, #787671)',
                    }}
                  >
                    ...还有 {relatedEdges.length - 15} 条
                  </span>
                )}
              </Space>
            </div>
          )}
        </Space>
      </div>
    </div>
  )
}

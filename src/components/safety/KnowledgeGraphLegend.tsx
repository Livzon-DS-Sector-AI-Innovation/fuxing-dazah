'use client'

import { useState } from 'react'
import { Button, Popover, Space, Tag } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import {
  NODE_TYPE_STYLE,
  RELATION_TYPE_STYLE,
  NODE_STATUS_LABEL,
} from './graphConstants'
import type { GraphNodeType, GraphRelationType } from '@/types/safety'

export default function KnowledgeGraphLegend() {
  const [open, setOpen] = useState(false)

  const content = (
    <div style={{ width: 260 }}>
      {/* 节点类型 */}
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>节点类型</div>
      <Space direction="vertical" size={4} style={{ width: '100%', marginBottom: 16 }}>
        {(Object.entries(NODE_TYPE_STYLE) as [GraphNodeType, typeof NODE_TYPE_STYLE[GraphNodeType]][]).map(
          ([type, style]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div
                style={{
                  width: 32,
                  height: 20,
                  borderRadius: 4,
                  background: style.bg,
                  border: `1.5px solid ${style.color}`,
                }}
              />
              <span style={{ fontSize: 12, color: 'var(--color-charcoal, #37352f)' }}>
                {style.label}
              </span>
            </div>
          ),
        )}
      </Space>

      {/* 关系类型 */}
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>关系类型</div>
      <Space direction="vertical" size={4} style={{ width: '100%', marginBottom: 16 }}>
        {(Object.entries(RELATION_TYPE_STYLE) as [GraphRelationType, typeof RELATION_TYPE_STYLE[GraphRelationType]][]).map(
          ([type, style]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width={32} height={14}>
                <line
                  x1={2} y1={7} x2={28} y2={7}
                  stroke={style.color}
                  strokeWidth={style.strokeWidth * 0.8}
                  strokeDasharray={style.strokeDasharray || undefined}
                />
                {type === 'conflicts_with' && (
                  <polygon points="28,4 30,7 28,10" fill={style.color} />
                )}
                {type !== 'conflicts_with' && (
                  <polygon points="28,4 30,7 28,10" fill={style.color} />
                )}
              </svg>
              <span style={{ fontSize: 12, color: 'var(--color-charcoal, #37352f)' }}>
                {style.label}
              </span>
            </div>
          ),
        )}
      </Space>

      {/* 状态标记 */}
      <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>状态标记</div>
      <div style={{ fontSize: 12, color: 'var(--color-slate, #5d5b54)', lineHeight: 1.6 }}>
        <em style={{ opacity: 0.7 }}>斜体+半透明</em> = AI 生成待审核<br />
        <span style={{ fontWeight: 500 }}>正常字重</span> = 人工已确认
      </div>
    </div>
  )

  return (
    <Popover
      content={content}
      title="图例"
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="leftBottom"
    >
      <Button
        size="small"
        icon={<QuestionCircleOutlined />}
        style={{
          background: 'white',
          borderRadius: 8,
          boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
          fontWeight: 500,
        }}
      >
        图例
      </Button>
    </Popover>
  )
}

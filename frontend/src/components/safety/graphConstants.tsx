'use client'

/** 知识图谱常量 — 节点/边样式、颜色映射、关系类型标签 */

import type { GraphNodeType, GraphRelationType, GraphEntityType } from '@/types/safety'
import {
  SafetyOutlined,
  FileTextOutlined,
  NumberOutlined,
  ApartmentOutlined,
  BulbOutlined,
} from '@ant-design/icons'
import type { ComponentType } from 'react'

// Ant Design 图标组件类型 (接受 style 等 props)
type AntdIcon = ComponentType<{ style?: React.CSSProperties }>

// ── 节点类型配色 (DESIGN.md tokens) ─────────────────────

export const NODE_TYPE_STYLE: Record<GraphNodeType, { color: string; bg: string; label: string; icon: AntdIcon }> = {
  document:  { color: '#0a1530', bg: '#e8ecf2', label: '法规文档', icon: FileTextOutlined },
  clause:    { color: '#5645d4', bg: '#eeebfa', label: '法规条款', icon: NumberOutlined },
  entity:    { color: '#dd5b00', bg: '#fceee6', label: '安全实体', icon: SafetyOutlined },
  category:  { color: '#2a9d99', bg: '#eaf5f5', label: '分类节点', icon: ApartmentOutlined },
  concept:   { color: '#7b3ff2', bg: '#f1ecfc', label: '概念',      icon: BulbOutlined },
}

// ── 实体类别配色 ────────────────────────────────────────

export const ENTITY_TYPE_STYLE: Record<GraphEntityType, { color: string; label: string }> = {
  equipment:  { color: '#dd5b00', label: '设备' },
  condition:  { color: '#e03131', label: '状态' },
  location:   { color: '#2a9d99', label: '场所' },
  operation:  { color: '#5645d4', label: '作业' },
  material:   { color: '#1aae39', label: '物料' },
  standard:   { color: '#0a1530', label: '标准' },
}

// ── 关系类型样式 ────────────────────────────────────────

export const RELATION_TYPE_STYLE: Record<GraphRelationType, {
  color: string
  strokeDasharray: string
  strokeWidth: number
  label: string
  markerEnd?: string
}> = {
  cites:          { color: '#1a1a1a', strokeDasharray: '',         strokeWidth: 2,   label: '引用'      },
  supplements:    { color: '#2a9d99', strokeDasharray: '6,3',      strokeWidth: 1.5, label: '补充'      },
  replaces:       { color: '#e03131', strokeDasharray: '',         strokeWidth: 3,   label: '替代',     markerEnd: 'arrowclosed' },
  belongs_to:     { color: '#5d5b54', strokeDasharray: '3,3',      strokeWidth: 1.5, label: '归属'      },
  related_to:     { color: '#787671', strokeDasharray: '8,4',      strokeWidth: 1.5, label: '相关'      },
  conflicts_with: { color: '#dd5b00', strokeDasharray: '',         strokeWidth: 2,   label: '冲突',     markerEnd: 'arrowclosed' },
}

// ── 状态标签 ────────────────────────────────────────────

export const NODE_STATUS_LABEL: Record<string, string> = {
  ai_generated:    'AI生成',
  human_confirmed: '已确认',
  deprecated:      '待删除',
  merged:          '已合并',
}

export const EDGE_STATUS_LABEL: Record<string, string> = {
  ai_generated:    'AI生成',
  human_confirmed: '已确认',
  human_deleted:   '已删除',
  human_added:     '人工新增',
}

// ── React Flow 节点默认配置 ──────────────────────────────

export const DEFAULT_NODE_STYLE = {
  padding: '8px 14px',
  borderRadius: '8px',
  fontSize: '13px',
  fontWeight: 500,
  border: '1.5px solid',
  minWidth: 120,
  maxWidth: 220,
  textAlign: 'center' as const,
}

export const AI_GENERATED_OPACITY = 0.75
export const HUMAN_CONFIRMED_OPACITY = 1.0

// ── 筛选选项 ────────────────────────────────────────────

export const NODE_TYPE_OPTIONS = Object.entries(NODE_TYPE_STYLE).map(([value, { label }]) => ({
  value,
  label,
}))

export const RELATION_TYPE_OPTIONS = Object.entries(RELATION_TYPE_STYLE).map(([value, { label }]) => ({
  value,
  label,
}))

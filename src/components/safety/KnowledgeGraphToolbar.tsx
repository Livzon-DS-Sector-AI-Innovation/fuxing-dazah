'use client'

import { useState, useCallback } from 'react'
import { Button, Input, Select, Space, Tooltip, App } from 'antd'
import {
  SearchOutlined,
  ReloadOutlined,
  ExpandOutlined,
  ExportOutlined,
} from '@ant-design/icons'
import { Panel } from '@xyflow/react'
import type { GraphNode } from '@/types/safety'
import { searchGraphNodes } from '@/actions/safety/knowledge-graph'
import { useKnowledgeGraphStore } from '@/stores/safety/knowledgeGraphStore'
import { NODE_TYPE_OPTIONS, RELATION_TYPE_OPTIONS } from './graphConstants'

interface ToolbarProps {
  onRefresh: () => void
  loading: boolean
  onFitView: () => void
}

export default function KnowledgeGraphToolbar({
  onRefresh,
  loading,
  onFitView,
}: ToolbarProps) {
  const { message } = App.useApp()
  const store = useKnowledgeGraphStore()
  const [searching, setSearching] = useState(false)

  // 搜索
  const handleSearch = useCallback(
    async (value: string) => {
      store.setSearchQuery(value)
      if (!value.trim()) {
        store.setSearchResults([])
        return
      }
      setSearching(true)
      try {
        const results = await searchGraphNodes(value, store.nodeTypeFilter || undefined)
        store.setSearchResults(results)
        if (results.length === 0) {
          message.info('未找到匹配节点')
        } else {
          message.success(`找到 ${results.length} 个节点`)
        }
      } catch {
        message.error('搜索失败')
      } finally {
        setSearching(false)
      }
    },
    [store, message],
  )

  // 导出图片
  const handleExport = useCallback(() => {
    const svgElement = document.querySelector('.react-flow__renderer svg')
    if (!svgElement) {
      message.warning('未找到画布元素')
      return
    }
    const serializer = new XMLSerializer()
    const svgStr = serializer.serializeToString(svgElement)
    const blob = new Blob([svgStr], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `知识图谱_${new Date().toISOString().slice(0, 10)}.svg`
    a.click()
    URL.revokeObjectURL(url)
    message.success('导出成功')
  }, [message])

  return (
    <Panel position="top-left" style={{ margin: 12 }}>
      <div
        style={{
          background: 'white',
          borderRadius: 10,
          padding: '8px 12px',
          boxShadow: '0 1px 6px rgba(0,0,0,0.08)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        {/* 搜索 */}
        <Input.Search
          placeholder="搜索节点..."
          allowClear
          size="small"
          style={{ width: 200 }}
          loading={searching}
          onSearch={handleSearch}
          onClear={() => store.setSearchResults([])}
        />

        <div style={{ width: 1, height: 20, background: 'var(--color-hairline, #e5e3df)' }} />

        {/* 节点类型筛选 */}
        <Select
          size="small"
          placeholder="节点类型"
          allowClear
          style={{ minWidth: 110 }}
          value={store.nodeTypeFilter}
          onChange={store.setNodeTypeFilter}
          options={NODE_TYPE_OPTIONS}
        />

        {/* 关系类型筛选 */}
        <Select
          size="small"
          placeholder="关系类型"
          allowClear
          style={{ minWidth: 100 }}
          value={store.relationTypeFilter}
          onChange={store.setRelationTypeFilter}
          options={RELATION_TYPE_OPTIONS}
        />

        <div style={{ width: 1, height: 20, background: 'var(--color-hairline, #e5e3df)' }} />

        {/* 操作按钮 */}
        <Space size={4}>
          <Tooltip title="刷新">
            <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh} />
          </Tooltip>
          <Tooltip title="适应画布">
            <Button size="small" icon={<ExpandOutlined />} onClick={onFitView} />
          </Tooltip>
          <Tooltip title="导出 SVG">
            <Button size="small" icon={<ExportOutlined />} onClick={handleExport} />
          </Tooltip>
        </Space>
      </div>
    </Panel>
  )
}

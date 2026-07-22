'use client'

import { useEffect, useMemo, useCallback, useRef, useState } from 'react'
import { App, Spin, Tag } from 'antd'
import { SearchOutlined, ApartmentOutlined, CloseOutlined } from '@ant-design/icons'
import type { GraphNode } from '@/types/safety'
import { getFullGraph } from '@/actions/safety/knowledge-graph'
import { useKnowledgeGraphStore } from '@/stores/safety/knowledgeGraphStore'
import {
  buildTreeData,
  searchTree,
  getAncestorIds,
} from '@/lib/buildTreeData'
import type { KnowledgeTreeNode } from '@/lib/buildTreeData'
import KnowledgeGraphTreeNode from './KnowledgeGraphTreeNode'
import {
  NODE_TYPE_STYLE,
  ENTITY_TYPE_STYLE,
  NODE_STATUS_LABEL,
  RELATION_TYPE_STYLE,
} from './graphConstants'
import type { GraphNodeType, GraphEntityType, GraphRelationType } from '@/types/safety'

// ═══════════════════════════════════════════════════════════════
// KnowledgeGraphTree — AI 文档导航索引
//
// 定位：RAG 检索的第一层索引，AI 和人都能快速定位文档。
// 设计：搜索框 → 面包屑 → 高密度目录树 → 内联详情面板
// ═══════════════════════════════════════════════════════════════

export default function KnowledgeGraphTree() {
  const { message } = App.useApp()
  const store = useKnowledgeGraphStore()
  const searchRef = useRef<HTMLInputElement>(null)
  const treeRef = useRef<HTMLDivElement>(null)
  const [searchInput, setSearchInput] = useState('')
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── 数据加载 ──────────────────────────────────────────

  const loadGraph = useCallback(async () => {
    store.setLoading(true)
    try {
      const data = await getFullGraph({ max_nodes: 500 })
      store.setGraphData(data)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '加载失败'
      store.setError(msg)
      message.error(msg)
    } finally {
      store.setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadGraph()
  }, [loadGraph])

  // ── 构建树 ─────────────────────────────────────────────

  const { roots, nodeMap } = useMemo(
    () => buildTreeData(store.nodes, store.edges),
    [store.nodes, store.edges],
  )

  // 默认展开前 2 层
  useEffect(() => {
    if (roots.length === 0) return
    const keys = new Set<string>()
    for (const root of roots) {
      if (root.children.length > 0) {
        keys.add(root.id)
        for (const child of root.children) {
          if (child.children.length > 0) keys.add(child.id)
        }
      }
    }
    store.setExpandedKeys(keys)
  }, [roots])

  // ── 搜索 ──────────────────────────────────────────────

  const matchedKeys = useMemo(
    () => searchTree(roots, store.searchQuery),
    [roots, store.searchQuery],
  )

  // 搜索时自动展开匹配路径
  useEffect(() => {
    if (!store.searchQuery.trim()) return
    const toExpand = new Set(store.expandedKeys)
    for (const key of matchedKeys) {
      const ancestors = getAncestorIds(key, nodeMap)
      for (const a of ancestors) toExpand.add(a)
    }
    store.setExpandedKeys(toExpand)
  }, [matchedKeys])

  // 防抖搜索
  const handleSearch = useCallback((value: string) => {
    setSearchInput(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => store.setSearchQuery(value), 150)
  }, [])

  const clearSearch = useCallback(() => {
    setSearchInput('')
    store.setSearchQuery('')
    searchRef.current?.focus()
  }, [])

  // ── Ctrl+K / Escape 快捷键 ───────────────────────────

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
        searchRef.current?.select()
      }
      if (e.key === 'Escape') {
        if (store.searchQuery) {
          clearSearch()
        } else if (store.selectedNodeId) {
          store.selectNode(null)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [clearSearch])

  // ── 键盘导航（↑↓ 在可见节点间移动，←→ 折叠/展开）───

  const flatVisibleIds = useMemo(() => {
    const ids: string[] = []
    function walk(node: KnowledgeTreeNode) {
      ids.push(node.id)
      if (store.expandedKeys.has(node.id)) {
        for (const child of node.children) walk(child)
      }
    }
    for (const root of roots) walk(root)
    return ids
  }, [roots, store.expandedKeys])

  const [focusIndex, setFocusIndex] = useState(-1)

  // 选中节点变化时同步 focusIndex
  useEffect(() => {
    if (store.selectedNodeId) {
      const idx = flatVisibleIds.indexOf(store.selectedNodeId)
      if (idx !== -1) setFocusIndex(idx)
    }
  }, [store.selectedNodeId])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (document.activeElement === searchRef.current) return
      if (flatVisibleIds.length === 0) return

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusIndex((i) => Math.min(i + 1, flatVisibleIds.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusIndex((i) => Math.max(i - 1, 0))
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        const id = flatVisibleIds[focusIndex] || flatVisibleIds[0]
        if (id) {
          const n = nodeMap.get(id)
          if (n && n.children.length > 0 && !store.expandedKeys.has(id)) {
            store.toggleExpanded(id)
          }
        }
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        const id = flatVisibleIds[focusIndex] || flatVisibleIds[0]
        if (id) {
          const n = nodeMap.get(id)
          if (n && n.children.length > 0 && store.expandedKeys.has(id)) {
            store.toggleExpanded(id)
          }
        }
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const id = flatVisibleIds[focusIndex] || flatVisibleIds[0]
        if (id) {
          store.selectNode(id)
          ;(treeRef.current as HTMLElement | null)?.focus()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [flatVisibleIds, focusIndex, nodeMap])

  // 聚焦节点滚入视图
  useEffect(() => {
    if (focusIndex < 0) return
    const id = flatVisibleIds[focusIndex]
    if (!id) return
    const escapedId = CSS.escape(id)
    const el = treeRef.current?.querySelector(
      `[data-node-id="${escapedId}"]`,
    )
    if (el) {
      ;(el as HTMLElement).scrollIntoView({
        block: 'nearest',
        behavior: 'smooth',
      })
    }
  }, [focusIndex])

  // ── 节点操作 ──────────────────────────────────────────

  const handleSelect = useCallback(
    (node: KnowledgeTreeNode) => {
      store.selectNode(store.selectedNodeId === node.id ? null : node.id)
    },
    [store.selectedNodeId],
  )

  const handleToggle = useCallback((nodeId: string) => {
    store.toggleExpanded(nodeId)
  }, [])

  // ── 面包屑 ────────────────────────────────────────────

  const breadcrumbs: KnowledgeTreeNode[] = useMemo(() => {
    if (!store.selectedNodeId) return []
    const path: KnowledgeTreeNode[] = []
    let current: KnowledgeTreeNode | undefined =
      nodeMap.get(store.selectedNodeId)
    while (current) {
      path.unshift(current)
      let parent: KnowledgeTreeNode | undefined
      for (const [, n] of nodeMap) {
        if (n.children.some((c) => c.id === current!.id)) {
          parent = n
          break
        }
      }
      current = parent
    }
    return path
  }, [store.selectedNodeId, nodeMap])

  // ── 选中节点的关联数据 ─────────────────────────────────

  const selectedNodeData = useMemo<GraphNode | null>(() => {
    if (!store.selectedNodeId) return null
    return store.nodes.find((n) => n.id === store.selectedNodeId) || null
  }, [store.nodes, store.selectedNodeId])

  const selectedRelations = useMemo(() => {
    if (!store.selectedNodeId) return []
    return store.edges.filter(
      (e) =>
        e.relation_type !== 'belongs_to' &&
        (e.source_node_id === store.selectedNodeId ||
          e.target_node_id === store.selectedNodeId),
    )
  }, [store.edges, store.selectedNodeId])

  const selectedChildren = useMemo(() => {
    if (!store.selectedNodeId) return []
    const childIds = store.edges
      .filter(
        (e) =>
          e.relation_type === 'belongs_to' &&
          e.target_node_id === store.selectedNodeId,
      )
      .map((e) => e.source_node_id)
    return store.nodes.filter((n) => childIds.includes(n.id))
  }, [store.nodes, store.edges, store.selectedNodeId])

  // ── 渲染：加载态 ──────────────────────────────────────

  if (store.loading && store.nodes.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          gap: 16,
        }}
      >
        <Spin size="default" />
        <span style={{ color: 'var(--color-steel, #787671)', fontSize: 14 }}>
          加载 AI 检索索引…
        </span>
      </div>
    )
  }

  // ── 渲染：空态 ────────────────────────────────────────

  if (!store.loading && store.nodes.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          gap: 12,
        }}
      >
        <div style={{ fontSize: 40, opacity: 0.3 }}>📭</div>
        <p
          style={{
            color: 'var(--color-steel, #787671)',
            margin: 0,
            fontSize: 14,
          }}
        >
          暂无索引数据
        </p>
        <p
          style={{
            color: 'var(--color-steel, #787671)',
            fontSize: 12,
            margin: 0,
          }}
        >
          同步知识库文档后，AI 将自动构建检索索引
        </p>
      </div>
    )
  }

  // ── 渲染 ──────────────────────────────────────────────

  const nodeStyle = selectedNodeData
    ? NODE_TYPE_STYLE[selectedNodeData.node_type as GraphNodeType]
    : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ═══════════════════════════════════════════════════
          搜索栏 — 页面核心交互
          ═══════════════════════════════════════════════════ */}

      <div
        style={{
          padding: '16px 20px 10px',
          flexShrink: 0,
          background: 'var(--color-canvas, #ffffff)',
        }}
      >
        <div style={{ position: 'relative', maxWidth: 560 }}>
          <SearchOutlined
            style={{
              position: 'absolute',
              left: 14,
              top: '50%',
              transform: 'translateY(-50%)',
              fontSize: 16,
              color: 'var(--color-steel, #787671)',
              pointerEvents: 'none',
            }}
          />
          <input
            ref={searchRef}
            type="text"
            value={searchInput}
            onChange={(e) => handleSearch(e.target.value)}
            placeholder="搜索法规、分类、概念…"
            aria-label="搜索知识库节点"
            style={{
              width: '100%',
              height: 40,
              paddingLeft: 40,
              paddingRight: store.searchQuery ? 72 : 60,
              borderRadius: 8,
              border: '1px solid var(--color-hairline, #ddd9d3)',
              background: 'var(--color-surface-soft, #fafaf9)',
              fontSize: 14,
              lineHeight: '40px',
              color: 'var(--color-charcoal, #37352f)',
              outline: 'none',
              boxSizing: 'border-box',
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor =
                'var(--color-primary, #5645d4)'
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor =
                'var(--color-hairline, #ddd9d3)'
            }}
          />

          {/* 清除按钮 */}
          {store.searchQuery && (
            <button
              onClick={clearSearch}
              aria-label="清除搜索"
              style={{
                position: 'absolute',
                right: 56,
                top: '50%',
                transform: 'translateY(-50%)',
                border: 'none',
                background: 'none',
                cursor: 'pointer',
                padding: 2,
                color: 'var(--color-stone, #a4a097)',
                fontSize: 16,
                lineHeight: 1,
              }}
            >
              <CloseOutlined style={{ fontSize: 12 }} />
            </button>
          )}

          {/* Ctrl+K */}
          <kbd
            style={{
              position: 'absolute',
              right: 10,
              top: '50%',
              transform: 'translateY(-50%)',
              fontSize: 11,
              fontFamily:
                'var(--font-mono, "SF Mono", "Cascadia Code", Consolas, monospace)',
              color: 'var(--color-stone, #a4a097)',
              background: 'var(--color-canvas, #ffffff)',
              border: '1px solid var(--color-hairline, #ddd9d3)',
              borderRadius: 4,
              padding: '1px 5px',
              lineHeight: '16px',
              pointerEvents: 'none',
            }}
          >
            Ctrl+K
          </kbd>

          {/* 结果计数 */}
          {store.searchQuery && (
            <span
              style={{
                position: 'absolute',
                left: 14,
                bottom: -18,
                fontSize: 11,
                color: 'var(--color-steel, #787671)',
              }}
            >
              {matchedKeys.size} 个匹配
            </span>
          )}
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════
          面包屑
          ═══════════════════════════════════════════════════ */}

      {breadcrumbs.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 2,
            padding: '6px 20px',
            fontSize: 12,
            color: 'var(--color-steel, #787671)',
            borderBottom: '1px solid var(--color-hairline-soft, #f0ede8)',
            flexShrink: 0,
            overflowX: 'auto',
            whiteSpace: 'nowrap',
          }}
        >
          <ApartmentOutlined style={{ marginRight: 4, fontSize: 13 }} />
          {breadcrumbs.map((crumb, i) => (
            <span
              key={crumb.id}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
              }}
            >
              {i > 0 && (
                <span
                  style={{
                    color: 'var(--color-stone, #a4a097)',
                    margin: '0 2px',
                  }}
                >
                  ›
                </span>
              )}
              <button
                onClick={() => store.selectNode(crumb.id)}
                style={{
                  border: 'none',
                  background: 'none',
                  cursor: 'pointer',
                  padding: '1px 4px',
                  fontSize: 12,
                  color:
                    i === breadcrumbs.length - 1
                      ? 'var(--color-charcoal, #37352f)'
                      : 'var(--color-steel, #787671)',
                  fontWeight: i === breadcrumbs.length - 1 ? 600 : 400,
                  borderRadius: 3,
                }}
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════
          目录树
          ═══════════════════════════════════════════════════ */}

      <div
        ref={treeRef}
        tabIndex={0}
        role="tree"
        aria-label="知识库文档导航索引"
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '6px 0',
          outline: 'none',
        }}
      >
        {roots.map((root) => (
          <KnowledgeGraphTreeNode
            key={root.id}
            node={root}
            level={0}
            selectedId={store.selectedNodeId}
            focusedId={flatVisibleIds[focusIndex] || null}
            expandedKeys={store.expandedKeys}
            searchQuery={store.searchQuery}
            onSelect={handleSelect}
            onToggleExpand={handleToggle}
          />
        ))}

        {/* 底部统计 */}
        <div
          style={{
            padding: '8px 20px',
            fontSize: 11,
            color: 'var(--color-stone, #a4a097)',
          }}
        >
          {store.nodes.length} 个节点 · {store.edges.length} 条关系 · AI
          索引
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════
          内联详情面板（替代右侧侧边面板）
          ═══════════════════════════════════════════════════ */}

      {selectedNodeData && (
        <div
          style={{
            flexShrink: 0,
            maxHeight: 220,
            overflowY: 'auto',
            borderTop: '1px solid var(--color-hairline, #ddd9d3)',
            background: 'var(--color-surface-soft, #fafaf9)',
            padding: '12px 20px',
          }}
        >
          {/* 标题行 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              marginBottom: 8,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontWeight: 600,
                  fontSize: 14,
                  color: 'var(--color-ink, #1a1a1a)',
                  marginBottom: 4,
                  fontStyle:
                    selectedNodeData.status === 'ai_generated'
                      ? 'italic'
                      : 'normal',
                }}
              >
                {selectedNodeData.name}
              </div>

              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {nodeStyle && (
                  <Tag
                    color={nodeStyle.color}
                    style={{ margin: 0, fontSize: 11 }}
                  >
                    {nodeStyle.label}
                  </Tag>
                )}
                {selectedNodeData.entity_type && (
                  <Tag
                    color={
                      ENTITY_TYPE_STYLE[
                        selectedNodeData.entity_type as GraphEntityType
                      ]?.color
                    }
                    style={{ margin: 0, fontSize: 11 }}
                  >
                    {
                      ENTITY_TYPE_STYLE[
                        selectedNodeData.entity_type as GraphEntityType
                      ]?.label
                    }
                  </Tag>
                )}
                <Tag
                  color={
                    selectedNodeData.status === 'human_confirmed'
                      ? 'green'
                      : 'default'
                  }
                  style={{ margin: 0, fontSize: 11 }}
                >
                  {NODE_STATUS_LABEL[selectedNodeData.status] ||
                    selectedNodeData.status}
                </Tag>
                {selectedNodeData.confidence != null && (
                  <span
                    style={{
                      fontSize: 11,
                      color: 'var(--color-steel, #787671)',
                    }}
                  >
                    置信度{' '}
                    {(selectedNodeData.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>

            <button
              onClick={() => store.selectNode(null)}
              aria-label="关闭详情"
              style={{
                border: 'none',
                background: 'none',
                cursor: 'pointer',
                padding: 2,
                color: 'var(--color-stone, #a4a097)',
                fontSize: 16,
                lineHeight: 1,
                flexShrink: 0,
              }}
            >
              <CloseOutlined style={{ fontSize: 14 }} />
            </button>
          </div>

          {/* AI 摘要 */}
          {selectedNodeData.ai_summary && (
            <div style={{ marginBottom: 8 }}>
              <p
                style={{
                  fontSize: 12,
                  color: 'var(--color-charcoal, #37352f)',
                  lineHeight: 1.5,
                  margin: 0,
                }}
              >
                {selectedNodeData.ai_summary}
              </p>
            </div>
          )}

          {/* 别名 */}
          {selectedNodeData.aliases &&
            selectedNodeData.aliases.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  gap: 4,
                  flexWrap: 'wrap',
                  marginBottom: 8,
                }}
              >
                {selectedNodeData.aliases.map((alias, i) => (
                  <Tag key={i} style={{ margin: 0, fontSize: 11 }}>
                    {alias}
                  </Tag>
                ))}
              </div>
            )}

          {/* 子文档 + 关联文档 快速跳转 */}
          {(selectedChildren.length > 0 ||
            selectedRelations.length > 0) && (
            <div
              style={{
                display: 'flex',
                gap: 4,
                flexWrap: 'wrap',
                alignItems: 'center',
                fontSize: 11,
                color: 'var(--color-steel, #787671)',
              }}
            >
              {selectedChildren.length > 0 && (
                <>
                  <span>包含:</span>
                  {selectedChildren.slice(0, 8).map((child) => (
                    <button
                      key={child.id}
                      onClick={() => store.selectNode(child.id)}
                      style={{
                        border: '1px solid var(--color-hairline, #ddd9d3)',
                        background: 'var(--color-canvas, #ffffff)',
                        borderRadius: 4,
                        padding: '1px 6px',
                        fontSize: 11,
                        cursor: 'pointer',
                        color: 'var(--color-charcoal, #37352f)',
                        maxWidth: 200,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {child.name}
                    </button>
                  ))}
                  {selectedChildren.length > 8 && (
                    <span>…+{selectedChildren.length - 8}</span>
                  )}
                </>
              )}

              {selectedRelations.length > 0 && (
                <>
                  {selectedChildren.length > 0 && (
                    <span style={{ margin: '0 4px' }}>·</span>
                  )}
                  <span>关联:</span>
                  {selectedRelations.slice(0, 6).map((edge) => {
                    const relStyle =
                      RELATION_TYPE_STYLE[
                        edge.relation_type as GraphRelationType
                      ]
                    const otherId =
                      edge.source_node_id === selectedNodeData.id
                        ? edge.target_node_id
                        : edge.source_node_id
                    const otherNode = store.nodes.find(
                      (n) => n.id === otherId,
                    )
                    return (
                      <button
                        key={edge.id}
                        onClick={() => store.selectNode(otherId)}
                        style={{
                          border: '1px solid var(--color-hairline, #ddd9d3)',
                          background: 'var(--color-canvas, #ffffff)',
                          borderRadius: 4,
                          padding: '1px 6px',
                          fontSize: 11,
                          cursor: 'pointer',
                          color:
                            relStyle?.color ||
                            'var(--color-charcoal, #37352f)',
                          maxWidth: 200,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                        title={`${relStyle?.label || edge.relation_type}: ${otherNode?.name || otherId}`}
                      >
                        {relStyle?.label || edge.relation_type}:{' '}
                        {otherNode?.name || otherId}
                      </button>
                    )
                  })}
                  {selectedRelations.length > 6 && (
                    <span>…+{selectedRelations.length - 6}</span>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

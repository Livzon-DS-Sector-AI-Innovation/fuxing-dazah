'use client'

import type { GraphNode, GraphEdge } from '@/types/safety'

/** 树节点 — 用于目录树渲染 */
export interface KnowledgeTreeNode {
  /** 节点唯一标识 (GraphNode.id) */
  id: string
  /** 节点名称 */
  name: string
  /** 节点类型 */
  nodeType: string
  /** 实体子类型（仅 entity 节点） */
  entityType?: string | null
  /** AI/人工状态 */
  status: string
  /** AI 生成摘要 */
  aiSummary?: string | null
  /** 别名列表 */
  aliases?: string[] | null
  /** AI 置信度 */
  confidence?: number | null
  /** 关联的知识库文章 ID */
  articleId?: string | null
  /** 元数据 */
  metadata?: Record<string, unknown> | null
  /** 创建时间 */
  createdAt?: string | null
  /** 子节点 */
  children: KnowledgeTreeNode[]
  /** 总子孙节点数（含自身） */
  childCount: number
  /** 深度（根 = 0） */
  depth: number
}

/**
 * 将 flat 的 nodes + edges 转为嵌套的树结构。
 *
 * 规则：
 * - belongs_to 边: child(source) → parent(target)
 * - 没有被任何 belongs_to 指向的 category 节点是根
 * - entity 节点挂在 category 下
 * - 孤儿节点（无 belongs_to 的 entity）→ 挂到虚拟"未分类"根
 *
 * @returns { roots, nodeMap } — 根节点数组 + id→KnowledgeTreeNode 映射
 */
export function buildTreeData(
  nodes: GraphNode[],
  edges: GraphEdge[],
): { roots: KnowledgeTreeNode[]; nodeMap: Map<string, KnowledgeTreeNode> } {
  const nodeMap = new Map<string, GraphNode>()
  for (const n of nodes) {
    nodeMap.set(n.id, n)
  }

  // childId → parentIds (从 belongs_to 边)
  const childParents = new Map<string, string[]>()
  const parentChildren = new Map<string, string[]>()
  for (const e of edges) {
    if (e.relation_type !== 'belongs_to') continue
    // source = child, target = parent
    if (!childParents.has(e.source_node_id)) {
      childParents.set(e.source_node_id, [])
    }
    childParents.get(e.source_node_id)!.push(e.target_node_id)

    if (!parentChildren.has(e.target_node_id)) {
      parentChildren.set(e.target_node_id, [])
    }
    parentChildren.get(e.target_node_id)!.push(e.source_node_id)
  }

  // 标记所有被其他节点指向的节点（作为子节点的节点）
  const isChild = new Set(childParents.keys())

  // 找根节点：category 节点中，没有被 belongs_to 指向的
  const rootCandidates = nodes.filter(
    (n) => n.node_type === 'category' && !isChild.has(n.id),
  )

  // 递归构建
  const built = new Set<string>()
  const treeMap = new Map<string, KnowledgeTreeNode>()

  function buildSubtree(nodeId: string, depth: number): KnowledgeTreeNode | null {
    const node = nodeMap.get(nodeId)
    if (!node || built.has(nodeId)) return null
    built.add(nodeId)

    const childIds = parentChildren.get(nodeId) || []
    const children: KnowledgeTreeNode[] = []
    for (const cid of childIds) {
      const child = buildSubtree(cid, depth + 1)
      if (child) children.push(child)
    }

    // 排序：category 在前，entity 在后；同类按名称字母
    children.sort((a, b) => {
      if (a.nodeType === 'category' && b.nodeType !== 'category') return -1
      if (a.nodeType !== 'category' && b.nodeType === 'category') return 1
      return a.name.localeCompare(b.name, 'zh-CN')
    })

    const childCount = 1 + children.reduce((sum, c) => sum + c.childCount, 0)

    const treeNode: KnowledgeTreeNode = {
      id: node.id,
      name: node.name,
      nodeType: node.node_type,
      entityType: node.entity_type,
      status: node.status,
      aiSummary: node.ai_summary,
      aliases: node.aliases,
      confidence: node.confidence,
      articleId: node.article_id,
      metadata: node.metadata,
      createdAt: node.created_at,
      children,
      childCount,
      depth,
    }
    treeMap.set(nodeId, treeNode)
    return treeNode
  }

  const roots: KnowledgeTreeNode[] = []
  for (const rc of rootCandidates) {
    // 只构建尚未被构建的（避免重复）
    if (!built.has(rc.id)) {
      const root = buildSubtree(rc.id, 0)
      if (root) roots.push(root)
    }
  }

  // 孤儿节点 → 虚拟"未分类"根
  const orphanNodes = nodes.filter((n) => !built.has(n.id))
  if (orphanNodes.length > 0) {
    const orphanChildren: KnowledgeTreeNode[] = orphanNodes.map((n) => ({
      id: n.id,
      name: n.name,
      nodeType: n.node_type,
      entityType: n.entity_type,
      status: n.status,
      aiSummary: n.ai_summary,
      aliases: n.aliases,
      confidence: n.confidence,
      articleId: n.article_id,
      metadata: n.metadata,
      createdAt: n.created_at,
      children: [],
      childCount: 1,
      depth: 1,
    }))
    orphanChildren.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))

    const orphanRoot: KnowledgeTreeNode = {
      id: '__orphans__',
      name: '未分类',
      nodeType: 'category',
      entityType: null,
      status: 'ai_generated',
      children: orphanChildren,
      childCount: 1 + orphanChildren.reduce((s, c) => s + c.childCount, 0),
      depth: 0,
    }
    roots.push(orphanRoot)
    treeMap.set('__orphans__', orphanRoot)
    for (const oc of orphanChildren) {
      treeMap.set(oc.id, oc)
    }
  }

  // 根节点排序
  roots.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))

  return { roots, nodeMap: treeMap }
}

/**
 * 搜索树：返回匹配 query 的节点及其祖先链。
 * 用于自动展开 + 高亮过滤。
 */
export function searchTree(
  roots: KnowledgeTreeNode[],
  query: string,
): Set<string> {
  const matched = new Set<string>()
  if (!query.trim()) return matched

  const q = query.toLowerCase()

  function match(node: KnowledgeTreeNode): boolean {
    const nameMatch = node.name.toLowerCase().includes(q)
    const aliasMatch = node.aliases?.some((a) => a.toLowerCase().includes(q))
    let childMatch = false

    for (const child of node.children) {
      if (match(child)) childMatch = true
    }

    if (nameMatch || aliasMatch || childMatch) {
      matched.add(node.id)
      return true
    }
    return false
  }

  for (const root of roots) {
    match(root)
  }

  return matched
}

/**
 * 获取节点的所有祖先 ID 列表（用于展开整条路径）。
 */
export function getAncestorIds(
  nodeId: string,
  nodeMap: Map<string, KnowledgeTreeNode>,
): string[] {
  const ancestors: string[] = []
  // 通过遍历 nodeMap 找到当前节点的父节点
  let current = nodeMap.get(nodeId)
  while (current) {
    // 查找其父节点
    let parent: KnowledgeTreeNode | undefined
    for (const [, node] of nodeMap) {
      if (node.children.some((c) => c.id === current!.id)) {
        parent = node
        break
      }
    }
    if (parent && !ancestors.includes(parent.id)) {
      ancestors.push(parent.id)
      current = parent
    } else {
      break
    }
  }
  return ancestors
}

import type { SafetyKnowledgeArticle } from '@/types/safety'

// ═══════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════

export interface CategoryStyle {
  color: string
  bg: string
  emoji: string
}

export interface KnowledgeMenuItem {
  key: string          // Bitable tags 值（如 '安全类'）或 group key（如 'laws_regulations'）
  label: string        // 中文显示名
  emoji: string
  count: number
  disabled?: boolean
}

export interface KnowledgeMenuGroup {
  key: string          // 'laws_regulations' | 'equipment_manuals' | 'management_systems'
  label: string        // '法规标准' | '设备说明书' | '安全管理制度'
  emoji: string
  sourceValue: string  // matches SafetyKnowledgeArticle.source: '法规标准库' | '设备说明书库' | '制度库'
  children: KnowledgeMenuItem[]
}

// ═══════════════════════════════════════════════════════════════
// Bitable 15 子分类 → 视觉样式（8 制度 + 7 法规）
// ═══════════════════════════════════════════════════════════════

export const BT_CATEGORY_STYLE: Record<string, CategoryStyle> = {
  // ── 安全管理制度（8 类） ──
  '目标职责':                   { color: '#dd5b00', bg: '#fff3eb', emoji: '🎯' },
  '制度化管理':                 { color: '#0075de', bg: '#eaf3fc', emoji: '📋' },
  '教育培训':                   { color: '#2a9d99', bg: '#daf5f4', emoji: '📚' },
  '现场管理':                   { color: '#5645d4', bg: '#e6e0f5', emoji: '🏭' },
  '安全风险管控及隐患排查':    { color: '#e03131', bg: '#fde9e9', emoji: '🔍' },
  '应急管理':                   { color: '#1aae39', bg: '#d9f3e1', emoji: '🆘' },
  '事故管理':                   { color: '#7b3ff2', bg: '#f0e8fd', emoji: '⚠️' },
  '持续改进':                   { color: '#5d5b54', bg: '#f0eeec', emoji: '🔄' },
  // ── 法规标准（7 类） ──
  '安全类':                     { color: '#0075de', bg: '#eaf3fc', emoji: '🛡️' },
  '建筑防火与消防':             { color: '#e03131', bg: '#fde9e9', emoji: '🧯' },
  '特种设备':                   { color: '#5645d4', bg: '#e6e0f5', emoji: '⚙️' },
  '危险作业':                   { color: '#dd5b00', bg: '#fff3eb', emoji: '🔥' },
  '职业健康':                   { color: '#1aae39', bg: '#d9f3e1', emoji: '💚' },
  '化学品管理':                 { color: '#7b3ff2', bg: '#f0e8fd', emoji: '🧪' },
  '其他相关法规':               { color: '#5d5b54', bg: '#f0eeec', emoji: '📜' },
}

/** 平台分类 fallback（tags 为空时使用） */
export const FALLBACK_STYLE: Record<string, CategoryStyle> = {
  laws_regulations:   { color: '#dd5b00', bg: '#fff3eb', emoji: '⚖️' },
  standards:          { color: '#0075de', bg: '#eaf3fc', emoji: '📋' },
  management_systems: { color: '#5645d4', bg: '#e6e0f5', emoji: '📁' },
  emergency_plans:    { color: '#1aae39', bg: '#d9f3e1', emoji: '🆘' },
  accident_cases:     { color: '#e03131', bg: '#fde9e9', emoji: '⚠️' },
  sds:                { color: '#7b3ff2', bg: '#f0e8fd', emoji: '🧪' },
  training_materials: { color: '#2a9d99', bg: '#daf5f4', emoji: '📚' },
  other:              { color: '#5d5b54', bg: '#f0eeec', emoji: '📄' },
}

// ═══════════════════════════════════════════════════════════════
// 菜单结构（同步多维表格两级分类）
// ═══════════════════════════════════════════════════════════════

/** "全部" 子项的 key 前缀，确保与 SubMenu 的 group key 不冲突 */
const ALL_PREFIX = 'all:'

export const KNOWLEDGE_MENU: KnowledgeMenuGroup[] = [
  {
    key: 'laws_regulations',
    label: '法规标准',
    emoji: '⚖️',
    sourceValue: '法规标准库',
    children: [
      { key: 'all:laws_regulations', label: '全部法规标准', emoji: '📋', count: 0 },
      { key: '安全类', label: '安全类', emoji: '🛡️', count: 0 },
      { key: '建筑防火与消防', label: '建筑防火与消防', emoji: '🧯', count: 0 },
      { key: '特种设备', label: '特种设备', emoji: '⚙️', count: 0 },
      { key: '危险作业', label: '危险作业', emoji: '🔥', count: 0 },
      { key: '职业健康', label: '职业健康', emoji: '💚', count: 0 },
      { key: '化学品管理', label: '化学品管理', emoji: '🧪', count: 0 },
      { key: '其他相关法规', label: '其他相关法规', emoji: '📜', count: 0 },
    ],
  },
  {
    key: 'equipment_manuals',
    label: '设备说明书',
    emoji: '📘',
    sourceValue: '设备说明书库',
    children: [
      { key: 'all:equipment_manuals', label: '全部设备说明书', emoji: '📘', count: 0 },
    ],
  },
  {
    key: 'management_systems',
    label: '安全管理制度',
    emoji: '📁',
    sourceValue: '制度库',
    children: [
      { key: 'all:management_systems', label: '全部安全管理制度', emoji: '📋', count: 0 },
      { key: '目标职责', label: '目标职责', emoji: '🎯', count: 0 },
      { key: '制度化管理', label: '制度化管理', emoji: '📋', count: 0 },
      { key: '教育培训', label: '教育培训', emoji: '📚', count: 0 },
      { key: '现场管理', label: '现场管理', emoji: '🏭', count: 0 },
      { key: '安全风险管控及隐患排查', label: '安全风险管控及隐患排查', emoji: '🔍', count: 0 },
      { key: '应急管理', label: '应急管理', emoji: '🆘', count: 0 },
      { key: '事故管理', label: '事故管理', emoji: '⚠️', count: 0 },
      { key: '持续改进', label: '持续改进', emoji: '🔄', count: 0 },
    ],
  },
]

/** 扁平化的 tag → 所属 group key 映射（快速查找，不含 "全部" 项） */
const TAG_TO_GROUP: Record<string, string> = {}
for (const group of KNOWLEDGE_MENU) {
  for (const child of group.children) {
    if (!child.key.startsWith(ALL_PREFIX)) {
      TAG_TO_GROUP[child.key] = group.key
    }
  }
}

/** 获取某个 key 所属的 group */
export function getGroupForKey(key: string): KnowledgeMenuGroup | undefined {
  // "all:" 前缀 → 查找对应 group
  if (key.startsWith(ALL_PREFIX)) {
    const groupKey = key.slice(ALL_PREFIX.length)
    return KNOWLEDGE_MENU.find((g) => g.key === groupKey)
  }
  // tag → group 映射
  const groupKey = TAG_TO_GROUP[key]
  if (groupKey) return KNOWLEDGE_MENU.find((g) => g.key === groupKey)
  return undefined
}

// ═══════════════════════════════════════════════════════════════
// 辅助函数
// ═══════════════════════════════════════════════════════════════

/** 获取文章的分类视觉样式 */
export function getCategoryStyle(
  tags: string | null | undefined,
  category: string,
): CategoryStyle {
  const tag = (tags as string) || ''
  return BT_CATEGORY_STYLE[tag] || FALLBACK_STYLE[category] || FALLBACK_STYLE.other
}

/** 按菜单 key 筛选文章 */
export function filterByMenuKey(
  articles: SafetyKnowledgeArticle[],
  key: string,
): SafetyKnowledgeArticle[] {
  const group = getGroupForKey(key)

  if (!group) return articles

  if (key.startsWith(ALL_PREFIX) || key === group.key) {
    // 一级 "全部"：匹配 source 或该 group 下所有子分类的 tags
    const childTagKeys = group.children
      .filter((c) => !c.key.startsWith(ALL_PREFIX))
      .map((c) => c.key)

    return articles.filter((a) => {
      const tag = (a.tags || '') as string
      // 优先匹配 tags
      if (tag && childTagKeys.includes(tag)) return true
      // fallback: 无 tags 的记录用 source 匹配
      if (!tag && a.source === group.sourceValue) return true
      return false
    })
  }

  // 二级：精确匹配 tags
  return articles.filter((a) => (a.tags as string || '') === key)
}

/** 计算各菜单项的文档数量 */
export function computeMenuCounts(
  articles: SafetyKnowledgeArticle[],
): Map<string, number> {
  const counts = new Map<string, number>()

  for (const a of articles) {
    const tag = (a.tags || '') as string
    const source = a.source || ''

    // 二级子分类计数
    if (tag) {
      counts.set(tag, (counts.get(tag) || 0) + 1)
    }

    // 一级 "全部" 计数（按 source 归属，key 使用 all: 前缀）
    for (const group of KNOWLEDGE_MENU) {
      const allKey = ALL_PREFIX + group.key
      if (source === group.sourceValue) {
        counts.set(allKey, (counts.get(allKey) || 0) + 1)
      } else if (tag && group.children.some((c) => c.key === tag)) {
        // tag 属于该 group，也算入该 group 的"全部"计数
        counts.set(allKey, (counts.get(allKey) || 0) + 1)
      }
    }
  }

  return counts
}

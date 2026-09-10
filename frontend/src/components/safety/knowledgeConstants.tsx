import type { SafetyKnowledgeArticle } from '@/types/safety'

// ═══════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════

export interface CategoryStyle {
  color: string
  bg: string
  emoji: string
}

/** 一级知识菜单项（按平台 category 归类） */
export interface KnowledgeMenuItem {
  key: string          // 唯一菜单 key（= 主 category 值）
  label: string        // 中文显示名
  emoji: string
  categories: string[] // 归入此菜单的平台 category 值
  color: string        // 色点颜色（与 FALLBACK_STYLE 对齐）
  disabled?: boolean
}

/** 向后兼容别名（旧代码以 KnowledgeMenuGroup 表示菜单分组） */
export type KnowledgeMenuGroup = KnowledgeMenuItem

// ═══════════════════════════════════════════════════════════════
// Bitable 15 子分类 → 视觉样式（tags 命中时优先使用）
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

/** 平台 category 分类 fallback（tags 为空时使用） */
export const FALLBACK_STYLE: Record<string, CategoryStyle> = {
  laws_regulations:         { color: '#dd5b00', bg: '#fff3eb', emoji: '⚖️' },
  standards:                { color: '#0075de', bg: '#eaf3fc', emoji: '📐' },
  management_systems:       { color: '#5645d4', bg: '#e6e0f5', emoji: '📁' },
  training_materials:       { color: '#2a9d99', bg: '#daf5f4', emoji: '📚' },
  emergency_plans:          { color: '#1aae39', bg: '#d9f3e1', emoji: '🆘' },
  accident_cases:           { color: '#e03131', bg: '#fde9e9', emoji: '⚠️' },
  sds:                      { color: '#7b3ff2', bg: '#f0e8fd', emoji: '🧪' },
  equipment_manuals:        { color: '#dd5b00', bg: '#fff3eb', emoji: '📘' },
  risk_assessment_standards:{ color: '#e03131', bg: '#fde9e9', emoji: '📋' },
  other:                    { color: '#5d5b54', bg: '#f0eeec', emoji: '📄' },
}

// ═══════════════════════════════════════════════════════════════
// 知识菜单（一级，按平台 category 归类）
// ═══════════════════════════════════════════════════════════════

export const KNOWLEDGE_MENU: KnowledgeMenuItem[] = [
  {
    key: 'laws_regulations',
    label: '法律法规',
    emoji: '⚖️',
    categories: ['laws_regulations'],
    color: FALLBACK_STYLE.laws_regulations.color,
  },
  {
    key: 'standards',
    label: '标准规范',
    emoji: '📐',
    categories: ['standards'],
    color: FALLBACK_STYLE.standards.color,
  },
  {
    key: 'management_systems',
    label: '安全管理制度',
    emoji: '📁',
    categories: ['management_systems', 'training_materials', 'emergency_plans', 'accident_cases'],
    color: FALLBACK_STYLE.management_systems.color,
  },
  {
    key: 'equipment_manuals',
    label: '设备说明书',
    emoji: '📘',
    categories: ['equipment_manuals'],
    color: FALLBACK_STYLE.equipment_manuals.color,
  },
  {
    key: 'sds',
    label: 'SDS / MSDS',
    emoji: '🧪',
    categories: ['sds'],
    color: FALLBACK_STYLE.sds.color,
  },
  {
    key: 'risk_assessment_standards',
    label: '风险评估标准',
    emoji: '📋',
    categories: ['risk_assessment_standards'],
    color: FALLBACK_STYLE.risk_assessment_standards.color,
  },
  {
    key: 'other',
    label: '其他',
    emoji: '📄',
    categories: ['other'],
    color: FALLBACK_STYLE.other.color,
  },
]

/** category → 菜单项 快速映射 */
const CATEGORY_TO_MENU: Record<string, KnowledgeMenuItem> = {}
for (const item of KNOWLEDGE_MENU) {
  for (const c of item.categories) {
    CATEGORY_TO_MENU[c] = item
  }
}

/** 获取某个菜单 key 对应的菜单项 */
export function getGroupForKey(key: string): KnowledgeMenuItem | undefined {
  return KNOWLEDGE_MENU.find((m) => m.key === key)
}

// ═══════════════════════════════════════════════════════════════
// 辅助函数
// ═══════════════════════════════════════════════════════════════

/** 获取文章的分类视觉样式（优先 tags，回退 category） */
export function getCategoryStyle(
  tags: string | null | undefined,
  category: string,
): CategoryStyle {
  const tag = (tags as string) || ''
  return BT_CATEGORY_STYLE[tag] || FALLBACK_STYLE[category] || FALLBACK_STYLE.other
}

/** 按菜单 key 筛选文章（基于平台 category 归类） */
export function filterByMenuKey(
  articles: SafetyKnowledgeArticle[],
  key: string,
): SafetyKnowledgeArticle[] {
  const menu = getGroupForKey(key)
  if (!menu) return articles
  return articles.filter((a) => menu.categories.includes(a.category))
}

/** 将后端全库分类计数映射为菜单计数（menuKey → count） */
export function mapCategoryCountsToMenu(
  byCategory: Record<string, number>,
): Map<string, number> {
  const counts = new Map<string, number>()
  for (const item of KNOWLEDGE_MENU) {
    let sum = 0
    for (const c of item.categories) {
      sum += byCategory[c] || 0
    }
    counts.set(item.key, sum)
  }
  return counts
}

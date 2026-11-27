// SOP 目录页的分组与匹配工具：纯函数，不依赖组件。
// 目录是「部门 → 岗位 → 培训条目」三层，页面左侧按部门导航、右侧按岗位分组展示。

import type { SopCatalogItem } from '@/types/hr'

/** 条目没写部门时的兜底分组名（导入只强制要求文件名称，理论上可能有这种行） */
export const NO_DEPARTMENT = '未指定部门'
/** 条目没写岗位时的分组名（GMP 文件目录 Word 文档解析出的条目只有部门） */
export const NO_POSITION = '未指定岗位'

export const byName = (a: string, b: string) => a.localeCompare(b, 'zh-CN')

export const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback)

export interface SopGroup {
  /** `${部门}|${岗位}`，页面内唯一 */
  key: string
  department: string
  /** null = 该部门下未指定岗位的条目 */
  position: string | null
  /** 培训类别去重后的预览，顺序同 items */
  categories: string[]
  items: SopCatalogItem[]
}

export interface DeptSection {
  department: string
  groups: SopGroup[]
  /** 该部门条目总数 */
  count: number
}

export function groupKey(department: string, positionName: string | null): string {
  return `${department}|${positionName ?? ''}`
}

/** 分组在页面上显示的岗位名 */
export const groupLabel = (position: string | null) => position ?? NO_POSITION

const lower = (value: string | null | undefined) => (value ?? '').toLowerCase()

/** 搜索命中：岗位名、培训类别、文件名称、SOP 编号任一包含关键词（kw 已 trim 并转小写） */
export function itemMatches(item: SopCatalogItem, kw: string): boolean {
  return lower(item.position_name).includes(kw)
    || lower(item.category).includes(kw)
    || item.file_name.toLowerCase().includes(kw)
    || lower(item.sop_number).includes(kw)
}

const itemOrder = (a: SopCatalogItem, b: SopCatalogItem) =>
  byName(a.category ?? '', b.category ?? '') || byName(a.file_name, b.file_name)

/** 按部门 → 岗位分组并排序：部门按 deptOrder（不在其中的按名称排在后面），未指定岗位的组排在最前，
 *  组内条目按培训类别、文件名称排序 */
export function buildSections(items: SopCatalogItem[], deptOrder: string[]): DeptSection[] {
  const rank = (dept: string) => {
    const index = deptOrder.indexOf(dept)
    return index === -1 ? Number.MAX_SAFE_INTEGER : index
  }
  const sections = new Map<string, Map<string, SopGroup>>()
  for (const item of items) {
    const dept = item.department || NO_DEPARTMENT
    let groups = sections.get(dept)
    if (!groups) {
      groups = new Map()
      sections.set(dept, groups)
    }
    const key = groupKey(dept, item.position_name || null)
    const group = groups.get(key)
    if (group) {
      group.items.push(item)
    } else {
      groups.set(key, {
        key,
        department: dept,
        position: item.position_name || null,
        categories: [],
        items: [item],
      })
    }
  }

  return [...sections.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || byName(a, b))
    .map(([department, groups]) => {
      const list = [...groups.values()]
        .sort((a, b) => Number(a.position !== null) - Number(b.position !== null)
          || byName(a.position ?? '', b.position ?? ''))
      for (const group of list) {
        group.items.sort(itemOrder)
        group.categories = [...new Set(group.items.map((item) => item.category || ''))]
      }
      return { department, groups: list, count: list.reduce((sum, group) => sum + group.items.length, 0) }
    })
}

/** 搜索结果的行顺序：同浏览态（部门 → 岗位 → 培训类别 → 文件名称） */
export function sortForSearch(items: SopCatalogItem[], deptOrder: string[]): SopCatalogItem[] {
  const rank = (dept: string) => {
    const index = deptOrder.indexOf(dept)
    return index === -1 ? Number.MAX_SAFE_INTEGER : index
  }
  return [...items].sort((a, b) =>
    rank(a.department || NO_DEPARTMENT) - rank(b.department || NO_DEPARTMENT)
    || Number(a.position_name === null) - Number(b.position_name === null)
    || byName(a.position_name ?? '', b.position_name ?? '')
    || itemOrder(a, b))
}

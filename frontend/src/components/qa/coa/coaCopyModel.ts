// 复制到其它模板的纯逻辑：同名默认配对 + 组装复制格。
// 不含 React / antd，只带 import type，可用 Node 24 类型剥离直接跑用例。
import type { CoaCopyCellInput, CoaProductField, CoaStandardItem } from '@/types/qa'
import type { CoaResultDraft } from './CoaResultInput'

/** 名字归一：全角转半角、忽略大小写与空白标点（与后端项目编码同一思路）。 */
export function normalizedName(value: string): string {
  return value.normalize('NFKC').toLowerCase().replace(/[^0-9a-z\u4e00-\u9fff]/g, '')
}

function groupByKey<T>(values: T[], keyOf: (value: T) => string): Map<string, T[]> {
  const groups = new Map<string, T[]>()
  for (const value of values) {
    const key = keyOf(value)
    groups.set(key, [...(groups.get(key) ?? []), value])
  }
  return groups
}

/**
 * 检测项目的同名默认配对：先按项目编码，再按归一后的中文名。
 * 中文名两侧都唯一才算——同名的「杂质」有好几个时分不清是哪一个，留给人工选。
 */
export function pairItems(
  target: CoaStandardItem[],
  source: CoaStandardItem[],
): Record<string, string> {
  const pairs: Record<string, string> = {}
  const sourceByCode = new Map(source.map((item) => [item.code, item]))
  const sourceByName = groupByKey(source, (item) => normalizedName(item.name_cn))
  const targetByName = groupByKey(target, (item) => normalizedName(item.name_cn))
  for (const item of target) {
    const byCode = sourceByCode.get(item.code)
    if (byCode) {
      pairs[item.id] = byCode.id
      continue
    }
    const name = normalizedName(item.name_cn)
    const candidates = sourceByName.get(name) ?? []
    if (name && candidates.length === 1 && targetByName.get(name)?.length === 1) {
      pairs[item.id] = candidates[0].id
    }
  }
  return pairs
}

/** 批次字段的同名默认配对：先按键，再按归一后的中文标签；类型要一致（日期不往文本里配）。 */
export function pairBatchFields(
  target: CoaProductField[],
  source: CoaProductField[],
): Record<string, string> {
  const pairs: Record<string, string> = {}
  const sourceByKey = new Map(source.map((field) => [field.key, field]))
  const sourceByLabel = groupByKey(source, (field) => normalizedName(field.label_cn))
  for (const field of target) {
    const byKey = sourceByKey.get(field.key)
    if (byKey && byKey.field_type === field.field_type) {
      pairs[field.key] = byKey.key
      continue
    }
    const candidates = (sourceByLabel.get(normalizedName(field.label_cn)) ?? []).filter(
      (candidate) => candidate.field_type === field.field_type,
    )
    if (candidates.length === 1) pairs[field.key] = candidates[0].key
  }
  return pairs
}

export interface CopyCellSource {
  targetItems: CoaStandardItem[]
  targetBatchFields: CoaProductField[]
  /** 这一格选的来源（批次字段键 / 来源项目 id）；没选返回 undefined */
  sourceOf: (kind: 'batch' | 'item', key: string) => string | undefined
  draftOf: (item: CoaStandardItem) => CoaResultDraft
  batchValueOf: (field: CoaProductField) => string | null | undefined
}

/** 配了来源、值也非空的格才出格（留空等于不复制）。批次字段在前，各自按目标模板的顺序。 */
export function buildCopyCells({
  targetItems,
  targetBatchFields,
  sourceOf,
  draftOf,
  batchValueOf,
}: CopyCellSource): CoaCopyCellInput[] {
  const cells: CoaCopyCellInput[] = []
  for (const field of targetBatchFields) {
    const source = sourceOf('batch', field.key)
    const value = (batchValueOf(field) ?? '').trim()
    if (source && value) cells.push({ kind: 'batch', source, target: field.key, value })
  }
  for (const item of targetItems) {
    const source = sourceOf('item', item.id)
    const draft = draftOf(item)
    if (!source || !draft.raw.trim()) continue
    cells.push({
      kind: 'item',
      source,
      target: item.id,
      value_num: draft.num,
      value_text: draft.text?.trim() || null,
    })
  }
  return cells
}

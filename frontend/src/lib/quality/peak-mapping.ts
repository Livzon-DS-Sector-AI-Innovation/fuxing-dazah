/**
 * 图谱峰表 → 在线计算表 inputs 映射（纯函数，无副作用）。
 *
 * 引擎输入键约定与后端 calc_engine.compute_normalization / 前端 CalcForm 一致：
 * total_peak_N（总峰面积）、main_peak_N（主峰面积）、<杂质key>_N（各杂质峰面积），N=1/2 双份。
 * 映射只做预填草稿：数值进表单后由检验员核对、经计算引擎与待确认流程落库（GMP 口径）。
 */

import type { CalcNormalizationCfg, ChromatogramPeak } from '@/types/quality'

/** 峰名归一化：去首尾/中间空格（含全角）、转小写。 */
export function normName(name: string): string {
  return name.replace(/[\s\u3000]+/g, '').toLowerCase()
}

/** 从 label 提取括号别名（如「杂质F（AF）」→ AF；无括号返回空）。 */
function parenAlias(label: string): string[] {
  const out: string[] = []
  for (const m of label.matchAll(/[（(]([^（）()]+)[)）]/g)) {
    const v = m[1].trim()
    if (v) out.push(v)
  }
  return out
}

/** 一个配置项（main_item/impurity）可被峰名命中的全部别名（归一化后）。 */
function aliasSet(stdName: string, label: string, key?: string): Set<string> {
  const aliases = new Set<string>()
  for (const v of [stdName, label, ...(key ? [key] : []), ...parenAlias(label)]) {
    const n = normName(v)
    if (n) aliases.add(n)
  }
  return aliases
}

export interface PeakMappedRow {
  /** inputs 键前缀（total_peak / main_peak / <杂质key>） */
  key: string
  label: string
  /** 是否主成分行 */
  isMain: boolean
  a1: number | null
  a2: number | null
}

export interface PeakMapResult {
  /** 直接可灌进 CalcForm 的 inputs（CalcForm 的 Inputs = Record<string, number | undefined>） */
  inputs: Record<string, number>
  rows: PeakMappedRow[]
  /** 未匹配到配置项目的峰名（保留在总峰面积内，只提示不静默丢） */
  unmatchedNames: string[]
}

/** 峰面积求和（area 为 null/undefined 的行不计；调用前可让用户删掉溶剂峰等无关行）。 */
function sumArea(peaks: ChromatogramPeak[] | undefined): number | null {
  if (!peaks || !peaks.length) return null
  const vals = peaks.map((p) => p.area).filter((v): v is number => v != null && v > 0)
  return vals.length ? Number(vals.reduce((a, b) => a + b, 0).toFixed(2)) : null
}

function matchPeak(
  peaks: ChromatogramPeak[] | undefined,
  aliases: Set<string>,
): number | null {
  if (!peaks) return null
  for (const p of peaks) {
    const n = normName(p.name)
    if (n && aliases.has(n) && p.area != null && p.area > 0) return p.area
  }
  return null
}

/**
 * 把第一/第二份峰表映射为归一化计算表 inputs。
 * total_peak_N = 该份全部峰面积之和；main/杂质按峰名精确匹配（std_name/label/括号别名/key）。
 */
export function mapPeaksToInputs(
  cfg: CalcNormalizationCfg,
  peaks1: ChromatogramPeak[],
  peaks2?: ChromatogramPeak[],
): PeakMapResult {
  const rows: PeakMappedRow[] = []
  const inputs: Record<string, number> = {}
  const matchedPeakNames = new Set<string>()

  const mark = (peaks: ChromatogramPeak[] | undefined, aliases: Set<string>): string | null => {
    if (!peaks) return null
    for (const p of peaks) {
      const n = normName(p.name)
      if (n && aliases.has(n)) { matchedPeakNames.add(n); return n }
    }
    return null
  }

  // 总峰面积：全部峰之和（双份各自求和）
  for (const [i, peaks] of [[1, peaks1], [2, peaks2]] as const) {
    const total = sumArea(peaks)
    if (total != null) inputs[`total_peak_${i}`] = total
  }
  rows.push({
    key: 'total_peak', label: '总峰面积', isMain: false,
    a1: inputs['total_peak_1'] ?? null,
    a2: inputs['total_peak_2'] ?? null,
  })

  // 主成分
  const mainAliases = aliasSet(cfg.main_item.std_name, cfg.main_item.label)
  const mainA1 = matchPeak(peaks1, mainAliases); mark(peaks1, mainAliases)
  const mainA2 = matchPeak(peaks2, mainAliases); mark(peaks2, mainAliases)
  if (mainA1 != null) inputs['main_peak_1'] = mainA1
  if (mainA2 != null) inputs['main_peak_2'] = mainA2
  rows.push({ key: 'main_peak', label: cfg.main_item.label, isMain: true, a1: mainA1, a2: mainA2 })

  // 各杂质
  for (const imp of cfg.impurities) {
    const aliases = aliasSet(imp.std_name, imp.label, imp.key)
    const a1 = matchPeak(peaks1, aliases); mark(peaks1, aliases)
    const a2 = matchPeak(peaks2, aliases); mark(peaks2, aliases)
    if (a1 != null) inputs[`${imp.key}_1`] = a1
    if (a2 != null) inputs[`${imp.key}_2`] = a2
    rows.push({ key: imp.key, label: imp.label, isMain: false, a1, a2 })
  }

  // 未匹配峰：不在配置项目里的（溶剂峰/系统峰/新杂质），保留在总峰面积里，仅提示
  const unmatchedNames: string[] = []
  for (const peaks of [peaks1, peaks2]) {
    for (const p of peaks ?? []) {
      const n = normName(p.name)
      if (n && !matchedPeakNames.has(n) && !unmatchedNames.includes(p.name.trim())) {
        unmatchedNames.push(p.name.trim())
      }
    }
  }

  return { inputs, rows, unmatchedNames }
}

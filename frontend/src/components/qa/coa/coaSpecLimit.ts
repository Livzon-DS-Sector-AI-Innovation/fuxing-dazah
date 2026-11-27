// COA 结果是否超出标准限度：限度解析 + 结果解析 + 判定。
//
// 纯函数、不落库：录入单、导入审核、出具记录表都在读取时现算，标准的上下限改了，
// 历史数据的标记自动跟着变。只做提醒、不拦保存，所以拿不准的一律不判——
// 判定词/描述性文字、单位与项目对不上的结果都不给结论。
// 边界值算合格，与同模块 APR 域 classify_point 同口径。

import type { CoaStandardItem } from '@/types/qa'

/** 待判定的结果：数值走 num；带比较符或单位的结果只在 text 里。 */
export interface CoaLimitValue {
  num: number | null
  text?: string | null
}

export interface CoaSpecLimit {
  min: number | null
  max: number | null
}

export type CoaLimitSide = 'above' | 'below'

/** definite=确定超出；possible=结果带比较符（＜2.0），无法确认在限度内。 */
export type CoaLimitCertainty = 'definite' | 'possible'

export interface CoaLimitHit {
  side: CoaLimitSide
  certainty: CoaLimitCertainty
  /** 被越过的那条限值 */
  bound: number
  /** 结果的显示文本：数值结果补项目单位，文字结果保留原文 */
  display: string
}

export interface CoaItemLimitHit {
  item: CoaStandardItem
  hit: CoaLimitHit
}

const nfkc = (text: string) => text.normalize('NFKC')

// 与后端 docx_parse._UNIT_TAIL 同一张表：数字后面只认这些单位尾缀，
// 其余形态（「3个」「1:2」「约1.0」）一律当文字、不判
const UNIT_TAIL =
  '%|ppm|ppb|µg/mg|μg/mg|ug/mg|eu/mg|cfu/g|cfu/ml|eu/ml|kg|mg|g|ml|l|cfu|eu|μm|um|nm|℃|°c'
const NUMBER = String.raw`[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?`
const NUMBER_RE = new RegExp(String.raw`^${NUMBER}$`)
// 「数字 + 可选单位」：捕获组依次是 数字、单位
const NUMBER_GROUP = String.raw`(${NUMBER})(?:(${UNIT_TAIL}))?`

// 全角比较符经 NFKC 归一成半角（＜ → <、＝ → =）；≤ ≧ 一类不是兼容字符，原样列出
const RESULT_RE = new RegExp(String.raw`^(<=?|≤|≦|>=?|≥|≧|=)?${NUMBER_GROUP}$`, 'i')
const BOUND_RE = new RegExp(String.raw`^${NUMBER_GROUP}$`, 'i')
// 标准原文的区间写法：A～B / A—B / A至B（两侧可带负号）；A-B 只在两侧都无符号时才算
// 区间，否则分隔符与负号分不开
const RANGE_WORD_RE = new RegExp(String.raw`^${NUMBER_GROUP}[~～至—–]${NUMBER_GROUP}$`, 'i')
const RANGE_DASH_RE = new RegExp(String.raw`^(\d+(?:\.\d+)?(?:(${UNIT_TAIL}))?)-(\d+(?:\.\d+)?(?:(${UNIT_TAIL}))?)$`, 'i')

function toNumber(text: string | undefined): number | null {
  if (!text || !NUMBER_RE.test(text)) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

// ─────────────────────── 限度 ───────────────────────


function boundLimit(min: number | null, max: number | null): CoaSpecLimit | null {
  if (min == null && max == null) return null
  if (min != null && max != null && min > max) return null
  return { min, max }
}


/** 标准原文里的数值限：≤/＜X → 上限，≥/＞X → 下限，A～B → 区间。
 *  口径同后端 parse_spec；解析不干净（「不得超过3个」「≤Y2 or GY2」）返回 null。 */
function parseSpecText(text: string | null): CoaSpecLimit | null {
  if (!text) return null
  const s = nfkc(text).toLowerCase().replace(/\s+/g, '')
  let m = /^[<≤](.+)$/.exec(s)
  if (m) return boundLimit(null, toNumber(BOUND_RE.exec(m[1])?.[1]))
  m = /^[>≥](.+)$/.exec(s)
  if (m) return boundLimit(toNumber(BOUND_RE.exec(m[1])?.[1]), null)
  m = RANGE_WORD_RE.exec(s) ?? RANGE_DASH_RE.exec(s)
  if (m) return boundLimit(toNumber(m[1]), toNumber(m[3]))
  return null
}


/** 项目的标准限度：下限/上限字段优先；两者都没填时回退解析标准原文
 *  （手工建的标准没填上下限也能判）。没有可判的限度返回 null。 */
export function specLimitOf(
  item: Pick<CoaStandardItem, 'spec_min' | 'spec_max' | 'spec_text'>,
): CoaSpecLimit | null {
  if (item.spec_min != null || item.spec_max != null) {
    return boundLimit(item.spec_min ?? null, item.spec_max ?? null)
  }
  return parseSpecText(item.spec_text)
}

// ─────────────────────── 结果 ───────────────────────


interface ParsedResult {
  op: '<' | '>' | null
  value: number
  unit: string | null
}


/** 结果 → 数值。数值结果直接取；文字结果只认「可选比较符 + 数字 + 可选单位」。 */
function parseResult(value: CoaLimitValue): ParsedResult | null {
  if (value.num != null) return { op: null, value: value.num, unit: null }
  const text = value.text?.trim()
  if (!text) return null
  const m = RESULT_RE.exec(nfkc(text))
  const num = toNumber(m?.[2])
  if (!m || num == null) return null
  // ≤ ≦ 与 ＜ 都算「不大于」，＞ ≥ ≧ 都算「不小于」：边界值本就按合格算，不必细分
  const op = !m[1] || m[1] === '=' ? null : '<≤≦'.includes(m[1][0]) ? '<' : '>'
  return { op, value: num, unit: m[3] ?? null }
}


/** 单位的比对键（只用于比较，不用于显示）：µ/μ → u、% 记作 pct、去掉符号。 */
function unitKey(unit: string | null): string | null {
  if (!unit) return null
  const key = nfkc(unit)
    .toLowerCase()
    .replace(/μ/g, 'u')
    .replace(/%/g, 'pct')
    .replace(/[^a-z0-9]/g, '')
  return key || null
}


/**
 * 结果是否超出限度；没超或判不了返回 null。
 *
 * 带比较符的结果只知一边：实际值 < X 时，X 不超过上限就在限内，X 超过上限只能记
 * 「可能超限」（证明不了在限内），X 不高于下限则一定低于下限。＞X 对称。
 */
export function checkSpecLimit(
  limit: CoaSpecLimit,
  value: CoaLimitValue,
  unit?: string | null,
): CoaLimitHit | null {
  const parsed = parseResult(value)
  if (!parsed) return null
  // 结果自带单位且与项目单位对不上（ppm 对 %）→ 不判，避免按错口径误报
  const resultUnit = unitKey(parsed.unit)
  const itemUnit = unitKey(unit ?? null)
  if (resultUnit && itemUnit && resultUnit !== itemUnit) return null

  const { min, max } = limit
  const { op, value: v } = parsed
  const hit = (side: CoaLimitSide, certainty: CoaLimitCertainty, bound: number): CoaLimitHit => ({
    side,
    certainty,
    bound,
    display:
      value.num != null
        ? withUnit(String(value.num), unit ?? null)
        : (value.text?.trim() ?? ''),
  })

  if (op === '<') {
    if (min != null && v <= min) return hit('below', 'definite', min)
    if (max != null && v > max) return hit('above', 'possible', max)
    if (min != null) return hit('below', 'possible', min)
    return null
  }
  if (op === '>') {
    if (max != null && v >= max) return hit('above', 'definite', max)
    if (min != null && v < min) return hit('below', 'possible', min)
    if (max != null) return hit('above', 'possible', max)
    return null
  }
  if (max != null && v > max) return hit('above', 'definite', max)
  if (min != null && v < min) return hit('below', 'definite', min)
  return null
}


/** 一组结果的越界项，按项目顺序。valueOf 返回 undefined 表示该项不判（没填 / 还在输入）。 */
export function collectLimitHits(
  items: CoaStandardItem[],
  valueOf: (item: CoaStandardItem) => CoaLimitValue | undefined,
): CoaItemLimitHit[] {
  const hits: CoaItemLimitHit[] = []
  for (const item of items) {
    const limit = specLimitOf(item)
    const value = valueOf(item)
    if (!limit || !value) continue
    const hit = checkSpecLimit(limit, value, item.unit)
    if (hit) hits.push({ item, hit })
  }
  return hits
}

// ─────────────────────── 文案 ───────────────────────


function withUnit(number: string, unit: string | null): string {
  if (!unit) return number
  return unit === '%' ? `${number}%` : `${number} ${unit}`
}


/** 限值的显示：优先沿用标准原文里的写法（3.0 而不是 3），再补项目单位。 */
function formatBound(bound: number, specText: string | null, unit: string | null): string {
  const literal = specText
    ? nfkc(specText)
        .match(/\d+(?:\.\d+)?/g)
        ?.find((text) => Number(text) === bound)
    : undefined
  return withUnit(literal ?? String(bound), unit)
}


/** 录入格里的标记：高于上限 / 低于下限 / 可能超限。 */
export function limitHitLabel(hit: CoaLimitHit): string {
  if (hit.certainty === 'possible') return '可能超限'
  return hit.side === 'above' ? '高于上限' : '低于下限'
}


/** 清单里的短标记：超标 / 可能超限。 */
export function limitHitStamp(hit: CoaLimitHit): string {
  return hit.certainty === 'possible' ? '可能超限' : '超标'
}


/** 完整说明：「结果 3.5%，高于上限 3.0%（标准 ≤3.0%）」。 */
export function limitHitDetail({
  item,
  hit,
}: {
  item: Pick<CoaStandardItem, 'spec_text' | 'unit'>
  hit: CoaLimitHit
}): string {
  const edge = hit.side === 'above' ? '上限' : '下限'
  const toward = hit.side === 'above' ? '高于' : '低于'
  const relation = `${hit.certainty === 'possible' ? '可能' : ''}${toward}${edge}`
  const spec = item.spec_text ? `（标准 ${item.spec_text}）` : ''
  return `结果 ${hit.display}，${relation} ${formatBound(hit.bound, item.spec_text, item.unit)}${spec}`
}


/** 越界计数：overs=确定超出，possible=可能超限。 */
export function tallyLimitHits(hits: CoaItemLimitHit[]): { overs: number; possible: number } {
  let overs = 0
  for (const { hit } of hits) if (hit.certainty === 'definite') overs += 1
  return { overs, possible: hits.length - overs }
}

/** 计数说明（按计数）：「2 项超出标准限度」「2 项超出标准限度、1 项可能超出」。 */
export function limitCountsText({ overs, possible }: { overs: number; possible: number }): string {
  const parts: string[] = []
  if (overs > 0) parts.push(`${overs} 项超出标准限度`)
  if (possible > 0) parts.push(`${possible} 项可能超出`)
  return parts.join('、')
}

/** 一组越界项的计数说明；没有越界返回空串。 */
export function limitTallyText(hits: CoaItemLimitHit[]): string {
  return limitCountsText(tallyLimitHits(hits))
}

/** 计数标记的统称：全是确定超标报「超标」，混有可能超限报「超限」，只有可能超限报「可能超限」。 */
export function limitCaption({ overs, possible }: { overs: number; possible: number }): string {
  if (!overs) return '可能超限'
  return possible ? '超限' : '超标'
}

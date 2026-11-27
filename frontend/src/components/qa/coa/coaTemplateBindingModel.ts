/** 模板标注抽屉的纯逻辑：地址解读、网格索引、前端侧的绑定推导与保存载荷。
 * 不依赖 React；推导口径与后端 template_bind 保持一致（后端保存时会再校验一遍）。
 */
import type {
  CoaResultColumns,
  CoaTemplateBindingInput,
  CoaTemplateBindingView,
  CoaTemplateField,
  CoaTemplateFmt,
  CoaTemplateGridBlock,
  CoaTemplateGridCell,
  CoaTemplateGridSection,
  CoaTemplateResidue,
  CoaTemplateSlot,
} from '@/types/qa'

// ─────────────────────── 地址解读 ───────────────────────

const PART_LABEL: Record<string, string> = { H: '页眉', F: '页脚' }

/** 数据位是不是表格格里的段落（正文/页眉段落返回 false）。 */
export function slotInTable(sid: string): boolean {
  return RESULT_SLOT_RE.test(sid)
}

// 表格格内段落：[前缀]T0.R2.G3.p0 → 第 1 组=表地址（含前缀），第 2 组=网格列
const RESULT_SLOT_RE = /^(.*T\d+)\.R\d+\.G(\d+)\.p\d+$/

/** 数据位是不是某张项目表「结果列」上的格子：结果列里非空又没绑定的格子要人工处理。 */
export function isResultSlot(sid: string, resultColumns: CoaResultColumns): boolean {
  const match = RESULT_SLOT_RE.exec(sid)
  return match !== null && resultColumns[match[1]] === Number(match[2])
}

/**
 * 地址 → 人能读的位置。
 * T0.R2.G3.p0 → 表 1 第 3 行 第 4 列；P1 → 正文第 2 段；H.P0 → 页眉第 1 段；
 * T0.R0.G1.T0.R0.G0.p0 → 表 1 第 1 行第 2 列内 表 1 第 1 行 第 1 列。
 */
export function describeSlot(sid: string): string {
  const head: string[] = []
  let main: string[] = []
  for (const token of sid.split('.')) {
    const part = /^([HF])(\d*)$/.exec(token)
    if (part) {
      head.push(`${PART_LABEL[part[1]] ?? ''}${part[2]}`)
      continue
    }
    const box = /^B(\d+)$/.exec(token)
    if (box) {
      head.push(`文本框 ${Number(box[1]) + 1} `)
      continue
    }
    const para = /^P(\d+)$/.exec(token)
    if (para) {
      if (!head.length) head.push('正文')
      main.push(`第 ${Number(para[1]) + 1} 段`)
      continue
    }
    const table = /^T(\d+)$/.exec(token)
    if (table) {
      if (main.length) {
        // 嵌套表：外层格子是位置前缀
        head.push(`${main.join(' ')}内 `)
        main = []
      }
      main.push(`表 ${Number(table[1]) + 1}`)
      continue
    }
    const row = /^R(\d+)$/.exec(token)
    if (row) {
      main.push(`第 ${Number(row[1]) + 1} 行`)
      continue
    }
    const col = /^G(\d+)$/.exec(token)
    if (col) {
      main.push(`第 ${Number(col[1]) + 1} 列`)
      continue
    }
    const inner = /^p(\d+)$/.exec(token)
    if (inner && Number(inner[1]) > 0) main.push(`第 ${Number(inner[1]) + 1} 段`)
  }
  // 不用「·」分隔：这个位置说明在清单里占一列，越短留给「所在行」的越多
  return `${head.join('')}${main.join(' ')}`
}

// ─────────────────────── 网格索引 ───────────────────────

/** 网格里每个段落的文字，以及它所在行（本格以外）的文字。 */
export interface GridIndex {
  textOf: Map<string, string>
  contextOf: Map<string, string>
}

function cellText(cell: CoaTemplateGridCell): string {
  return cell.paras
    .map((para) => para.text)
    .filter((text) => text.trim())
    .join(' ⏎ ')
}

export function indexGrid(grid: CoaTemplateGridSection[]): GridIndex {
  const textOf = new Map<string, string>()
  const contextOf = new Map<string, string>()
  const walk = (blocks: CoaTemplateGridBlock[]) => {
    for (const block of blocks) {
      if (block.type === 'p') {
        textOf.set(block.sid, block.text)
      } else if (block.type === 'table') {
        for (const row of block.rows) {
          for (const cell of row.cells) {
            const context = row.cells
              .filter((other) => other.sid !== cell.sid)
              .map(cellText)
              .filter(Boolean)
              .join(' ｜ ')
            for (const para of cell.paras) {
              textOf.set(para.sid, para.text)
              contextOf.set(para.sid, context)
            }
          }
        }
      } else {
        walk(block.blocks)
      }
    }
  }
  for (const section of grid) walk(section.blocks)
  return { textOf, contextOf }
}

// 标题行一类的占位值：XXXXXXXX / ____ / 一串数字（与后端 guess_inline_value 同口径）
const INLINE_VALUE_RE = /[XxＸｘ×＊*＿_—–-]{3,}|\d{4,}[A-Za-z0-9_-]*/g
/** 去掉全部空白（比较「当前值是否相同」用）。 */
const squash = (text: string) => text.replace(/\s+/g, '')

/** 在预览里点一个段落给字段：推导替换方式与原文（口径同后端 derive_slot）。
 *  格式由调用方按字段与新位置上的文字决定。
 */
export function slotFromGrid(
  sid: string,
  index: GridIndex,
  fmt: CoaTemplateFmt
): CoaTemplateSlot {
  const text = index.textOf.get(sid) ?? ''
  let mode: CoaTemplateSlot['mode'] = 'replace'
  let sample = text
  if (!slotInTable(sid)) {
    // 值夹在固定文字中间（标题行流水号）：取最后一个占位符/数字串
    const matches = text.match(INLINE_VALUE_RE)
    const guess = matches ? matches[matches.length - 1] : null
    if (guess && guess.replace(/\s+/g, '') !== text.replace(/\s+/g, '')) {
      mode = 'inplace'
      sample = guess
    }
  }
  return {
    sid,
    mode,
    sample,
    fmt,
    context: (index.contextOf.get(sid) ?? '').slice(0, 160),
    flags: [],
  }
}

// ─────────────────────── 格式规则 ───────────────────────

type FieldShape = Pick<
  CoaTemplateField,
  'kind' | 'type' | 'value_type' | 'unit' | 'spec_text'
>
type Defaults = CoaTemplateBindingView['defaults']

function joinerOf(raw: string): '' | ' ' | '\n' {
  return raw === ' ' || raw === '\n' ? raw : ''
}

// 计数型限度（不得超过 5 个、≤6000 个/g、≤1000cfu/g）：结果是整数个数
const COUNT_SPEC_RE = /个|粒|cfu/i

/** 数值型项目的默认小数位：结果是整数个数时取 0——计数型限度（不得超过 5 个、≤1000cfu/g），
 *  或限度都是「大的整数」（≥1050IU/mg、≤5000ppm）；其余取模板默认（与后端同口径）。
 *  计数型先判：这类标准的文字里常同时带百分比阈值（＞0.30%的杂质不得超过 5 个）。 */
export function defaultDecimals(specText: string | null, fallback: number): number {
  const spec = specText ?? ''
  if (COUNT_SPEC_RE.test(spec)) return 0
  const numbers = spec.match(/\d+(?:\.\d+)?/g) ?? []
  if (numbers.length > 0 && numbers.every((n) => !n.includes('.') && Number(n) >= 10)) {
    return 0
  }
  return fallback
}

/** 字段能选的格式类型：日期型批次字段只有日期，批次文字字段只有文字，项目可数值可文字。 */
export function allowedKinds(field: FieldShape): CoaTemplateFmt['kind'][] {
  if (field.kind === 'batch') return field.type === 'date' ? ['date'] : ['text']
  return ['number', 'text']
}

/** 格式编辑里列出的类型：字段现在允许的，外加这一位当前的类型。
 *  确认之后字段类型变了（文字 → 日期）时，原来确认的格式要看得见、改得掉，
 *  不能因为只剩一个可选项而被锁死。 */
export function offeredKinds(field: FieldShape, fmt: CoaTemplateFmt): CoaTemplateFmt['kind'][] {
  const allowed = allowedKinds(field)
  return allowed.includes(fmt.kind) ? allowed : [...allowed, fmt.kind]
}

/** 新绑定一个位置时的格式：按字段类型给默认值，用户可再改。 */
export function defaultFmt(field: FieldShape, defaults: Defaults): CoaTemplateFmt {
  const bilingual = defaults.verdict_bilingual
  const joiner = joinerOf(defaults.joiner)
  if (field.kind === 'batch') {
    return field.type === 'date'
      ? { kind: 'date', pattern: defaults.date_pattern }
      : { kind: 'text' }
  }
  if (field.value_type === 'number') {
    return {
      kind: 'number',
      decimals: defaultDecimals(field.spec_text, defaults.decimals),
      suffix: field.unit ?? '',
      bilingual,
      joiner,
    }
  }
  return { kind: 'text', bilingual, joiner, suffix: field.unit ?? '' }
}

/** 切换格式类型：单位、补英文、连接符沿用原来的，其余取新类型的默认值。 */
export function fmtForKind(
  kind: CoaTemplateFmt['kind'],
  current: CoaTemplateFmt,
  field: FieldShape,
  defaults: Defaults
): CoaTemplateFmt {
  const unit = current.suffix ?? field.unit ?? ''
  const bilingual = current.bilingual ?? defaults.verdict_bilingual
  const joiner = current.joiner ?? joinerOf(defaults.joiner)
  if (kind === 'number') {
    return {
      kind: 'number',
      decimals: current.decimals ?? defaultDecimals(field.spec_text, defaults.decimals),
      suffix: unit,
      bilingual,
      joiner,
    }
  }
  if (kind === 'date') {
    return { kind: 'date', pattern: current.pattern ?? defaults.date_pattern }
  }
  return { kind: 'text', suffix: unit, bilingual, joiner }
}

/** 位置上现有的文字像哪种日期写法 → 对应的 strftime。 */
function matchDatePattern(text: string): string | null {
  if (/^\d{4}\.\d{1,2}\.\d{1,2}$/.test(text)) return '%Y.%m.%d'
  if (/^\d{4}-\d{1,2}-\d{1,2}$/.test(text)) return '%Y-%m-%d'
  if (/^\d{4}\/\d{1,2}\/\d{1,2}$/.test(text)) return '%Y/%m/%d'
  if (/^\d{4}年\d{1,2}月\d{1,2}日$/.test(text)) return '%Y年%m月%d日'
  if (/^\d{1,2} [A-Za-z]{3} \d{4}$/.test(text)) return '%d %b %Y'
  if (/^\d{1,2} [A-Za-z]+ \d{4}$/.test(text)) return '%d %B %Y'
  return null
}

// 「符合规定Conform」「未检出\nNot detected」：中文后面紧跟英文
const BILINGUAL_RE = /^([^\n]*[\u4e00-\u9fff])([^A-Za-z]*?)(\n[ \t]*|[ \t]+)?([A-Za-z][\s\S]*)$/

/** 按位置上现有的文字推格式（口径同后端 infer_format）：人工挑位置时用。 */
export function fmtFromSample(text: string, field: FieldShape, defaults: Defaults): CoaTemplateFmt {
  const sample = text.trim()
  if (field.kind === 'batch') {
    if (field.type === 'date') {
      return { kind: 'date', pattern: matchDatePattern(sample) ?? defaults.date_pattern }
    }
    return { kind: 'text' }
  }
  if (!sample) return defaultFmt(field, defaults)
  const number = /^([+-]?\d+(?:\.\d+)?)(.*)$/.exec(sample)
  if (number && !/[\u4e00-\u9fff]/.test(sample)) {
    const decimals = number[1].includes('.') ? number[1].split('.')[1].length : 0
    return { kind: 'number', decimals, suffix: number[2].trim() }
  }
  const pair = BILINGUAL_RE.exec(sample)
  if (pair) return { kind: 'text', bilingual: true, joiner: joinerOf(pair[3] ?? '') }
  const unit = field.unit ?? ''
  if (unit && sample.endsWith(unit) && squash(sample) !== squash(unit)) {
    return { kind: 'text', suffix: unit }
  }
  return { kind: 'text' }
}

export const DATE_PATTERN_OPTIONS: { value: string; label: string }[] = [
  { value: '%Y.%m.%d', label: '2026.01.02' },
  { value: '%Y-%m-%d', label: '2026-01-02' },
  { value: '%Y/%m/%d', label: '2026/01/02' },
  { value: '%Y年%m月%d日', label: '2026年01月02日' },
]

export const JOINER_OPTIONS: { value: '' | ' ' | '\n'; label: string }[] = [
  { value: '', label: '无间隔' },
  { value: ' ', label: '空格' },
  { value: '\n', label: '换行' },
]

/** 内置的判定词英文对照（模板里学到的对照在此之外叠加）。是后端
 *  `template_bind.BUILTIN_VERDICTS` 的镜像：只用来显示和计数，生成 COA 用的是后端那份，改要两处一起改。 */
export const BUILTIN_VERDICTS: readonly (readonly [string, string])[] = [
  ['符合规定', 'Conform'],
  ['不符合规定', 'Does not conform'],
  ['未检出', 'Not detected'],
  ['低于报告限', 'Below reporting limit'],
]

/** 对照表的一行从哪来：内置 / 这份标准自己加的 / 这份标准给内置换了英文写法。 */
export type VerdictSource = 'builtin' | 'custom' | 'override'

export interface VerdictRow {
  cn: string
  en: string
  source: VerdictSource
}

/**
 * 把内置对照和这份标准的自定义合成一张表（生成 COA 时的取值顺序一样：同一个中文以自定义为准）。
 * 自定义和内置写法相同的——AI 从模板里照着学到的那条——按内置显示，同一条不在表里出现两遍。
 */
export function mergeVerdicts(
  custom: Record<string, string>,
  builtIn: readonly (readonly [string, string])[] = BUILTIN_VERDICTS
): VerdictRow[] {
  const builtInKeys = new Set(builtIn.map(([cn]) => cn))
  const rows: VerdictRow[] = builtIn.map(([cn, en]) => {
    const own = custom[cn]
    return { cn, en: own ?? en, source: own === undefined || own === en ? 'builtin' : 'override' }
  })
  for (const [cn, en] of Object.entries(custom)) {
    if (!builtInKeys.has(cn)) rows.push({ cn, en, source: 'custom' })
  }
  return rows
}

const JOINER_NOTE: Record<string, string> = { ' ': '，空格隔开', '\n': '，换行' }

/** 格式规则 → 核对清单里的一句话摘要（完整的编辑器点开那一行才出现）。 */
export function describeFmt(fmt: CoaTemplateFmt): string {
  if (fmt.kind === 'date') {
    const known = DATE_PATTERN_OPTIONS.find((option) => option.value === fmt.pattern)
    return `日期 ${known?.label ?? fmt.pattern ?? ''}`.trim()
  }
  const joiner = fmt.joiner === ' ' || fmt.joiner === '\n' ? JOINER_NOTE[fmt.joiner] : ''
  if (fmt.kind === 'number') {
    const parts = [`数值 · ${fmt.decimals ? `${fmt.decimals} 位小数` : '整数'}`]
    if (fmt.suffix) parts.push(`后缀 ${fmt.suffix}`)
    // 数值位登记成文字判定（符合规定、未检出）时才会用到补英文
    if (fmt.bilingual) parts.push(`判定补英文${joiner}`)
    return parts.join(' · ')
  }
  const parts = ['文字']
  if (fmt.suffix) parts.push(`后缀 ${fmt.suffix}`)
  parts.push(fmt.bilingual ? `补英文${joiner}` : '不补英文')
  return parts.join(' · ')
}

// ─────────────────────── 绑定/解绑（人工挑位置） ───────────────────────

/** 这一步被绑上或被摘下来的数据位：被绑上的离开「待处理」和固定文字；
 *  被摘下来又没被别的字段接手的，落在结果列且非空就进「待处理」（口径同后端 result_residue）。 */
function settleResidue(
  view: CoaTemplateBindingView,
  touched: CoaTemplateSlot[],
  resultColumns: CoaResultColumns
): CoaTemplateBindingView {
  const bound = new Set(view.fields.flatMap((field) => field.slots.map((slot) => slot.sid)))
  const staticSids = new Set(view.static_slots)
  const residue = new Map<string, CoaTemplateResidue>(
    view.residue.map((item) => [item.sid, item])
  )
  for (const slot of touched) {
    if (bound.has(slot.sid)) {
      residue.delete(slot.sid)
      staticSids.delete(slot.sid)
    } else if (isResultSlot(slot.sid, resultColumns) && slot.sample.trim()) {
      residue.set(slot.sid, {
        sid: slot.sid,
        text: slot.sample.trim().slice(0, 60),
        context: slot.context.slice(0, 120),
      })
    }
  }
  return { ...view, residue: [...residue.values()], static_slots: [...staticSids] }
}

/** 把数据位绑到字段上：这个字段原来的位置被替换；别处绑在同一位置的让位。
 *  位置是人工指定的，相关字段的校验标记随之清掉。 */
export function bindSlotToField(
  view: CoaTemplateBindingView,
  fieldKey: string,
  sid: string,
  index: GridIndex,
  resultColumns: CoaResultColumns
): CoaTemplateBindingView {
  const field = view.fields.find((f) => f.field === fieldKey)
  if (!field) return view
  const text = index.textOf.get(sid) ?? ''
  // 位置上已有文字就按它推格式（0.23% → 2 位 + %）；空位沿用这个字段原来的格式，没有就按类型给默认值
  const fmt = text.trim()
    ? fmtFromSample(text, field, view.defaults)
    : (field.slots[0]?.fmt ?? defaultFmt(field, view.defaults))
  const slot = slotFromGrid(sid, index, fmt)
  const touched: CoaTemplateSlot[] = [slot]
  const fields = view.fields.map((f) => {
    if (f.field === fieldKey) {
      touched.push(...f.slots)
      return { ...f, slots: [slot], bound: true, flags: [] }
    }
    if (f.slots.some((s) => s.sid === sid)) {
      touched.push(...f.slots.filter((s) => s.sid === sid))
      const slots = f.slots.filter((s) => s.sid !== sid)
      return { ...f, slots, bound: slots.length > 0, flags: [] }
    }
    return f
  })
  return settleResidue({ ...view, fields }, touched, resultColumns)
}

/** 从字段上摘掉若干数据位（取消位置 / 这个字段不再写入模板）。 */
export function detachSlots(
  view: CoaTemplateBindingView,
  fieldKey: string,
  sids: string[],
  resultColumns: CoaResultColumns
): CoaTemplateBindingView {
  const dropped = new Set(sids)
  const detached: CoaTemplateSlot[] = []
  const fields = view.fields.map((f) => {
    if (f.field !== fieldKey) return f
    detached.push(...f.slots.filter((s) => dropped.has(s.sid)))
    const slots = f.slots.filter((s) => !dropped.has(s.sid))
    return { ...f, slots, bound: slots.length > 0, flags: [] }
  })
  return settleResidue({ ...view, fields }, detached, resultColumns)
}

// ─────────────────────── 核对进度与保存载荷 ───────────────────────

export interface BindingStatus {
  /** 绑定了位置、但带着待确认的校验标记 */
  flagged: CoaTemplateField[]
  /** 没有标注位置 */
  unbound: CoaTemplateField[]
  boundCount: number
  /** 结果列里待处理的格子数 */
  unhandled: number
  canSave: boolean
  /** 不能保存的原因（可以保存时为空） */
  reason: string
}

/**
 * 这一字段要不要人确认才能保存：有位置、且带着校验标记。
 * 没标注位置的字段不带「确认无误」，它的事是「标注位置」，归在「未标注」里；
 * 清单的「需确认」和底栏的「待确认」都按这个数，两处口径一致。
 */
export const needsConfirm = (field: CoaTemplateField): boolean =>
  field.slots.length > 0 && field.flags.length > 0

export function bindingStatus(view: CoaTemplateBindingView): BindingStatus {
  const flagged = view.fields.filter(needsConfirm)
  const unbound = view.fields.filter((f) => f.slots.length === 0)
  const reasons: string[] = []
  if (view.fields.length - unbound.length === 0) reasons.push('还没有标注任何位置')
  if (flagged.length) reasons.push(`${flagged.length} 个字段带校验标记，请逐个确认`)
  if (view.residue.length) reasons.push(`${view.residue.length} 个结果列格子待处理`)
  return {
    flagged,
    unbound,
    boundCount: view.fields.length - unbound.length,
    unhandled: view.residue.length,
    canSave: reasons.length === 0,
    reason: reasons.join('；'),
  }
}

export type ReviewFilter = 'review' | 'all' | 'unbound'

/** AI 标完后清单默认看哪一页：有要人确认的字段先看它们，否则直接看全部（保存前要人工过目）。 */
export function defaultFilter(view: CoaTemplateBindingView): ReviewFilter {
  return view.fields.some(needsConfirm) ? 'review' : 'all'
}

/** 搜索命中：字段中英文名、标准原文、单位、位置、位置上的现有文字。空格分词，每个词都要出现。 */
export function matchesQuery(field: CoaTemplateField, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  // 多个词里夹着的单字母（如「杂质 A」的 A）不单独算依据：它几乎出现在每一行
  const tokens = words.length > 1 ? words.filter((word) => word.length > 1) : words
  const haystack = [
    field.label_cn,
    field.label_en ?? '',
    field.spec_text ?? '',
    field.unit ?? '',
    ...field.slots.map((slot) => `${describeSlot(slot.sid)} ${slot.sample}`),
  ]
    .join(' ')
    .toLowerCase()
  return tokens.every((token) => haystack.includes(token))
}

/** 核对清单的行：带校验标记的排最前；搜索时字段名里直接包含搜索词的排前面；其余保持原顺序。 */
export function visibleFields(
  view: CoaTemplateBindingView,
  filter: ReviewFilter,
  query = ''
): CoaTemplateField[] {
  const keyword = query.trim().toLowerCase()
  const rank = (f: CoaTemplateField) =>
    (f.flags.length > 0 ? 0 : 2) + (keyword && f.label_cn.toLowerCase().includes(keyword) ? 0 : 1)
  return view.fields
    .filter((f) =>
      filter === 'review' ? needsConfirm(f) : filter === 'unbound' ? f.slots.length === 0 : true
    )
    .filter((f) => !keyword || matchesQuery(f, keyword))
    .sort((a, b) => rank(a) - rank(b))
}

/** 只带该类型用得到的键（后端入参 extra=forbid）。 */
function fmtPayload(fmt: CoaTemplateFmt): CoaTemplateFmt {
  if (fmt.kind === 'number') {
    return { kind: 'number', decimals: fmt.decimals, suffix: fmt.suffix, bilingual: fmt.bilingual, joiner: fmt.joiner }
  }
  if (fmt.kind === 'date') return { kind: 'date', pattern: fmt.pattern }
  return { kind: 'text', suffix: fmt.suffix, bilingual: fmt.bilingual, joiner: fmt.joiner }
}

/** 「确认标注并保存」的入参：原位替换的带上要替换的原文，整格替换的不带（后端按格子推导）。 */
export function toBindingPayload(view: CoaTemplateBindingView): CoaTemplateBindingInput {
  return {
    fields: view.fields
      .filter((f) => f.slots.length > 0)
      .map((f) => ({
        field: f.field,
        required: f.required,
        slots: f.slots.map((s) => ({
          sid: s.sid,
          fmt: fmtPayload(s.fmt),
          ...(s.mode === 'inplace' ? { sample: s.sample } : {}),
        })),
      })),
    // 重新打开已保存的标注时，之前确认过的固定文字格在 static_slots 里，本轮新确认的在 residue 里
    static_slots: [...new Set([...view.static_slots, ...view.residue.map((r) => r.sid)])],
    verdicts: view.verdicts,
  }
}

export function fieldKindLabel(field: CoaTemplateField): string {
  return field.kind === 'batch' ? '批次信息' : '检测项目'
}

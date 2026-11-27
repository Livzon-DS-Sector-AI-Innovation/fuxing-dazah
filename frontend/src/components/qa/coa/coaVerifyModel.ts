// COA 验证的纯展示逻辑：把后端的比对结果翻成给 non-technical 的人看的结论文字。
// 不含 React，可直接用 Node 跑用例。
import type { CoaVerifyDifference, CoaVerifyResult, CoaVerifySlot, CoaVerifyVerdict } from '@/types/qa'

export type VerdictTone = 'success' | 'warning' | 'error'

export const VERDICT_META: Record<CoaVerifyVerdict, { tone: VerdictTone; label: string }> = {
  identical: { tone: 'success', label: '逐字节一致' },
  content_match: { tone: 'success', label: '内容一致' },
  altered: { tone: 'error', label: '不一致' },
  no_record: { tone: 'warning', label: '无生成记录' },
}

/** 每种结论对应的一句话标题。 */
export function verdictTitle(verdict: CoaVerifyVerdict): string {
  switch (verdict) {
    case 'identical':
      return '系统原件，没有任何改动'
    case 'content_match':
      return '内容与系统原件一致'
    case 'altered':
      return '与系统原件不一致'
    case 'no_record':
      return '系统没有出过这份文件'
  }
}

function countMismatched(slots: CoaVerifySlot[]): number {
  return slots.filter((slot) => slot.status === 'differs' || slot.status === 'context_differs').length
}

/**
 * 结论下面那段解释：说清「凭什么这么判」，数字直接取自比对结果。
 * 是哪一次生成、谁生成的由旁边的信息行交代，这里不重复。
 */
export function verdictExplanation(result: CoaVerifyResult): string {
  switch (result.verdict) {
    case 'identical':
      return '与系统留档的原件逐字节一致。'
    case 'content_match':
      return '文件里的文字与系统原件完全一致；字节不同是因为文件被 Word、WPS 重新保存或转存过。'
    case 'altered': {
      const changed = countMismatched(result.slots)
      const parts: string[] = []
      if (changed) parts.push(`系统填写的位置有 ${changed} 处对不上`)
      if (result.unresolved) parts.push(`${result.unresolved} 处在文件里找不到`)
      if (result.other_differences.length) {
        parts.push(`系统没填写的位置也有 ${result.other_differences.length} 处不同`)
      }
      return `${parts.join('，') || '有位置对不上'}。文件在生成后被改过，或者不是系统出的。`
    }
    case 'no_record':
      return result.report
        ? `批号 ${result.report.batch_no} 在系统里没有生成记录。`
        : '文件里的批号在系统里没有生成记录。'
  }
}

/** 比对范围的说明：full_text 是完整比对，written_only 要如实说明只比了哪些。 */
export function scopeNote(result: CoaVerifyResult): string | null {
  if (result.verdict === 'identical') return null
  if (result.scope === 'full_text') return '比对的是文件里的全部文字，不含字体和排版。'
  if (result.scope === 'written_only') {
    return `留档原件已不在存储里：这次只比对了系统填写的 ${result.compared} 处，其余固定文字没有比对。`
  }
  return null
}

/** 有逐位置明细可看的结论：对上了留档才比得了位置。 */
export function hasSlotDetail(verdict: CoaVerifyVerdict): boolean {
  return verdict === 'altered' || verdict === 'content_match'
}

/** 一个系统写入位置的状态文字；一致时返回 null（明细里默认只列对不上的）。 */
export function slotProblem(slot: CoaVerifySlot): string | null {
  switch (slot.status) {
    case 'differs':
      return '内容被改'
    case 'context_differs':
      return '内容没变，同一段里的其它文字被改'
    case 'missing_position':
      return '文件里找不到这一处'
    case 'match':
      return null
  }
}

/** 系统没写入的位置上的差异，一行文字。位置说明来自 describeSlot（由调用方传入，避免循环依赖）。 */
export function differenceLine(
  difference: CoaVerifyDifference,
  describe: (sid: string) => string,
): string {
  const where = difference.sid ? `${difference.where} ${describe(difference.sid)}` : difference.where
  switch (difference.status) {
    case 'added':
      return `${where}：多出「${difference.actual}」`
    case 'missing_position':
      return `${where}：「${difference.expected}」不见了`
    case 'differs':
      return `${where}：「${difference.expected}」变成「${difference.actual}」`
  }
}

export function formatVerifyTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

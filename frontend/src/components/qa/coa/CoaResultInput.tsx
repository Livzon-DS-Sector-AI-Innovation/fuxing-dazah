'use client'

import { useId } from 'react'
import { Input, Segmented } from 'antd'
import type { CoaValueInput, CoaValueType } from '@/types/qa'
import { CoaLimitMark } from './CoaLimitFlag'
import { checkSpecLimit, limitHitDetail, limitHitLabel } from './coaSpecLimit'
import type { CoaSpecLimit } from './coaSpecLimit'
import styles from './CoaResultInput.module.css'

export type CoaResultMode = 'num' | 'text'

/** 结果草稿：mode=输入框当前形态，raw=输入框原文（唯一真值，解析只发生在落库形态上）；
 * num/text=落库形态——未改动的编辑基值原样回传，不给历史报告无声改写。 */
export interface CoaResultDraft {
  mode: CoaResultMode
  raw: string
  num: number | null
  text: string | null
}

/** 数值，以及敲到一半的数值（"4." "-" "1e-5"）；空串不算。 */
const NUMERIC_LIKE = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d*)?$/

function toNum(raw: string): number | null {
  return NUMERIC_LIKE.test(raw) && Number.isFinite(Number(raw)) ? Number(raw) : null
}

/** 落库值 → 草稿（编辑回填 / 导入识别值）。有数值即数值形态；原文优先取文字影子，
 * 保留 4.50 这类有效位。 */
export function toResultDraft(value: {
  value_num: number | null
  value_text: string | null
}): CoaResultDraft {
  if (value.value_num != null) {
    return {
      mode: 'num',
      raw: value.value_text || String(value.value_num),
      num: value.value_num,
      text: value.value_text,
    }
  }
  return { mode: 'text', raw: value.value_text ?? '', num: null, text: value.value_text }
}

/** 按项目类型建空草稿：数值型项目默认数值形态（模板已声明类型，不必逐行切换）。 */
export function emptyResultDraft(valueType: CoaValueType): CoaResultDraft {
  return { mode: valueType === 'number' ? 'num' : 'text', raw: '', num: null, text: null }
}

/** 输入框改动。数值形态下清空仍是数值形态；敲入非数值内容（如 <0.20）自动转为文字形态。 */
export function editResultDraft(draft: CoaResultDraft, raw: string): CoaResultDraft {
  if (!raw.trim()) return { mode: draft.mode, raw: '', num: null, text: null }
  if (draft.mode === 'num' && NUMERIC_LIKE.test(raw.trim())) {
    return { mode: 'num', raw, num: toNum(raw.trim()), text: raw }
  }
  return { mode: 'text', raw, num: null, text: raw }
}

/** 切换形态。转文字保留已敲内容（挪到前面补个 < 即可）；转数值能解析的照单全收，
 * 解析不了的（"符合规定"）清空。 */
export function switchResultMode(draft: CoaResultDraft, mode: CoaResultMode): CoaResultDraft {
  if (mode === draft.mode) return draft
  if (mode === 'text') return { mode, raw: draft.raw, num: null, text: draft.raw }
  const num = toNum(draft.raw.trim())
  return num == null ? emptyResultDraft('number') : { mode, raw: draft.raw, num, text: draft.raw }
}

/** 草稿 → 载荷；空结果不落（未填即留空）。 */
export function draftToValueInput(item_id: string, draft: CoaResultDraft): CoaValueInput | null {
  if (!draft.raw.trim()) return null
  return { item_id, value_num: draft.num, value_text: draft.text?.trim() || null }
}

/** 回车跳到列表里当前输入框的下一个，浏览器顺带把它滚进可视区；列表走完停在原地。 */
function focusNextOf(inputs: HTMLElement[], current: HTMLElement) {
  inputs[inputs.indexOf(current) + 1]?.focus()
}

/** 检测结果格回车：同一张表内按 DOM 顺序找下一个结果框。 */
function focusNextResultInput(current: HTMLElement) {
  const scope = current.closest<HTMLElement>('[data-coa-result-scope]') ?? document
  focusNextOf(
    Array.from(scope.querySelectorAll<HTMLElement>('[data-coa-result-input]')),
    current,
  )
}

/**
 * 报告信息里的输入框回车：跳到报告信息的下一个输入框，字段走完就跳到检测结果的
 * 第一个（先填报告信息、再从上往下填结果，是登记的实际顺序）。
 * 报告信息的输入框带 data-coa-head-input，整个表单容器带 data-coa-form-scope；
 * 报告信息在 DOM 里排在检测结果后面，所以顺序要自己拼。手工登记与导入审核共用。
 */
export function focusNextHeadInput(event: { currentTarget: HTMLElement }) {
  const root = event.currentTarget.closest<HTMLElement>('[data-coa-form-scope]')
  if (!root) return
  focusNextOf(
    [
      ...root.querySelectorAll<HTMLElement>('[data-coa-head-input]'),
      ...root.querySelectorAll<HTMLElement>('[data-coa-result-input]'),
    ],
    event.currentTarget,
  )
}

/**
 * 检测结果录入格：[类型位][输入框][单位位]，手工登记与导入预览共用。
 * 类型位平时是一枚灰字，行悬停或行内聚焦时才换成「数值 / 文字」切换器——
 * 类型默认跟模板，绝大多数行用不到切换，不必每行都挂一个控件。
 *
 * 给了 limit 就顺带判越界：超限时输入框染底色，框内右侧出一枚文字标记，
 * 悬停看详情。只提醒、不拦保存。
 */
export function CoaResultInput({
  itemKey,
  label,
  draft,
  unit,
  onChange,
  limit,
  specText,
  settled = true,
  onBlur,
}: {
  /** 行键；同时是回车跳行时定位输入框的 data 键 */
  itemKey: string
  /** 项目名，拼进无障碍名称（每格一个输入框，光靠行文字读不出归属） */
  label: string
  draft: CoaResultDraft
  /** 单位位：undefined=不留位（导入预览无单位数据）；null=留空位（同列单位宽窄不一，保持输入框对齐） */
  unit?: string | null
  onChange: (draft: CoaResultDraft) => void
  /** 项目的标准限度；没有可判的限度（或调用方不判）就不传 */
  limit?: CoaSpecLimit | null
  /** 标准原文，拼进标记的悬停说明 */
  specText?: string | null
  /** 这格是否已输完（见 useSettledInput）：输入途中不显示越界标记 */
  settled?: boolean
  onBlur?: () => void
}) {
  const isNum = draft.mode === 'num'
  const hit =
    limit && settled
      ? checkSpecLimit(limit, { num: draft.num, text: draft.raw }, unit ?? null)
      : null
  const markId = useId()
  return (
    <div className={styles.cell}>
      <div className={styles.typeSlot}>
        {/* 灰字停在切换器选中项的位置上，淡入淡出时文字不跳 */}
        <span
          className={`${styles.typeLabel} ${isNum ? styles.typeLabelNum : styles.typeLabelText}`}
          aria-hidden="true"
        >
          {isNum ? '数值' : '文字'}
        </span>
        <Segmented
          className={styles.typeSwitch}
          size="small"
          aria-label={`${label} 的结果类型`}
          value={draft.mode}
          options={[
            { value: 'num', label: '数值' },
            { value: 'text', label: '文字' },
          ]}
          onChange={(mode) => onChange(switchResultMode(draft, mode === 'num' ? 'num' : 'text'))}
        />
      </div>
      <Input
        size="small"
        className={`${styles.input} ${
          hit ? (hit.certainty === 'possible' ? styles.inputPossible : styles.inputOvers) : ''
        }`}
        aria-label={`${label} 的结果`}
        aria-describedby={hit ? markId : undefined}
        data-coa-result-input={itemKey}
        data-coa-limit-hit={hit ? '' : undefined}
        inputMode={isNum ? 'decimal' : undefined}
        placeholder={isNum ? undefined : '符合规定 / <0.20'}
        value={draft.raw}
        onChange={(e) => onChange(editResultDraft(draft, e.target.value))}
        onBlur={onBlur}
        onPressEnter={(e) => focusNextResultInput(e.currentTarget)}
        // 容器常驻：聚焦时才插入 suffix 会改变 DOM 结构，输入框会失焦（antd FAQ）
        suffix={
          <span className={styles.suffix}>
            {hit && (
              <CoaLimitMark
                hit={hit}
                bare
                id={markId}
                title={limitHitDetail({
                  item: { spec_text: specText ?? null, unit: unit ?? null },
                  hit,
                })}
              >
                {limitHitLabel(hit)}
              </CoaLimitMark>
            )}
          </span>
        }
      />
      {unit !== undefined && (
        <span className={styles.unit} title={unit || undefined}>
          {unit}
        </span>
      )}
    </div>
  )
}

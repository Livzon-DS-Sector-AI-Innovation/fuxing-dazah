import type { FormInstance, FormRule as Rule } from 'antd'
import type { CoaStandard } from '@/types/qa'

type CodedStandard = Pick<CoaStandard, 'id' | 'code'>

export interface StandardCodeScope {
  /** 归属产品的短码，只用在提示文案里 */
  productCode?: string
  /** 编辑已有标准时排除自己：编号没改不算重复 */
  excludeId?: string
  /** 撞号后怎么办，接在「…已存在」后面 */
  fix: string
}

/** 模板编号在产品内唯一。比较口径镜像后端创建/改名：去首尾空格后精确比较，区分大小写。 */
function normalizeStandardCode(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** 占用这个编号的已有标准。清单还没加载出来时返回 null（先放行，后端仍会拦）。 */
function findStandardByCode(
  code: unknown,
  standards: readonly CodedStandard[] | undefined,
  excludeId?: string
): CodedStandard | null {
  const normalized = normalizeStandardCode(code)
  if (!normalized || !standards) return null
  return (
    standards.find((standard) => standard.code === normalized && standard.id !== excludeId) ?? null
  )
}

/** 这个编号已被占用时的完整提示；没撞（或清单还没到）返回 undefined。前半句与后端 409 文案同口径。 */
export function takenCodeMessage(
  code: unknown,
  standards: readonly CodedStandard[] | undefined,
  scope: StandardCodeScope
): string | undefined {
  const hit = findStandardByCode(code, standards, scope.excludeId)
  if (!hit) return undefined
  return `产品 ${scope.productCode ?? ''} 下模板编号 ${hit.code} 已存在，${scope.fix}`
}

/** 「模板编号」字段要挂的校验时机（Form.Item 的 validateTrigger）。必填在输入时就查；
 * 唯一性规则只在失焦和提交时查，输入过程中不打扰——字段默认只认 onChange，
 * 不挂上 onBlur 的话失焦根本走不到规则。 */
export const STANDARD_CODE_VALIDATE_TRIGGER = ['onChange', 'onBlur']

/**
 * 「模板编号」字段的唯一性规则，要和 STANDARD_CODE_VALIDATE_TRIGGER 搭配使用。
 * 规则随每次渲染重建，表单校验时取的是最新一份，可以直接闭包当前的清单。
 */
export function standardCodeRule(
  standards: readonly CodedStandard[] | undefined,
  scope: StandardCodeScope
): Rule {
  return {
    validateTrigger: 'onBlur',
    validator: (_, value) => {
      const message = takenCodeMessage(value, standards, scope)
      return message ? Promise.reject(new Error(message)) : Promise.resolve()
    },
  }
}

/** 校验没过时把焦点送到第一个出错的字段。这里是手动 validateFields，
 * Form 的 scrollToFirstError 只跟着 submit 事件走，管不到。 */
export function focusFirstError(form: FormInstance) {
  const first = form.getFieldsError().find((field) => field.errors.length > 0)
  if (first) form.scrollToField(first.name, { focus: true, block: 'nearest' })
}

'use client'

import { Form, Input, InputNumber, Select, Switch } from 'antd'
import type { FieldDef, FieldValueInput } from '@/types/production'

/** 把 antd Form values（key 为 field_key）转为后端 field_values 数组 */
export function buildFieldValues(
  defs: FieldDef[],
  values: Record<string, unknown>,
): FieldValueInput[] {
  return defs
    .filter(d => values[d.field_key] !== undefined && values[d.field_key] !== null && values[d.field_key] !== '')
    .map(d => ({ field_key: d.field_key, value: values[d.field_key] as never }))
}

/** 动态渲染一组字段定义。required 阻断；numeric 超限 warningOnly 警示不阻断（与后端 is_abnormal 对齐） */
export function DynamicFieldFormItems({ defs }: { defs: FieldDef[] }) {
  const sorted = [...defs].sort((a, b) => a.sort_order - b.sort_order)
  return (
    <>
      {sorted.map(d => {
        const label = d.field_group
          ? `${d.field_label}（${d.field_group}）${d.unit ? ` (${d.unit})` : ''}`
          : `${d.field_label}${d.unit ? ` (${d.unit})` : ''}`
        const rules: object[] = []
        if (d.required) rules.push({ required: true, message: `请填写${d.field_label}` })
        if (d.data_type === 'numeric' && (d.min_value !== null || d.max_value !== null)) {
          rules.push({
            warningOnly: true,
            validator: (_: unknown, v: number | undefined) => {
              if (v === undefined || v === null) return Promise.resolve()
              if (d.min_value !== null && v < d.min_value)
                return Promise.reject(new Error(`低于下限 ${d.min_value}，将标记为异常`))
              if (d.max_value !== null && v > d.max_value)
                return Promise.reject(new Error(`超过上限 ${d.max_value}，将标记为异常`))
              return Promise.resolve()
            },
          })
        }
        const isBoolean = d.data_type === 'boolean'
        return (
          <Form.Item
            key={d.field_key}
            name={d.field_key}
            label={label}
            rules={rules}
            {...(isBoolean ? { valuePropName: 'checked' } : {})}
          >
            {d.data_type === 'numeric' ? (
              <InputNumber style={{ width: '100%' }} />
            ) : isBoolean ? (
              <Switch />
            ) : d.data_type === 'select' ? (
              <Select options={(d.options ?? []).map(o => ({ value: o, label: o }))} />
            ) : (
              <Input />
            )}
          </Form.Item>
        )
      })}
    </>
  )
}

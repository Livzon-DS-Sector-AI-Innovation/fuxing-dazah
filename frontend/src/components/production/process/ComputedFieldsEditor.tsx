'use client'

import { Button, Input, Select } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { ComputedFieldIn } from '@/types/production'

/** 展示节点选项（node_code + 节点名） */
export interface ComputedFieldNodeOption {
  node_code: string
  node_name: string
}

/** 可引用的路线数值字段 */
export interface ComputedFieldOption {
  node_code: string
  field_key: string
  field_label: string
}

/** 运算符快捷按钮：展示符号与实际插入公式的字符（后端语法为 + - * / ( )） */
const OPERATORS: { label: string; insert: string }[] = [
  { label: '+', insert: '+' },
  { label: '-', insert: '-' },
  { label: '×', insert: '*' },
  { label: '÷', insert: '/' },
  { label: '(', insert: '(' },
  { label: ')', insert: ')' },
]

const cardStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e5e3df',
  borderRadius: 10,
  padding: 12,
  marginBottom: 8,
}
const rowStyle: React.CSSProperties = {
  display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap',
}

interface Props {
  nodes: ComputedFieldNodeOption[]
  field_options: ComputedFieldOption[]
  value?: ComputedFieldIn[]
  onChange?: (v: ComputedFieldIn[]) => void
}

export function ComputedFieldsEditor({ nodes, field_options, value = [], onChange }: Props) {
  const update = (idx: number, patch: Partial<ComputedFieldIn>) => {
    const next = value.map((f, i) => (i === idx ? { ...f, ...patch } : f))
    onChange?.(next)
  }
  const add = () =>
    onChange?.([
      ...value,
      {
        node_code: '',
        field_key: '',
        field_label: '',
        unit: null,
        formula: '',
        sort_order: value.length + 1,
      },
    ])
  const remove = (idx: number) => onChange?.(value.filter((_, i) => i !== idx))

  const nameByCode = new Map(nodes.map(n => [n.node_code, n.node_name]))
  const refOptions = field_options.map(o => ({
    value: `${o.node_code}.${o.field_key}`,
    label: `${nameByCode.get(o.node_code) ?? o.node_code}.${o.field_label}`,
  }))

  /** 向公式末尾追加字符（字段引用追加为 {node_code.field_key}） */
  const appendFormula = (idx: number, text: string) =>
    update(idx, { formula: (value[idx].formula ?? '') + text })

  return (
    <div>
      {value.length === 0 && (
        <p style={{ color: '#787671', textAlign: 'center', margin: '32px 0' }}>
          暂未配置计算字段，点击下方按钮添加
        </p>
      )}
      {value.map((f, i) => (
        <div key={i} style={cardStyle}>
          {/* ── 第一行：节点 + 字段键 + 显示名 + 单位 + 删除 ── */}
          <div style={{ ...rowStyle, marginBottom: 10, alignItems: 'center' }}>
            <Select
              placeholder="展示节点"
              value={f.node_code || undefined}
              options={nodes.map(n => ({
                value: n.node_code,
                label: `${n.node_name || '未命名'}（${n.node_code}）`,
              }))}
              onChange={v => update(i, { node_code: v ?? '' })}
              style={{ width: 160 }}
            />
            <Input
              placeholder="字段键 *"
              value={f.field_key}
              onChange={e => update(i, { field_key: e.target.value })}
              style={{ width: 120 }}
            />
            <Input
              placeholder="显示名 *"
              value={f.field_label}
              onChange={e => update(i, { field_label: e.target.value })}
              style={{ flex: 1, minWidth: 140 }}
            />
            <Input
              placeholder="单位"
              value={f.unit ?? ''}
              onChange={e => update(i, { unit: e.target.value || null })}
              style={{ width: 80 }}
            />
            <Button
              size="small"
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => remove(i)}
            />
          </div>

          {/* ── 第二行：公式 + 字段引用下拉 + 运算符快捷按钮 ── */}
          <Input.TextArea
            placeholder="公式，如 {N1.进罐量}*2 + 100"
            value={f.formula}
            onChange={e => update(i, { formula: e.target.value })}
            autoSize={{ minRows: 2, maxRows: 6 }}
          />
          <div style={{ ...rowStyle, marginTop: 8, alignItems: 'center' }}>
            <Select
              showSearch={{ optionFilterProp: 'label' }}
              placeholder="插入字段引用"
              value={null}
              options={refOptions}
              onChange={v => appendFormula(i, `{${v}}`)}
              style={{ width: 240 }}
            />
            {OPERATORS.map(op => (
              <Button key={op.label} size="small" onClick={() => appendFormula(i, op.insert)}>
                {op.label}
              </Button>
            ))}
          </div>
        </div>
      ))}
      <Button icon={<PlusOutlined />} onClick={add} block style={{ marginTop: 4 }}>
        添加计算字段
      </Button>
    </div>
  )
}

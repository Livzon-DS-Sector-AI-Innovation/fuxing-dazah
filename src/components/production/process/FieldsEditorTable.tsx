'use client'

import { Button, Checkbox, Input, InputNumber, Select } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { FieldDefIn } from '@/types/production'

// ── 常量 ──

/** 阶段色标：开始 = 绿色，结束 = 蓝色 */
const PHASE_BAR: Record<string, string> = { start: '#1aae39', end: '#0075de' }
const PHASE_BG: Record<string, string> = { start: '#f0faf2', end: '#f0f5fc' }
const PHASE_LABEL: Record<string, string> = { start: '开始', end: '结束' }
const TYPE_LABEL: Record<string, string> = {
  numeric: '数值',
  text: '文本',
  boolean: '布尔',
  select: '选项',
}

/** ── 卡片样式 ── */
const cardStyle = (phase: string): React.CSSProperties => ({
  background: '#fff',
  border: '1px solid #e5e3df',
  borderLeft: `4px solid ${PHASE_BAR[phase]}`,
  borderRadius: 10,
  padding: 12,
  marginBottom: 8,
})
const rowStyle: React.CSSProperties = {
  display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap',
}
const gutter = 10

interface Props {
  value: FieldDefIn[]
  onChange: (fields: FieldDefIn[]) => void
}

export function FieldsEditorTable({ value, onChange }: Props) {
  const update = (idx: number, patch: Partial<FieldDefIn>) => {
    const next = value.map((f, i) => (i === idx ? { ...f, ...patch } : f))
    onChange(next)
  }
  const add = () =>
    onChange([
      ...value,
      {
        field_key: `field_${value.length + 1}`,
        field_label: '',
        field_group: null,
        phase: 'end',
        data_type: 'numeric',
        options: null,
        unit: null,
        required: false,
        min_value: null,
        max_value: null,
        sort_order: value.length + 1,
      },
    ])
  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx))

  return (
    <div>
      {value.length === 0 && (
        <p style={{ color: '#787671', textAlign: 'center', margin: '40px 0' }}>
          暂无字段，点击下方按钮添加
        </p>
      )}
      {value.map((f, i) => (
        <div key={i} style={cardStyle(f.phase)}>
          {/* ── 第一行：阶段 + 显示名 + 必填 + 删除 ── */}
          <div style={{ ...rowStyle, marginBottom: gutter, alignItems: 'center' }}>
            <span
              style={{
                background: PHASE_BG[f.phase],
                color: PHASE_BAR[f.phase],
                fontWeight: 600,
                fontSize: 13,
                padding: '2px 10px',
                borderRadius: 6,
                flexShrink: 0,
              }}
            >
              {PHASE_LABEL[f.phase]}
            </span>
            <Input
              placeholder="显示名 *"
              value={f.field_label}
              onChange={e => update(i, { field_label: e.target.value })}
              style={{ flex: 1, minWidth: 160 }}
            />
            <Input
              placeholder="字段键"
              value={f.field_key}
              onChange={e => update(i, { field_key: e.target.value })}
              style={{ width: 130 }}
            />
            <Checkbox
              checked={f.required}
              onChange={e => update(i, { required: e.target.checked })}
            >
              必填
            </Checkbox>
            <Button
              size="small"
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => remove(i)}
            />
          </div>

          {/* ── 第二行：类型 + 单位 + 分组 + 条件字段 ── */}
          <div style={rowStyle}>
            {/* 类型 */}
            <Select
              value={f.data_type}
              style={{ width: 110 }}
              options={Object.entries(TYPE_LABEL).map(([v, l]) => ({
                value: v,
                label: l,
              }))}
              onChange={v => {
                const reset: Partial<FieldDefIn> = { data_type: v }
                // 切类型时清掉与前类型绑定的条件字段
                if (v === 'select') {
                  reset.min_value = null
                  reset.max_value = null
                  reset.unit = null
                }
                if (v === 'numeric') reset.options = null
                if (v === 'boolean' || v === 'text') {
                  reset.min_value = null
                  reset.max_value = null
                  reset.options = null
                  reset.unit = null
                }
                update(i, reset)
              }}
            />
            {/* 单位（数值类） */}
            {(f.data_type === 'numeric' || f.data_type === 'text') && (
              <Input
                placeholder="单位"
                value={f.unit ?? ''}
                onChange={e => update(i, { unit: e.target.value || null })}
                style={{ width: 80 }}
              />
            )}
            {/* 分组 */}
            <Input
              placeholder="分组标签"
              value={f.field_group ?? ''}
              onChange={e => update(i, { field_group: e.target.value || null })}
              style={{ width: 130 }}
            />
            {/* 数值：下限 + 上限 */}
            {f.data_type === 'numeric' && (
              <>
                <InputNumber
                  placeholder="下限"
                  value={f.min_value ?? undefined}
                  onChange={v => update(i, { min_value: v ?? null })}
                  style={{ width: 100 }}
                />
                <span style={{ lineHeight: '32px', color: '#787671' }}>~</span>
                <InputNumber
                  placeholder="上限"
                  value={f.max_value ?? undefined}
                  onChange={v => update(i, { max_value: v ?? null })}
                  style={{ width: 100 }}
                />
              </>
            )}
            {/* 选项类型：tags */}
            {f.data_type === 'select' && (
              <Select
                mode="tags"
                value={f.options ?? []}
                onChange={v => update(i, { options: v })}
                style={{ flex: 1, minWidth: 200 }}
                placeholder="输入选项后回车"
              />
            )}
          </div>
        </div>
      ))}
      <Button
        icon={<PlusOutlined />}
        onClick={add}
        block
        style={{ marginTop: 4 }}
      >
        添加字段
      </Button>
    </div>
  )
}

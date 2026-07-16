'use client'

import { useEffect, useState } from 'react'
import { Button, Descriptions, Drawer, Empty, Tag } from 'antd'
import type { FieldDef, FieldDefIn, RouteNode } from '@/types/production'
import { FieldsEditorTable } from './FieldsEditorTable'

const DATA_TYPE_LABEL: Record<string, string> = {
  numeric: '数值',
  text: '文本',
  boolean: '布尔',
  select: '选项',
}

const toFieldIn = (f: FieldDef): FieldDefIn => ({
  field_key: f.field_key,
  field_label: f.field_label,
  field_group: f.field_group,
  phase: f.phase,
  data_type: f.data_type,
  options: f.options,
  unit: f.unit,
  required: f.required,
  min_value: f.min_value,
  max_value: f.max_value,
  sort_order: f.sort_order,
})

function FieldGroup({ title, fields }: { title: string; fields: FieldDef[] }) {
  if (!fields.length) return null
  return (
    <Descriptions
      title={title}
      column={1}
      size="small"
      bordered
      style={{ marginBottom: 16 }}
      items={fields.map(f => ({
        key: f.id,
        label: (
          <span>
            {f.field_label}
            {f.required && <span style={{ color: '#e03131' }}> *</span>}
          </span>
        ),
        children: (
          <span>
            <Tag>{DATA_TYPE_LABEL[f.data_type]}</Tag>
            {f.unit && <Tag>{f.unit}</Tag>}
            {f.field_group && <Tag color="blue">{f.field_group}</Tag>}
            {f.data_type === 'numeric' && (f.min_value !== null || f.max_value !== null) && (
              <span style={{ color: '#787671', fontSize: 12 }}>
                范围 {f.min_value ?? '-∞'} ~ {f.max_value ?? '+∞'}
              </span>
            )}
          </span>
        ),
      }))}
    />
  )
}

interface Props {
  open: boolean
  node: RouteNode | null
  editable: boolean
  onClose: () => void
  onSave?: (fields: FieldDefIn[]) => void
}

export function NodeFieldsDrawer({ open, node, editable, onClose, onSave }: Props) {
  const isEdit = editable && !!onSave
  const [localFields, setLocalFields] = useState<FieldDefIn[]>([])
  useEffect(() => {
    if (open && node) setLocalFields(node.fields.map(toFieldIn))
    // 依赖 node?.id 而非 node：RouteGraphEditor 每次 render 内联构造新 node 对象，
    // 依赖整个 node 会在父级重渲染时重置 localFields，丢失用户正在编辑的内容
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, node?.id])

  const startFields = node?.fields.filter(f => f.phase === 'start') ?? []
  const endFields = node?.fields.filter(f => f.phase === 'end') ?? []

  return (
    <Drawer
      title={node ? `${node.name}（${node.node_code}）字段配置` : '字段配置'}
      open={open}
      onClose={onClose}
      size="large"
      destroyOnHidden
      footer={
        isEdit ? (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" onClick={() => onSave?.(localFields)}>
              保存字段
            </Button>
          </div>
        ) : undefined
      }
    >
      {isEdit ? (
        <FieldsEditorTable value={localFields} onChange={setLocalFields} />
      ) : !node?.fields.length ? (
        <Empty description="该工序尚未配置字段" />
      ) : (
        <>
          <FieldGroup title="开始工序时填写" fields={startFields} />
          <FieldGroup title="结束工序时填写" fields={endFields} />
        </>
      )}
    </Drawer>
  )
}

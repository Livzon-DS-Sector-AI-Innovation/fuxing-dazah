'use client'

import { useState } from 'react'
import { App, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { actionError } from '@/components/qa/deviation/shared'
import { replaceCoaStandardFields, restoreCoaStandardFields } from '@/actions/qa'
import type { CoaProductField } from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import styles from './CoaStandardFieldsSection.module.css'
import {
  CoaBatchFieldsEditor,
  rowsToFieldPayload,
  stripBuiltinFields,
  toFieldRow,
  validateFieldRows,
  type CoaBatchFieldRow,
  type CoaFieldMark,
} from './CoaBatchFieldsEditor'

/** 生效集 vs 产品默认的行级差异：标记（新增/已修改）+ 被移除的默认字段。
 * 内置 3 字段（品名/批号/流水号）恒定存在，不参与差异比对。 */
function diffFields(effective: CoaProductField[], defaults: CoaProductField[]) {
  const eff = stripBuiltinFields(effective)
  const def = stripBuiltinFields(defaults)
  const defMap = new Map(def.map((f) => [f.key, f]))
  const effKeys = new Set(eff.map((f) => f.key))
  const marks: Record<string, CoaFieldMark> = {}
  for (const f of eff) {
    const d = defMap.get(f.key)
    if (!d) {
      marks[f.key] = { text: '新增', color: 'green' }
    } else if (
      d.label_cn !== f.label_cn ||
      (d.label_en ?? '') !== (f.label_en ?? '') ||
      d.field_type !== f.field_type
    ) {
      marks[f.key] = { text: '已修改', color: 'orange' }
    }
  }
  const removed = def.filter((f) => !effKeys.has(f.key))
  return { marks, removed }
}

/**
 * 标准单页的批次信息字段区块：直接展示生效字段集（标准覆盖 ?? 产品默认），
 * 自定义时行级标注与产品默认的差异（新增/已修改/已移除）。
 */
export function CoaStandardFieldsSection({
  standardId,
  fields,
  defaults,
  custom,
  canManage,
  onSaved,
}: {
  standardId: string
  fields: CoaProductField[]
  defaults: CoaProductField[]
  custom: boolean
  canManage: boolean
  onSaved: () => void
}) {
  const { message, modal } = App.useApp()
  const [editing, setEditing] = useState(false)
  // 产品默认集在各模板间一样，默认收起省版面；自定义集是差异，默认展开
  const [showTable, setShowTable] = useState(custom)
  const [saving, setSaving] = useState(false)

  const handleSave = async (rows: CoaBatchFieldRow[]) => {
    const problem = validateFieldRows(rows)
    if (problem) {
      message.warning(problem)
      return
    }
    setSaving(true)
    try {
      const result = await replaceCoaStandardFields(standardId, rowsToFieldPayload(rows))
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(`已保存 ${rows.length} 个批次字段（自定义）`)
      setEditing(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const handleRestore = () => {
    confirmAsync(modal, {
      title: '恢复产品默认？',
      content: '该模板的自定义批次字段将被删除，改用产品默认字段集。',
      okButtonProps: DANGER_OK_PROPS,
      onOk: async () => {
        setSaving(true)
        try {
          const result = await restoreCoaStandardFields(standardId)
          if (!result.success) {
            message.error(actionError(result))
            return
          }
          message.success('已恢复产品默认字段集')
          onSaved()
        } finally {
          setSaving(false)
        }
      },
    })
  }

  const { marks, removed } = diffFields(fields, defaults)
  const added = Object.values(marks).filter((m) => m.text === '新增').length
  const changed = Object.keys(marks).length - added

  return (
    <div>
      {editing ? (
        <FieldsEditBlock
          key={`edit-${fields.length}-${String(custom)}`}
          initialFields={fields}
          saving={saving}
          onCancel={() => setEditing(false)}
          onSave={handleSave}
        />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
            <span style={{ color: 'var(--color-steel)', fontSize: 12.5 }}>
              {custom
                ? `自定义字段集：较产品默认 新增 ${added} / 修改 ${changed} / 移除 ${removed.length}`
                : `产品默认字段集（共 ${fields.length} 个），产品下各模板共用，可在产品管理中调整`}
              {!custom && !showTable && fields.length > 0 && `：${fields.map((f) => f.label_cn).join('、')}`}
            </span>
            <span style={{ display: 'inline-flex', gap: 8, flex: 'none' }}>
              <Button
                size="small"
                type="text"
                aria-expanded={showTable}
                onClick={() => setShowTable((v) => !v)}
              >
                {showTable ? '收起' : '展开'}
              </Button>
              {canManage && (
                <Button size="small" onClick={() => setEditing(true)}>
                  自定义
                </Button>
              )}
              {custom && canManage && (
                <Button
                  size="small"
                  type="text"
                  danger
                  loading={saving}
                  onClick={handleRestore}
                >
                  恢复默认
                </Button>
              )}
            </span>
          </div>
          <div
            className={`${styles.collapse} ${showTable ? '' : styles.collapsed}`}
            inert={!showTable}
          >
            <CoaBatchFieldsEditor
              rows={stripBuiltinFields(fields).map(toFieldRow)}
              onChange={() => {}}
              editable={false}
              marks={custom ? marks : undefined}
            />
          </div>
          {custom && removed.length > 0 && (
            <p style={{ margin: '8px 0 0', color: 'var(--color-steel)', fontSize: 12 }}>
              产品默认还有、该模板未用的字段：
              {removed.map((f) => `${f.label_cn}（${f.key}）`).join('、')}
            </p>
          )}
        </>
      )}
    </div>
  )
}



/** 编辑块：条件挂载初始化行集（详情数据变了重开编辑即重置）。 */
function FieldsEditBlock({
  initialFields,
  saving,
  onCancel,
  onSave,
}: {
  initialFields: CoaProductField[]
  saving: boolean
  onCancel: () => void
  onSave: (rows: CoaBatchFieldRow[]) => Promise<void>
}) {
  const [rows, setRows] = useState<CoaBatchFieldRow[]>(() =>
    stripBuiltinFields(initialFields).map(toFieldRow)
  )

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
        <Button
          size="small"
          icon={<PlusOutlined />}
          onClick={() => setRows([...rows, toFieldRow({ key: '', label_cn: '', field_type: 'text' })])}
        >
          新增字段
        </Button>
      </div>
      <CoaBatchFieldsEditor rows={rows} onChange={setRows} editable />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
        <Button onClick={onCancel}>取消</Button>
        <Button type="primary" loading={saving} onClick={() => void onSave(rows)}>
          保存（写自定义）
        </Button>
      </div>
    </>
  )
}

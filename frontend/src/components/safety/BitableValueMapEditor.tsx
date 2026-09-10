'use client'

// 值转换（value_map）子编辑器：键值对表格为主 + JSON 编辑器兜底，双向同步
// - 键值对模式：源值 → 目标值 两列 + 添加/删除行；空值行保存时剔除
// - JSON 模式：TextArea（mono）+ 格式化；JSON 非法时禁止切回键值对（design.md §5.3）
// - 空对象 / 空数组 → 保存为 null（未配置）

import { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

import { MONO_FONT, UI, FIELD_TYPE_UI } from './bitableConfigConstants'
import type { BitableFieldType } from '@/types/safety'

interface BitableValueMapEditorProps {
  open: boolean
  value: Record<string, string> | null | undefined
  fieldType?: BitableFieldType | string | null
  onOk: (value: Record<string, string> | null) => void
  onClose: () => void
}

interface Pair {
  key: string
  value: string
}

/** 字段类型 → 软提示（不阻断，仅文案差异，design.md §5.3） */
const TYPE_HINTS: Partial<Record<string, { text: string; tone: 'info' | 'warning' }>> = {
  enum: { text: '该类型常用于值转换（如 已关闭→closed）', tone: 'info' },
  combined_text: { text: '该类型常用于值转换（如 已关闭→closed）', tone: 'info' },
  multi_select: { text: '该类型常用于值转换（如 已关闭→closed）', tone: 'info' },
  text: { text: '该类型一般无需值转换', tone: 'info' },
  datetime: { text: '该类型一般无需值转换', tone: 'info' },
  person: { text: '该类型不支持值转换，请清空', tone: 'warning' },
  attachment: { text: '该类型不支持值转换，请清空', tone: 'warning' },
}

function objectToPairs(value: Record<string, string> | null | undefined): Pair[] {
  if (!value) return []
  return Object.entries(value).map(([k, v]) => ({ key: k, value: v }))
}

function pairsToObject(pairs: Pair[]): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const p of pairs) {
    const k = p.key.trim()
    if (k) obj[k] = p.value
  }
  return obj
}

/** JSON 解析并校验为「字符串值对象」，失败返回错误文案 */
function parseJsonObject(text: string): { ok: true; value: Record<string, string> } | { ok: false; error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text || '{}')
  } catch {
    return { ok: false, error: 'JSON 格式错误，请检查括号与引号' }
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: '值转换必须是 JSON 对象（如 {"已关闭": "closed"}）' }
  }
  for (const [k, v] of Object.entries(parsed)) {
    if (typeof v !== 'string') {
      return { ok: false, error: `「${k}」的目标值必须是字符串` }
    }
  }
  return { ok: true, value: parsed as Record<string, string> }
}

export default function BitableValueMapEditor({
  open,
  value,
  fieldType,
  onOk,
  onClose,
}: BitableValueMapEditorProps) {
  const [mode, setMode] = useState<'kv' | 'json'>('kv')
  const [pairs, setPairs] = useState<Pair[]>([])
  const [jsonText, setJsonText] = useState('{}')
  const [jsonError, setJsonError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const initPairs = objectToPairs(value)
    setPairs(initPairs)
    setMode('kv')
    setJsonText(JSON.stringify(pairsToObject(initPairs), null, 2))
    setJsonError(null)
  }, [open, value])

  const hint = fieldType ? TYPE_HINTS[fieldType] : undefined
  const typeLabel = fieldType ? (FIELD_TYPE_UI[fieldType as BitableFieldType]?.label ?? fieldType) : null

  const switchToJson = () => {
    setJsonText(JSON.stringify(pairsToObject(pairs), null, 2))
    setJsonError(null)
    setMode('json')
  }

  const switchToKv = () => {
    const parsed = parseJsonObject(jsonText)
    if (!parsed.ok) {
      setJsonError(parsed.error)
      return // JSON 非法 → 禁止切回键值对
    }
    setPairs(Object.entries(parsed.value).map(([k, v]) => ({ key: k, value: v })))
    setJsonError(null)
    setMode('kv')
  }

  const formatJson = () => {
    const parsed = parseJsonObject(jsonText)
    if (!parsed.ok) {
      setJsonError(parsed.error)
      return
    }
    setJsonText(JSON.stringify(parsed.value, null, 2))
    setJsonError(null)
  }

  const handleOk = () => {
    if (mode === 'json') {
      const parsed = parseJsonObject(jsonText)
      if (!parsed.ok) {
        setJsonError(parsed.error)
        return
      }
      onOk(Object.keys(parsed.value).length > 0 ? parsed.value : null)
    } else {
      const obj = pairsToObject(pairs)
      onOk(Object.keys(obj).length > 0 ? obj : null)
    }
    onClose()
  }

  const updatePair = (index: number, patch: Partial<Pair>) => {
    setPairs((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  return (
    <Modal
      title={
        <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>
          值转换{typeLabel ? ` · ${typeLabel}` : ''}
        </span>
      }
      open={open}
      onCancel={onClose}
      width={600}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleOk}>
            确定
          </Button>
        </Space>
      }
    >
      {/* 模式切换 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space size={8}>
          <Button size="small" type={mode === 'kv' ? 'primary' : 'default'} onClick={() => (mode === 'json' ? switchToKv() : undefined)}>
            键值对
          </Button>
          <Button size="small" type={mode === 'json' ? 'primary' : 'default'} onClick={switchToJson}>
            JSON
          </Button>
        </Space>
        {mode === 'json' && (
          <Button size="small" onClick={formatJson}>
            格式化
          </Button>
        )}
      </div>

      {/* 键值对模式 */}
      {mode === 'kv' && (
        <div>
          <div
            style={{
              display: 'flex',
              gap: 12,
              fontSize: 12,
              fontWeight: 600,
              color: UI.slate,
              marginBottom: 6,
            }}
          >
            <span style={{ flex: 1 }}>源值（Bitable 中的中文值）</span>
            <span style={{ flex: 1 }}>目标值（模型枚举 / 字段值）</span>
            <span style={{ width: 32 }} />
          </div>
          {pairs.length === 0 ? (
            <div style={{ fontSize: 12, color: UI.muted, padding: '8px 0 12px' }}>暂无值转换项，点击「添加一行」开始配置</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8 }}>
              {pairs.map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <Input
                    size="small"
                    placeholder="如：已关闭"
                    value={p.key}
                    onChange={(e) => updatePair(i, { key: e.target.value })}
                    style={{ flex: 1 }}
                  />
                  <Input
                    size="small"
                    placeholder="如：closed"
                    value={p.value}
                    onChange={(e) => updatePair(i, { value: e.target.value })}
                    style={{ flex: 1 }}
                  />
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setPairs((prev) => prev.filter((_, idx) => idx !== i))}
                  />
                </div>
              ))}
            </div>
          )}
          <Button size="small" icon={<PlusOutlined />} onClick={() => setPairs((prev) => [...prev, { key: '', value: '' }])}>
            添加一行
          </Button>
        </div>
      )}

      {/* JSON 模式 */}
      {mode === 'json' && (
        <div>
          <Input.TextArea
            rows={6}
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value)
              if (jsonError) setJsonError(null)
            }}
            style={{ fontFamily: MONO_FONT, fontSize: 12 }}
          />
          {jsonError && (
            <div style={{ fontSize: 12, color: UI.error, marginTop: 6 }}>{jsonError}，修正后才能切回键值对模式</div>
          )}
        </div>
      )}

      {/* 类型联动软提示 */}
      {hint && (
        <Alert
          type={hint.tone}
          showIcon
          message={<span style={{ fontSize: 12 }}>{hint.text}</span>}
          style={{ marginTop: 12 }}
        />
      )}
    </Modal>
  )
}

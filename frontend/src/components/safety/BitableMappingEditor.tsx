'use client'

// 右·卡二：字段映射（Bitable → 模型，仅此方向可编辑；design.md §2.4 / §5.2）
// 只读预览 ⇄ 行内编辑模式切换：源/目标 Input、类型 Select、默认值 Input、可选 Switch、
// 值转换「配置 (n)」打开 BitableValueMapEditor、行尾删除（Popconfirm）、「+ 新增映射」置底
// 保存前校验：源字段/目标字段非空 + 源字段唯一；保存走 Modal.confirm → PUT 全量替换

import { useMemo, useState } from 'react'
import { Alert, App, Button, Empty, Input, Modal, Popconfirm, Select, Skeleton, Space, Switch, Table, Tag } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { updateBitableMappings } from '@/actions/safety'
import type {
  BitableDomainOverview,
  BitableFieldMapping,
  BitableFieldType,
  BitableMappingStatus,
} from '@/types/safety'
import { CARD_STYLE, FIELD_TYPE_OPTIONS, FieldTypeTag, MONO_FONT, UI } from './bitableConfigConstants'
import BitableValueMapEditor from './BitableValueMapEditor'

interface BitableMappingEditorProps {
  domain: BitableDomainOverview | null
  kind: string | null
  onKindChange: (kind: string) => void
  /** 'db'=自定义映射 / 'default'=代码内置默认映射（fallback） */
  status: BitableMappingStatus | null
  mappings: BitableFieldMapping[]
  loading: boolean
  onOpenAudit: () => void
  onSaved: () => void
}

function emptyRow(): BitableFieldMapping {
  return { source_field: '', target_field: '', field_type: 'text', default_value: null, value_map: null, optional: false }
}

export default function BitableMappingEditor({
  domain,
  kind,
  onKindChange,
  status,
  mappings,
  loading,
  onOpenAudit,
  onSaved,
}: BitableMappingEditorProps) {
  const { message } = App.useApp()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<BitableFieldMapping[]>([])
  const [saving, setSaving] = useState(false)
  const [valueMapTarget, setValueMapTarget] = useState<number | null>(null)
  const [validateError, setValidateError] = useState<string | null>(null)

  const kindOptions = useMemo(
    () => (domain?.kinds ?? []).map((k) => ({ value: k.kind, label: `${k.label}（${k.kind}）` })),
    [domain],
  )

  /** 进入编辑：深拷贝 mappings 为草稿；退出/取消直接丢弃 */
  const enterEdit = () => {
    setDraft(mappings.map((m) => ({ ...m, value_map: m.value_map ? { ...m.value_map } : null })))
    setValidateError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraft([])
    setValidateError(null)
  }

  const updateRow = (index: number, patch: Partial<BitableFieldMapping>) => {
    setDraft((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)))
    setValidateError(null)
  }

  const deleteRow = (index: number) => {
    setDraft((prev) => prev.filter((_, i) => i !== index))
    setValidateError(null)
  }

  const handleSave = () => {
    // 保存前校验：源字段/目标字段非空 + 源字段唯一（design.md §5.2）
    const errors: string[] = []
    const seen = new Map<string, number>()
    draft.forEach((r, i) => {
      const src = (r.source_field ?? '').trim()
      const tgt = (r.target_field ?? '').trim()
      if (!src) errors.push(`第 ${i + 1} 行：源字段不能为空`)
      if (!tgt) errors.push(`第 ${i + 1} 行：目标字段不能为空`)
      if (src) {
        const prev = seen.get(src)
        if (prev !== undefined) errors.push(`源字段「${src}」重复（第 ${prev + 1} 行与第 ${i + 1} 行）`)
        else seen.set(src, i)
      }
    })
    if (errors.length > 0) {
      setValidateError(errors.join('；'))
      return
    }
    Modal.confirm({
      title: '保存映射',
      content: '保存映射：将保存至配置中心供后续字段解析使用，当前事件解析仍以代码内置映射为准，确认保存？',
      okText: '确认保存',
      cancelText: '取消',
      onOk: async () => {
        if (!domain || !kind) return
        setSaving(true)
        try {
          const payload: BitableFieldMapping[] = draft.map((r) => ({
            ...r,
            source_field: (r.source_field ?? '').trim() || null,
            target_field: (r.target_field ?? '').trim(),
            default_value: r.default_value === '' ? null : r.default_value,
          }))
          const res = await updateBitableMappings(domain.key, kind, payload)
          if (res.code === 200 && res.data) {
            message.success('字段映射已保存，实时生效')
            setEditing(false)
            setDraft([])
            setValidateError(null)
            onSaved()
          } else {
            message.error(res.message || '保存失败')
          }
        } catch (e) {
          message.error(e instanceof Error ? e.message : '保存失败')
        } finally {
          setSaving(false)
        }
      },
    })
  }

  const valueMapCount = (r: BitableFieldMapping) => (r.value_map ? Object.keys(r.value_map).length : 0)

  const readColumns: ColumnsType<BitableFieldMapping> = useMemo(
    () => [
      {
        title: '源字段',
        key: 'source_field',
        width: 180,
        render: (_, r) => (
          <span style={{ fontSize: 13, color: r.source_field ? UI.ink : UI.muted }}>
            {r.source_field || '—'}
          </span>
        ),
      },
      {
        title: '目标字段',
        key: 'target_field',
        width: 170,
        render: (_, r) => <span style={{ fontFamily: MONO_FONT, fontSize: 13, color: UI.ink }}>{r.target_field}</span>,
      },
      {
        title: '类型',
        key: 'field_type',
        width: 100,
        render: (_, r) => <FieldTypeTag type={r.field_type} />,
      },
      {
        title: '默认值',
        key: 'default_value',
        width: 120,
        render: (_, r) => (
          <span style={{ fontSize: 13, color: r.default_value != null && r.default_value !== '' ? UI.slate : UI.muted }}>
            {r.default_value != null && r.default_value !== '' ? String(r.default_value) : '—'}
          </span>
        ),
      },
      {
        title: '值转换',
        key: 'value_map',
        width: 90,
        render: (_, r) => {
          const n = valueMapCount(r)
          return n > 0 ? (
            <Tag style={{ borderRadius: 6, fontWeight: 600, color: '#391c57', background: UI.lavender, borderColor: 'transparent' }}>
              {n} 项
            </Tag>
          ) : (
            <span style={{ fontSize: 13, color: UI.muted }}>—</span>
          )
        },
      },
      {
        title: '可选',
        key: 'optional',
        width: 70,
        render: (_, r) => (
          <span style={{ fontSize: 13, color: UI.slate }}>{r.optional ? '是' : '否'}</span>
        ),
      },
    ],
    [],
  )

  const editColumns: ColumnsType<BitableFieldMapping> = useMemo(
    () => [
      {
        title: '源字段',
        key: 'source_field',
        width: 170,
        render: (_, r, i) => (
          <Input
            size="small"
            placeholder="Bitable 中文列名"
            value={r.source_field ?? ''}
            onChange={(e) => updateRow(i, { source_field: e.target.value })}
          />
        ),
      },
      {
        title: '目标字段',
        key: 'target_field',
        width: 160,
        render: (_, r, i) => (
          <Input
            size="small"
            placeholder="模型字段名"
            style={{ fontFamily: MONO_FONT }}
            value={r.target_field}
            onChange={(e) => updateRow(i, { target_field: e.target.value })}
          />
        ),
      },
      {
        title: '类型',
        key: 'field_type',
        width: 110,
        render: (_, r, i) => (
          <Select<BitableFieldType>
            size="small"
            style={{ width: '100%' }}
            options={FIELD_TYPE_OPTIONS}
            value={r.field_type ?? 'text'}
            onChange={(v) => updateRow(i, { field_type: v })}
          />
        ),
      },
      {
        title: '默认值',
        key: 'default_value',
        width: 110,
        render: (_, r, i) => (
          <Input
            size="small"
            placeholder="解析失败兜底"
            value={r.default_value == null ? '' : String(r.default_value)}
            onChange={(e) => updateRow(i, { default_value: e.target.value })}
          />
        ),
      },
      {
        title: '值转换',
        key: 'value_map',
        width: 100,
        render: (_, r, i) => {
          const n = valueMapCount(r)
          return (
            <Button
              size="small"
              type="link"
              style={{ padding: 0, fontWeight: 600, color: UI.primary, fontSize: 13 }}
              onClick={() => setValueMapTarget(i)}
            >
              配置 ({n})
            </Button>
          )
        },
      },
      {
        title: '可选',
        key: 'optional',
        width: 64,
        render: (_, r, i) => (
          <Switch size="small" checked={!!r.optional} onChange={(v) => updateRow(i, { optional: v })} />
        ),
      },
      {
        title: '操作',
        key: 'action',
        width: 56,
        render: (_, _r, i) => (
          <Popconfirm
            title="删除映射"
            description="删除后该字段回退使用默认映射，确认？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteRow(i)}
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ),
      },
    ],
    [],
  )

  const kindLabel = kindOptions.find((o) => o.value === kind)?.label

  return (
    <div style={{ ...CARD_STYLE, padding: 16 }}>
      {/* 卡头 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 4,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>字段映射</span>
          <Tag style={{ borderRadius: 6, fontWeight: 600, color: UI.slate, borderColor: UI.hairline, marginInlineEnd: 0 }}>
            Bitable → 模型
          </Tag>
          <Select
            size="small"
            style={{ width: 210 }}
            placeholder="选择表类型"
            value={kind ?? undefined}
            options={kindOptions}
            onChange={onKindChange}
          />
        </div>
        <Space size={8}>
          <Button size="small" onClick={onOpenAudit}>
            审计
          </Button>
          {editing ? (
            <>
              <Button size="small" onClick={cancelEdit} disabled={saving}>
                取消
              </Button>
              <Button size="small" type="primary" loading={saving} onClick={handleSave}>
                保存映射
              </Button>
            </>
          ) : (
            <Button size="small" type="primary" onClick={enterEdit} disabled={!kind || loading}>
              编辑映射
            </Button>
          )}
        </Space>
      </div>
      <div style={{ fontSize: 12, color: UI.muted, marginBottom: 12 }}>
        反向映射由映射交集自动推导，无需配置；行内编辑后保存即生效
        {status === 'default' && !editing && '（当前使用代码内置默认映射，保存后切换为自定义）'}
      </div>

      {/* 校验错误提示 */}
      {editing && validateError && (
        <Alert
          type="error"
          showIcon
          message={<span style={{ fontSize: 13 }}>{validateError}</span>}
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 表格 */}
      {loading && !editing ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : !kind ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该域暂无可配置表类型" />
      ) : editing ? (
        <Table<BitableFieldMapping>
          rowKey={(_, i) => `draft-${i}`}
          size="small"
          columns={editColumns}
          dataSource={draft}
          pagination={false}
          scroll={{ x: 820 }}
          footer={() => (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Button size="small" icon={<PlusOutlined />} onClick={() => setDraft((prev) => [...prev, emptyRow()])}>
                新增映射
              </Button>
              <span style={{ fontSize: 12, color: UI.steel }}>{kindLabel ? `表类型：${kindLabel}` : ''}</span>
            </div>
          )}
        />
      ) : mappings.length === 0 ? (
        <div style={{ padding: '8px 0' }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无字段映射，运行将使用代码内置默认映射">
            <Button size="small" type="primary" onClick={enterEdit}>
              编辑映射仍可手动新增
            </Button>
          </Empty>
        </div>
      ) : (
        <Table<BitableFieldMapping>
          rowKey={(_, i) => `read-${i}`}
          size="small"
          columns={readColumns}
          dataSource={mappings}
          pagination={false}
          scroll={{ x: 720 }}
        />
      )}

      <BitableValueMapEditor
        open={valueMapTarget !== null}
        value={valueMapTarget !== null ? draft[valueMapTarget]?.value_map : undefined}
        fieldType={valueMapTarget !== null ? draft[valueMapTarget]?.field_type : undefined}
        onOk={(v) => {
          if (valueMapTarget !== null) updateRow(valueMapTarget, { value_map: v })
        }}
        onClose={() => setValueMapTarget(null)}
      />
    </div>
  )
}

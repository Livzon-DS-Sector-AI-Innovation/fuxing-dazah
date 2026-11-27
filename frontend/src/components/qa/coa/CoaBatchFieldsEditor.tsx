'use client'

import { Button, Input, Popconfirm, Select, Table, Tag } from 'antd'
import type { CoaProductFieldInput, CoaFieldType } from '@/types/qa'

/**
 * 内置批次字段（与后端 service/coa/common.py BUILTIN_BATCH_FIELDS 同表）：
 * 品名/批号必填、流水号选填（登记时往往还没分配），三者在编辑器置顶锁定展示，不进载荷。
 */
export const BUILTIN_FIELD_DEFS: {
  key: string
  label_cn: string
  label_en: string
  field_type: CoaFieldType
}[] = [
  { key: 'product_name', label_cn: '品名', label_en: 'Product Name', field_type: 'text' },
  { key: 'batch_no', label_cn: '批号', label_en: 'Batch No.', field_type: 'text' },
  { key: 'serial_no', label_cn: '流水号', label_en: 'Serial No.', field_type: 'text' },
]

/** 与后端 builtin_key_of 同口径的别名归一：NFKC + 小写 + 去空白/标点。 */
const BUILTIN_ALIAS: [builtinKey: string, aliases: string[]][] = [
  ['product_name', ['productname', 'product', '品名', '产品名称', '产品名']],
  ['batch_no', ['batchno', 'batchnumber', 'batch', 'lot', 'lotno', 'lotnumber', '批号', '批次号', '批次编号']],
  ['serial_no', ['serialno', 'serialnumber', 'sn', 'series', '流水号', '序列号']],
]

function normalizeToken(value: string): string {
  return Array.from(value.normalize('NFKC').toLowerCase())
    .filter((ch) => /[\p{L}\p{N}]/u.test(ch))
    .join('')
}

const BUILTIN_ALIAS_MAP: Map<string, string> = (() => {
  const map = new Map<string, string>()
  for (const [key, aliases] of BUILTIN_ALIAS) {
    for (const token of [key, ...aliases]) {
      map.set(normalizeToken(token), key)
    }
  }
  return map
})()

/** 字段键/标签归一后命中内置字段 → 返回内置键（品名/批号/流水号及同义变体）。 */
export function builtinKeyOf(keyOrLabel: string): string | null {
  const token = normalizeToken(keyOrLabel)
  return token ? (BUILTIN_ALIAS_MAP.get(token) ?? null) : null
}

/** 报告固定列（与后端 service/coa/common.py REPORT_COLUMN_ALIASES 同表）。 */
export type CoaReportColumn = 'mfg_date' | 'exp_date' | 'packaging' | 'batch_size' | 'storage'

const REPORT_COLUMN_ALIAS: [column: CoaReportColumn, aliases: string[]][] = [
  ['mfg_date', ['mfgdate', 'manufacturingdate', 'manufacturedate', 'productiondate', '生产日期', '制造日期']],
  [
    'exp_date',
    ['expdate', 'expirydate', 'expirationdate', 'expiry', 'expiration', '有效期', '有效期至', '失效期', '失效日期', '有效日期'],
  ],
  ['packaging', ['package', 'packing', 'packagingspec', '包装', '包装规格', '包装形式']],
  ['batch_size', ['batchsize', 'quantity', '批量', '数量']],
  [
    'storage',
    ['storagecondition', 'storecondition', 'storageconditions', '储存条件', '贮存条件', '储藏条件', '储存', '贮存'],
  ],
]

const REPORT_COLUMN_ALIAS_MAP: Map<string, CoaReportColumn> = (() => {
  const map = new Map<string, CoaReportColumn>()
  for (const [column, aliases] of REPORT_COLUMN_ALIAS) {
    for (const token of [column, ...aliases]) {
      map.set(normalizeToken(token), column)
    }
  }
  return map
})()

/**
 * 字段键归一后命中报告固定列 → 返回列名，否则 null。后端只按键判定（不看标签）：
 * 命中时该字段的值镜像写固定列，读取时也从固定列合成——导入登记据此把 docx
 * 识别到的固定列值回填到对应模板字段。
 */
export function reportColumnKeyOf(key: string): CoaReportColumn | null {
  const token = normalizeToken(key)
  return token ? (REPORT_COLUMN_ALIAS_MAP.get(token) ?? null) : null
}

/**
 * 过滤内置行：编辑器恒定自行渲染内置 3 字段，入参行集只留自定义
 * （兼容旧缓存里未带 builtin 标记的保留键行）。
 */
export function stripBuiltinFields<T extends { builtin?: boolean; key: string }>(
  fields: T[]
): T[] {
  return fields.filter((f) => !f.builtin && builtinKeyOf(f.key) === null)
}

/**
 * 编辑行：入参形态 + 本地行键。注意不能占用 `key`——那是字段键本身
 * （retest_date），本地行键挂 rowKey（项目行的 key 模式在这里撞名）。
 */
export interface CoaBatchFieldRow extends CoaProductFieldInput {
  rowKey: string
  builtin?: boolean
  /** 已落库行：字段键是历史报告 batch_data 的存储锚点，锁定不可改。 */
  persisted?: boolean
}

let rowSeq = 0

export function toFieldRow(
  field: CoaProductFieldInput & { id?: string | null }
): CoaBatchFieldRow {
  rowSeq += 1
  return { ...field, rowKey: `f-${rowSeq}`, persisted: field.id != null }
}

/** 编辑器置顶的内置锁定行（展示态，不参与编辑/载荷）。 */
const BUILTIN_ROWS: CoaBatchFieldRow[] = BUILTIN_FIELD_DEFS.map((def, index) => ({
  ...def,
  rowKey: `builtin-${index}`,
  builtin: true,
}))

/** 行集 → 全量替换载荷：排序=行序，空串归 null；内置行恒不进载荷。 */
export function rowsToFieldPayload(rows: CoaBatchFieldRow[]): CoaProductFieldInput[] {
  return rows
    .filter((row) => !row.builtin)
    .map((row, index) => ({
      key: (row.key ?? '').trim(),
      label_cn: (row.label_cn ?? '').trim(),
      label_en: row.label_en?.trim() || null,
      field_type: row.field_type,
      sort_order: index,
    }))
}

/** 校验：返回首个问题的提示文案，全部合法返回 null。 */
export function validateFieldRows(rows: CoaBatchFieldRow[]): string | null {
  const blank = rows.find((row) => !(row.key ?? '').trim() || !(row.label_cn ?? '').trim())
  if (blank) return '存在未填写字段键或中文标签的行'
  const seen = new Set<string>()
  for (const row of rows) {
    const k = (row.key ?? '').trim()
    const hit = builtinKeyOf(k) ?? builtinKeyOf((row.label_cn ?? '').trim())
    if (hit) {
      return `字段 [${k}] 与内置字段重复：品名/批号/流水号是内置字段，恒定存在，无需配置`
    }
    const folded = k.toLowerCase()
    if (seen.has(folded)) return `字段键 [${k}] 重复，同一产品内需唯一`
    seen.add(folded)
  }
  return null
}

const FIELD_TYPE_OPTIONS: { value: CoaFieldType; label: string }[] = [
  { value: 'text', label: '文本' },
  { value: 'date', label: '日期' },
]

/** 行级差异标记：字段 key → 标签（与产品默认对比，仅展示）。 */
export interface CoaFieldMark {
  text: string
  color: string
}

/**
 * 产品批次信息字段受控行内编辑表格：内置 3 字段（品名/批号/流水号）置顶
 * 锁定展示，其后为可编辑自定义行（字段键/中英标签/类型/删除）。
 * 全量替换语义由调用方提交；空表=仅剩内置字段。
 */
export function CoaBatchFieldsEditor({
  rows,
  onChange,
  editable,
  scrollY,
  marks,
}: {
  rows: CoaBatchFieldRow[]
  onChange: (rows: CoaBatchFieldRow[]) => void
  editable: boolean
  /** 表体最大高度；缺省不内部滚动，交给外层容器统一滚。 */
  scrollY?: number
  /** 与产品默认的行级差异标记（按字段 key 匹配；自定义模板展示用）。 */
  marks?: Record<string, CoaFieldMark>
}) {
  const updateRow = (rowKey: string, patch: Partial<CoaBatchFieldRow>) => {
    onChange(rows.map((row) => (row.rowKey === rowKey ? { ...row, ...patch } : row)))
  }
  const removeRow = (rowKey: string) =>
    onChange(rows.filter((row) => row.rowKey !== rowKey))

  return (
    <Table<CoaBatchFieldRow>
      rowKey="rowKey"
      size="small"
      dataSource={[...BUILTIN_ROWS, ...rows]}
      pagination={false}
      {...(scrollY ? { scroll: { y: scrollY } } : {})}
      columns={[
        {
          title: '#',
          width: 40,
          align: 'center',
          render: (_v, _row, index) => index + 1,
        },
        ...(marks
          ? [
              {
                title: '对比默认',
                width: 76,
                render: (_v: unknown, row: CoaBatchFieldRow) => {
                  const mark = marks[row.key.trim()]
                  return mark ? (
                    <Tag color={mark.color} style={{ marginInlineEnd: 0 }}>
                      {mark.text}
                    </Tag>
                  ) : null
                },
              },
            ]
          : []),
        {
          title: '字段键',
          dataIndex: 'key',
          width: 200,
          render: (v: string, row) =>
            row.builtin ? (
              <span>
                {v}{' '}
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                  {v === 'serial_no' ? '内置 · 选填' : '内置 · 必填'}
                </Tag>
              </span>
            ) : editable && !row.persisted ? (
              <Input
                size="small"
                value={v}
                placeholder="retest_date"
                onChange={(e) => updateRow(row.rowKey, { key: e.target.value })}
              />
            ) : (
              <span>
                {v}
                {editable && row.persisted && (
                  <Tag style={{ marginInlineStart: 6, marginInlineEnd: 0 }}>已保存</Tag>
                )}
              </span>
            ),
        },
        {
          title: '标签（中文）',
          dataIndex: 'label_cn',
          render: (v: string, row) =>
            !row.builtin && editable ? (
              <Input
                size="small"
                value={v}
                placeholder="复验期"
                onChange={(e) => updateRow(row.rowKey, { label_cn: e.target.value })}
              />
            ) : (
              v
            ),
        },
        {
          title: '标签（英文）',
          dataIndex: 'label_en',
          width: 200,
          render: (v: string | null, row) =>
            !row.builtin && editable ? (
              <Input
                size="small"
                value={v ?? ''}
                placeholder="Retest Date"
                onChange={(e) => updateRow(row.rowKey, { label_en: e.target.value })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '类型',
          dataIndex: 'field_type',
          width: 96,
          render: (v: CoaFieldType, row) =>
            !row.builtin && editable ? (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={v}
                options={FIELD_TYPE_OPTIONS}
                onChange={(next) => updateRow(row.rowKey, { field_type: next })}
              />
            ) : (
              v === 'date' ? '日期' : '文本'
            ),
        },
        ...(editable
          ? [
              {
                title: '操作',
                width: 64,
                render: (_v: unknown, row: CoaBatchFieldRow) =>
                  row.builtin ? null : (
                    <Popconfirm title="删除该行？" onConfirm={() => removeRow(row.rowKey)}>
                      <Button type="text" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  ),
              },
            ]
          : []),
      ]}
    />
  )
}

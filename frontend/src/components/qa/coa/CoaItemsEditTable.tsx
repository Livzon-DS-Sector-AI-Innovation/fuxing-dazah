'use client'

import { Button, Input, InputNumber, Popconfirm, Select, Table } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import type { CoaItemInput, CoaStandardItem, CoaValueType } from '@/types/qa'
import { VALUE_TYPE_OPTIONS } from './CoaShared'

/** 编辑行：入参形态 + 本地行键（新建行无 id）。 */
export interface CoaItemRow extends CoaItemInput {
  key: string
}

let rowSeq = 0

export function toItemRow(item: CoaItemInput): CoaItemRow {
  rowSeq += 1
  return { ...item, key: item.id ?? `new-${rowSeq}` }
}

/** 行集 → 全量替换载荷：排序=行序，空串归 null；数值型行的默认值恒不进载荷。 */
export function rowsToItemPayload(rows: CoaItemRow[]): CoaItemInput[] {
  return rows.map((row, index) => ({
    id: row.id ?? null,
    group_name: row.group_name || null,
    name_cn: (row.name_cn ?? '').trim(),
    name_en: row.name_en || null,
    value_type: row.value_type,
    unit: row.unit || null,
    spec_text: row.spec_text || null,
    spec_min: row.spec_min ?? null,
    spec_max: row.spec_max ?? null,
    sort_order: index,
    default_value:
      row.value_type === 'text' ? row.default_value?.trim() || null : null,
    remark: row.remark || null,
  }))
}

/** 校验：返回首个问题的提示文案，全部合法返回 null。 */
export function validateItemRows(rows: CoaItemRow[]): string | null {
  const blank = rows.find((row) => !(row.name_cn ?? '').trim())
  if (blank) return '存在未填写中文名的项目行'
  // 同表内重名（忽略大小写/首尾空白）；跨标准允许同名（矩阵合并同列）
  const seen = new Set<string>()
  for (const row of rows) {
    const key = (row.name_cn ?? '').trim().toLowerCase()
    if (seen.has(key)) return `项目 [${row.name_cn?.trim()}] 名称重复，同一标准内项目名称需唯一`
    seen.add(key)
  }
  return null
}

/**
 * 标准项目受控行内编辑表格：新增/删除/上下移/双语名/类型/单位/标准原文/
 * 默认值（text 型登记预填用）。全量替换语义由调用方提交（带 id=保留更新；
 * 不在表中的既有项目由后端软删让号——项目必然启用，无停用态）。
 */
export function CoaItemsEditTable({
  rows,
  onChange,
  editable,
  scrollY = 460,
  focusRowKey,
}: {
  rows: CoaItemRow[]
  onChange: (rows: CoaItemRow[]) => void
  editable: boolean
  /** 表体最大高度；false = 不内部滚动，交给外层容器统一滚 */
  scrollY?: number | false
  /** 新增行定位：该行挂载时聚焦中文名输入框，浏览器会把整行滚进可视区 */
  focusRowKey?: string | null
}) {
  const updateRow = (key: string, patch: Partial<CoaItemRow>) => {
    onChange(rows.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const removeRow = (key: string) => onChange(rows.filter((row) => row.key !== key))

  const moveRow = (key: string, offset: -1 | 1) => {
    const index = rows.findIndex((row) => row.key === key)
    const target = index + offset
    if (index < 0 || target < 0 || target >= rows.length) return
    const next = [...rows]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    onChange(next)
  }

  return (
    <Table<CoaItemRow>
      rowKey="key"
      size="small"
      dataSource={rows}
      pagination={false}
      // x 滚动：列按自然宽度渲染；窄容器（导入弹窗）横向滚动，避免「标准原文」被挤成 0 宽
      scroll={{ x: 1234, ...(scrollY ? { y: scrollY } : {}) }}
      columns={[
        {
          title: '#',
          width: 40,
          align: 'center',
          render: (_v, _row, index) => index + 1,
        },
        {
          title: '项目（中文）',
          dataIndex: 'name_cn',
          width: 170,
          render: (v: string, row) =>
            editable ? (
              <Input
                size="small"
                value={v}
                autoFocus={row.key === focusRowKey}
                onChange={(e) => updateRow(row.key, { name_cn: e.target.value })}
              />
            ) : (
              v
            ),
        },
        {
          title: '项目（英文）',
          dataIndex: 'name_en',
          width: 180,
          render: (v: string | null, row) =>
            editable ? (
              <Input
                size="small"
                value={v ?? ''}
                onChange={(e) => updateRow(row.key, { name_en: e.target.value })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '类型',
          dataIndex: 'value_type',
          width: 112,
          render: (v: CoaValueType, row) =>
            editable ? (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={v}
                options={VALUE_TYPE_OPTIONS}
                // 切到数值型时清掉默认值（默认值仅文本型可用，后端同口径 422）
                onChange={(next) =>
                  updateRow(row.key, {
                    value_type: next,
                    ...(next === 'number' ? { default_value: null } : {}),
                  })
                }
              />
            ) : (
              v === 'number' ? '数值' : '文字'
            ),
        },
        {
          title: '单位',
          dataIndex: 'unit',
          width: 80,
          render: (v: string | null, row) =>
            editable ? (
              <Input
                size="small"
                value={v ?? ''}
                onChange={(e) => updateRow(row.key, { unit: e.target.value })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '标准原文',
          dataIndex: 'spec_text',
          width: 240,
          render: (v: string | null, row) =>
            editable ? (
              <Input
                size="small"
                value={v ?? ''}
                placeholder="≤3.0% / 2.5～4.5 / 白色粉末"
                onChange={(e) => updateRow(row.key, { spec_text: e.target.value })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '下限',
          dataIndex: 'spec_min',
          width: 76,
          render: (v: number | null, row) =>
            editable ? (
              <InputNumber
                size="small"
                style={{ width: '100%' }}
                value={v}
                onChange={(next) => updateRow(row.key, { spec_min: next })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '上限',
          dataIndex: 'spec_max',
          width: 76,
          render: (v: number | null, row) =>
            editable ? (
              <InputNumber
                size="small"
                style={{ width: '100%' }}
                value={v}
                onChange={(next) => updateRow(row.key, { spec_max: next })}
              />
            ) : (
              v ?? '—'
            ),
        },
        {
          title: '默认值',
          dataIndex: 'default_value',
          width: 120,
          render: (v: string | null, row) =>
            row.value_type !== 'text' ? (
              '—'
            ) : editable ? (
              <Input
                size="small"
                value={v ?? ''}
                placeholder="符合规定"
                title="登记 COA 时预填该文字（可改）"
                onChange={(e) => updateRow(row.key, { default_value: e.target.value })}
              />
            ) : (
              v ?? '—'
            ),
        },
        ...(editable
          ? [
              {
                title: '操作',
                width: 140,
                render: (_v: unknown, row: CoaItemRow) => (
                  <>
                    <Button
                      type="text"
                      size="small"
                      aria-label="上移"
                      icon={<ArrowUpOutlined />}
                      onClick={() => moveRow(row.key, -1)}
                    />
                    <Button
                      type="text"
                      size="small"
                      aria-label="下移"
                      icon={<ArrowDownOutlined />}
                      onClick={() => moveRow(row.key, 1)}
                    />
                    <Popconfirm title="删除该行？" onConfirm={() => removeRow(row.key)}>
                      <Button type="text" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </>
                ),
              },
            ]
          : []),
      ]}
    />
  )
}

/** 兼容入口：标准详情 items → 可编辑行。 */
export function standardItemsToRows(items: CoaStandardItem[]): CoaItemRow[] {
  return items.map(toItemRow)
}

'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { App, Button, DatePicker, Form, Input, Modal, Select, Spin, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { actionError } from '@/components/qa/deviation/shared'
import { copyCoaReport } from '@/actions/qa'
import { fetchCoaMatrix, fetchCoaStandardDetail } from '@/lib/api/qa'
import type { CoaProductField, CoaReport, CoaStandard, CoaStandardItem } from '@/types/qa'
import { stripBuiltinFields } from './CoaBatchFieldsEditor'
import { CoaResultInput, emptyResultDraft, toResultDraft } from './CoaResultInput'
import type { CoaResultDraft } from './CoaResultInput'
import { useSettledInput } from './CoaLimitFlag'
import { collectLimitHits, limitTallyText, specLimitOf } from './coaSpecLimit'
import { buildCopyCells, pairBatchFields, pairItems } from './coaCopyModel'
import pageStyles from './CoaIssuancePage.module.css'
import styles from './CoaCopyModal.module.css'

type CopyKind = 'batch' | 'item'

/** 分组标题行（批次信息 / 检测结果）：只占第一格并横跨整行。 */
interface GroupRow {
  type: 'group'
  key: string
  label: string
}

/** 字段行：目标模板的一个批次字段或一个检测项目。 */
interface CellRow {
  type: 'cell'
  /** 行键 `batch:<字段键>` / `item:<项目 id>`，同时是输入停手判定与回车跳行的键 */
  key: string
  /** 序号：批次字段在前、检测项目在后，连着编 */
  no: number
  kind: CopyKind
  /** 目标格：批次字段键 / 项目 id */
  targetKey: string
  label: string
  /** 检测项目的标准要求 */
  hint: string | null
  item?: CoaStandardItem
  field?: CoaProductField
}

type CopyRow = GroupRow | CellRow

const isGroup = (row: CopyRow): row is GroupRow => row.type === 'group'

/** 矩阵值的文字：原文优先，没原文用数值；空值返回 null。 */
function valueText(value: { num: number | null; text: string | null } | undefined): string | null {
  if (!value) return null
  return value.text || (value.num != null ? String(value.num) : null)
}

/** 侧栏横向表单布局：与手工登记同款，两处不同——
 *  标签列 80px：带冒号的「目标模板」在 72px 里会折成两行；
 *  内容列 flex-basis 取 0：表单行是 flex-wrap，按内容宽度算的话下拉里的长模板名
 *  会把整块内容挤到标签下一行。 */
const PANEL_FORM_LAYOUT = {
  layout: 'horizontal',
  labelAlign: 'left',
  labelCol: { flex: '0 0 80px' },
  wrapperCol: { flex: '1 1 0' },
  className: pageStyles.panelForm,
} as const

/**
 * 复制到其它模板：把来源记录里的若干格登记到同产品另一模板的同批号记录。
 *
 * 左边一张表列出目标模板的批次信息字段和检测项目，每行选一个来源格（同名的默认
 * 配好），值可以直接改；右边选目标模板，新建时可以顺手填流水号（选填）。
 * 目标模板下没有这个批号 → 新建（没配来源、项目又有默认值的自动填默认值）；
 * 已有 → 只写入配了来源的格，其余不动；这时默认只给空格配来源，免得把目标里
 * 特意改过的值悄悄换回来源值。来源关系只落库，界面上不展示。
 */
export function CoaCopyModal({
  source,
  product,
  sourceStandard,
  standards,
  onSaved,
  onClose,
}: {
  /** 来源记录：出具记录表里的一行（带 value_map / batch_info） */
  source: CoaReport
  product: { id: string }
  sourceStandard: CoaStandard & { items?: CoaStandardItem[]; batch_fields?: CoaProductField[] }
  /** 当前产品启用的模板（含来源模板） */
  standards: CoaStandard[]
  onSaved: () => void
  onClose: () => void
}) {
  const { message } = App.useApp()
  const others = standards.filter((s) => s.id !== sourceStandard.id)
  const [targetId, setTargetId] = useState<string | undefined>(others[0]?.id)
  const [serialNo, setSerialNo] = useState('')
  // 每格选的来源与改过的值（覆盖层，基值派生合并）。换目标模板时在事件回调里清空
  const [picks, setPicks] = useState<Record<string, string | null | undefined>>({})
  const [itemEdits, setItemEdits] = useState<Record<string, CoaResultDraft>>({})
  const [batchEdits, setBatchEdits] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  // 越界标记等停手再出（见 useSettledInput）
  const settling = useSettledInput()
  const target = others.find((s) => s.id === targetId)

  // 目标模板的字段与项目；目标模板下这个批号的记录（和出具页的查询共用缓存）
  const detailQuery = useQuery({
    queryKey: ['qa', 'coa', 'standard-detail', targetId],
    queryFn: () => fetchCoaStandardDetail(targetId!),
    enabled: !!targetId,
  })
  const matrixQuery = useQuery({
    queryKey: ['qa', 'coa', 'matrix', product.id, targetId],
    queryFn: () => fetchCoaMatrix(product.id, targetId ? [targetId] : []),
    enabled: !!targetId,
  })
  const existing = matrixQuery.data?.rows.find((row) => row.batch_no === source.batch_no) ?? null
  const ready = detailQuery.data !== undefined && matrixQuery.data !== undefined
  const creating = ready && !existing

  const sourceItems = sourceStandard.items ?? []
  const sourceBatchFields = stripBuiltinFields(sourceStandard.batch_fields ?? [])
  const targetItems = detailQuery.data?.items ?? []
  const targetBatchFields = stripBuiltinFields(detailQuery.data?.batch_fields ?? [])
  const autoItems = pairItems(targetItems, sourceItems)
  const autoFields = pairBatchFields(targetBatchFields, sourceBatchFields)

  /** 目标记录里这一格现有的值（没有记录或没填 → null）。 */
  const existingText = (kind: CopyKind, key: string): string | null =>
    existing
      ? kind === 'item'
        ? valueText(existing.value_map?.[key])
        : (existing.batch_info?.[key] ?? null)
      : null
  const sourceOf = (kind: CopyKind, key: string): string | undefined => {
    const picked = picks[`${kind}:${key}`]
    // 显式清空（null）不回落到自动配对
    if (picked !== undefined) return picked ?? undefined
    // 目标记录里这一格已经有值：不默认配来源，免得把目标里特意改过的值悄悄换回来源值；
    // 要覆盖就手动选。默认只给空格配来源（补空）
    if (existingText(kind, key) !== null) return undefined
    return kind === 'item' ? autoItems[key] : autoFields[key]
  }
  const sourceText = (kind: CopyKind, key: string): string | null =>
    kind === 'item'
      ? valueText(source.value_map?.[key])
      : (source.batch_info?.[key] ?? null)

  // 结果基值：配了来源就取来源值，否则按模板类型落空草稿；行内改过的覆盖在上面
  const baseDraft: Record<string, CoaResultDraft> = {}
  for (const item of targetItems) {
    const sourceId = sourceOf('item', item.id)
    const value = sourceId ? source.value_map?.[sourceId] : undefined
    baseDraft[item.id] = value
      ? toResultDraft({ value_num: value.num, value_text: value.text })
      : emptyResultDraft(item.value_type)
  }
  const draftOf = (item: CoaStandardItem): CoaResultDraft =>
    itemEdits[item.id] ?? baseDraft[item.id]
  const batchValueOf = (field: CoaProductField): string | undefined => {
    const edited = batchEdits[field.key]
    if (edited !== undefined) return edited
    const sourceKey = sourceOf('batch', field.key)
    return sourceKey ? (sourceText('batch', sourceKey) ?? undefined) : undefined
  }
  const cells = buildCopyCells({
    targetItems,
    targetBatchFields,
    sourceOf,
    draftOf,
    batchValueOf,
  })
  // 新建时没配来源、但项目配了默认值的：后端自动填
  const defaultCount = creating
    ? targetItems.filter((item) => item.default_value && !sourceOf('item', item.id)).length
    : 0
  const meta = [`将写入 ${cells.length} 格`, defaultCount > 0 && `${defaultCount} 项填默认值`]
    .filter(Boolean)
    .join('，')

  const pickSource = (kind: CopyKind, key: string, next: string | undefined) => {
    settling.settle()
    setPicks((prev) => ({ ...prev, [`${kind}:${key}`]: next ?? null }))
    // 换了来源，这一格之前改过的值作废
    if (kind === 'item') {
      setItemEdits((prev) => {
        const nextEdits = { ...prev }
        delete nextEdits[key]
        return nextEdits
      })
    } else {
      setBatchEdits((prev) => {
        const nextEdits = { ...prev }
        delete nextEdits[key]
        return nextEdits
      })
    }
  }

  const changeTarget = (id: string) => {
    settling.settle()
    setTargetId(id)
    setPicks({})
    setItemEdits({})
    setBatchEdits({})
  }

  const batchRows: CellRow[] = targetBatchFields.map((field, index) => ({
    type: 'cell',
    key: `batch:${field.key}`,
    no: index + 1,
    kind: 'batch',
    targetKey: field.key,
    label: field.label_cn,
    hint: null,
    field,
  }))
  const itemRows: CellRow[] = targetItems.map((item, index) => ({
    type: 'cell',
    key: `item:${item.id}`,
    no: batchRows.length + index + 1,
    kind: 'item',
    targetKey: item.id,
    label: item.name_cn,
    hint: item.spec_text,
    item,
  }))
  // 一张表：批次信息在前、检测结果在后，各带一行分组标题
  const rows: CopyRow[] = [
    ...(batchRows.length
      ? [{ type: 'group', key: 'group:batch', label: '批次信息' } satisfies GroupRow, ...batchRows]
      : []),
    { type: 'group', key: 'group:item', label: '检测结果' },
    ...itemRows,
  ]

  /** 来源下拉的选项：批次字段对批次字段（日期目标只列日期来源）、项目对项目。 */
  const optionsOf = (row: CellRow) =>
    row.kind === 'item'
      ? sourceItems.map((item) => ({ value: item.id, label: item.name_cn }))
      : (row.field?.field_type === 'date'
          ? sourceBatchFields.filter((field) => field.field_type === 'date')
          : sourceBatchFields
        ).map((field) => ({ value: field.key, label: field.label_cn }))

  /** 没配来源的格不动：新建时配了默认值的项目由后端填；已有记录的显示现值。 */
  const idleCell = (row: CellRow) => {
    if (creating && row.item?.default_value) {
      return <span className={styles.defaultHint}>默认：{row.item.default_value}</span>
    }
    const current = existingText(row.kind, row.targetKey)
    return current ? (
      <span className={pageStyles.cellEllipsis} title={current}>
        {current}
      </span>
    ) : (
      <span className={pageStyles.emptyCell}>—</span>
    )
  }

  /** 值：配了来源才可改。检测项目走结果录入格，批次字段按类型给日期或文本框。 */
  const valueCell = (row: CellRow) => {
    if (!sourceOf(row.kind, row.targetKey)) return idleCell(row)
    if (row.item) {
      const item = row.item
      return (
        <CoaResultInput
          itemKey={row.key}
          label={row.label}
          draft={draftOf(item)}
          unit={item.unit ?? null}
          limit={specLimitOf(item)}
          specText={item.spec_text}
          settled={settling.unsettledId !== row.key}
          onBlur={settling.settle}
          onChange={(next) => {
            settling.markUnsettled(row.key)
            setItemEdits((prev) => ({ ...prev, [item.id]: next }))
          }}
        />
      )
    }
    const field = row.field!
    const raw = batchValueOf(field) ?? ''
    const label = `${row.label} 的值`
    return field.field_type === 'date' ? (
      <DatePicker
        size="small"
        aria-label={label}
        style={{ width: '100%' }}
        value={raw ? dayjs(raw) : null}
        onChange={(value) =>
          setBatchEdits((prev) => ({
            ...prev,
            [field.key]: value ? value.format('YYYY-MM-DD') : '',
          }))
        }
      />
    ) : (
      <Input
        size="small"
        aria-label={label}
        value={raw}
        onChange={(e) => setBatchEdits((prev) => ({ ...prev, [field.key]: e.target.value }))}
      />
    )
  }

  const columns: ColumnsType<CopyRow> = [
    {
      title: '#',
      key: 'index',
      width: 44,
      // 分组标题行：第一格横跨整行，其余格不渲染
      onCell: (row) => (isGroup(row) ? { colSpan: 4 } : {}),
      render: (_v, row) =>
        isGroup(row) ? (
          <span className={styles.groupLabel}>{row.label}</span>
        ) : (
          <span className={pageStyles.sheetIndex}>{row.no}</span>
        ),
    },
    {
      title: '复制到',
      key: 'target',
      onCell: (row) => (isGroup(row) ? { colSpan: 0 } : {}),
      render: (_v, row) =>
        isGroup(row) ? null : (
          <div className={pageStyles.itemCell}>
            <span className={pageStyles.entryName}>{row.label}</span>
            {row.hint && <span className={pageStyles.entrySpec}>{row.hint}</span>}
          </div>
        ),
    },
    {
      title: `来源（${sourceStandard.code}）`,
      key: 'source',
      width: 248,
      onCell: (row) => (isGroup(row) ? { colSpan: 0 } : {}),
      render: (_v, row) =>
        isGroup(row) ? null : (
          <Select
            size="small"
            className={styles.sourceSelect}
            aria-label={`${row.label} 的来源`}
            placeholder="选择来源"
            allowClear
            showSearch={{ optionFilterProp: 'label' }}
            value={sourceOf(row.kind, row.targetKey)}
            options={optionsOf(row)}
            optionRender={(option) => (
              <div className={styles.sourceOption}>
                <span className={styles.sourceName}>{option.label}</span>
                <span className={styles.sourceValue}>
                  {sourceText(row.kind, String(option.value)) ?? '未填'}
                </span>
              </div>
            )}
            onChange={(next) => pickSource(row.kind, row.targetKey, next)}
          />
        ),
    },
    {
      title: '值',
      key: 'value',
      width: 272,
      onCell: (row) => (isGroup(row) ? { colSpan: 0 } : {}),
      render: (_v, row) => (isGroup(row) ? null : valueCell(row)),
    },
  ]

  const handleSave = async () => {
    if (!target || !ready || saving) return
    if (!cells.length) {
      message.warning('先给要复制的格选上来源')
      return
    }
    setSaving(true)
    try {
      const result = await copyCoaReport(source.id, {
        standard_id: target.id,
        serial_no: creating ? serialNo.trim() || null : null,
        cells,
      })
      if (!result.success || !result.data) {
        message.error(actionError(result))
        return
      }
      // 越界只提醒不拦：存完了再点名有几项超出目标模板的标准限度
      const hits = collectLimitHits(targetItems, (item) =>
        sourceOf('item', item.id)
          ? { num: draftOf(item).num, text: draftOf(item).raw }
          : undefined,
      )
      const tally = limitTallyText(hits)
      const done = result.data.created
        ? `已在 ${target.code} 登记批号 ${source.batch_no}`
        : `已更新 ${target.code} 的批号 ${source.batch_no}`
      if (tally) message.warning(`${done}，${tally}`)
      else message.success(done)
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const sheet = (() => {
    if (!target) {
      return <div className={pageStyles.inlineEmpty}>这个产品没有其它启用的模板</div>
    }
    if (detailQuery.isError || matrixQuery.isError) {
      return (
        <div className={pageStyles.entryState}>
          <span className={pageStyles.detailError}>模板数据加载失败，请关闭后重试。</span>
        </div>
      )
    }
    if (!ready) {
      return (
        <div className={pageStyles.entryState}>
          <Spin size="small" /> 正在加载模板…
        </div>
      )
    }
    return (
      <Table<CopyRow>
        rowKey="key"
        size="small"
        className={pageStyles.sheetTable}
        dataSource={rows}
        pagination={false}
        tableLayout="fixed"
        rowClassName={(row) => (isGroup(row) ? styles.groupRow : '')}
        locale={{ emptyText: <div className={pageStyles.inlineEmpty}>该模板还没有字段和检测项目</div> }}
        columns={columns}
      />
    )
  })()

  return (
    <Modal
      title="复制到其它模板"
      open
      width={1120}
      centered
      className={pageStyles.entryModal}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="save"
          type="primary"
          loading={saving}
          disabled={!target || !ready}
          onClick={() => void handleSave()}
        >
          {creating ? '登记' : '保存'}
        </Button>,
      ]}
    >
      <div className={pageStyles.entryBody}>
        <section className={pageStyles.entrySheet}>
          <div className={pageStyles.entryHead}>
            <h3 className={pageStyles.entryTitle}>
              复制内容{target && ` · ${target.code}`}
            </h3>
            {ready && <span className={pageStyles.sheetMeta}>{meta}</span>}
          </div>
          <div className={pageStyles.sheetScroll} data-coa-result-scope>
            {sheet}
          </div>
        </section>

        <section className={pageStyles.entryPanel}>
          <h3 className={pageStyles.entryTitle}>报告信息</h3>
          <dl className={`${pageStyles.panelMeta} ${styles.panelMeta}`}>
            <dt>来源</dt>
            <dd title={sourceStandard.name}>
              {sourceStandard.code}
              {sourceStandard.name && <small>{sourceStandard.name}</small>}
            </dd>
            <dt>批号</dt>
            <dd>{source.batch_no}</dd>
          </dl>
          <Form {...PANEL_FORM_LAYOUT}>
            {/* 不加 required：带星号后 72px 标签列放不下「目标模板」会折行（默认已选中） */}
            <Form.Item
              label="目标模板"
              htmlFor="coa-copy-target"
              help={target?.name && <span className={pageStyles.fieldHint}>{target.name}</span>}
            >
              <Select
                id="coa-copy-target"
                showSearch={{ optionFilterProp: 'label' }}
                placeholder="选择目标模板"
                value={targetId}
                options={others.map((s) => ({
                  value: s.id,
                  label: `${s.code} ${s.name}${s.customer ? ` · ${s.customer}` : ''}`,
                }))}
                onChange={changeTarget}
              />
            </Form.Item>
            {/* 流水号选填：登记时往往还没分配 */}
            {creating ? (
              <Form.Item label="流水号" htmlFor="coa-copy-serial" help="选填，不带过来源的">
                <Input
                  id="coa-copy-serial"
                  placeholder="还没分配可留空"
                  autoCorrect="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={serialNo}
                  onChange={(e) => setSerialNo(e.target.value)}
                  onPressEnter={() => void handleSave()}
                />
              </Form.Item>
            ) : (
              existing && (
                <Form.Item
                  label="流水号"
                  help="已有该批号的记录，默认只补空格；覆盖需手动选来源"
                >
                  <span className={styles.existingNote}>{existing.serial_no ?? '—'}</span>
                </Form.Item>
              )
            )}
          </Form>
        </section>
      </div>
    </Modal>
  )
}

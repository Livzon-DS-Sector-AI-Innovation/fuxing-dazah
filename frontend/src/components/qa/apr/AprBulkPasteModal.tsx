'use client'

import { useMemo, useState } from 'react'
import { App, Button, Input, Modal, Table } from 'antd'
import { actionError, subtleText } from '@/components/qa/deviation/shared'
import { createAprItemsBulk } from '@/actions/qa-apr'
import type { AprItemCategory, AprItemDraft, AprSection, AprValueType } from '@/types/qa-apr'
import { CATEGORY_LABEL, CATEGORY_OPTIONS, VALUE_TYPE_OPTIONS, parseSpecRange } from './AprConfigShared'

const BULK_HEADER = '名称\t分组\t类别\t类型\t单位\t标准原文\t下限\t上限\t编码'

const CATEGORY_ALIAS: Record<string, AprItemCategory> = {
  cpp: 'cpp',
  关键工艺参数: 'cpp',
  关键参数: 'cpp',
  工艺参数: 'cpp',
  ipc: 'ipc',
  中间控制参数: 'ipc',
  中控参数: 'ipc',
  中控: 'ipc',
  test: 'test',
  检验项目: 'test',
  检验: 'test',
  info: 'info',
  批次信息: 'info',
  批信息: 'info',
}

const VALUE_TYPE_ALIAS: Record<string, AprValueType> = {
  number: 'number',
  数值: 'number',
  数字: 'number',
  num: 'number',
  text: 'text',
  文字: 'text',
  文字判定: 'text',
  文本: 'text',
  判定: 'text',
}

type DraftField =
  | 'name_cn'
  | 'name_en'
  | 'group_name'
  | 'category'
  | 'value_type'
  | 'unit'
  | 'spec_text'
  | 'spec_min'
  | 'spec_max'
  | 'code'

const HEADER_ALIAS: Record<string, DraftField> = {
  名称: 'name_cn',
  中文名: 'name_cn',
  项目: 'name_cn',
  项目名称: 'name_cn',
  参数: 'name_cn',
  检验项目: 'name_cn',
  name: 'name_cn',
  英文名: 'name_en',
  英文名称: 'name_en',
  name_en: 'name_en',
  分组: 'group_name',
  表头分组: 'group_name',
  组: 'group_name',
  group: 'group_name',
  类别: 'category',
  参数类别: 'category',
  category: 'category',
  类型: 'value_type',
  值类型: 'value_type',
  数据类型: 'value_type',
  type: 'value_type',
  单位: 'unit',
  unit: 'unit',
  标准: 'spec_text',
  标准原文: 'spec_text',
  标准限: 'spec_text',
  限度: 'spec_text',
  规格: 'spec_text',
  spec: 'spec_text',
  下限: 'spec_min',
  标准下限: 'spec_min',
  最小值: 'spec_min',
  min: 'spec_min',
  上限: 'spec_max',
  标准上限: 'spec_max',
  最大值: 'spec_max',
  max: 'spec_max',
  编码: 'code',
  代码: 'code',
  code: 'code',
}

/** 单次批量建列上限，与后端 AprItemsBulkCreate.max_length 一致。 */
const MAX_BULK_ROWS = 300

/** 无表头时的固定列序（与弹窗说明一致）。 */
const POSITIONAL_ORDER: DraftField[] = [
  'name_cn',
  'group_name',
  'category',
  'value_type',
  'unit',
  'spec_text',
  'spec_min',
  'spec_max',
  'code',
]

interface ParsedRow extends AprItemDraft {
  line: number
}

interface ParseIssue {
  line: number | null
  message: string
}

interface ParseResult {
  rows: ParsedRow[]
  issues: ParseIssue[]
  mode: 'header' | 'positional'
  headerLabels: string[]
}

function normalizeHeader(cell: string): string {
  return cell
    .trim()
    .toLowerCase()
    .replace(/[\s　:：()（）]/g, '')
}

function splitCells(line: string): string[] {
  if (line.includes('\t')) return line.split('\t').map((cell) => cell.trim())
  if (line.includes(',')) return line.split(',').map((cell) => cell.trim())
  return line.split(/\s{2,}/).map((cell) => cell.trim())
}

function toNumber(raw: string | undefined): number | null {
  if (raw == null) return null
  const text = raw.trim().replace(/%$/, '')
  if (!text) return null
  const parsed = Number(text)
  return Number.isFinite(parsed) ? parsed : null
}

function parseBulkText(text: string): ParseResult {
  const lines = text
    .split(/\r?\n/)
    .map((line, index) => ({ text: line, line: index + 1 }))
    .filter((entry) => entry.text.trim())

  if (lines.length === 0) {
    return { rows: [], issues: [], mode: 'positional', headerLabels: [] }
  }

  const allCells = lines.map((entry) => splitCells(entry.text))
  const firstCells = allCells[0]
  const mappedFields = firstCells.map((cell) => HEADER_ALIAS[normalizeHeader(cell)] ?? null)
  const headerHits = mappedFields.filter(Boolean).length
  const hasHeader = headerHits >= 2 && mappedFields.includes('name_cn')
  const fields: (DraftField | null)[] = hasHeader ? mappedFields : POSITIONAL_ORDER

  const rows: ParsedRow[] = []
  const issues: ParseIssue[] = []
  const seenCodes = new Set<string>()
  const body = hasHeader ? lines.slice(1) : lines
  const bodyCells = hasHeader ? allCells.slice(1) : allCells

  body.forEach((entry, index) => {
    const cells = bodyCells[index]
    if (!cells.some((cell) => cell)) return
    const record: Partial<Record<DraftField, string>> = {}
    fields.forEach((field, cellIndex) => {
      if (!field) return
      // 有表头时按表头列取；重复别名只认第一列
      if (hasHeader && record[field] !== undefined) return
      record[field] = cells[cellIndex] ?? ''
    })

    const name = (record.name_cn ?? '').trim()
    if (!name) {
      issues.push({ line: entry.line, message: '缺少名称，已跳过' })
      return
    }

    const categoryText = (record.category ?? '').trim()
    const category = categoryText
      ? CATEGORY_ALIAS[categoryText] ?? CATEGORY_ALIAS[categoryText.toLowerCase()]
      : 'test'
    if (!category) {
      issues.push({
        line: entry.line,
        message: `类别「${categoryText}」无法识别，可用：${CATEGORY_OPTIONS.map((option) => option.label).join(' / ')}`,
      })
      return
    }

    const valueTypeText = (record.value_type ?? '').trim()
    const valueType = valueTypeText
      ? VALUE_TYPE_ALIAS[valueTypeText] ?? VALUE_TYPE_ALIAS[valueTypeText.toLowerCase()]
      : 'number'
    if (!valueType) {
      issues.push({
        line: entry.line,
        message: `类型「${valueTypeText}」无法识别，可用：${VALUE_TYPE_OPTIONS.map((option) => option.label).join(' / ')}`,
      })
      return
    }

    const code = (record.code ?? '').trim() || null
    if (code) {
      if (seenCodes.has(code)) {
        issues.push({ line: entry.line, message: `编码 ${code} 在本批粘贴里重复` })
        return
      }
      seenCodes.add(code)
    }

    const specMin = toNumber(record.spec_min)
    const specMax = toNumber(record.spec_max)
    if ((record.spec_min ?? '').trim() && specMin === null) {
      issues.push({ line: entry.line, message: `下限「${record.spec_min}」不是数字` })
      return
    }
    if ((record.spec_max ?? '').trim() && specMax === null) {
      issues.push({ line: entry.line, message: `上限「${record.spec_max}」不是数字` })
      return
    }
    const specText = (record.spec_text ?? '').trim() || null
    if (valueType === 'number' && specMin == null && specMax == null && specText) {
      const parsed = parseSpecRange(specText)
      if (parsed) {
        rows.push({
          line: entry.line,
          name_cn: name,
          name_en: (record.name_en ?? '').trim() || null,
          group_name: (record.group_name ?? '').trim() || null,
          category,
          value_type: valueType,
          unit: (record.unit ?? '').trim() || null,
          spec_text: specText,
          spec_min: parsed.min,
          spec_max: parsed.max,
          code,
        })
        return
      }
    }

    rows.push({
      line: entry.line,
      name_cn: name,
      name_en: (record.name_en ?? '').trim() || null,
      group_name: (record.group_name ?? '').trim() || null,
      category,
      value_type: valueType,
      unit: (record.unit ?? '').trim() || null,
      spec_text: specText,
      spec_min: specMin,
      spec_max: specMax,
      code,
    })
  })

  // 后端 AprItemsBulkCreate 限 300 行：超量在解析出口就拦下并给出明确提示，
  // 而不是提交后收到一条泛化的 422
  if (rows.length > MAX_BULK_ROWS) {
    issues.push({
      line: null,
      message: `一次最多导入 ${MAX_BULK_ROWS} 行（当前 ${rows.length} 行），请分批粘贴。`,
    })
  }

  return {
    rows,
    issues,
    mode: hasHeader ? 'header' : 'positional',
    headerLabels: hasHeader
      ? fields.filter((field): field is DraftField => field !== null).map((field) => HEADER_LABEL[field])
      : [],
  }
}

const HEADER_LABEL: Record<DraftField, string> = {
  name_cn: '名称',
  name_en: '英文名',
  group_name: '分组',
  category: '类别',
  value_type: '类型',
  unit: '单位',
  spec_text: '标准原文',
  spec_min: '下限',
  spec_max: '上限',
  code: '编码',
}

function toDraft(row: ParsedRow): AprItemDraft {
  return {
    name_cn: row.name_cn,
    name_en: row.name_en,
    group_name: row.group_name,
    category: row.category,
    value_type: row.value_type,
    unit: row.unit,
    spec_text: row.spec_text,
    spec_min: row.spec_min,
    spec_max: row.spec_max,
    code: row.code,
  }
}

const SAMPLE = [
  BULK_HEADER,
  '斜面培养基消后PH\t斜面培养基配制\t中间控制参数\t数值\t\t6.6±0.4\t6.2\t7.0\t',
  '保温时间\t斜面培养基配制\t关键工艺参数\t数值\tmin\t20-30分钟\t20\t30\t',
  '培养基灭菌条件\t斜面培养基配制\t关键工艺参数\t文字判定\t\t符合标准\t\t\t',
].join('\n')

interface AprBulkPasteModalProps {
  section: AprSection
  onClose: () => void
  onImported: () => void
}

/**
 * 从 Excel 粘贴列定义：自动识别表头（名称/分组/类别…），没有表头时按固定列序解析。
 * 有问题的行会逐行列出并阻止导入，避免半截成功。
 */
export function AprBulkPasteModal({ section, onClose, onImported }: AprBulkPasteModalProps) {
  const { message } = App.useApp()
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const parsed = useMemo(() => parseBulkText(text), [text])
  const canSubmit = parsed.rows.length > 0 && parsed.issues.length === 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      const result = await createAprItemsBulk(section.id, parsed.rows.map(toDraft))
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(`已导入 ${parsed.rows.length} 个列定义`)
      onImported()
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  const copyHeader = async () => {
    try {
      await navigator.clipboard.writeText(BULK_HEADER)
      message.success('表头已复制，可粘贴到 Excel 第一行')
    } catch {
      message.warning('浏览器不允许写剪贴板，请手动输入表头')
    }
  }

  return (
    <Modal
      title={
        <div>
          <div className="text-[16px]">批量粘贴列定义</div>
          <div className="mt-0.5 text-[12px] font-normal text-[var(--color-steel)]">
            {section.name}：每行一个列定义
          </div>
        </div>
      }
      open
      width={900}
      onOk={handleSubmit}
      onCancel={onClose}
      okText={parsed.rows.length > 0 ? `导入 ${parsed.rows.length} 行` : '导入'}
      cancelText="取消"
      okButtonProps={{ disabled: !canSubmit }}
      confirmLoading={submitting}
      mask={{ closable: false }}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div style={subtleText} className="leading-[1.6]">
          从 Excel 选中区域直接粘贴（制表符分隔），首行可带表头会自动识别；无表头时按
          「名称 / 分组 / 类别 / 类型 / 单位 / 标准原文 / 下限 / 上限 / 编码」顺序解析。
        </div>
        <div className="flex gap-2">
          <Button size="small" onClick={() => setText(SAMPLE)} disabled={!!text.trim()}>
            填入示例
          </Button>
          <Button size="small" onClick={copyHeader}>
            复制表头
          </Button>
        </div>
      </div>
      <Input.TextArea
        value={text}
        onChange={(event) => setText(event.target.value)}
        rows={9}
        placeholder={`${BULK_HEADER}\n斜面培养基消后PH\t斜面培养基配制\t中间控制参数\t数值\t\t6.6±0.4\t6.2\t7.0`}
        style={{ fontFamily: 'monospace', fontSize: 12 }}
      />

      {parsed.issues.length > 0 && (
        <div className="mt-3 max-h-[104px] overflow-y-auto rounded-md bg-[var(--color-tint-rose)] px-3 py-2 text-[12px] text-[var(--color-error)]">
          {parsed.issues.map((issue) => (
            <div key={`${issue.line}-${issue.message}`}>
              {issue.line != null ? `第 ${issue.line} 行：` : ''}
              {issue.message}
            </div>
          ))}
        </div>
      )}

      {parsed.rows.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[12px]">
            <span className="font-semibold text-[var(--color-charcoal)]">
              已识别 {parsed.rows.length} 行
              {parsed.issues.length > 0 ? `，还有 ${parsed.issues.length} 行有问题` : ''}
            </span>
            <span style={subtleText}>
              {parsed.mode === 'header'
                ? `按表头识别：${parsed.headerLabels.join(' / ')}`
                : '未识别到表头，按固定列序解析'}
            </span>
          </div>
          <Table<ParsedRow>
            size="small"
            rowKey="line"
            pagination={false}
            scroll={{ y: 210 }}
            dataSource={parsed.rows}
            columns={[
              { title: '行', dataIndex: 'line', width: 48 },
              { title: '名称', dataIndex: 'name_cn', width: 180, ellipsis: true },
              { title: '分组', dataIndex: 'group_name', width: 130, ellipsis: true, render: (v: string | null) => v || '—' },
              {
                title: '类别',
                dataIndex: 'category',
                width: 110,
                render: (v: AprItemCategory) => CATEGORY_LABEL[v],
              },
              {
                title: '类型',
                dataIndex: 'value_type',
                width: 70,
                render: (v: AprValueType) => (v === 'number' ? '数值' : '文字'),
              },
              { title: '单位', dataIndex: 'unit', width: 70, render: (v: string | null) => v || '—' },
              { title: '标准', dataIndex: 'spec_text', ellipsis: true, render: (v: string | null) => v || '—' },
              { title: '下限', dataIndex: 'spec_min', width: 66, render: (v: number | null) => v ?? '—' },
              { title: '上限', dataIndex: 'spec_max', width: 66, render: (v: number | null) => v ?? '—' },
            ]}
          />
        </div>
      )}
    </Modal>
  )
}

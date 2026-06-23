'use client'

import React, { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { Button, message, Modal } from 'antd'
import {
  DownloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
  CheckCircleFilled,
  ArrowLeftOutlined,
  UndoOutlined,
  PlusOutlined,
  RightOutlined,
  DownOutlined,
  DeleteOutlined,
} from '@ant-design/icons'

import { T } from '@/components/safety/shared-styles'

/* ─────── design tokens ─────── */

const TOKENS = {
  primary: T.primary,
  ink: T.ink,
  charcoal: T.charcoal,
  slate: T.slate,
  steel: T.steel,
  muted: T.muted,
  canvas: T.canvas,
  surface: T.surface,
  hairline: T.hairline,
  hairlineSoft: T.hairlineSoft,
  cardTintLavender: T.cardTintLavender,
  brandPurple800: '#391c57',
  semanticSuccess: '#1aae39',
  error: '#e03131',
} as const

const RADIUS = { sm: 6, md: 8, lg: 12, full: 9999 } as const

/* ─────── chapter definitions ─────── */

interface ChapterDef {
  id: number
  title: string
  label: string
  placeholder: string
}

const CHAPTER_DEFS: ChapterDef[] = [
  { id: 1, title: '1. 目的', label: '第 1 章 · 目的', placeholder: '描述本规程的目的和适用范围...' },
  { id: 2, title: '2. 岗位安全管理职责', label: '第 2 章 · 岗位安全管理职责', placeholder: '列出各级岗位人员的安全管理职责...' },
  { id: 3, title: '3. 岗位主要风险分析', label: '第 3 章 · 岗位主要风险分析', placeholder: '表格形式列出风险类别、产生原因、可能后果、涉及工序、管控措施...' },
  { id: 4, title: '4. 岗位劳动防护用品佩戴要求', label: '第 4 章 · 劳动防护用品佩戴要求', placeholder: '描述劳保用品佩戴要求，表格形式列出不同操作步骤的 PPE 配置...' },
  { id: 5, title: '5. 工艺控制参数', label: '第 5 章 · 工艺控制参数', placeholder: '表格形式列出关键工艺参数的正常范围、报警值、联锁值...' },
  { id: 6, title: '6. 岗位安全操作要求', label: '第 6 章 · 岗位安全操作要求', placeholder: '描述作业前准备要求、通用安全要求、作业结束后的清理检查要求...' },
  { id: 7, title: '7. 生产工艺流程', label: '第 7 章 · 生产工艺流程', placeholder: '按工艺阶段分节，每个阶段包含安全要求和操作步骤...' },
  { id: 8, title: '8. 异常工况处置', label: '第 8 章 · 异常工况处置', placeholder: '表格形式列出异常工况、描述、处置步骤、预防措施...' },
  { id: 9, title: '9. 岗位应急处置要求', label: '第 9 章 · 岗位应急处置要求', placeholder: '按事故类型分节描述灼烫、中毒、火灾等应急处理措施...' },
]

/* ─────── header metadata ─────── */

interface HeaderMeta {
  docNumber: string
  effectiveDate: string
  department: string
}

const DEFAULT_META: HeaderMeta = {
  docNumber: '',
  effectiveDate: '',
  department: '',
}

function parseHeaderMeta(md: string): { meta: HeaderMeta; rest: string } {
  const lines = md.split('\n')
  const meta: HeaderMeta = { ...DEFAULT_META }
  let consumeUntil = 0

  for (let i = 0; i < Math.min(lines.length, 10); i++) {
    const line = lines[i]
    const docMatch = line.match(/^\*\*文件编号[：:]\s*\*\*\s*(.*)/)
    if (docMatch) { meta.docNumber = docMatch[1].trim(); consumeUntil = i + 1; continue }

    const dateMatch = line.match(/^\*\*生效日期[：:]\s*\*\*\s*(.*)/)
    if (dateMatch) { meta.effectiveDate = dateMatch[1].trim(); consumeUntil = i + 1; continue }

    const deptMatch = line.match(/^\*\*颁发部门[：:]\s*\*\*\s*(.*)/)
    if (deptMatch) { meta.department = deptMatch[1].trim(); consumeUntil = i + 1; continue }

    if (line.trim() === '---') { consumeUntil = i + 1; continue }
    if (!line.trim()) { consumeUntil = i + 1; continue }
    break
  }

  return { meta, rest: lines.slice(consumeUntil).join('\n') }
}

function guessMetaFromContent(_regulationName: string, preamble: string): HeaderMeta {
  const meta = { ...DEFAULT_META }
  const deptMatch = preamble.match(/(?:部门|颁发部门|所属部门)[：:]\s*(.+)/)
  if (deptMatch) meta.department = deptMatch[1].trim()
  const docMatch = preamble.match(/(?:文件编号|编号|文档号)[：:]\s*(.+)/)
  if (docMatch) meta.docNumber = docMatch[1].trim()
  const dateMatch = preamble.match(/(?:生效日期|实施日期|日期)[：:]\s*(.+)/)
  if (dateMatch) meta.effectiveDate = dateMatch[1].trim()
  return meta
}

/* ─────── signature table ─────── */

interface SigTableData {
  authorDate: string
  reviewerDate: string
  approverDate: string
  versions: { version: string; date: string; changes: string }[]
}

const EMPTY_SIG: SigTableData = {
  authorDate: '',
  reviewerDate: '',
  approverDate: '',
  versions: [],
}

/** Strip ALL markdown table blocks from text — ensures no duplicate sig table in preamble. */
function stripMarkdownTables(md: string): string {
  const lines = md.split('\n')
  const out: string[] = []
  let inTable = false
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      inTable = true
      continue
    }
    if (inTable) {
      inTable = false
      if (!trimmed) continue
    }
    out.push(line)
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

function parseSigTable(preambleMd: string): SigTableData {
  const data: SigTableData = { ...EMPTY_SIG, versions: [] }
  const lines = preambleMd.split('\n')
  const tableRows: string[][] = []
  let inTable = false

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      if (/^\|[\s\-:]+\|$/.test(trimmed.replace(/\|/g, '|').replace(/[\s\-:]/g, ''))) continue
      const cells = trimmed.slice(1, -1).split('|').map((c) => c.trim())
      if (!inTable) { inTable = true; tableRows.length = 0 }
      tableRows.push(cells)
    } else if (inTable && trimmed === '') {
      break
    } else if (inTable) {
      break
    }
  }

  if (tableRows.length >= 1) {
    const sigRow = tableRows[0]
    if (sigRow.length >= 6) {
      data.authorDate = sigRow[1] || ''
      data.reviewerDate = sigRow[3] || ''
      data.approverDate = sigRow[5] || ''
    }
  }

  for (let r = 2; r < tableRows.length; r++) {
    const row = tableRows[r]
    if (row.length >= 4) {
      data.versions.push({ version: row[1] || '', date: row[2] || '', changes: row[3] || '' })
    }
  }

  return data
}

function serializeSigTable(data: SigTableData): string {
  const rows: string[] = []
  rows.push(
    `| **制定人**<br/>**日 期** | ${data.authorDate} | **审核人**<br/>**日 期** | ${data.reviewerDate} | **批准人**<br/>**日 期** | ${data.approverDate} |`,
  )
  rows.push('| **文件历史** | **版本号** | **日期** | **变更说明** | | |')
  for (const v of data.versions) {
    rows.push(`| | ${v.version} | ${v.date} | ${v.changes} | | |`)
  }
  if (data.versions.length === 0) {
    rows.push('| | | | | | |')
  }
  return rows.join('\n')
}

/* ─────── chapter parser ─────── */

function parseChapters(md: string): { preamble: string; chapters: Record<number, string> } {
  const chapters: Record<number, string> = {}
  let preamble = ''

  interface HeadingPos { id: number; title: string; start: number }
  const positions: HeadingPos[] = []

  for (const def of CHAPTER_DEFS) {
    const idx = md.indexOf(`# ${def.title}`)
    if (idx !== -1) positions.push({ id: def.id, title: def.title, start: idx })
  }
  positions.sort((a, b) => a.start - b.start)

  for (let i = 0; i < positions.length; i++) {
    const current = positions[i]
    const headingText = `# ${current.title}`
    const contentStart = current.start + headingText.length
    let contentIdx = contentStart
    while (contentIdx < md.length && md[contentIdx] === '\n') contentIdx++

    const endIdx = i + 1 < positions.length ? positions[i + 1].start : md.length
    let content = md.slice(contentIdx, endIdx)
    content = content.replace(/\n{3,}$/, '\n\n').trimEnd()
    chapters[current.id] = content

    if (i === 0 && current.start > 0) {
      preamble = md.slice(0, current.start).trim()
    }
  }

  for (const def of CHAPTER_DEFS) {
    if (!(def.id in chapters)) chapters[def.id] = ''
  }

  return { preamble, chapters }
}

function reassembleChapters(preamble: string, chapters: Record<number, string>): string {
  const parts: string[] = []
  if (preamble.trim()) parts.push(preamble.trim())
  for (const def of CHAPTER_DEFS) {
    parts.push(`# ${def.title}\n\n${chapters[def.id] || ''}`)
  }
  return parts.join('\n\n')
}

/* ═══════════════════════════════════════════════════════════════════════════
   GENERIC MARKDOWN TABLE PARSER / SERIALIZER
   ═══════════════════════════════════════════════════════════════════════════ */

interface MarkdownTable {
  headers: string[]
  rows: string[][]
}

/** Parse a markdown table into structured data. Returns null if no table found. */
function parseMarkdownTable(md: string): MarkdownTable | null {
  const lines = md.split('\n')
  const tableLines: string[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      // Skip separator lines like |---|---|
      if (/^\|[\s\-:]+\|$/.test(trimmed)) continue
      tableLines.push(trimmed)
    } else if (tableLines.length > 0) {
      // Table ended — stop scanning
      break
    }
  }

  if (tableLines.length < 2) return null

  const headers = tableLines[0].slice(1, -1).split('|').map((c) => c.trim())
  const rows = tableLines.slice(1).map((line) =>
    line.slice(1, -1).split('|').map((c) => c.trim()),
  )

  return { headers, rows }
}

/** Serialize structured table data back to markdown table string. */
function serializeMarkdownTable(table: MarkdownTable): string {
  const lines: string[] = []
  lines.push('| ' + table.headers.map((h) => ` ${h} `).join('|') + '|')
  lines.push('|' + table.headers.map(() => '---------').join('|') + '|')
  for (const row of table.rows) {
    const padded = [...row, ...Array(Math.max(0, table.headers.length - row.length)).fill('')]
    lines.push('| ' + padded.map((c) => ` ${c} `).join('|') + '|')
  }
  return lines.join('\n')
}

/** Split chapter content into: text before table, the table, text after table. */
function splitAroundTable(md: string): { before: string; table: MarkdownTable | null; after: string } {
  const lines = md.split('\n')
  let tableStart = -1
  let tableEnd = -1

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      if (/^\|[\s\-:]+\|$/.test(trimmed)) continue // skip separator
      if (tableStart === -1) tableStart = i
      tableEnd = i
    } else if (tableStart !== -1) {
      // Table ended
      break
    }
  }

  if (tableStart === -1) {
    return { before: md.trim(), table: null, after: '' }
  }

  const before = lines.slice(0, tableStart).join('\n').trim()
  const tableMd = lines.slice(tableStart, tableEnd + 1).join('\n')
  const after = lines.slice(tableEnd + 1).join('\n').trim()

  return {
    before,
    table: parseMarkdownTable(tableMd),
    after,
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   TEXT STRUCTURE PARSERS
   ═══════════════════════════════════════════════════════════════════════════ */

interface TextBlock {
  label: string
  content: string
}

/** Parse Ch2 bullet list into labeled text blocks. */
function parseBulletList(md: string): TextBlock[] {
  const lines = md.split('\n')
  const blocks: TextBlock[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ')) {
      const content = trimmed.slice(2).trim()
      // Extract role label from content
      const roleMatch = content.match(/^([^负责参与]+)(负责|参与)(.+)$/)
      const label = roleMatch ? roleMatch[1].trim() : `职责项 ${blocks.length + 1}`
      const body = roleMatch ? (roleMatch[2] + roleMatch[3]).trim() : content
      blocks.push({ label, content: body })
    }
  }
  return blocks
}

function serializeBulletList(blocks: TextBlock[]): string {
  return blocks.map((b) => `- ${b.label}${b.content}`).join('\n')
}

/** Parse Ch6-style content: H2 sections with numbered lists. */
interface SectionBlock {
  title: string
  items: string[]
}

function parseNumberedSections(md: string): SectionBlock[] {
  const sections: SectionBlock[] = []
  const lines = md.split('\n')
  let currentSection: SectionBlock | null = null

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    // H2 heading: ## 作业前要求
    const h2Match = trimmed.match(/^## (.+)/)
    if (h2Match) {
      if (currentSection && currentSection.items.length > 0) {
        sections.push(currentSection)
      }
      currentSection = { title: h2Match[1].trim(), items: [] }
      continue
    }

    // Numbered item: 1. xxx or 1. xxx
    const numMatch = trimmed.match(/^\d+[\.\、\)]\s*(.+)/)
    if (numMatch && currentSection) {
      currentSection.items.push(numMatch[1].trim())
      continue
    }

    // Plain text — add to current section
    if (currentSection && trimmed) {
      currentSection.items.push(trimmed)
    }
  }

  if (currentSection && currentSection.items.length > 0) {
    sections.push(currentSection)
  }

  return sections
}

function serializeNumberedSections(sections: SectionBlock[]): string {
  const lines: string[] = []
  for (let i = 0; i < sections.length; i++) {
    const s = sections[i]
    if (i > 0) lines.push('')
    lines.push(`## ${s.title}`)
    lines.push('')
    s.items.forEach((item, j) => {
      lines.push(`${j + 1}. ${item}`)
    })
  }
  return lines.join('\n')
}

/** Parse Ch7-style content: H2 stages with optional H3 sub-sections and numbered lists. */
interface StageBlock {
  stageName: string
  safetyItems: string[]
  operationItems: string[]
}

function parseStageBlocks(md: string): StageBlock[] {
  const stages: StageBlock[] = []
  const lines = md.split('\n')
  let currentStage: StageBlock | null = null
  let currentMode: 'safety' | 'operation' | null = null

  // Skip preamble line (e.g., "本岗位生产工艺流程主要包括以下工序：")
  let startIdx = 0
  for (let i = 0; i < Math.min(lines.length, 3); i++) {
    if (lines[i].trim().startsWith('## ')) {
      startIdx = i
      break
    }
  }

  for (let i = startIdx; i < lines.length; i++) {
    const trimmed = lines[i].trim()
    if (!trimmed) continue

    const h2Match = trimmed.match(/^## (.+)/)
    if (h2Match) {
      if (currentStage) stages.push(currentStage)
      currentStage = { stageName: h2Match[1].trim(), safetyItems: [], operationItems: [] }
      currentMode = null
      continue
    }

    const h3Match = trimmed.match(/^### (.+)/)
    if (h3Match && currentStage) {
      const h3Title = h3Match[1].trim()
      currentMode = h3Title.includes('安全') ? 'safety' : h3Title.includes('操作') ? 'operation' : null
      continue
    }

    // Numbered item
    const numMatch = trimmed.match(/^\d+[\.\、\)]\s*(.+)/)
    if (numMatch && currentStage && currentMode) {
      const content = numMatch[1].trim()
      if (currentMode === 'safety') {
        currentStage.safetyItems.push(content)
      } else {
        currentStage.operationItems.push(content)
      }
      continue
    }

    // Plain text in current stage
    if (currentStage && trimmed) {
      if (currentMode === 'safety') {
        currentStage.safetyItems.push(trimmed)
      } else if (currentMode === 'operation') {
        currentStage.operationItems.push(trimmed)
      }
    }
  }

  if (currentStage) stages.push(currentStage)
  return stages
}

function serializeStageBlocks(stages: StageBlock[], preamble: string): string {
  const lines: string[] = []
  if (preamble.trim()) {
    lines.push(preamble.trim())
    lines.push('')
  }
  for (let i = 0; i < stages.length; i++) {
    const s = stages[i]
    if (i > 0) lines.push('')
    lines.push(`## ${s.stageName}`)
    lines.push('')

    if (s.safetyItems.length > 0) {
      lines.push('### 安全要求')
      lines.push('')
      s.safetyItems.forEach((item, j) => {
        lines.push(`${j + 1}. ${item}`)
      })
      lines.push('')
    }

    if (s.operationItems.length > 0) {
      lines.push('### 操作步骤')
      lines.push('')
      s.operationItems.forEach((item, j) => {
        lines.push(`${j + 1}. ${item}`)
      })
      lines.push('')
    }
  }
  return lines.join('\n')
}

/** Parse Ch9-style content: H2 emergency categories with mixed content. */
interface EmergencyBlock {
  category: string
  content: string  // Free-form text for each category
}

function parseEmergencyBlocks(md: string): EmergencyBlock[] {
  const blocks: EmergencyBlock[] = []
  const lines = md.split('\n')
  let currentBlock: EmergencyBlock | null = null
  let contentLines: string[] = []
  let preambleLines: string[] = []
  let inPreamble = true

  for (const line of lines) {
    const trimmed = line.trim()

    const h2Match = trimmed.match(/^## (.+)/)
    if (h2Match) {
      inPreamble = false
      if (currentBlock) {
        currentBlock.content = contentLines.join('\n').trim()
        blocks.push(currentBlock)
      }
      currentBlock = { category: h2Match[1].trim(), content: '' }
      contentLines = []
      continue
    }

    if (inPreamble) {
      if (trimmed) preambleLines.push(trimmed)
      continue
    }

    if (currentBlock) {
      contentLines.push(line)
    }
  }

  if (currentBlock) {
    currentBlock.content = contentLines.join('\n').trim()
    blocks.push(currentBlock)
  }

  return blocks
}

function serializeEmergencyBlocks(blocks: EmergencyBlock[], preamble: string): string {
  const lines: string[] = []
  if (preamble.trim()) {
    lines.push(preamble.trim())
    lines.push('')
  }
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if (i > 0) lines.push('')
    lines.push(`## ${b.category}`)
    if (b.content.trim()) {
      lines.push('')
      lines.push(b.content)
    }
  }
  return lines.join('\n')
}

/* ─────── preview CSS ─────── */

const PREVIEW_CSS = `
  .sop-paper h1 {
    font-size: 22px; font-weight: 700; line-height: 1.35; color: #000000;
    border-bottom: 2px solid ${TOKENS.primary}; padding-bottom: 8px; margin: 0 0 20px 0;
  }
  .sop-paper h2 {
    font-size: 18px; font-weight: 600; line-height: 1.4; color: ${TOKENS.ink};
    border-bottom: 1px solid ${TOKENS.hairline}; padding-bottom: 6px; margin: 18px 0 10px 0;
  }
  .sop-paper h3 {
    font-size: 15px; font-weight: 600; line-height: 1.45; color: ${TOKENS.charcoal};
    margin: 14px 0 8px 0;
  }
  .sop-paper h4 {
    font-size: 14px; font-weight: 600; line-height: 1.45; color: ${TOKENS.charcoal};
    margin: 10px 0 6px 0;
  }
  .sop-paper p {
    margin: 8px 0; line-height: 1.8; font-size: 15px; font-weight: 400; color: ${TOKENS.ink};
  }
  .sop-paper table {
    width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13px;
  }
  .sop-paper th {
    background: ${TOKENS.cardTintLavender}; padding: 7px 8px;
    border: 1px solid ${TOKENS.hairline}; font-weight: 600; text-align: center;
    color: ${TOKENS.charcoal}; font-size: 13px;
  }
  .sop-paper td {
    padding: 6px 8px; border: 1px solid ${TOKENS.hairline}; font-size: 13px;
    color: ${TOKENS.ink}; line-height: 1.5;
  }
  .sop-paper tbody tr:nth-child(even) { background: #fafaf9; }
  .sop-paper tbody tr:nth-child(odd)  { background: ${TOKENS.canvas}; }
  .sop-paper ul, .sop-paper ol { margin: 8px 0; padding-left: 28px; }
  .sop-paper li { margin: 4px 0; line-height: 1.7; color: ${TOKENS.ink}; font-size: 15px; }
  .sop-paper hr { border: none; border-top: 1px solid ${TOKENS.hairline}; margin: 20px 0; }
  .sop-paper strong { font-weight: 600; color: ${TOKENS.charcoal}; }

  .sop-paper .paper-header-bar {
    display: flex; gap: 20px; padding-bottom: 14px; margin-bottom: 18px;
    border-bottom: 2px solid ${TOKENS.primary};
    font-size: 13px; color: ${TOKENS.charcoal};
  }
  .sop-paper .paper-header-bar .hdr-field {
    display: flex; align-items: center; gap: 6px; white-space: nowrap;
  }
  .sop-paper .paper-header-bar .hdr-label {
    font-weight: 600; color: ${TOKENS.steel}; font-size: 12px;
  }
  .sop-paper .paper-header-bar input {
    border: none; border-bottom: 1px dashed ${TOKENS.hairline}; outline: none;
    font-size: 13px; color: ${TOKENS.ink}; padding: 2px 4px; background: transparent;
    width: 130px; font-family: inherit; transition: border-color 0.15s;
  }
  .sop-paper .paper-header-bar input:focus {
    border-bottom-color: ${TOKENS.primary}; border-bottom-style: solid;
  }

  .sop-paper .sig-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px; }
  .sop-paper .sig-table th, .sop-paper .sig-table td {
    border: 1px solid ${TOKENS.hairline}; padding: 6px 8px; text-align: center;
  }
  .sop-paper .sig-table th {
    background: ${TOKENS.cardTintLavender}; font-weight: 600; color: ${TOKENS.charcoal}; font-size: 12px;
  }
  .sop-paper .sig-table .sig-label {
    font-weight: 600; font-size: 12px; color: ${TOKENS.charcoal}; line-height: 1.5;
  }
  .sop-paper .sig-table .sig-cell {
    min-width: 70px; height: 36px; vertical-align: middle;
  }
  .sop-paper .sig-table .sig-cell input, .sop-paper .sig-table .ver-cell input {
    width: 100%; border: none; outline: none; text-align: center; font-size: 13px;
    color: ${TOKENS.ink}; background: transparent; padding: 2px 4px; font-family: inherit;
  }
  .sop-paper .sig-table .sig-cell input:focus, .sop-paper .sig-table .ver-cell input:focus {
    background: #fafaf9;
  }
  .sop-paper .sig-table .ver-changes input { text-align: left; }

  .sop-paper .paper-chapter { margin-bottom: 4px; }
  .sop-paper .paper-chapter-title {
    font-size: 18px; font-weight: 600; color: ${TOKENS.ink};
    border-bottom: 1px solid ${TOKENS.hairline}; padding-bottom: 6px;
    margin: 22px 0 10px 0; line-height: 1.4;
  }

  /* ── Editable content table (chapters 3,4,5,8) ── */
  .sop-paper .content-table { width: 100%; border-collapse: collapse; margin: 0 0 8px 0; font-size: 13px; }
  .sop-paper .content-table th {
    background: ${TOKENS.cardTintLavender}; padding: 7px 6px;
    border: 1px solid ${TOKENS.hairline}; font-weight: 600; text-align: center;
    color: ${TOKENS.charcoal}; font-size: 12px; white-space: nowrap;
  }
  .sop-paper .content-table td {
    padding: 0; border: 1px solid ${TOKENS.hairline}; vertical-align: top;
  }
  .sop-paper .content-table td input,
  .sop-paper .content-table td textarea {
    width: 100%; border: none; outline: none; font-size: 13px; color: ${TOKENS.ink};
    background: transparent; padding: 6px 8px; font-family: inherit; resize: vertical;
    border-radius: 0; line-height: 1.5;
  }
  .sop-paper .content-table td input:focus,
  .sop-paper .content-table td textarea:focus {
    background: #f8f7ff; box-shadow: inset 0 0 0 1px ${TOKENS.primary};
  }
  .sop-paper .content-table .col-del {
    width: 32px; text-align: center; vertical-align: middle; padding: 0;
  }
  .sop-paper .content-table .col-del .row-del-btn {
    font-size: 16px; color: ${TOKENS.muted}; cursor: pointer; padding: 2px 6px;
    line-height: 1; transition: all 0.15s; user-select: none; display: inline-block;
  }
  .sop-paper .content-table .col-del .row-del-btn:hover { color: ${TOKENS.error}; }

  /* ── Structured text blocks (chapters 1,2,6,7,9) ── */
  .sop-paper .structured-block { margin-bottom: 12px; }
  .sop-paper .structured-block .block-label {
    font-size: 12px; font-weight: 600; color: ${TOKENS.steel};
    margin-bottom: 4px; display: flex; align-items: center; gap: 6px;
  }
  .sop-paper .structured-block .block-input {
    width: 100%; border: none; outline: none; resize: vertical;
    font-size: 14px; line-height: 1.7; color: ${TOKENS.ink};
    background: #fcfcfb; padding: 8px 10px; border-radius: 4px;
    font-family: inherit;
    box-shadow: 0 0 0 1px ${TOKENS.hairlineSoft};
    transition: box-shadow 0.15s;
  }
  .sop-paper .structured-block .block-input:focus {
    box-shadow: 0 0 0 2px ${TOKENS.primary};
  }
  .sop-paper .structured-block .block-textarea {
    min-height: 42px;
  }

  .sop-paper .structured-section {
    margin-bottom: 16px; padding: 12px 14px;
    background: ${TOKENS.canvas}; border: 1px solid ${TOKENS.hairline};
    border-radius: ${RADIUS.sm}px;
  }
  .sop-paper .structured-section .section-title-row {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 10px; padding-bottom: 6px;
    border-bottom: 1px solid ${TOKENS.hairline};
  }
  .sop-paper .structured-section .collapse-toggle {
    cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
    width: 20px; height: 20px; border-radius: 4px; color: ${TOKENS.steel};
    flex-shrink: 0; transition: all 0.15s;
  }
  .sop-paper .structured-section .collapse-toggle:hover {
    background: ${TOKENS.cardTintLavender}; color: ${TOKENS.primary};
  }
  .sop-paper .structured-section .section-title-input {
    flex: 1; border: none; outline: none; font-size: 14px; font-weight: 600;
    color: ${TOKENS.charcoal}; background: transparent; padding: 2px 4px;
    border-bottom: 1px dashed transparent; transition: border-color 0.15s;
    font-family: inherit;
  }
  .sop-paper .structured-section .section-title-input:focus {
    border-bottom-color: ${TOKENS.primary};
  }
  .sop-paper .structured-section .section-title {
    font-size: 14px; font-weight: 600; color: ${TOKENS.charcoal};
    margin-bottom: 10px; padding-bottom: 6px;
    border-bottom: 1px solid ${TOKENS.hairline};
  }
  .sop-paper .structured-section .section-subtitle {
    font-size: 13px; font-weight: 600; color: ${TOKENS.steel};
    margin: 10px 0 6px 0;
  }

  .sop-paper .add-row-btn {
    display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
    color: ${TOKENS.primary}; cursor: pointer; margin-top: 4px; padding: 4px 8px;
    border-radius: 4px; transition: background 0.15s; user-select: none;
  }
  .sop-paper .add-row-btn:hover { background: ${TOKENS.cardTintLavender}; }
  .sop-paper .add-section-btn {
    display: inline-flex; align-items: center; gap: 4px; font-size: 13px;
    color: ${TOKENS.primary}; cursor: pointer; margin-top: 8px; padding: 8px 14px;
    border-radius: ${RADIUS.sm}px; border: 1px dashed ${TOKENS.primary};
    transition: all 0.15s; user-select: none; font-weight: 500;
  }
  .sop-paper .add-section-btn:hover { background: ${TOKENS.cardTintLavender}; }
  .sop-paper .row-del-btn {
    font-size: 16px; color: ${TOKENS.muted}; cursor: pointer; padding: 0 4px;
    line-height: 1; transition: all 0.15s; user-select: none; display: inline-block;
  }
  .sop-paper .row-del-btn:hover { color: ${TOKENS.error}; }
  .sop-paper .add-ver-btn {
    display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
    color: ${TOKENS.primary}; cursor: pointer; margin-top: 6px; padding: 4px 8px;
    border-radius: 4px; transition: background 0.15s; user-select: none;
  }
  .sop-paper .add-ver-btn:hover { background: ${TOKENS.cardTintLavender}; }

  .sop-paper .chapter-preamble-text {
    font-size: 14px; line-height: 1.8; color: ${TOKENS.ink}; margin-bottom: 12px;
    padding: 8px 10px; background: #fcfcfb; border-radius: 4px;
    box-shadow: 0 0 0 1px ${TOKENS.hairlineSoft};
  }
  .sop-paper .chapter-preamble-text textarea {
    width: 100%; border: none; outline: none; resize: vertical;
    font-size: 14px; line-height: 1.8; color: ${TOKENS.ink};
    background: transparent; padding: 0; font-family: inherit;
    min-height: 42px;
  }
  .sop-paper .chapter-preamble-text textarea:focus { box-shadow: none; }
`

/* ═══════════════════════════════════════════════════════════════════════════
   SUB-COMPONENTS
   ═══════════════════════════════════════════════════════════════════════════ */

/** Editable HTML table for table-based chapters (3, 4, 5, 8). */
function EditableContentTable({
  table,
  onChange,
}: {
  table: MarkdownTable
  onChange: (table: MarkdownTable) => void
}) {
  const updateCell = useCallback(
    (rowIdx: number, colIdx: number, value: string) => {
      const newRows = table.rows.map((row, ri) =>
        ri === rowIdx ? row.map((cell, ci) => (ci === colIdx ? value : cell)) : [...row],
      )
      onChange({ ...table, rows: newRows })
    },
    [table, onChange],
  )

  const addRow = useCallback(() => {
    const newRow = table.headers.map(() => '')
    onChange({ ...table, rows: [...table.rows, newRow] })
  }, [table, onChange])

  const deleteRow = useCallback(
    (idx: number) => {
      onChange({ ...table, rows: table.rows.filter((_, i) => i !== idx) })
    },
    [table, onChange],
  )

  return (
    <div>
      <table className="content-table">
        <thead>
          <tr>
            {table.headers.map((h, ci) => (
              <th key={ci}>{h}</th>
            ))}
            <th className="col-del"></th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci}>
                  <input
                    value={cell}
                    onChange={(e) => updateCell(ri, ci, e.target.value)}
                    placeholder="—"
                    aria-label={`${table.headers[ci] || '列' + (ci + 1)} 第${ri + 1}行`}
                  />
                </td>
              ))}
              <td className="col-del">
                <span className="row-del-btn" onClick={() => deleteRow(ri)} title="删除此行">×</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="add-row-btn" onClick={addRow}>
        <PlusOutlined style={{ fontSize: 10 }} />
        添加行
      </div>
    </div>
  )
}

/* ─────── component interface ─────── */

interface SopContentEditorProps {
  regulationId: string
  regulationName: string
  content: string
  onBack: () => void
  onSaved: () => void
}

/* ─────── component ─────── */

export default function SopContentEditor({
  regulationId,
  regulationName,
  content: initialContent,
  onBack,
  onSaved,
}: SopContentEditorProps) {
  /* ── state ── */
  const [headerMeta, setHeaderMeta] = useState<HeaderMeta>({ ...DEFAULT_META })
  const [sigTable, setSigTable] = useState<SigTableData>({ ...EMPTY_SIG, versions: [] })
  const [chapters, setChapters] = useState<Record<number, string>>({})
  const [preambleText, setPreambleText] = useState('')
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [isDirty, setIsDirty] = useState(false)
  const [collapsedKeys, setCollapsedKeys] = useState<Record<string, boolean>>({})

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const toggleCollapse = useCallback((key: string) => {
    setCollapsedKeys((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  /* ── initialise ── */

  useEffect(() => {
    const { meta, rest } = parseHeaderMeta(initialContent)
    const parsed = parseChapters(rest)
    const preamble = parsed.preamble
    const sig = parseSigTable(preamble)
    const preambleWithoutSig = stripMarkdownTables(preamble)

    let finalMeta = meta
    if (!meta.docNumber && !meta.effectiveDate && !meta.department) {
      finalMeta = guessMetaFromContent(regulationName, preamble)
    }

    setHeaderMeta(finalMeta)
    setSigTable(sig)
    setPreambleText(preambleWithoutSig)
    setChapters(parsed.chapters)
    setIsDirty(false)
  }, [initialContent, regulationName])

  /* ── clear saved indicator ── */

  useEffect(() => {
    if (justSaved) {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      saveTimerRef.current = setTimeout(() => setJustSaved(false), 2000)
    }
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [justSaved])

  /* ── derived ── */

  const fullPreambleMarkdown = useMemo(() => {
    const parts: string[] = []
    const metaLines: string[] = []
    if (headerMeta.docNumber.trim()) metaLines.push(`**文件编号:** ${headerMeta.docNumber.trim()}`)
    if (headerMeta.effectiveDate.trim()) metaLines.push(`**生效日期:** ${headerMeta.effectiveDate.trim()}`)
    if (headerMeta.department.trim()) metaLines.push(`**颁发部门:** ${headerMeta.department.trim()}`)
    if (metaLines.length > 0) { parts.push(metaLines.join('\n')); parts.push('---') }
    if (preambleText.trim()) parts.push(preambleText.trim())
    parts.push(serializeSigTable(sigTable))
    return parts.join('\n\n')
  }, [headerMeta, preambleText, sigTable])

  const fullContent = useMemo(
    () => reassembleChapters(fullPreambleMarkdown, chapters),
    [fullPreambleMarkdown, chapters],
  )

  const totalChars = useMemo(() => fullContent.replace(/\s/g, '').length, [fullContent])
  const totalLines = useMemo(() => fullContent.split('\n').length, [fullContent])

  /* ── handlers ── */

  const markDirty = useCallback(() => setIsDirty(true), [])

  const handleMetaChange = useCallback(
    (field: keyof HeaderMeta, value: string) => { setHeaderMeta((prev) => ({ ...prev, [field]: value })); markDirty() },
    [markDirty],
  )

  const handleSigChange = useCallback(
    (field: keyof SigTableData, value: string) => { setSigTable((prev) => ({ ...prev, [field]: value })); markDirty() },
    [markDirty],
  )

  const handleVersionChange = useCallback(
    (idx: number, field: 'version' | 'date' | 'changes', value: string) => {
      setSigTable((prev) => ({
        ...prev,
        versions: prev.versions.map((v, i) => (i === idx ? { ...v, [field]: value } : v)),
      }))
      markDirty()
    },
    [markDirty],
  )

  const addVersion = useCallback(() => {
    setSigTable((prev) => ({ ...prev, versions: [...prev.versions, { version: '', date: '', changes: '' }] }))
    markDirty()
  }, [markDirty])

  const removeVersion = useCallback(
    (idx: number) => { setSigTable((prev) => ({ ...prev, versions: prev.versions.filter((_, i) => i !== idx) })); markDirty() },
    [markDirty],
  )

  const handlePreambleChange = useCallback(
    (value: string) => { setPreambleText(value); markDirty() },
    [markDirty],
  )

  const handleChapterChange = useCallback(
    (id: number, value: string) => { setChapters((prev) => ({ ...prev, [id]: value })); markDirty() },
    [markDirty],
  )

  /* ── revert ── */

  const handleRevert = useCallback(() => {
    if (!isDirty) return
    Modal.confirm({
      title: '撤回修改',
      content: '确定要撤回所有未保存的修改吗？此操作不可恢复。',
      okText: '确定撤回',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => {
        const { meta, rest } = parseHeaderMeta(initialContent)
        const parsed = parseChapters(rest)
        const preamble = parsed.preamble
        const sig = parseSigTable(preamble)
        const preambleWithoutSig = stripMarkdownTables(preamble)

        let finalMeta = meta
        if (!meta.docNumber && !meta.effectiveDate && !meta.department) {
          finalMeta = guessMetaFromContent(regulationName, preamble)
        }

        setHeaderMeta(finalMeta)
        setSigTable(sig)
        setPreambleText(preambleWithoutSig)
        setChapters(parsed.chapters)
        setIsDirty(false)
        message.success('已撤回所有修改')
      },
    })
  }, [isDirty, initialContent, regulationName])

  /* ── save / export ── */

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const { updateSopContent } = await import('@/actions/safety')
      await updateSopContent(regulationId, fullContent, 'reviewed')
      setJustSaved(true); setIsDirty(false); onSaved()
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally { setSaving(false) }
  }, [regulationId, fullContent, onSaved])

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const { exportSopPdf } = await import('@/actions/safety')
      const blob = await exportSopPdf(regulationId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${regulationName || '标准化操规'}.pdf`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('PDF 下载已开始')
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '导出失败')
    } finally { setExporting(false) }
  }, [regulationId, regulationName])

  const handleSaveAndExport = useCallback(async () => {
    setSaving(true)
    try {
      const { updateSopContent } = await import('@/actions/safety')
      await updateSopContent(regulationId, fullContent, 'reviewed')
      setJustSaved(true); setIsDirty(false); onSaved()
      setSaving(false)
      await handleExport()
    } catch (err: unknown) {
      message.error(err instanceof Error ? err.message : '保存失败')
      setSaving(false)
    }
  }, [regulationId, fullContent, onSaved, handleExport])

  const handleBack = useCallback(() => {
    if (isDirty) {
      Modal.confirm({
        title: '未保存的修改',
        content: '您有未保存的修改内容，确定要返回列表吗？',
        okText: '确定离开',
        cancelText: '继续编辑',
        onOk: () => { setIsDirty(false); onBack() },
      })
    } else {
      onBack()
    }
  }, [isDirty, onBack])

  /* ── Ctrl+S ── */

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); handleSave() }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleSave])

  /* ═══════════════════════════════════════════════════════════════════════════
     CHAPTER RENDERERS
     ═══════════════════════════════════════════════════════════════════════════ */

  /** Render a table-based chapter (Ch3,4,5,8) with editable HTML table. */
  function renderTableChapter(chapterId: number, content: string) {
    const { before, table, after } = splitAroundTable(content)
    const handleTableChange = (t: MarkdownTable) => {
      const parts: string[] = []
      if (before) parts.push(before)
      parts.push(serializeMarkdownTable(t))
      if (after) parts.push(after)
      handleChapterChange(chapterId, parts.join('\n\n'))
    }

    return (
      <div>
        {before ? (
          <div className="chapter-preamble-text">
            <textarea
              value={before}
              onChange={(e) => {
                const newBefore = e.target.value
                const parts: string[] = []
                if (newBefore.trim()) parts.push(newBefore.trim())
                if (table) parts.push(serializeMarkdownTable(table))
                if (after) parts.push(after)
                handleChapterChange(chapterId, parts.join('\n\n'))
              }}
              rows={2}
              aria-label="章节说明文字"
              style={{ width: '100%', border: 'none', outline: 'none', resize: 'vertical', fontSize: 14, lineHeight: 1.8, color: TOKENS.ink, background: 'transparent', fontFamily: 'inherit', minHeight: 42 }}
            />
          </div>
        ) : null}
        {table ? (
          <EditableContentTable table={table} onChange={handleTableChange} />
        ) : (
          <div style={{ padding: '12px 14px', color: TOKENS.muted, fontSize: 13, background: '#fafaf9', borderRadius: RADIUS.sm, textAlign: 'center' }}>
            未能识别表格，请检查 Markdown 格式
          </div>
        )}
        {after ? (
          <div style={{ marginTop: 10 }} className="chapter-preamble-text">
            <textarea
              value={after}
              onChange={(e) => {
                const newAfter = e.target.value
                const parts: string[] = []
                if (before) parts.push(before)
                if (table) parts.push(serializeMarkdownTable(table))
                if (newAfter.trim()) parts.push(newAfter.trim())
                handleChapterChange(chapterId, parts.join('\n\n'))
              }}
              rows={2}
              aria-label="章节补充文字"
              style={{ width: '100%', border: 'none', outline: 'none', resize: 'vertical', fontSize: 14, lineHeight: 1.8, color: TOKENS.ink, background: 'transparent', fontFamily: 'inherit', minHeight: 42 }}
            />
          </div>
        ) : null}
      </div>
    )
  }

  /** Render Ch2: bullet list items as labeled fields. */
  function renderCh2(content: string) {
    const blocks = parseBulletList(content)
    if (blocks.length === 0) {
      return (
        <div className="structured-block">
          <textarea
            className="block-input block-textarea"
            value={content}
            onChange={(e) => handleChapterChange(2, e.target.value)}
            placeholder="列出各级岗位人员的安全管理职责..."
            rows={4}
            aria-label="岗位安全管理职责"
          />
        </div>
      )
    }

    const handleBlockChange = (idx: number, newContent: string) => {
      const newBlocks = blocks.map((b, i) => (i === idx ? { ...b, content: newContent } : b))
      handleChapterChange(2, serializeBulletList(newBlocks))
    }

    return (
      <div>
        {blocks.map((block, idx) => (
          <div key={idx} className="structured-block">
            <div className="block-label">{block.label}</div>
            <input
              className="block-input"
              value={block.content}
              onChange={(e) => handleBlockChange(idx, e.target.value)}
              placeholder={`${block.label}的职责说明...`}
              aria-label={block.label}
            />
          </div>
        ))}
      </div>
    )
  }

  /** Render Ch6: H2 sections with numbered items. */
  function renderCh6(content: string) {
    const sections = parseNumberedSections(content)
    if (sections.length === 0) {
      return (
        <div className="structured-block">
          <textarea
            className="block-input block-textarea"
            value={content}
            onChange={(e) => handleChapterChange(6, e.target.value)}
            placeholder="描述作业前准备要求、通用安全要求、作业结束后的清理检查要求..."
            rows={6}
            aria-label="岗位安全操作要求"
          />
        </div>
      )
    }

    const handleTitleChange = (sectionIdx: number, value: string) => {
      const newSections = sections.map((s, si) =>
        si === sectionIdx ? { ...s, title: value } : s,
      )
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    const handleItemChange = (sectionIdx: number, itemIdx: number, value: string) => {
      const newSections = sections.map((s, si) =>
        si === sectionIdx
          ? { ...s, items: s.items.map((it, ii) => (ii === itemIdx ? value : it)) }
          : s,
      )
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    const addItem = (sectionIdx: number) => {
      const newSections = sections.map((s, si) =>
        si === sectionIdx ? { ...s, items: [...s.items, ''] } : s,
      )
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    const removeItem = (sectionIdx: number, itemIdx: number) => {
      const newSections = sections.map((s, si) =>
        si === sectionIdx
          ? { ...s, items: s.items.filter((_, ii) => ii !== itemIdx) }
          : s,
      )
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    const addSection = () => {
      const newSections = [...sections, { title: '新节', items: [] }]
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    const removeSection = (sectionIdx: number) => {
      const newSections = sections.filter((_, si) => si !== sectionIdx)
      handleChapterChange(6, serializeNumberedSections(newSections))
    }

    return (
      <div>
        {sections.map((section, si) => {
          const collapseKey = `ch6-${si}`
          const collapsed = collapsedKeys[collapseKey] ?? true
          return (
            <div key={si} className="structured-section">
              <div className="section-title-row">
                <span
                  className="collapse-toggle"
                  onClick={() => toggleCollapse(collapseKey)}
                  title={collapsed ? '展开' : '收起'}
                >
                  {collapsed ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
                </span>
                <input
                  className="section-title-input"
                  value={section.title}
                  onChange={(e) => handleTitleChange(si, e.target.value)}
                  placeholder="节标题"
                  aria-label={`第${si + 1}节标题`}
                />
                <span
                  className="row-del-btn"
                  onClick={() => removeSection(si)}
                  title="删除本节"
                  style={{ marginLeft: 'auto', flexShrink: 0 }}
                >
                  <DeleteOutlined style={{ fontSize: 13 }} />
                </span>
              </div>
              {!collapsed && (
                <>
                  {section.items.map((item, ii) => (
                    <div key={ii} className="structured-block" style={{ marginBottom: 8 }}>
                      <div className="block-label">{ii + 1}.</div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                        <input
                          className="block-input"
                          value={item}
                          onChange={(e) => handleItemChange(si, ii, e.target.value)}
                          placeholder={`${section.title} · 第${ii + 1}项`}
                          aria-label={`${section.title} 第${ii + 1}项`}
                          style={{ flex: 1 }}
                        />
                        <span
                          className="row-del-btn"
                          onClick={() => removeItem(si, ii)}
                          title="删除此项"
                          style={{ marginTop: 6 }}
                        >
                          ×
                        </span>
                      </div>
                    </div>
                  ))}
                  <div className="add-row-btn" onClick={() => addItem(si)}>
                    <PlusOutlined style={{ fontSize: 10 }} />
                    添加项
                  </div>
                </>
              )}
            </div>
          )
        })}
        <div className="add-section-btn" onClick={addSection}>
          <PlusOutlined style={{ fontSize: 10 }} />
          添加节
        </div>
      </div>
    )
  }

  /** Render Ch7: H2 stages with H3 sub-sections and numbered items. */
  function renderCh7(content: string) {
    // Extract preamble (everything before first ##)
    const lines = content.split('\n')
    let preambleEnd = 0
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) { preambleEnd = i; break }
    }
    const preamble = lines.slice(0, preambleEnd).join('\n').trim()
    const body = lines.slice(preambleEnd).join('\n')

    const stages = parseStageBlocks(body)

    if (stages.length === 0) {
      return (
        <div className="structured-block">
          <textarea
            className="block-input block-textarea"
            value={content}
            onChange={(e) => handleChapterChange(7, e.target.value)}
            placeholder="按工艺阶段分节，每个阶段包含安全要求和操作步骤..."
            rows={8}
            aria-label="生产工艺流程"
          />
        </div>
      )
    }

    const handleStageNameChange = (stageIdx: number, value: string) => {
      const newStages = stages.map((s, si) =>
        si === stageIdx ? { ...s, stageName: value } : s,
      )
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    const handleItemChange = (
      stageIdx: number,
      mode: 'safety' | 'operation',
      itemIdx: number,
      value: string,
    ) => {
      const newStages = stages.map((s, si) => {
        if (si !== stageIdx) return s
        if (mode === 'safety') {
          return { ...s, safetyItems: s.safetyItems.map((it, ii) => (ii === itemIdx ? value : it)) }
        }
        return { ...s, operationItems: s.operationItems.map((it, ii) => (ii === itemIdx ? value : it)) }
      })
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    const addItem = (stageIdx: number, mode: 'safety' | 'operation') => {
      const newStages = stages.map((s, si) => {
        if (si !== stageIdx) return s
        if (mode === 'safety') return { ...s, safetyItems: [...s.safetyItems, ''] }
        return { ...s, operationItems: [...s.operationItems, ''] }
      })
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    const removeItem = (stageIdx: number, mode: 'safety' | 'operation', itemIdx: number) => {
      const newStages = stages.map((s, si) => {
        if (si !== stageIdx) return s
        if (mode === 'safety') return { ...s, safetyItems: s.safetyItems.filter((_, ii) => ii !== itemIdx) }
        return { ...s, operationItems: s.operationItems.filter((_, ii) => ii !== itemIdx) }
      })
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    const addStage = () => {
      const newStages = [...stages, { stageName: '新工序', safetyItems: [], operationItems: [] }]
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    const removeStage = (stageIdx: number) => {
      const newStages = stages.filter((_, si) => si !== stageIdx)
      handleChapterChange(7, serializeStageBlocks(newStages, preamble))
    }

    return (
      <div>
        {preamble ? (
          <div className="chapter-preamble-text" style={{ marginBottom: 14 }}>
            <textarea
              value={preamble}
              onChange={(e) => {
                handleChapterChange(7, serializeStageBlocks(stages, e.target.value))
              }}
              rows={1}
              aria-label="工序说明"
              style={{ width: '100%', border: 'none', outline: 'none', resize: 'vertical', fontSize: 14, lineHeight: 1.8, color: TOKENS.ink, background: 'transparent', fontFamily: 'inherit', minHeight: 36 }}
            />
          </div>
        ) : null}
        {stages.map((stage, si) => {
          const collapseKey = `ch7-${si}`
          const collapsed = collapsedKeys[collapseKey] ?? true
          return (
            <div key={si} className="structured-section">
              <div className="section-title-row">
                <span
                  className="collapse-toggle"
                  onClick={() => toggleCollapse(collapseKey)}
                  title={collapsed ? '展开' : '收起'}
                >
                  {collapsed ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
                </span>
                <input
                  className="section-title-input"
                  value={stage.stageName}
                  onChange={(e) => handleStageNameChange(si, e.target.value)}
                  placeholder="工序名称"
                  aria-label={`工序${si + 1}名称`}
                />
                <span
                  className="row-del-btn"
                  onClick={() => removeStage(si)}
                  title="删除此工序"
                  style={{ marginLeft: 'auto', flexShrink: 0 }}
                >
                  <DeleteOutlined style={{ fontSize: 13 }} />
                </span>
              </div>
              {!collapsed && (
                <>
                  {/* Safety items */}
                  <div className="section-subtitle">安全要求</div>
                  {stage.safetyItems.map((item, ii) => (
                    <div key={`s-${ii}`} className="structured-block" style={{ marginBottom: 8 }}>
                      <div className="block-label">{ii + 1}.</div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                        <input
                          className="block-input"
                          value={item}
                          onChange={(e) => handleItemChange(si, 'safety', ii, e.target.value)}
                          placeholder={`${stage.stageName} 安全要求第${ii + 1}项`}
                          aria-label={`${stage.stageName} 安全要求 ${ii + 1}`}
                          style={{ flex: 1 }}
                        />
                        <span className="row-del-btn" onClick={() => removeItem(si, 'safety', ii)} title="删除此项" style={{ marginTop: 6 }}>×</span>
                      </div>
                    </div>
                  ))}
                  {stage.safetyItems.length === 0 && (
                    <div style={{ padding: '6px 0', color: TOKENS.muted, fontSize: 12 }}>暂无安全要求</div>
                  )}
                  <div className="add-row-btn" onClick={() => addItem(si, 'safety')} style={{ marginBottom: 10 }}>
                    <PlusOutlined style={{ fontSize: 10 }} />
                    添加安全要求
                  </div>
                  {/* Operation items */}
                  <div className="section-subtitle">操作步骤</div>
                  {stage.operationItems.map((item, ii) => (
                    <div key={`o-${ii}`} className="structured-block" style={{ marginBottom: 8 }}>
                      <div className="block-label">{ii + 1}.</div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                        <input
                          className="block-input"
                          value={item}
                          onChange={(e) => handleItemChange(si, 'operation', ii, e.target.value)}
                          placeholder={`${stage.stageName} 操作步骤第${ii + 1}项`}
                          aria-label={`${stage.stageName} 操作步骤 ${ii + 1}`}
                          style={{ flex: 1 }}
                        />
                        <span className="row-del-btn" onClick={() => removeItem(si, 'operation', ii)} title="删除此项" style={{ marginTop: 6 }}>×</span>
                      </div>
                    </div>
                  ))}
                  {stage.operationItems.length === 0 && (
                    <div style={{ padding: '6px 0', color: TOKENS.muted, fontSize: 12 }}>暂无操作步骤</div>
                  )}
                  <div className="add-row-btn" onClick={() => addItem(si, 'operation')}>
                    <PlusOutlined style={{ fontSize: 10 }} />
                    添加操作步骤
                  </div>
                </>
              )}
            </div>
          )
        })}
        <div className="add-section-btn" onClick={addStage}>
          <PlusOutlined style={{ fontSize: 10 }} />
          添加工序
        </div>
      </div>
    )
  }

  /** Render Ch9: H2 emergency categories with mixed content. */
  function renderCh9(content: string) {
    const lines = content.split('\n')
    let preambleEnd = 0
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].trim().startsWith('## ')) { preambleEnd = i; break }
    }
    const preamble = lines.slice(0, preambleEnd).join('\n').trim()
    const body = lines.slice(preambleEnd).join('\n')

    const blocks = parseEmergencyBlocks(body)

    if (blocks.length === 0) {
      return (
        <div className="structured-block">
          <textarea
            className="block-input block-textarea"
            value={content}
            onChange={(e) => handleChapterChange(9, e.target.value)}
            placeholder="按事故类型分节描述灼烫、中毒、火灾等应急处理措施..."
            rows={8}
            aria-label="岗位应急处置要求"
          />
        </div>
      )
    }

    const handleCategoryNameChange = (idx: number, value: string) => {
      const newBlocks = blocks.map((b, i) => (i === idx ? { ...b, category: value } : b))
      handleChapterChange(9, serializeEmergencyBlocks(newBlocks, preamble))
    }

    const handleBlockContentChange = (idx: number, newContent: string) => {
      const newBlocks = blocks.map((b, i) => (i === idx ? { ...b, content: newContent } : b))
      handleChapterChange(9, serializeEmergencyBlocks(newBlocks, preamble))
    }

    const addCategory = () => {
      const newBlocks = [...blocks, { category: '新应急类别', content: '' }]
      handleChapterChange(9, serializeEmergencyBlocks(newBlocks, preamble))
    }

    const removeCategory = (idx: number) => {
      const newBlocks = blocks.filter((_, i) => i !== idx)
      handleChapterChange(9, serializeEmergencyBlocks(newBlocks, preamble))
    }

    return (
      <div>
        {preamble ? (
          <div className="chapter-preamble-text" style={{ marginBottom: 14 }}>
            <textarea
              value={preamble}
              onChange={(e) => {
                handleChapterChange(9, serializeEmergencyBlocks(blocks, e.target.value))
              }}
              rows={1}
              aria-label="应急处置说明"
              style={{ width: '100%', border: 'none', outline: 'none', resize: 'vertical', fontSize: 14, lineHeight: 1.8, color: TOKENS.ink, background: 'transparent', fontFamily: 'inherit', minHeight: 36 }}
            />
          </div>
        ) : null}
        {blocks.map((block, idx) => {
          const collapseKey = `ch9-${idx}`
          const collapsed = collapsedKeys[collapseKey] ?? true
          return (
            <div key={idx} className="structured-section">
              <div className="section-title-row">
                <span
                  className="collapse-toggle"
                  onClick={() => toggleCollapse(collapseKey)}
                  title={collapsed ? '展开' : '收起'}
                >
                  {collapsed ? <RightOutlined style={{ fontSize: 10 }} /> : <DownOutlined style={{ fontSize: 10 }} />}
                </span>
                <input
                  className="section-title-input"
                  value={block.category}
                  onChange={(e) => handleCategoryNameChange(idx, e.target.value)}
                  placeholder="应急类别名称"
                  aria-label={`应急类别${idx + 1}名称`}
                />
                <span
                  className="row-del-btn"
                  onClick={() => removeCategory(idx)}
                  title="删除此类别"
                  style={{ marginLeft: 'auto', flexShrink: 0 }}
                >
                  <DeleteOutlined style={{ fontSize: 13 }} />
                </span>
              </div>
              {!collapsed && (
                <div className="structured-block" style={{ marginTop: 8 }}>
                  <textarea
                    className="block-input block-textarea"
                    value={block.content}
                    onChange={(e) => handleBlockContentChange(idx, e.target.value)}
                    placeholder={`${block.category}的应急处置措施...`}
                    rows={4}
                    aria-label={block.category}
                  />
                </div>
              )}
            </div>
          )
        })}
        <div className="add-section-btn" onClick={addCategory}>
          <PlusOutlined style={{ fontSize: 10 }} />
          添加应急类别
        </div>
      </div>
    )
  }

  /** Dispatch to the correct chapter renderer. */
  const renderChapterContent = useCallback(
    (chapterId: number, content: string) => {
      // Table chapters: 3, 4, 5, 8
      if ([3, 4, 5, 8].includes(chapterId)) {
        return renderTableChapter(chapterId, content)
      }

      // Text chapters with specific structure
      switch (chapterId) {
        case 2: return renderCh2(content)
        case 6: return renderCh6(content)
        case 7: return renderCh7(content)
        case 9: return renderCh9(content)
        // Ch1: simple text — still a textarea but styled differently
        case 1:
        default:
          return (
            <div className="structured-block">
              <textarea
                className="block-input block-textarea"
                value={content}
                onChange={(e) => handleChapterChange(chapterId, e.target.value)}
                placeholder={CHAPTER_DEFS.find((d) => d.id === chapterId)?.placeholder || '请输入内容...'}
                rows={3}
                aria-label={CHAPTER_DEFS.find((d) => d.id === chapterId)?.label || `第${chapterId}章`}
              />
            </div>
          )
      }
    },
    [handleChapterChange, chapters, collapsedKeys],
  )

  /* ── key styles ── */

  const S = {
    topBar: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
      padding: '10px 24px', background: TOKENS.canvas,
      borderBottom: `1px solid ${TOKENS.hairline}`,
      boxShadow: '0 1px 4px rgba(15,15,15,0.04)',
      flexShrink: 0, zIndex: 10,
    } as React.CSSProperties,

    topLeft: { display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, flex: 1 } as React.CSSProperties,
    topRight: { display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 } as React.CSSProperties,

    backBtn: {
      display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 500,
      color: TOKENS.steel, cursor: 'pointer', padding: '6px 10px', borderRadius: RADIUS.sm,
      border: `1px solid ${TOKENS.hairline}`, background: TOKENS.canvas,
      transition: 'all 0.15s', whiteSpace: 'nowrap' as const, userSelect: 'none' as const,
    } as React.CSSProperties,

    sopName: {
      fontSize: 16, fontWeight: 600, color: TOKENS.ink,
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
      maxWidth: 360,
    } as React.CSSProperties,

    badge: {
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: TOKENS.cardTintLavender, color: TOKENS.brandPurple800,
      fontSize: 12, fontWeight: 600, padding: '3px 8px', borderRadius: RADIUS.sm,
      whiteSpace: 'nowrap' as const, flexShrink: 0,
    } as React.CSSProperties,

    stats: {
      fontSize: 12, fontWeight: 400, color: TOKENS.muted, whiteSpace: 'nowrap' as const,
    } as React.CSSProperties,

    savedDot: {
      display: 'inline-flex', alignItems: 'center', gap: 4,
      color: TOKENS.semanticSuccess, fontSize: 12, fontWeight: 500,
      transition: 'opacity 0.3s ease',
    } as React.CSSProperties,

    mainArea: {
      flex: 1, overflow: 'auto', display: 'flex', justifyContent: 'center',
      background: TOKENS.surface, padding: '20px',
    } as React.CSSProperties,

    paperOuter: {
      width: '100%', maxWidth: 860, background: TOKENS.canvas,
      border: `1px solid ${TOKENS.hairline}`, borderRadius: RADIUS.lg,
      boxShadow: '0px 4px 12px 0px rgba(15,15,15,0.08), 0px 1px 2px 0px rgba(15,15,15,0.04)',
      padding: '36px 48px', overflowY: 'auto' as const, height: 'fit-content',
    } as React.CSSProperties,
  }

  /* ── render ── */

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: TOKENS.surface }}>
      {/* ═══ TOP BAR ═══ */}
      <div style={S.topBar}>
        <div style={S.topLeft}>
          <div
            style={S.backBtn}
            onClick={handleBack}
            onMouseEnter={(e) => { e.currentTarget.style.background = TOKENS.surface }}
            onMouseLeave={(e) => { e.currentTarget.style.background = TOKENS.canvas }}
          >
            <ArrowLeftOutlined style={{ fontSize: 12 }} />
            返回列表
          </div>
          <div style={S.sopName}>{regulationName}</div>
          <div style={S.badge}>
            <ThunderboltOutlined style={{ fontSize: 11 }} />
            AI 生成
          </div>
        </div>

        <div style={S.topRight}>
          <span style={S.stats}>
            {totalChars.toLocaleString()} 字 · {totalLines.toLocaleString()} 行 · 9 章
          </span>
          {justSaved && (
            <span style={S.savedDot}>
              <CheckCircleFilled style={{ fontSize: 11 }} />
              已保存
            </span>
          )}
          {isDirty && (
            <Button
              icon={<UndoOutlined />}
              onClick={handleRevert}
              disabled={saving || exporting}
              size="small"
              style={{
                height: 32, borderRadius: RADIUS.sm, fontSize: 13, fontWeight: 500,
                border: `1px solid ${TOKENS.error}`, color: TOKENS.error, background: TOKENS.canvas,
              }}
            >
              撤回
            </Button>
          )}
          <Button
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving && !exporting}
            disabled={saving || exporting || !isDirty}
            size="small"
            style={{
              height: 32, borderRadius: RADIUS.sm, fontSize: 13, fontWeight: 500,
              border: `1px solid ${TOKENS.hairline}`, color: TOKENS.ink, background: TOKENS.canvas,
            }}
          >
            仅保存
          </Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleSaveAndExport}
            loading={saving || exporting}
            disabled={!fullContent.trim()}
            size="small"
            style={{
              height: 32, paddingLeft: 14, paddingRight: 14, fontSize: 13, fontWeight: 500,
              borderRadius: RADIUS.sm, background: TOKENS.primary, borderColor: TOKENS.primary,
              boxShadow: 'none',
            }}
          >
            保存并导出 PDF
          </Button>
        </div>
      </div>

      {/* ═══ MAIN: PAPER VIEW ═══ */}
      <div style={S.mainArea} className="sop-paper-scroll">
        <div style={S.paperOuter}>
          <style dangerouslySetInnerHTML={{ __html: PREVIEW_CSS }} />
          <div className="sop-paper">
            {/* ── Header Metadata Bar ── */}
            <div className="paper-header-bar">
              <div className="hdr-field">
                <span className="hdr-label">文件编号</span>
                <input value={headerMeta.docNumber} onChange={(e) => handleMetaChange('docNumber', e.target.value)} placeholder="编号" />
              </div>
              <div className="hdr-field">
                <span className="hdr-label">生效日期</span>
                <input value={headerMeta.effectiveDate} onChange={(e) => handleMetaChange('effectiveDate', e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="hdr-field">
                <span className="hdr-label">颁发部门</span>
                <input value={headerMeta.department} onChange={(e) => handleMetaChange('department', e.target.value)} placeholder="部门名称" style={{ width: 160 }} />
              </div>
            </div>

            {/* ── Signature / Approval Table ── */}
            <table className="sig-table">
              <tbody>
                <tr>
                  <th className="sig-label" style={{ width: '16.6%' }}>制定人<br />日 期</th>
                  <td className="sig-cell" style={{ width: '16.6%' }}>
                    <input value={sigTable.authorDate} onChange={(e) => handleSigChange('authorDate', e.target.value)} placeholder="签名/日期" />
                  </td>
                  <th className="sig-label" style={{ width: '16.6%' }}>审核人<br />日 期</th>
                  <td className="sig-cell" style={{ width: '16.6%' }}>
                    <input value={sigTable.reviewerDate} onChange={(e) => handleSigChange('reviewerDate', e.target.value)} placeholder="签名/日期" />
                  </td>
                  <th className="sig-label" style={{ width: '16.6%' }}>批准人<br />日 期</th>
                  <td className="sig-cell" style={{ width: '16.6%' }}>
                    <input value={sigTable.approverDate} onChange={(e) => handleSigChange('approverDate', e.target.value)} placeholder="签名/日期" />
                  </td>
                </tr>
                <tr>
                  <th>文件历史</th>
                  <th>版本号</th>
                  <th>日期</th>
                  <th colSpan={2}>变更说明</th>
                  <th></th>
                </tr>
                {sigTable.versions.map((ver, idx) => (
                  <tr key={idx}>
                    <td style={{ textAlign: 'center', color: TOKENS.steel, fontSize: 12 }}>{idx + 1}</td>
                    <td className="ver-cell"><input value={ver.version} onChange={(e) => handleVersionChange(idx, 'version', e.target.value)} placeholder="版本号" /></td>
                    <td className="ver-cell"><input value={ver.date} onChange={(e) => handleVersionChange(idx, 'date', e.target.value)} placeholder="日期" /></td>
                    <td className="ver-cell ver-changes" colSpan={2}><input value={ver.changes} onChange={(e) => handleVersionChange(idx, 'changes', e.target.value)} placeholder="变更说明" /></td>
                    <td style={{ textAlign: 'center', width: 30 }}><span className="row-del-btn" onClick={() => removeVersion(idx)} title="删除此行">×</span></td>
                  </tr>
                ))}
                {sigTable.versions.length === 0 && (
                  <tr>
                    <td style={{ textAlign: 'center', color: TOKENS.muted, fontSize: 12 }}>1</td>
                    <td className="ver-cell"><input value="" onChange={() => {}} placeholder="版本号" disabled /></td>
                    <td className="ver-cell"><input value="" onChange={() => {}} placeholder="日期" disabled /></td>
                    <td className="ver-cell ver-changes" colSpan={2}><input value="" onChange={() => {}} placeholder="变更说明" disabled /></td>
                    <td></td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className="add-ver-btn" onClick={addVersion}>+ 添加版本记录</div>

            {/* ── Preamble text ── */}
            <div style={{ marginTop: 18 }} className="structured-block">
              <textarea
                className="block-input block-textarea"
                value={preambleText}
                onChange={(e) => handlePreambleChange(e.target.value)}
                placeholder="点击此处添加说明文本..."
                rows={2}
                aria-label="说明文本"
              />
            </div>

            {/* ── Chapters 1-9 (structured editing) ── */}
            {CHAPTER_DEFS.map((def) => {
              const content = chapters[def.id] || ''

              return (
                <div key={def.id} className="paper-chapter">
                  <div className="paper-chapter-title">{def.title}</div>
                  {renderChapterContent(def.id, content)}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* scrollbar styling */}
      <style dangerouslySetInnerHTML={{ __html: `
        .sop-paper-scroll::-webkit-scrollbar { width: 8px; }
        .sop-paper-scroll::-webkit-scrollbar-track { background: transparent; }
        .sop-paper-scroll::-webkit-scrollbar-thumb { background: #c8c4be; border-radius: 9999px; }
        .sop-paper-scroll::-webkit-scrollbar-thumb:hover { background: #a4a097; }
      `}} />
    </div>
  )
}

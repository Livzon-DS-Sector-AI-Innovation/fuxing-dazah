'use client'

import { useMemo } from 'react'
import { Button, Empty, Input, InputNumber, Select, Space, Spin, Tooltip } from 'antd'
import { DeleteOutlined, FileDoneOutlined } from '@ant-design/icons'
import type { HardwareMaterialRecord } from '@/types/warehouse-hardware'
import { StatusTag } from '@/components/warehouse'
import { MANAGED_CLASS_TONE } from './constants'

export interface ErpDocRow {
  material_id?: string
  name: string
  spec?: string
  unit?: string
  quantity: number
  match_confidence?: string
  match_score?: number
  managed_class?: string | null
  low?: boolean
  memory?: boolean
}

export interface ErpDocGroup {
  key: string
  delivery_note_no?: string | null
  supplier_name?: string | null
  rows: ErpDocRow[]
}

export interface ErpDocGroupStatus extends ErpDocGroup {
  all_matched: boolean
  mode: 'stocked' | 'direct'
}

/** 匹配置信度阈值：低于此分的行归为未匹配（与后端 matcher.LOW_CONFIDENCE_THRESHOLD 对齐）。 */
export const MATCH_SCORE_THRESHOLD = 75

/**
 * 单行是否匹配成功：有物料ID且置信度达标。
 *
 * 手动选定物料（match_confidence='manual'）视为 100 分——用户已人工确认，
 * 不受阈值限制（后端 pickMaterial 亦写 score=100）。
 */
export function isRowMatched(row: ErpDocRow): boolean {
  if (!row.material_id) return false
  if (row.match_confidence === 'manual') return true
  const score = row.match_score
  if (score == null) return true // 无分数信息（历史/OCR 通道）不拦，交由人工核对
  return score >= MATCH_SCORE_THRESHOLD
}

export function docStatusOf(d: ErpDocGroup): ErpDocGroupStatus {
  return {
    ...d,
    // 整单全行匹配才算 matched（保留字段供批量建单筛选；界面已改为行级统计）
    all_matched: d.rows.length > 0 && d.rows.every((r) => isRowMatched(r)),
    mode: d.rows.some((r) => r.managed_class === 'stocked') ? 'stocked' : 'direct',
  }
}

interface MaterialOption {
  value: string
  label: string
  material?: HardwareMaterialRecord
}

interface Props {
  docs: ErpDocGroup[]
  building: boolean
  materialOptions: MaterialOption[]
  onMaterialKeyword: (kw: string) => void
  materialLoading: boolean
  onRowPatch: (docKey: string, rowIdx: number, patch: Partial<ErpDocRow>) => void
  onRowRemove: (docKey: string, rowIdx: number) => void
  onPickMaterial: (docKey: string, rowIdx: number, material: HardwareMaterialRecord) => void
  onBuildDoc: (doc: ErpDocGroupStatus) => void
  onBuildAll: () => void
}

const MODE_LABEL = { stocked: '共用类', direct: '直发' } as const

function RowTag({ row }: { row: ErpDocRow }) {
  if (!row.material_id) return <StatusTag tone="danger" label="未匹配" />
  if (row.memory) return <StatusTag tone="info" label="记忆匹配" />
  if (row.low) return <StatusTag tone="warn" label="低置信需核对" />
  return <StatusTag tone="ok" label="已匹配" />
}

function DocRowsEditor({
  doc,
  materialOptions,
  onMaterialKeyword,
  materialLoading,
  onRowPatch,
  onRowRemove,
  onPickMaterial,
}: {
  doc: ErpDocGroup
  materialOptions: MaterialOption[]
  onMaterialKeyword: (kw: string) => void
  materialLoading: boolean
  onRowPatch: (docKey: string, rowIdx: number, patch: Partial<ErpDocRow>) => void
  onRowRemove: (docKey: string, rowIdx: number) => void
  onPickMaterial: (docKey: string, rowIdx: number, material: HardwareMaterialRecord) => void
}) {
  return (
    <div className="mt-2 flex flex-col gap-2">
      {doc.rows.map((row, idx) => (
        <Space key={idx} align="start" wrap={false}>
          <Select
            showSearch
            allowClear
            value={row.material_id}
            placeholder="搜索选择物料"
            filterOption={false}
            onSearch={onMaterialKeyword}
            notFoundContent={materialLoading ? <Spin size="small" /> : '无匹配物料'}
            options={
              row.material_id && !materialOptions.some((o) => o.value === row.material_id)
                ? [{ value: row.material_id, label: row.name }, ...materialOptions]
                : materialOptions
            }
            style={{ width: 250 }}
            onClear={() => onRowPatch(doc.key, idx, { material_id: undefined })}
            onChange={(v) => {
              const hit = materialOptions.find((o) => o.value === v)
              if (hit?.material) onPickMaterial(doc.key, idx, hit.material)
            }}
          />
          <Input
            value={row.name}
            placeholder="品名"
            style={{ width: 150 }}
            onChange={(e) => onRowPatch(doc.key, idx, { name: e.target.value })}
          />
          <Input
            value={row.spec}
            placeholder="规格（可空）"
            style={{ width: 140 }}
            onChange={(e) => onRowPatch(doc.key, idx, { spec: e.target.value })}
          />
          <Input
            value={row.unit}
            placeholder="单位"
            style={{ width: 70 }}
            onChange={(e) => onRowPatch(doc.key, idx, { unit: e.target.value })}
          />
          <InputNumber
            value={row.quantity}
            min={1}
            precision={0}
            placeholder="数量"
            style={{ width: 100 }}
            onChange={(v) => onRowPatch(doc.key, idx, { quantity: v ?? 1 })}
          />
          <RowTag row={row} />
          <Tooltip title="删除该行（清单外/误流行可删除，整单删空后单据消失）">
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onRowRemove(doc.key, idx)}
            />
          </Tooltip>
        </Space>
      ))}
    </div>
  )
}

function DocCard({
  doc,
  extra,
  children,
}: {
  doc: ErpDocGroupStatus
  extra?: React.ReactNode
  children?: React.ReactNode
}) {
  const unmatched = doc.rows.filter((r) => !isRowMatched(r)).length
  return (
    <div className="rounded-md border border-neutral-200 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">
          单号 {doc.delivery_note_no || '（无单号）'}
          <span className="ml-2 text-xs font-normal text-neutral-500">
            {doc.supplier_name || '供应商未知'} · {doc.rows.length} 行
            {unmatched > 0 && (
              <span className="text-red-500">（{unmatched} 行未匹配，建单时自动跳过）</span>
            )}
          </span>
          <span className="ml-2">
            <StatusTag tone={MANAGED_CLASS_TONE[doc.mode]} label={MODE_LABEL[doc.mode]} />
          </span>
        </span>
        {extra}
      </div>
      {children}
    </div>
  )
}

export function HardwareReceiptErpDocs({
  docs,
  building,
  materialOptions,
  onMaterialKeyword,
  materialLoading,
  onRowPatch,
  onRowRemove,
  onPickMaterial,
  onBuildDoc,
  onBuildAll,
}: Props) {
  const statuses = useMemo(() => docs.map(docStatusOf), [docs])

  // 按行统计（2026-11-24 口径变更）：不再按整单二分，每行独立判定
  const stats = useMemo(() => {
    let matched = 0
    let unmatched = 0
    for (const d of statuses) {
      for (const r of d.rows) {
        if (isRowMatched(r)) matched += 1
        else unmatched += 1
      }
    }
    const buildable = statuses.filter((d) => d.rows.some((r) => isRowMatched(r)))
    return { matched, unmatched, buildable }
  }, [statuses])

  if (statuses.length === 0) {
    return <Empty description="没有可处理的单据（全部已建单或已删空）" />
  }

  const rowsEditorProps = {
    materialOptions,
    onMaterialKeyword,
    materialLoading,
    onRowPatch,
    onRowRemove,
    onPickMaterial,
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Space size="middle">
          <span className="text-sm">
            本批共 <b>{stats.matched + stats.unmatched}</b> 行：
            <span className="ml-1 text-green-600">已匹配 {stats.matched} 行</span>
            {stats.unmatched > 0 && (
              <span className="ml-2 text-red-500">未匹配 {stats.unmatched} 行</span>
            )}
          </span>
        </Space>
        <Button
          type="primary"
          icon={<FileDoneOutlined />}
          loading={building}
          disabled={stats.buildable.length === 0}
          onClick={onBuildAll}
        >
          批量建单（{stats.buildable.length} 张 · 仅含已匹配行）
        </Button>
      </div>

      <div className="flex max-h-[420px] flex-col gap-3 overflow-y-auto">
        {statuses.map((doc) => {
          const rowMatched = doc.rows.filter((r) => isRowMatched(r)).length
          const canBuild = rowMatched > 0
          return (
            <DocCard
              key={doc.key}
              doc={doc}
              extra={
                <Space size="small">
                  <span className="text-xs text-neutral-500">
                    已匹配 {rowMatched}/{doc.rows.length} 行
                  </span>
                  {canBuild ? (
                    <Button
                      size="small"
                      type="primary"
                      loading={building}
                      onClick={() => onBuildDoc(doc)}
                    >
                      建单（{rowMatched} 行）
                    </Button>
                  ) : (
                    <Tooltip title="请先为至少一行选择物料">
                      <Button size="small" disabled>
                        建单
                      </Button>
                    </Tooltip>
                  )}
                </Space>
              }
            >
              <DocRowsEditor doc={doc} {...rowsEditorProps} />
            </DocCard>
          )
        })}
      </div>
    </div>
  )
}

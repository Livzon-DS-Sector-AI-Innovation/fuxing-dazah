'use client'

import { useState } from 'react'
import { App, Button, Input, Select, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import { ReportAnalyzeItem, ReportMatchCandidate } from '@/types/meter'
import { matchOne } from '@/lib/api/meter'

/** 行数据：文件名可能重复，统一使用父组件生成的 _key 作为行标识。 */
export type ReportMatchRow = ReportAnalyzeItem & { _key: string }

interface Props {
  rows: ReportMatchRow[]
  loading?: boolean
  source: 'instrument' | 'gas_detector'
  onRowChange: (key: string, patch: Partial<ReportAnalyzeItem>) => void
}

/** 候选值编码：`type:id`（type = instrument / gas_detector）。 */
function encodeCandidate(c: ReportMatchCandidate): string {
  return `${c.type}:${c.id}`
}

const methodTag = (method: string | null | undefined) => {
  if (method === 'vision') return <Tag color="blue">AI识别</Tag>
  return <Tag color="red">识别失败</Tag>
}

/**
 * 报告内容识别 + 匹配结果表（ReportDialog / BatchUploadDialog 共用）。
 * 名称/编号/校准日期可编辑（含识别失败行——失败最需要人工补录）；
 * 未匹配行可从候选中手动选择关联，或修正字段后点"重新关联"。
 */
export function ReportMatchTable({ rows, loading, source, onRowChange }: Props) {
  const { message } = App.useApp()
  const [rematching, setRematching] = useState<string | null>(null)

  const handleRematch = async (row: ReportMatchRow) => {
    setRematching(row._key)
    try {
      const res = await matchOne(
        row.extraction.instrument_name,
        row.extraction.serial_number,
        source,
      )
      onRowChange(row._key, {
        matched_type: res.matched_type,
        matched_id: res.matched_id,
        matched_name: res.matched_name,
        matched_department: res.matched_department,
        candidates: res.candidates,
      })
      if (!res.matched_id) message.warning('仍未匹配到台账记录，可继续修正字段或手动选择候选')
    } catch (e) {
      message.error(e instanceof Error ? `重新关联失败：${e.message}` : '重新关联失败')
    } finally {
      setRematching(null)
    }
  }

  const handleSelect = (row: ReportMatchRow, value: string | undefined) => {
    if (!value) {
      onRowChange(row._key, {
        matched_type: null, matched_id: null, matched_name: null, matched_department: null,
      })
      return
    }
    const [type, id] = value.split(':')
    const cand = row.candidates.find(c => c.type === type && c.id === id)
    onRowChange(row._key, {
      matched_type: type as ReportAnalyzeItem['matched_type'],
      matched_id: id,
      // code 与后端自动匹配口径一致：instrument=资产编号，gas_detector=产品编号
      matched_name: cand ? `${cand.name} [${cand.code ?? ''}]` : null,
      matched_department: cand?.department ?? null,
    })
  }

  const columns: TableColumnsType<ReportMatchRow> = [
    { title: '文件名', dataIndex: 'filename', ellipsis: true, width: 180 },
    {
      title: '识别', key: 'method', width: 90,
      render: (_, r) => methodTag(r.extraction.method),
    },
    {
      title: '仪器名称', key: 'name', width: 140,
      render: (_, r) => (
        <Input
          size="small"
          value={r.extraction.instrument_name ?? ''}
          placeholder={r.extraction.method === 'failed' ? (r.extraction.error ?? '手动输入') : '—'}
          onChange={(e) => onRowChange(r._key, {
            extraction: { ...r.extraction, instrument_name: e.target.value || null },
          })}
        />
      ),
    },
    {
      title: '出厂编号', key: 'serial', width: 140,
      render: (_, r) => (
        <Input
          size="small"
          value={r.extraction.serial_number ?? ''}
          placeholder="—"
          onChange={(e) => onRowChange(r._key, {
            extraction: { ...r.extraction, serial_number: e.target.value || null },
          })}
        />
      ),
    },
    {
      title: '校准日期', key: 'cal_date', width: 115,
      render: (_, r) => (
        <Input
          size="small"
          value={r.extraction.calibration_date ?? ''}
          placeholder="YYYY-MM-DD"
          onChange={(e) => onRowChange(r._key, {
            extraction: { ...r.extraction, calibration_date: e.target.value || null },
          })}
        />
      ),
    },
    {
      title: '证书编号', key: 'cert_no', width: 140, ellipsis: true,
      render: (_, r) => r.extraction.certificate_no || '-',
    },
    {
      title: '匹配结果', key: 'match', width: 220,
      render: (_, r) => {
        const candidates = r.candidates ?? []
        const options = candidates.map(c => ({
          value: encodeCandidate(c),
          label: `${c.name} [${c.code ?? ''}]${c.department ? ` · ${c.department}` : ''}`,
        }))
        const value = r.matched_id && r.matched_type
          ? `${r.matched_type}:${r.matched_id}`
          : undefined
        // 精确匹配命中的行 candidates 为空，把当前匹配项补进 options，否则 Select 显示原始编码
        if (value && !options.some(o => o.value === value)) {
          options.unshift({
            value,
            label: `${r.matched_name ?? '已匹配'}${r.matched_department ? ` · ${r.matched_department}` : ''}`,
          })
        }
        const disabled = options.length === 0
        return (
          <Select
            size="small"
            style={{ width: '100%' }}
            placeholder={disabled ? '无候选' : '选择台账记录'}
            value={value}
            options={options}
            disabled={disabled}
            onChange={(v) => handleSelect(r, v)}
          />
        )
      },
    },
    {
      title: '部门', key: 'dept', width: 110, ellipsis: true,
      render: (_, r) => r.matched_department || '-',
    },
    {
      title: '操作', key: 'actions', width: 90, fixed: 'right',
      render: (_, r) => (
        <Button
          size="small"
          loading={rematching === r._key}
          onClick={() => handleRematch(r)}
        >
          重新关联
        </Button>
      ),
    },
  ]

  return (
    <Table<ReportMatchRow>
      rowKey="_key"
      columns={columns}
      dataSource={rows}
      loading={loading}
      size="small"
      pagination={rows.length > 20 ? { pageSize: 20 } : false}
      scroll={{ x: 1100, y: 400 }}
    />
  )
}

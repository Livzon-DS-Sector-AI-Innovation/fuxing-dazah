'use client'

import { useEffect, useMemo, useState } from 'react'
import { App, Button, Checkbox, Drawer, Input, Select, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FileDoneOutlined } from '@ant-design/icons'

import { generateURsConclusion, getURsItems, reviewURsItemsBatch } from '@/actions/safety'
import type { URSStandardItem } from '@/types/safety'
import { T } from '../shared-styles'
import { APPLICABILITY_UI, ITEM_VERDICT_UI } from './ursConstants'

interface Props {
  recordId: string | null
  onClose: () => void
  onOpenConclusion?: (id: string) => void
}

interface EditableItem extends URSStandardItem {
  _verdict: string
  _comment: string
  _rect: boolean
}

export function URSItemReviewDrawer({ recordId, onClose, onOpenConclusion }: Props) {
  const { message } = App.useApp()
  const [items, setItems] = useState<EditableItem[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)

  const load = async (id: string) => {
    setLoading(true)
    const res = await getURsItems(id)
    setLoading(false)
    if (res.code >= 200 && res.code < 300) {
      setItems((res.data ?? []).map((it) => ({
        ...it,
        _verdict: it.review_status === 'passed' || it.review_status === 'failed' ? it.review_status : 'passed',
        _comment: it.review_comment ?? '',
        _rect: it.rectification_required,
      })))
    } else message.error(res.message || '加载失败')
  }

  useEffect(() => {
    if (recordId) load(recordId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId])

  const applicable = useMemo(() => items.filter((it) => it.applicability !== 'not_applicable'), [items])
  const skipped = items.filter((it) => it.applicability === 'not_applicable')

  const updateItem = (id: string, patch: Partial<EditableItem>) => {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)))
  }

  const handleSave = async () => {
    if (!recordId) return
    setSaving(true)
    const payload = applicable.map((it) => ({
      item_id: it.id, verdict: it._verdict, comment: it._comment, rectification_required: it._rect,
    }))
    const res = await reviewURsItemsBatch(recordId, payload)
    setSaving(false)
    if (res.code >= 200 && res.code < 300) message.success(`已保存 ${res.data?.length ?? 0} 条审核结论`)
    else message.error(res.message || '保存失败')
  }

  const handleConclusion = async () => {
    if (!recordId) return
    setGenerating(true)
    const res = await generateURsConclusion(recordId)
    setGenerating(false)
    if (res.code >= 200 && res.code < 300) {
      message.success('结论已生成')
      onOpenConclusion?.(recordId)
    } else message.error(res.message || '生成失败')
  }

  const columns: ColumnsType<EditableItem> = [
    {
      title: '条款', width: 90,
      render: (_, r) => (
        <span>
          {r.item_no}
          {r.is_veto && <Tag color="red" style={{ marginLeft: 4, fontSize: 11 }}>否决</Tag>}
        </span>
      ),
    },
    { title: '标准条款', dataIndex: 'standard_title', width: 220 },
    {
      title: '适配', width: 80,
      render: (_, r) => {
        const ui = APPLICABILITY_UI[r.applicability] ?? { label: r.applicability, pill: undefined }
        return <span style={ui.pill}>{ui.label}</span>
      },
    },
    {
      title: 'AI 预填', width: 200,
      render: (_, r) => {
        const ui = ITEM_VERDICT_UI[r.review_status] ?? { label: r.review_status, pill: undefined }
        return (
          <div>
            <span style={ui.pill}>{ui.label}</span>
            {r.ai_suggestion && <div style={{ fontSize: 11, color: T.steel, marginTop: 2 }}>{r.ai_suggestion}</div>}
          </div>
        )
      },
    },
    {
      title: '审核结论', width: 120,
      render: (_, r) => (
        <Select size="small" style={{ width: 100 }} value={r._verdict} onChange={(v) => updateItem(r.id, { _verdict: v })}
          options={[{ value: 'passed', label: '通过' }, { value: 'failed', label: '不通过' }]} />
      ),
    },
    {
      title: '整改', width: 60,
      render: (_, r) => <Checkbox checked={r._rect} onChange={(e) => updateItem(r.id, { _rect: e.target.checked })} />,
    },
    {
      title: '意见', width: 220,
      render: (_, r) => <Input size="small" value={r._comment} onChange={(e) => updateItem(r.id, { _comment: e.target.value })} placeholder="审核意见" />,
    },
  ]

  return (
    <Drawer title="标准条款逐条审核" width={980} open={!!recordId} loading={loading} onClose={onClose}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 12, color: T.steel }}>
            适用 {applicable.length} 项（否决项 {applicable.filter((i) => i.is_veto).length}）｜不适用 {skipped.length} 项自动跳过
          </span>
          <div>
            <Button style={{ marginRight: 8 }} onClick={onClose}>关闭</Button>
            <Button loading={saving} onClick={handleSave}>保存审核结论</Button>
            <Button type="primary" icon={<FileDoneOutlined />} loading={generating} onClick={handleConclusion} style={{ background: T.primary, borderColor: T.primary, marginLeft: 8 }}>
              生成结论
            </Button>
          </div>
        </div>
      }>
      <Table rowKey="id" size="small" columns={columns} dataSource={applicable} pagination={false} />
    </Drawer>
  )
}

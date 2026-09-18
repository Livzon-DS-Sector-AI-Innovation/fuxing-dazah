'use client'

import { useState } from 'react'
import {
  Modal, Table, Input, InputNumber, Select, Button, Popconfirm, Alert, Typography, Space,
} from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

const { Text } = Typography

export interface ImportDraftDocument {
  file_no: string
  product_name: string
  product_code: string | null
  product_internal_code: string | null
  specification: string | null
  valid_years: string | null
  effective_date: string | null
  version: string | null
}

export interface ImportDraftItem {
  seq: number | null
  category: string | null
  item_name: string
  sop_no: string | null
  standard_text: string | null
  operator: string | null
  limit_min: number | null
  limit_max: number | null
  method_source: string | null
  remark: string | null
}

export interface ImportDraft {
  document: ImportDraftDocument
  items: ImportDraftItem[]
  existing: { id: string; product_name: string } | null
}

interface Props {
  open: boolean
  draft: ImportDraft | null
  confirming: boolean
  onCancel: () => void
  onConfirm: (document: ImportDraftDocument, items: ImportDraftItem[]) => void
}

const OPERATOR_OPTIONS = [
  { label: '（无，人工判定）', value: '' },
  { label: '≤', value: '≤' },
  { label: '≥', value: '≥' },
  { label: '<', value: '<' },
  { label: '>', value: '>' },
  { label: '范围', value: '范围' },
]

export default function ImportConfirmModal({ open, draft, confirming, onCancel, onConfirm }: Props) {
  // 草稿编辑态：父组件每次解析成功换 key 重挂载本组件，初始化即拿到新草稿（不用 effect 同步）
  const [doc, setDoc] = useState<ImportDraftDocument | null>(draft?.document ?? null)
  const [items, setItems] = useState<ImportDraftItem[]>(draft?.items ?? [])

  if (!doc) return null

  const setDocField = (key: keyof ImportDraftDocument, value: string) => {
    setDoc((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const setItemField = (index: number, patch: Partial<ImportDraftItem>) => {
    setItems((prev) => prev.map((it, i) => (i === index ? { ...it, ...patch } : it)))
  }

  const removeItem = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  const columns = [
    {
      title: '序号', key: 'seq', width: 70,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <InputNumber size="small" style={{ width: '100%' }} value={it.seq ?? undefined}
          onChange={(v) => setItemField(i, { seq: v ?? null })} />
      ),
    },
    {
      title: '子项目', key: 'item_name', width: 150,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Input size="small" value={it.item_name} onChange={(e) => setItemField(i, { item_name: e.target.value })} />
      ),
    },
    {
      title: 'SOP号', key: 'sop_no', width: 120,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Input size="small" value={it.sop_no ?? ''} onChange={(e) => setItemField(i, { sop_no: e.target.value || null })} />
      ),
    },
    {
      title: '合格标准', key: 'standard_text', width: 170,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Input size="small" value={it.standard_text ?? ''} onChange={(e) => setItemField(i, { standard_text: e.target.value || null })} />
      ),
    },
    {
      title: '运算符', key: 'operator', width: 130,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Select
          size="small" style={{ width: '100%' }}
          value={it.operator ?? ''}
          onChange={(v) => setItemField(i, { operator: v || null })}
          options={OPERATOR_OPTIONS}
        />
      ),
    },
    {
      title: '下限', key: 'limit_min', width: 80,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <InputNumber size="small" style={{ width: '100%' }} value={it.limit_min ?? undefined}
          onChange={(v) => setItemField(i, { limit_min: v ?? null })} />
      ),
    },
    {
      title: '上限', key: 'limit_max', width: 80,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <InputNumber size="small" style={{ width: '100%' }} value={it.limit_max ?? undefined}
          onChange={(v) => setItemField(i, { limit_max: v ?? null })} />
      ),
    },
    {
      title: '来源', key: 'method_source', width: 100,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Input size="small" value={it.method_source ?? ''} onChange={(e) => setItemField(i, { method_source: e.target.value || null })} />
      ),
    },
    {
      title: '备注', key: 'remark', width: 120,
      render: (_: any, it: ImportDraftItem, i: number) => (
        <Input size="small" value={it.remark ?? ''} onChange={(e) => setItemField(i, { remark: e.target.value || null })} />
      ),
    },
    {
      title: '操作', key: 'actions', width: 60, fixed: 'right' as const,
      render: (_: any, _it: ImportDraftItem, i: number) => (
        <Popconfirm title="删除该行?" onConfirm={() => removeItem(i)}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Modal
      title="确认导入解析结果（请核对并修改，确认后落库）"
      open={open}
      onCancel={onCancel}
      onOk={() => onConfirm(doc, items)}
      okText={draft?.existing ? '确认覆盖' : '确认导入'}
      confirmLoading={confirming}
      width={1280}
    >
      <div className="space-y-3 mt-4">
        {draft?.existing && (
          <Alert
            type="warning"
            showIcon
            message={`该文件编号已导入（产品：${draft.existing.product_name}）——确认后将覆盖更新：文档头与项目行会被替换，绑定模板保留，已建任务不受影响`}
          />
        )}

        <Space wrap size={8}>
          <Text strong>文件编号：</Text>
          <Input size="small" style={{ width: 170 }} value={doc.file_no} onChange={(e) => setDocField('file_no', e.target.value)} />
          <Text strong>产品名称：</Text>
          <Input size="small" style={{ width: 240 }} value={doc.product_name} onChange={(e) => setDocField('product_name', e.target.value)} />
          <Text strong>代号：</Text>
          <Input size="small" style={{ width: 90 }} value={doc.product_code ?? ''} onChange={(e) => setDocField('product_code', e.target.value)} />
          <Text strong>产品代码：</Text>
          <Input size="small" style={{ width: 110 }} value={doc.product_internal_code ?? ''} onChange={(e) => setDocField('product_internal_code', e.target.value)} />
          <Text strong>版本：</Text>
          <Input size="small" style={{ width: 80 }} value={doc.version ?? ''} onChange={(e) => setDocField('version', e.target.value)} />
          <Text strong>规格：</Text>
          <Input size="small" style={{ width: 110 }} value={doc.specification ?? ''} onChange={(e) => setDocField('specification', e.target.value)} />
          <Text strong>有效期：</Text>
          <Input size="small" style={{ width: 100 }} value={doc.valid_years ?? ''} onChange={(e) => setDocField('valid_years', e.target.value)} />
          <Text strong>生效日期：</Text>
          <Input size="small" style={{ width: 130 }} value={doc.effective_date ?? ''} onChange={(e) => setDocField('effective_date', e.target.value)} />
        </Space>

        <Space style={{ marginBottom: 8 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={() => setItems((prev) => [...prev, {
            seq: null, category: null, item_name: '', sop_no: null, standard_text: null,
            operator: null, limit_min: null, limit_max: null, method_source: null, remark: null,
          }])}>
            添加一行
          </Button>
          <Text type="secondary">共 {items.length} 行</Text>
        </Space>
        <Table
          rowKey={(r, i) => `${i}`}
          size="small"
          columns={columns}
          dataSource={items}
          pagination={false}
          scroll={{ x: 1400, y: 380 }}
        />
      </div>
    </Modal>
  )
}

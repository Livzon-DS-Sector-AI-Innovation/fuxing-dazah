'use client'

import { useState } from 'react'
import {
  Button,
  Input,
  Modal,
  Select,
  Switch,
  Table,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { fetchIntermediateTypesClient } from '@/lib/api/production-client'
import type { NodeIntermediateIn } from '@/types/production'

interface Props {
  open: boolean
  intermediates: NodeIntermediateIn[]
  nodeName: string
  onClose: () => void
  onSave: (intermediates: NodeIntermediateIn[]) => void
}

type IntermediateRow = NodeIntermediateIn & { _idx: number }

/** 公用列定义（不含方向和成品，这两个按区不同） */
function makeColumns(
  typeOptions: { value: string; label: string }[],
  direction: 'output' | 'input',
  update: (i: number, patch: Partial<NodeIntermediateIn>) => void,
  remove: (i: number) => void,
  showProductSwitch: boolean,
) {
  const cols: TableColumnsType<IntermediateRow> = [
    {
      title: '物料',
      width: 200,
      render: (_, r: IntermediateRow) => (
        <Select
          size="small"
          style={{ width: '100%' }}
          showSearch
          value={r.intermediate_type_id || undefined}
          options={typeOptions}
          placeholder={direction === 'input' ? '选择消耗物料' : '选择产出物'}
          onChange={v => update(r._idx, { intermediate_type_id: v })}
        />
      ),
    },
    {
      title: '单位覆盖',
      width: 90,
      render: (_, r: IntermediateRow) => (
        <Input
          size="small"
          placeholder="默认"
          value={r.unit_override ?? ''}
          onChange={e => update(r._idx, { unit_override: e.target.value || undefined })}
        />
      ),
    },
    {
      title: '必填',
      width: 60,
      render: (_, r: IntermediateRow) => (
        <Switch
          size="small"
          checked={r.required}
          onChange={v => update(r._idx, { required: v })}
        />
      ),
    },
    {
      title: '备注',
      render: (_, r: IntermediateRow) => (
        <Input
          size="small"
          value={r.remark ?? ''}
          onChange={e => update(r._idx, { remark: e.target.value || undefined })}
        />
      ),
    },
    {
      title: '',
      width: 40,
      render: (_, r: IntermediateRow) => (
        <Button
          size="small"
          type="text"
          danger
          icon={<DeleteOutlined />}
          onClick={() => remove(r._idx)}
        />
      ),
    },
  ]

  if (showProductSwitch) {
    cols.splice(3, 0, {
      title: '成品',
      width: 60,
      render: (_, r: IntermediateRow) => (
        <Switch
          size="small"
          checked={r.is_product}
          onChange={v => update(r._idx, { is_product: v })}
        />
      ),
    })
  }

  return cols
}

export function NodeIntermediatesEditor({ open, intermediates, nodeName, onClose, onSave }: Props) {
  const { data: typeData } = useQuery({
    queryKey: ['intermediate-types', ''],
    queryFn: () => fetchIntermediateTypesClient({ page_size: 100 }),
    enabled: open,
  })

  // ponytail: 原材料管理未实现，消耗暂与产出共用 intermediate types 列表
  // 后续原材料系统上线后，消耗区 select 需合并 raw materials
  const typeOptions = (typeData?.items ?? []).map(t => ({
    value: t.id,
    label: `${t.name} (${t.code})`,
  }))

  return (
    <Modal
      title={`「${nodeName}」消耗 / 产出配置`}
      open={open}
      width={680}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      <EditorBody
        key={open ? 'open' : 'closed'}
        intermediates={intermediates}
        typeOptions={typeOptions}
        onSave={onSave}
        onClose={onClose}
      />
    </Modal>
  )
}

function EditorBody({
  intermediates,
  typeOptions,
  onSave,
  onClose,
}: {
  intermediates: NodeIntermediateIn[]
  typeOptions: { value: string; label: string }[]
  onSave: (items: NodeIntermediateIn[]) => void
  onClose: () => void
}) {
  const [items, setItems] = useState<NodeIntermediateIn[]>(intermediates)

  const update = (i: number, patch: Partial<NodeIntermediateIn>) =>
    setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)))

  const add = (direction: 'output' | 'input') =>
    setItems([...items, { intermediate_type_id: '', direction, required: false, is_product: false, sort_order: items.length }])

  const remove = (i: number) => setItems(items.filter((_, idx) => idx !== i))

  const handleOk = () => {
    const valid = items.filter(it => it.intermediate_type_id)
    onSave(valid)
    onClose()
  }

  const outputItems = items.filter(it => it.direction === 'output')
  const inputItems = items.filter(it => it.direction === 'input')

  return (
    <>
      {/* ── 产出区 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 500, marginBottom: 8, color: '#1aae39' }}>产出物</div>
        <div style={{ marginBottom: 8 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={() => add('output')}>
            添加产出
          </Button>
        </div>
        <Table<IntermediateRow>
          size="small"
          rowKey="_idx"
          dataSource={outputItems.map((it) => ({ ...it, _idx: items.indexOf(it) }))}
          pagination={false}
          columns={makeColumns(typeOptions, 'output', update, remove, true)}
        />
      </div>

      {/* ── 消耗区 ── */}
      <div>
        <div style={{ fontWeight: 500, marginBottom: 8, color: '#dd5b00' }}>消耗</div>
        <div style={{ marginBottom: 8 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={() => add('input')}>
            添加消耗
          </Button>
        </div>
        <Table<IntermediateRow>
          size="small"
          rowKey="_idx"
          dataSource={inputItems.map((it) => ({ ...it, _idx: items.indexOf(it) }))}
          pagination={false}
          columns={makeColumns(typeOptions, 'input', update, remove, false)}
        />
      </div>

      {/* 底部按钮 */}
      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <Button onClick={onClose} style={{ marginRight: 8 }}>取消</Button>
        <Button type="primary" onClick={handleOk}>确定</Button>
      </div>
    </>
  )
}

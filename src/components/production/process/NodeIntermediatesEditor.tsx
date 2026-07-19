'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Input,
  Modal,
  Select,
  Switch,
  Table,
} from 'antd'
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

export function NodeIntermediatesEditor({ open, intermediates, nodeName, onClose, onSave }: Props) {
  const [items, setItems] = useState<NodeIntermediateIn[]>(intermediates)

  useEffect(() => {
    if (open) setItems(intermediates)
  }, [open, intermediates])

  const { data: typeData } = useQuery({
    queryKey: ['intermediate-types', ''],
    queryFn: () => fetchIntermediateTypesClient({ page_size: 100 }),
    enabled: open,
  })

  const typeOptions = (typeData?.items ?? []).map(t => ({
    value: t.id,
    label: `${t.name} (${t.code})`,
  }))

  const update = (i: number, patch: Partial<NodeIntermediateIn>) =>
    setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)))

  const add = (direction: 'output' | 'input') =>
    setItems([...items, { intermediate_type_id: '', direction, required: false, sort_order: items.length }])

  const remove = (i: number) => setItems(items.filter((_, idx) => idx !== i))

  const handleOk = () => {
    const valid = items.filter(it => it.intermediate_type_id)
    onSave(valid)
    onClose()
  }

  return (
    <Modal
      title={`「${nodeName}」中间体绑定`}
      open={open}
      width={680}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={() => add('output')}>
          添加产出
        </Button>
        <Button size="small" icon={<PlusOutlined />} onClick={() => add('input')}>
          添加消耗
        </Button>
      </div>
      <Table<NodeIntermediateIn & { _idx: number }>
        size="small"
        rowKey="_idx"
        dataSource={items.map((it, i) => ({ ...it, _idx: i }))}
        pagination={false}
        columns={[
          {
            title: '方向',
            width: 80,
            render: (_, r) => (
              <Select
                size="small"
                style={{ width: '100%' }}
                value={r.direction}
                options={[
                  { value: 'output', label: '产出' },
                  { value: 'input', label: '消耗' },
                ]}
                onChange={v => update(r._idx, { direction: v })}
              />
            ),
          },
          {
            title: '中间体',
            width: 200,
            render: (_, r) => (
              <Select
                size="small"
                style={{ width: '100%' }}
                showSearch
                value={r.intermediate_type_id || undefined}
                options={typeOptions}
                placeholder="选择中间体"
                onChange={v => update(r._idx, { intermediate_type_id: v })}
              />
            ),
          },
          {
            title: '单位覆盖',
            width: 90,
            render: (_, r) => (
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
            render: (_, r) => (
              <Switch
                size="small"
                checked={r.required}
                onChange={v => update(r._idx, { required: v })}
              />
            ),
          },
          {
            title: '成品',
            width: 60,
            render: (_, r) => (
              <Switch
                size="small"
                checked={r.is_product}
                disabled={r.direction !== 'output'}
                onChange={v => update(r._idx, { is_product: v })}
              />
            ),
          },
          {
            title: '备注',
            render: (_, r) => (
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
            render: (_, r) => (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => remove(r._idx)}
              />
            ),
          },
        ]}
      />
    </Modal>
  )
}

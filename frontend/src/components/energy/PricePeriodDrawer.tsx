'use client'

import { useEffect, useState } from 'react'
import { Drawer, Button, Select, InputNumber, Space, App, Popconfirm, Tag, Empty, Spin } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  fetchPricePeriods,
  createPricePeriod,
  deletePricePeriod,
  resetPricePeriods,
} from '@/lib/api/energy'

interface PricePeriodRow {
  id: string
  category: string
  start_hour: number
  end_hour: number
  months: number[]
}

const CAT_OPTIONS = [
  { label: '尖峰', value: '尖' },
  { label: '高峰', value: '峰' },
  { label: '平段', value: '平' },
  { label: '低谷', value: '谷' },
]

const MONTH_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  label: `${i + 1}月`,
  value: i + 1,
}))

const ALL_MONTHS = Array.from({ length: 12 }, (_, i) => i + 1)

const CAT_COLORS: Record<string, string> = {
  '尖': '#e03131', '峰': '#dd5b00', '平': '#1677ff', '谷': '#1aae39',
}

interface Props {
  open: boolean
  onClose: () => void
}

export function PricePeriodDrawer({ open, onClose }: Props) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<PricePeriodRow[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // 新增表单
  const [newCat, setNewCat] = useState<string>('峰')
  const [newStart, setNewStart] = useState<number>(10)
  const [newEnd, setNewEnd] = useState<number>(11)
  const [newMonths, setNewMonths] = useState<number[]>(ALL_MONTHS)

  const load = async () => {
    setLoading(true)
    try {
      const data = await fetchPricePeriods()
      setRows(data)
    } catch {
      message.error('加载规则失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (open) load() }, [open])

  const handleAdd = async () => {
    if (newStart >= newEnd) { message.warning('开始小时必须小于结束小时'); return }
    if (newMonths.length === 0) { message.warning('请选择适用月份'); return }
    setSaving(true)
    try {
      await createPricePeriod({
        category: newCat,
        start_hour: newStart,
        end_hour: newEnd,
        months: newMonths,
      })
      message.success('添加成功')
      setNewStart(newEnd)  // 快捷：下一个时段
      setNewEnd(Math.min(newEnd + 1, 24))
      await load()
    } catch {
      message.error('添加失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deletePricePeriod(id)
      message.success('已删除')
      await load()
    } catch {
      message.error('删除失败')
    }
  }

  const handleReset = async () => {
    try {
      await resetPricePeriods()
      message.success('已重置为默认规则')
      await load()
    } catch {
      message.error('重置失败')
    }
  }

  // 按分类分组显示
  const grouped: Record<string, PricePeriodRow[]> = {}
  for (const r of rows) {
    if (!grouped[r.category]) grouped[r.category] = []
    grouped[r.category].push(r)
  }
  const order = ['尖', '峰', '平', '谷']

  return (
    <Drawer
      title="峰谷时段规则配置"
      open={open}
      onClose={onClose}
      size="large"
      destroyOnHidden
      extra={
        <Popconfirm title="重置为默认规则？所有自定义规则将被覆盖。" onConfirm={handleReset}>
          <Button icon={<ReloadOutlined />} size="small">重置默认</Button>
        </Popconfirm>
      }
    >
      <Spin spinning={loading}>
        {/* 新增表单 */}
        <div style={{
          padding: 12, background: '#f6f5f4', borderRadius: 8, marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        }}>
          <Select value={newCat} onChange={setNewCat} options={CAT_OPTIONS} style={{ width: 80 }} size="small" />
          <InputNumber value={newStart} onChange={(v) => setNewStart(v ?? 0)} min={0} max={23} size="small" style={{ width: 52 }} placeholder="起" />
          <span style={{ color: '#a4a097' }}>~</span>
          <InputNumber value={newEnd} onChange={(v) => setNewEnd(v ?? 1)} min={1} max={24} size="small" style={{ width: 52 }} placeholder="止" />
          <Select
            mode="multiple" value={newMonths} onChange={setNewMonths}
            options={MONTH_OPTIONS} size="small" style={{ minWidth: 120, maxWidth: 260 }}
            placeholder="月份"
            maxTagCount={2}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} loading={saving} size="small">
            添加
          </Button>
        </div>

        {rows.length === 0 && !loading ? (
          <Empty description="暂无规则，请添加或重置默认" />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {order.filter((cat) => grouped[cat]?.length).map((cat) => (
              <div key={cat}>
                <Tag color={CAT_COLORS[cat]} style={{ marginBottom: 6, fontSize: 13 }}>
                  {CAT_OPTIONS.find((o) => o.value === cat)?.label || cat}
                </Tag>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {grouped[cat].map((r) => (
                    <div key={r.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px',
                      background: '#fafaf9', borderRadius: 6, fontSize: 13,
                    }}>
                      <span style={{ color: '#37352f', fontWeight: 500 }}>
                        {String(r.start_hour).padStart(2, '0')}:00 ~ {String(r.end_hour).padStart(2, '0')}:00
                      </span>
                      <span style={{ color: '#a4a097', flex: 1 }}>
                        {r.months.length === 12 ? '全年' : (
                          r.months.length >= 9
                            ? `除${ALL_MONTHS.filter((m) => !r.months.includes(m)).join('、')}月`
                            : r.months.map((m) => `${m}月`).join('、')
                        )}
                      </span>
                      <Popconfirm title="删除此规则？" onConfirm={() => handleDelete(r.id)}>
                        <Button type="link" danger size="small" style={{ padding: 0, height: 20, fontSize: 11 }}>
                          删除
                        </Button>
                      </Popconfirm>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Spin>
    </Drawer>
  )
}

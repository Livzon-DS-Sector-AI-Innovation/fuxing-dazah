'use client'

import { useEffect, useState, useCallback } from 'react'
import { App, Drawer, Select, Checkbox, Button, Switch, Popconfirm, Space } from 'antd'
import { PlusOutlined, DeleteOutlined, ClockCircleOutlined, UserOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { fetchRouteSchedules } from '@/lib/api/inspection'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { createSchedule, updateSchedule, deleteSchedule } from '@/actions/inspection'
import { PersonnelSelect } from '@/components/equipment'
import type { InspectionRouteSchedule } from '@/types/inspection'
import type { Personnel } from '@/types/equipment-personnel'

const C = {
  navy: '#0a1530',
  purple: '#5645d4',
  ink: '#1a1a1a',
  slate: '#5d5b54',
  stone: '#a4a097',
  hairline: '#e5e3df',
  hairlineSoft: '#ede9e4',
  surface: '#f6f5f4',
  surfaceSoft: '#fafaf9',
  canvas: '#ffffff',
  success: '#1aae39',
}

type FrequencyType = 'daily' | 'weekly' | 'monthly'

const WEEK_OPTIONS = [
  { label: '一', value: 1 }, { label: '二', value: 2 }, { label: '三', value: 3 },
  { label: '四', value: 4 }, { label: '五', value: 5 }, { label: '六', value: 6 }, { label: '日', value: 0 },
]

const MONTH_OPTIONS = Array.from({ length: 31 }, (_, i) => ({ label: `${i + 1}号`, value: i + 1 }))

const TIME_OPTIONS = Array.from({ length: 24 * 4 }, (_, i) => {
  const h = Math.floor(i / 4); const m = (i % 4) * 15
  const v = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  return { label: v, value: v }
})

function buildCron(
  type: FrequencyType,
  time: string,
  weekDays: number[],
  monthDays: number[],
): string {
  const [hr, min] = time.split(':')
  if (type === 'daily') return `${min} ${hr} * * *`
  if (type === 'weekly') return `${min} ${hr} * * ${weekDays.join(',')}`
  return `${min} ${hr} ${monthDays.join(',')} * *`
}

function describeCron(expr: string): string {
  const parts = expr.split(' ')
  if (parts.length < 5) return expr
  const minVals = parts[0].split(',')
  const hrVals = parts[1].split(',')
  const dom = parts[2]
  const dow = parts[4]
  // Handle both single-time and legacy cartesian-product cron
  const times = hrVals.flatMap(h =>
    minVals.map(m => `${h.padStart(2, '0')}:${m.padStart(2, '0')}`)
  )
  const timeStr = times.join('、')
  if (dow !== '*') {
    const dayMap: Record<string, string> = { '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '0': '日' }
    const days = dow.split(',').map((d: string) => dayMap[d] || d).join('、')
    return `每周${days} ${timeStr}`
  }
  if (dom !== '*') return `每月${dom.split(',').join('、')}号 ${timeStr}`
  return `每天 ${timeStr}`
}

export function InspectionScheduleDrawer() {
  const { message } = App.useApp()
  const {
    scheduleDrawerOpen, scheduleRouteId, scheduleRouteName, closeScheduleDrawer,
  } = useInspectionStore()

  const [schedules, setSchedules] = useState<InspectionRouteSchedule[]>([])
  const [loading, setLoading] = useState(false)
  const [personnel, setPersonnel] = useState<Personnel[]>([])

  // add form
  const [freqType, setFreqType] = useState<FrequencyType>('daily')
  const [times, setTimes] = useState<string[]>(['09:00'])
  const [weekDays, setWeekDays] = useState<number[]>([1])
  const [monthDays, setMonthDays] = useState<number[]>([1])
  const [assigneeId, setAssigneeId] = useState<string | undefined>(undefined)

  const load = useCallback(async () => {
    if (!scheduleRouteId) return
    setLoading(true)
    try {
      setSchedules(await fetchRouteSchedules(scheduleRouteId))
    } catch {
      message.error('加载定时任务失败')
    } finally { setLoading(false) }
  }, [scheduleRouteId, message])

  useEffect(() => {
    if (scheduleDrawerOpen) {
      load()
      if (personnel.length === 0) {
        fetchPersonnelList({}).then(r => setPersonnel(r.items.filter(p => p.is_active && p.user_id))).catch(() => {})
      }
    }
  }, [scheduleDrawerOpen, load, personnel.length])

  const handleAdd = async () => {
    if (!scheduleRouteId) return
    if (!assigneeId) { message.warning('请选择巡检人员'); return }
    if (times.length === 0) { message.warning('请选择时间'); return }
    try {
      for (const t of times) {
        const cron = buildCron(freqType, t, weekDays, monthDays)
        await createSchedule(scheduleRouteId, { cron_expression: cron, assigned_to: assigneeId })
      }
      message.success(`已添加 ${times.length} 个定时任务`)
      setTimes(['09:00']); setWeekDays([1]); setMonthDays([1]); setAssigneeId(undefined)
      load()
    } catch (e: unknown) { message.error((e as Error).message || '添加失败') }
  }

  const handleToggle = async (s: InspectionRouteSchedule) => {
    if (!scheduleRouteId) return
    try {
      await updateSchedule(scheduleRouteId, s.id, { is_active: !s.is_active })
      load()
    } catch (e: unknown) { message.error((e as Error).message || '操作失败') }
  }

  const handleDelete = async (s: InspectionRouteSchedule) => {
    if (!scheduleRouteId) return
    try {
      await deleteSchedule(scheduleRouteId, s.id)
      message.success('已删除')
      load()
    } catch (e: unknown) { message.error((e as Error).message || '删除失败') }
  }

  return (
    <Drawer
      title={null}
      size={480}
      open={scheduleDrawerOpen}
      onClose={closeScheduleDrawer}
      destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}
    >
      {/* HEADER */}
      <div style={{
        background: C.navy, padding: '18px 28px',
        borderBottom: `3px solid ${C.purple}`,
      }}>
        <div style={{
          fontSize: 11, fontWeight: 600, letterSpacing: 2,
          color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2,
        }}>
          Schedule Configuration
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff', lineHeight: 1.3 }}>
          线路定时任务
        </div>
        <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.6)', marginTop: 4 }}>
          {scheduleRouteName}
        </div>
      </div>

      {/* BODY */}
      <div style={{ padding: '24px 28px' }}>
        {/* Add Form */}
        <div style={{
          padding: 20, background: C.canvas, borderRadius: 12,
          border: `1px solid ${C.hairline}`, marginBottom: 24,
        }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.ink, marginBottom: 16 }}>
            添加定时任务
          </div>

          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.slate, marginBottom: 6 }}>
              频率类型
            </div>
            <Select
              value={freqType} onChange={setFreqType}
              style={{ width: '100%', height: 42 }}
              options={[
                { label: '每天', value: 'daily' },
                { label: '每周', value: 'weekly' },
                { label: '每月', value: 'monthly' },
              ]}
            />
          </div>

          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.slate, marginBottom: 6 }}>
              时间 {freqType === 'daily' ? '（可多选）' : ''}
            </div>
            {freqType === 'daily' ? (
              <Select
                mode="multiple"
                value={times}
                onChange={setTimes}
                style={{ width: '100%' }}
                options={TIME_OPTIONS}
              />
            ) : (
              <Select
                value={times[0]}
                onChange={(v) => setTimes([v])}
                style={{ width: '100%' }}
                options={TIME_OPTIONS}
              />
            )}
          </div>

          {freqType === 'weekly' && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.slate, marginBottom: 6 }}>
                周几
              </div>
              <Checkbox.Group
                options={WEEK_OPTIONS}
                value={weekDays}
                onChange={(v) => setWeekDays(v as number[])}
              />
            </div>
          )}

          {freqType === 'monthly' && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.slate, marginBottom: 6 }}>
                几号
              </div>
              <Select
                mode="multiple" value={monthDays} onChange={setMonthDays}
                style={{ width: '100%' }} options={MONTH_OPTIONS}
              />
            </div>
          )}

          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.slate, marginBottom: 6 }}>
              巡检人员 <span style={{ color: '#e03131' }}>*</span>
            </div>
            <PersonnelSelect
              value={assigneeId} onChange={setAssigneeId}
              personnel={personnel}
              placeholder="选择巡检人员"
              style={{ width: '100%' }}
            />
          </div>

          <Button
            type="primary" icon={<PlusOutlined />} onClick={handleAdd} block
            style={{
              height: 40, borderRadius: 8,
              background: C.purple, borderColor: C.purple,
              fontWeight: 600, fontSize: 13,
            }}
          >
            添加
          </Button>
        </div>

        {/* Schedule List */}
        <div style={{ fontSize: 14, fontWeight: 600, color: C.ink, marginBottom: 14 }}>
          已配置的定时任务 ({schedules.length})
        </div>

        {schedules.length === 0 && !loading && (
          <div style={{ textAlign: 'center', padding: '40px 20px', color: C.stone, fontSize: 13 }}>
            暂无定时任务，请添加
          </div>
        )}

        <Space orientation="vertical" size={12} style={{ width: '100%' }}>
          {schedules.map(s => (
            <div key={s.id} style={{
              padding: '16px 18px', background: C.canvas,
              borderRadius: 12, border: `1px solid ${C.hairline}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <ClockCircleOutlined style={{ color: C.purple, fontSize: 13 }} />
                    <span style={{ fontSize: 14, fontWeight: 600, color: C.ink }}>
                      {describeCron(s.cron_expression)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: C.slate }}>
                    <UserOutlined />
                    <span>{s.assignee_name || '未指定'}</span>
                  </div>
                  {s.next_trigger_at && (
                    <div style={{ fontSize: 11, color: C.stone, marginTop: 4 }}>
                      下次执行: {new Date(s.next_trigger_at).toLocaleString('zh-CN')}
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <Switch size="small" checked={s.is_active} onChange={() => handleToggle(s)} />
                  <Popconfirm
                    title="确定删除？" onConfirm={() => handleDelete(s)}
                    okText="删除" cancelText="取消"
                  >
                    <span style={{ cursor: 'pointer', color: C.slate, fontSize: 14 }}>
                      <DeleteOutlined />
                    </span>
                  </Popconfirm>
                </div>
              </div>
            </div>
          ))}
        </Space>
      </div>
    </Drawer>
  )
}

'use client'

import { useEffect, useState } from 'react'
import { App, Avatar, DatePicker, Drawer, Form, Select, Typography } from 'antd'
import { UserOutlined, CheckSquareOutlined, CalendarOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { createInspectionTask } from '@/actions/inspection'
import { fetchInspectionRoutes } from '@/lib/api/inspection'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import type { InspectionTemplate } from '@/types/equipment'
import type { InspectionRoute } from '@/types/inspection'
import type { Personnel } from '@/types/equipment-personnel'
import dayjs from 'dayjs'

const { Text } = Typography

interface Props {
  templates: InspectionTemplate[]
  equipments: { id: string; name: string; equipment_no: string }[]
}

const C = { navy: '#0a1530', purple: '#5645d4', ink: '#1a1a1a', slate: '#5d5b54',
  stone: '#a4a097', hairline: '#e5e3df', surface: '#f6f5f4', canvas: '#ffffff' }
const AV = ['#5645d4', '#7b3ff2', '#dd5b00', '#0075de', '#1aae39', '#2a9d99']
function avColor(n: string) { let h = 0; for (let i = 0; i < n.length; i++) h = n.charCodeAt(i) + ((h << 5) - h); return AV[Math.abs(h) % AV.length] }

export function InspectionTaskDrawer({ templates, equipments }: Props) {
  const { message } = App.useApp()
  const { taskDrawerOpen, closeTaskDrawer, triggerTasksRefresh } = useInspectionStore()
  const [form] = Form.useForm()
  const [routes, setRoutes] = useState<InspectionRoute[]>([])
  const [personnel, setPersonnel] = useState<Personnel[]>([])
  const planType = Form.useWatch('plan_type', form) || '设备巡检'

  useEffect(() => {
    if (taskDrawerOpen) {
      if (routes.length === 0) fetchInspectionRoutes({ page: 1, page_size: 200 }).then(r => setRoutes(r.items.filter(x => x.is_active))).catch(() => {})
      fetchPersonnelList({}).then(r => setPersonnel(r.items.filter(p => p.is_active))).catch(() => {})
    }
  }, [taskDrawerOpen, routes.length])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const isRoute = values.plan_type === '线路巡检'
      await createInspectionTask({
        route_id: isRoute ? values.route_id : undefined,
        equipment_ids: !isRoute && values.equipment_ids?.length ? values.equipment_ids : undefined,
        template_ids: values.template_ids?.length ? values.template_ids : undefined,
        plan_type: values.plan_type || '设备巡检',
        assigned_to: values.assigned_to || undefined,
        planned_time: values.planned_time.toISOString(),
      })
      message.success('巡检任务已创建')
      form.resetFields()
      closeTaskDrawer()
      triggerTasksRefresh()
    } catch (err: unknown) {
      if ((err as { errorFields?: unknown[] })?.errorFields) return
      message.error((err as Error).message || '创建失败')
    }
  }

  return (
    <Drawer title={null} size={520} open={taskDrawerOpen}
      onClose={() => { closeTaskDrawer() }}
      destroyOnHidden styles={{ body: { padding: 0, background: C.surface } }}>
      {/* header */}
      <div style={{ background: C.navy, padding: '18px 28px', borderBottom: `3px solid ${C.purple}` }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>Inspection Task Assignment</div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff' }}>创建巡检任务</div>
      </div>

      <div style={{ padding: '24px 28px 100px' }}>
        <Form form={form} layout="vertical" requiredMark={false} preserve={false}
          onValuesChange={c => { if ('plan_type' in c) { form.setFieldValue(c.plan_type === '线路巡检' ? 'equipment_ids' : 'route_id', undefined) } }}>
          {/* type */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <CheckSquareOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>巡检类型</span>
            </div>
            <Form.Item name="plan_type" noStyle initialValue="设备巡检">
              <Select size="middle" style={{ width: '100%' }}
                options={[{ label: '线路巡检', value: '线路巡检' }, { label: '设备巡检', value: '设备巡检' }]} />
            </Form.Item>
          </div>

          {/* route / equipment */}
          {planType === '线路巡检' ? (
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>巡检线路</span>
              </div>
              <Form.Item name="route_id" noStyle rules={[{ required: true, message: '请选择巡检线路' }]}>
                <Select showSearch placeholder="选择巡检线路" optionFilterProp="label"
                  popupMatchSelectWidth={false} style={{ width: '100%' }}
                  options={routes.map(r => ({ label: `${r.name} — ${r.equipment_count}台 · ${r.location_count || 0}地点`, value: r.id }))} />
              </Form.Item>
            </div>
          ) : (
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>巡检设备（可多选）</span>
              </div>
              <Form.Item name="equipment_ids" noStyle rules={[{ required: true, type: 'array', min: 1, message: '请至少选一台设备' }]}>
                <Select mode="multiple" showSearch placeholder="选择设备" optionFilterProp="label"
                  popupMatchSelectWidth={false} maxTagCount="responsive" style={{ width: '100%' }}
                  options={equipments.map(e => ({ label: `${e.name} (${e.equipment_no})`, value: e.id }))} />
              </Form.Item>
            </div>
          )}

          {/* templates */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>检查模板</span>
              {planType === '线路巡检' && <span style={{ fontSize: 11, color: C.stone }}>（线路模式自动获取）</span>}
            </div>
            <Form.Item name="template_ids" noStyle
              rules={planType === '设备巡检' ? [{ required: true, type: 'array', min: 1, message: '请选模板' }] : undefined}>
              <Select mode="multiple" showSearch placeholder={planType === '线路巡检' ? '从路线地点配置获取' : '选择模板（可多选）'}
                disabled={planType === '线路巡检'} optionFilterProp="label"
                popupMatchSelectWidth={false} maxTagCount="responsive" style={{ width: '100%' }}
                options={templates.map(t => ({ label: t.name, value: t.id }))} />
            </Form.Item>
          </div>

          {/* planned time */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <CalendarOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>计划时间</span>
            </div>
            <Form.Item name="planned_time" noStyle rules={[{ required: true, message: '请选择计划时间' }]} initialValue={dayjs()}>
              <DatePicker showTime={{ format: 'HH:mm' }} getPopupContainer={() => document.body}
                size="middle"
                style={{ width: '100%', borderRadius: 8 }} />
            </Form.Item>
          </div>

          {/* assignee */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <UserOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>巡检人员</span>
            </div>
            <Form.Item name="assigned_to" noStyle rules={[{ required: true, message: '请选择巡检人员' }]}>
              <Select showSearch placeholder="选择巡检人员" optionFilterProp="label"
                popupMatchSelectWidth={false} style={{ width: '100%' }}
                options={personnel.map(p => ({ label: `${p.name}${p.department ? ' · ' + p.department : ''}`, value: p.user_id || p.id }))}
                optionRender={o => {
                  const p = personnel.find(pe => (pe.user_id || pe.id) === o.value)
                  if (!p) return <Text>{o.label}</Text>
                  return (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <Avatar size={28} src={p.avatar_url || undefined}
                        style={{ backgroundColor: p.avatar_url ? 'transparent' : avColor(p.name), flexShrink: 0, fontSize: 11, fontWeight: 700 }}
                        icon={!p.avatar_url ? <UserOutlined /> : undefined}>
                        {!p.avatar_url ? p.name.charAt(0) : undefined}
                      </Avatar>
                      <div style={{ lineHeight: 1.3 }}>
                        <Text style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</Text>
                        {p.department && <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>{p.department}{p.employee_no ? ` · ${p.employee_no}` : ''}</Text>}
                      </div>
                    </div>
                  )
                }} />
            </Form.Item>
          </div>
        </Form>
      </div>

      {/* footer */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '14px 24px', background: C.canvas, borderTop: `1px solid ${C.hairline}`, display: 'flex', gap: 10, justifyContent: 'flex-end', boxShadow: '0 -4px 16px rgba(0,0,0,0.06)' }}>
        <button onClick={() => closeTaskDrawer()} style={{ padding: '10px 20px', background: 'transparent', color: C.slate, border: `1px solid ${C.hairline}`, borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}>取消</button>
        <button onClick={handleSubmit} style={{ padding: '10px 28px', background: C.purple, color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', boxShadow: '0 2px 8px rgba(86,69,212,0.3)' }}>创建任务</button>
      </div>
    </Drawer>
  )
}

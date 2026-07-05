'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input } from 'antd'
import { EnvironmentOutlined, FileTextOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { createInspectionRoute, updateInspectionRoute } from '@/actions/equipment'

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
}

export function InspectionRouteDrawer() {
  const { message } = App.useApp()
  const { routeDrawerOpen, editingRoute, closeRouteDrawer, triggerRoutesRefresh } = useInspectionStore()
  const [form] = Form.useForm()
  const isEdit = !!editingRoute

  useEffect(() => {
    if (routeDrawerOpen) {
      if (editingRoute) {
        form.setFieldsValue({
          name: editingRoute.name,
          description: editingRoute.description ?? undefined,
        })
      } else {
        form.resetFields()
      }
    }
  }, [routeDrawerOpen, editingRoute, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingRoute) {
        const result = await updateInspectionRoute(editingRoute.id, values)
        if (!result.success) { message.error(result.error); return }
        message.success('路线已更新')
      } else {
        const result = await createInspectionRoute(values)
        if (!result.success) { message.error(result.error); return }
        message.success('路线已创建')
      }
      form.resetFields()
      closeRouteDrawer()
      triggerRoutesRefresh()
    } catch (err: unknown) {
      if ((err as { errorFields?: unknown[] })?.errorFields) return
      message.error((err as Error).message || '操作失败')
    }
  }

  return (
    <Drawer
      title={null}
      size={460}
      open={routeDrawerOpen}
      onClose={closeRouteDrawer}
      destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}
    >
      {/* ═══ HEADER ═══ */}
      <div style={{
        background: C.navy, padding: '18px 28px',
        borderBottom: `3px solid ${C.purple}`,
      }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>
          Inspection Route {isEdit ? 'Settings' : 'Creation'}
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff', lineHeight: 1.3 }}>
          {isEdit ? '编辑巡检线路' : '新建巡检线路'}
        </div>
      </div>

      {/* ═══ FORM ═══ */}
      <div style={{ padding: '24px 28px 100px' }}>
        <Form form={form} layout="vertical" requiredMark={false}>
          {/* 路线名称 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
            }}>
              <EnvironmentOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                路线名称
              </span>
            </div>
            <Form.Item name="name" noStyle rules={[{ required: true, message: '请输入路线名称' }]}>
              <Input
                placeholder="如：A车间一楼日检路线"
                style={{
                  borderRadius: 8, height: 42, fontSize: 14,
                  border: `1px solid ${C.hairline}`,
                }}
              />
            </Form.Item>
          </div>

          {/* 路线描述 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
            }}>
              <FileTextOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                路线描述
              </span>
              <span style={{ fontSize: 11, color: C.stone }}>（选填）</span>
            </div>
            <Form.Item name="description" noStyle>
              <Input.TextArea
                rows={3}
                placeholder="描述巡检路线的覆盖范围、注意事项等..."
                style={{
                  borderRadius: 8, fontSize: 13,
                  border: `1px solid ${C.hairline}`,
                }}
              />
            </Form.Item>
          </div>

          {/* 提示卡片 */}
          <div style={{
            padding: '12px 16px', borderRadius: 8,
            background: '#e6e0f5', border: '1px solid #d6b6f6',
            fontSize: 12, color: '#391c57', lineHeight: 1.6,
          }}>
            <strong>💡 提示：</strong>创建路线后，请在路线列表点击
            <span style={{ color: C.purple, fontWeight: 600 }}>「定时」</span>
            配置定时执行计划，再点击
            <span style={{ color: C.purple, fontWeight: 600 }}>「设备」</span>
            配置巡检地点、设备和检查模板。
          </div>
        </Form>
      </div>

      {/* ═══ FOOTER ═══ */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        padding: '14px 24px',
        background: C.canvas,
        borderTop: `1px solid ${C.hairline}`,
        display: 'flex', gap: 10, justifyContent: 'flex-end',
        boxShadow: '0 -4px 16px rgba(0,0,0,0.06)',
      }}>
        <button
          onClick={closeRouteDrawer}
          style={{
            padding: '10px 20px',
            background: 'transparent', color: C.slate, border: `1px solid ${C.hairline}`,
            borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          取消
        </button>
        <button
          onClick={handleSubmit}
          style={{
            padding: '10px 28px',
            background: C.purple, color: '#fff', border: 'none',
            borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            fontFamily: 'inherit',
            boxShadow: `0 2px 8px rgba(86,69,212,0.3)`,
          }}
        >
          {isEdit ? '保存修改' : '创建路线'}
        </button>
      </div>
    </Drawer>
  )
}

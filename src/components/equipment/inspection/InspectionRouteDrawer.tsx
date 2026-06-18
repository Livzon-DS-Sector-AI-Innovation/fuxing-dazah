'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, InputNumber, Select, Space } from 'antd'
import { EnvironmentOutlined, CalendarOutlined, FileTextOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { createInspectionRoute, updateInspectionRoute } from '@/actions/inspection'

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
          period_type: editingRoute.period_type,
          period_value: editingRoute.period_value ?? undefined,
          description: editingRoute.description ?? undefined,
        })
      } else {
        form.setFieldsValue({ period_type: '每日' })
      }
    }
  }, [routeDrawerOpen, editingRoute, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingRoute) {
        await updateInspectionRoute(editingRoute.id, values)
        message.success('路线已更新')
      } else {
        await createInspectionRoute(values)
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

  const periodType = Form.useWatch('period_type', form)

  const periodLabel = periodType === '每日' ? '每隔几天巡检一次'
    : periodType === '每周' ? '每隔几周巡检一次'
    : periodType === '每月' ? '每隔几月巡检一次'
    : '周期数值'

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

          {/* 巡检周期 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
            }}>
              <CalendarOutlined style={{ color: C.purple, fontSize: 13 }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.slate, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                巡检周期
              </span>
            </div>
            <div style={{
              padding: '14px 16px', background: C.surfaceSoft,
              borderRadius: 10, border: `1px solid ${C.hairlineSoft}`,
            }}>
              <Form.Item name="period_type" noStyle initialValue="每日">
                <Select
                  size="middle"
                  style={{ width: '100%', marginBottom: 12 }}
                  options={[
                    { label: '每日巡检', value: '每日' },
                    { label: '每周巡检', value: '每周' },
                    { label: '每月巡检', value: '每月' },
                    { label: '专项巡检（无固定周期）', value: '专项' },
                  ]}
                />
              </Form.Item>
              {periodType && periodType !== '专项' && (
                <Form.Item name="period_value" noStyle>
                  <Space.Compact style={{ width: '100%' }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center',
                      padding: '0 11px', fontSize: 12, color: C.stone,
                      background: '#fafaf9', border: `1px solid ${C.hairline}`,
                      borderRadius: '7px 0 0 7px', whiteSpace: 'nowrap',
                    }}>{periodLabel}</span>
                    <InputNumber min={1} style={{ flex: 1, borderRadius: '0 7px 7px 0' }}
                      placeholder="1" />
                  </Space.Compact>
                </Form.Item>
              )}
              {periodType === '专项' && (
                <div style={{ fontSize: 12, color: C.stone, padding: '6px 0 0' }}>
                  专项巡检无固定周期，需手动创建任务
                </div>
              )}
            </div>
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
            <span style={{ color: C.purple, fontWeight: 600 }}>「设备」</span>
            按钮配置巡检地点、设备和检查模板。
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

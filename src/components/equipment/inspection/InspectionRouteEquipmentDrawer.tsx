'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { App, Drawer, Select, InputNumber } from 'antd'
import {
  PlusOutlined, DeleteOutlined, EnvironmentOutlined,
  ToolOutlined, FileTextOutlined, DownOutlined, RightOutlined,
  HolderOutlined,
} from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { setRouteLocations } from '@/actions/equipment'
import { fetchInspectionRouteById } from '@/lib/api/inspection'
import type { RouteLocationItem } from '@/types/inspection'
import type { InspectionTemplate as InspectionTemplateType } from '@/types/equipment'

interface LocationOption { id: string; name: string; code: string }

interface Props {
  equipments: { id: string; name: string; equipment_no: string; location_id: string }[]
  locations: LocationOption[]
  templates: InspectionTemplateType[]
}

interface LocationRow {
  key: string; location_id: string; location_name?: string
  sort_order: number; equipments: EquipmentRow[]; collapsed?: boolean
}
interface EquipmentRow {
  key: string; equipment_id: string; equipment_name?: string
  equipment_no?: string; sort_order: number; template_ids: string[]
}

/* ═══════════════════════════════════════════════════════
   Design: Industrial-Editorial
   Inspired by factory inspection route sheets —
   numbered stations, equipment spec entries,
   navy-stamped headers with purple accents.
   ═══════════════════════════════════════════════════════ */

const C = {
  navy: '#0a1530',
  purple: '#5645d4',
  purpleDeep: '#3a2a99',
  purpleLight: '#e6e0f5',
  ink: '#1a1a1a',
  charcoal: '#37352f',
  slate: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
  muted: '#bbb8b1',
  hairline: '#e5e3df',
  hairlineSoft: '#ede9e4',
  surface: '#f6f5f4',
  surfaceSoft: '#fafaf9',
  canvas: '#ffffff',
  error: '#e03131',
  green: '#1aae39',
}

export function InspectionRouteEquipmentDrawer({ equipments, locations, templates }: Props) {
  const { message } = App.useApp()
  const { routeEquipmentDrawerOpen, editingRouteId, closeRouteEquipmentDrawer, triggerRoutesRefresh } = useInspectionStore()
  const [locationRows, setLocationRows] = useState<LocationRow[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  /* ── data ── */
  const loadData = useCallback(async () => {
    if (!editingRouteId) return
    setLoading(true)
    try {
      const detail = await fetchInspectionRouteById(editingRouteId)
      setLocationRows((detail.locations || []).map(loc => ({
        key: loc.id, location_id: loc.location_id,
        location_name: loc.location_name || undefined,
        sort_order: loc.sort_order, collapsed: false,
        equipments: (loc.equipments || []).map(eq => ({
          key: eq.id, equipment_id: eq.equipment_id,
          equipment_name: eq.equipment_name || undefined,
          equipment_no: eq.equipment_no || undefined,
          sort_order: eq.sort_order,
          template_ids: (eq.templates || []).map(t => t.template_id),
        })),
      })))
    } catch { message.error('加载路线配置失败') }
    finally { setLoading(false) }
  }, [editingRouteId, message])

  useEffect(() => { if (routeEquipmentDrawerOpen && editingRouteId) loadData() },
    [routeEquipmentDrawerOpen, editingRouteId, loadData])

  /* ── mutations ── */
  const toggle = (k: string) => setLocationRows(prev =>
    prev.map(r => r.key === k ? { ...r, collapsed: !r.collapsed } : r))

  const addLoc = () => {
    setLocationRows(prev => [...prev, {
      key: `new_loc_${Date.now()}`, location_id: '', sort_order: prev.length,
      equipments: [], collapsed: false,
    }])
    // scroll to bottom after render
    setTimeout(() => {
      listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
    }, 80)
  }
  const rmLoc = (k: string) => setLocationRows(prev => prev.filter(r => r.key !== k))
  const updLoc = (k: string, f: string, v: unknown) =>
    setLocationRows(prev => prev.map(r => r.key === k ? { ...r, [f]: v } : r))

  const addEq = (locKey: string) => setLocationRows(prev => prev.map(r => {
    if (r.key !== locKey) return r
    return { ...r, equipments: [...r.equipments, { key: `new_eq_${Date.now()}`, equipment_id: '', sort_order: r.equipments.length, template_ids: [] }] }
  }))
  const rmEq = (locKey: string, eqKey: string) => setLocationRows(prev => prev.map(r => {
    if (r.key !== locKey) return r
    return { ...r, equipments: r.equipments.filter(e => e.key !== eqKey) }
  }))
  const updEq = (locKey: string, eqKey: string, f: string, v: unknown) => setLocationRows(prev => prev.map(r => {
    if (r.key !== locKey) return r
    return { ...r, equipments: r.equipments.map(e => e.key === eqKey ? { ...e, [f]: v } : e) }
  }))

  /* ── save ── */
  const handleSave = async () => {
    if (!editingRouteId) return
    const items: RouteLocationItem[] = locationRows.map(loc => ({
      location_id: loc.location_id, sort_order: loc.sort_order,
      equipments: loc.equipments.filter(e => e.equipment_id).map(e => ({
        equipment_id: e.equipment_id, sort_order: e.sort_order, template_ids: e.template_ids,
      })),
    }))
    if (items.length === 0 || items.every(l => l.equipments.length === 0)) {
      message.warning('请至少配置一个地点且每个地点至少一台设备'); return
    }
    setSaving(true)
    const result = await setRouteLocations(editingRouteId, items)
    setSaving(false)
    if (!result.success) { message.error(result.error); return }
    message.success('路线配置已保存'); closeRouteEquipmentDrawer(); triggerRoutesRefresh()
  }

  /* ── helpers ── */
  const tplOptions = templates.map(t => ({ label: t.name, value: t.id }))
  const eqOptions = (locationId: string) => equipments
    .filter(e => e.location_id === locationId)
    .map(e => ({ label: `${e.name} (${e.equipment_no})`, value: e.id }))
  const locOptions = locations.map(l => ({ label: `${l.name} (${l.code})`, value: l.id }))

  return (
    <Drawer
      title={null}
      size={840}
      open={routeEquipmentDrawerOpen}
      onClose={closeRouteEquipmentDrawer}
      destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}
    >
      {/* ═══ HEADER ═══ */}
      <div style={{
        background: C.navy, padding: '18px 28px',
        borderBottom: `3px solid ${C.purple}`,
      }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>
          Inspection Route Configuration
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff', lineHeight: 1.3 }}>
          配置路线地点和设备
        </div>
      </div>

      {/* ═══ STATS BAR ═══ */}
      <div style={{
        margin: '0 24px', padding: '14px 20px',
        background: C.canvas, borderRadius: '0 0 12px 12px',
        border: `1px solid ${C.hairline}`, borderTop: 'none',
        display: 'flex', gap: 32,
      }}>
        <Stat label="地点数" value={locationRows.length} color={C.purple} />
        <Stat label="设备总数" value={locationRows.reduce((s, l) => s + l.equipments.length, 0)} color={C.navy} />
        <Stat label="模板绑定" value={
          new Set(locationRows.flatMap(l => l.equipments.flatMap(e => e.template_ids))).size
        } color={C.charcoal} />
      </div>

      {/* ═══ CONTENT ═══ */}
      <div ref={listRef} style={{ padding: '24px 24px 80px', overflow: 'auto', maxHeight: 'calc(100vh - 240px)' }}>
        {/* location cards */}
        {locationRows.map((loc, idx) => {
          const eqCount = loc.equipments.filter(e => e.equipment_id).length
          const tplCount = new Set(loc.equipments.flatMap(e => e.template_ids)).size

          return (
            <div key={loc.key} style={{
              marginBottom: 16,
              background: C.canvas, borderRadius: 12,
              border: `1px solid ${C.hairline}`,
              overflow: 'hidden',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}>
              {/* location header */}
              <div
                onClick={() => toggle(loc.key)}
                style={{
                  padding: '16px 20px', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 14,
                  background: loc.collapsed ? C.canvas : C.surfaceSoft,
                  borderBottom: loc.collapsed ? 'none' : `1px solid ${C.hairlineSoft}`,
                  transition: 'background 0.15s',
                }}
              >
                {/* station number */}
                <div style={{
                  width: 40, height: 40, borderRadius: 10,
                  background: loc.location_id ? C.purple : C.steel,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff', fontSize: 18, fontWeight: 700,
                  flexShrink: 0,
                  boxShadow: loc.location_id ? `0 3px 12px rgba(86,69,212,0.25)` : 'none',
                }}>
                  {idx + 1}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <EnvironmentOutlined style={{ color: loc.location_id ? C.purple : C.muted, fontSize: 14 }} />
                    <span style={{ fontSize: 15, fontWeight: 600, color: loc.location_id ? C.ink : C.muted }}>
                      {loc.location_name || '未选择地点'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 14, marginTop: 4 }}>
                    <span style={{ fontSize: 11, color: C.stone, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <ToolOutlined style={{ fontSize: 10 }} /> {eqCount} 台设备
                    </span>
                    <span style={{ fontSize: 11, color: C.stone, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <FileTextOutlined style={{ fontSize: 10 }} /> {tplCount} 个模板
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    onClick={e => { e.stopPropagation(); rmLoc(loc.key) }}
                    style={{
                      background: 'transparent', border: 'none', cursor: 'pointer',
                      color: C.error, fontSize: 16, padding: '4px 8px', borderRadius: 6,
                      lineHeight: 1,
                    }}
                    title="删除地点"
                  >
                    <DeleteOutlined />
                  </button>
                  {loc.collapsed ? <RightOutlined style={{ color: C.muted, fontSize: 12 }} /> : <DownOutlined style={{ color: C.muted, fontSize: 12 }} />}
                </div>
              </div>

              {/* location body */}
              {!loc.collapsed && (
                <div style={{ padding: '16px 20px 20px' }}>
                  {/* location selector row */}
                  <div style={{
                    display: 'flex', gap: 10, marginBottom: 18,
                    padding: '12px 14px', background: C.surfaceSoft,
                    borderRadius: 8, border: `1px solid ${C.hairlineSoft}`,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: C.stone, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        地点选择
                      </div>
                      <Select
                        showSearch={{ optionFilterProp: 'label' }} size="small" style={{ width: '100%' }}
                        placeholder="选择巡检地点"
                        value={loc.location_id || undefined}
                        onChange={(v) => {
                          const l = locations.find(lo => lo.id === v)
                          updLoc(loc.key, 'location_id', v)
                          updLoc(loc.key, 'location_name', l?.name)
                        }}
                        options={locOptions}
                      />
                    </div>
                    <div style={{ width: 80 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: C.stone, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                        巡检顺序
                      </div>
                      <InputNumber
                        size="small" min={0} style={{ width: '100%' }}
                        value={loc.sort_order}
                        onChange={v => updLoc(loc.key, 'sort_order', v || 0)}
                      />
                    </div>
                  </div>

                  {/* equipment list */}
                  <div style={{
                    fontSize: 11, fontWeight: 600, color: C.steel,
                    textTransform: 'uppercase', letterSpacing: 0.8,
                    marginBottom: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  }}>
                    <span>设备列表 · {eqCount} 台</span>
                    <button
                      onClick={() => addEq(loc.key)}
                      style={{
                        background: 'transparent', border: 'none', cursor: 'pointer',
                        color: C.purple, fontSize: 12, fontWeight: 600, fontFamily: 'inherit',
                        display: 'flex', alignItems: 'center', gap: 4,
                      }}
                    >
                      <PlusOutlined style={{ fontSize: 10 }} /> 添加设备
                    </button>
                  </div>

                  {loc.equipments.map((eq, ei) => (
                    <div key={eq.key} style={{
                      marginBottom: 8,
                      background: C.surfaceSoft, borderRadius: 8,
                      border: `1px solid ${eq.equipment_id ? C.hairline : '#e03131'}`,
                      overflow: 'hidden',
                    }}>
                      {/* equipment row */}
                      <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
                        {/* drag handle hint */}
                        <HolderOutlined style={{ color: C.muted, fontSize: 13, flexShrink: 0 }} />

                        {/* equipment number */}
                        <div style={{
                          minWidth: 24, height: 24, borderRadius: 6,
                          background: eq.equipment_id ? C.purpleLight : '#ffe8d4',
                          color: eq.equipment_id ? C.purpleDeep : C.slate,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 11, fontWeight: 700,
                        }}>
                          {ei + 1}
                        </div>

                        {/* equipment select */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <Select
                            showSearch={{ optionFilterProp: 'label' }} size="small" style={{ width: '100%' }}
                            placeholder="选择设备"
                            value={eq.equipment_id || undefined}
                            onChange={(v) => {
                              const e = equipments.find(ee => ee.id === v)
                              updEq(loc.key, eq.key, 'equipment_id', v)
                              updEq(loc.key, eq.key, 'equipment_name', e?.name)
                              updEq(loc.key, eq.key, 'equipment_no', e?.equipment_no)
                            }}
                            options={eqOptions(loc.location_id)}
                          />
                          {eq.equipment_name && (
                            <div style={{ fontSize: 11, color: C.stone, marginTop: 2, paddingLeft: 2 }}>
                              {eq.equipment_name} · {eq.equipment_no}
                            </div>
                          )}
                        </div>

                        {/* sort */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span style={{ fontSize: 10, color: C.stone, fontWeight: 500 }}>顺序</span>
                          <InputNumber
                            size="small" min={0} style={{ width: 52 }}
                            value={eq.sort_order}
                            onChange={v => updEq(loc.key, eq.key, 'sort_order', v || 0)}
                          />
                        </div>

                        {/* remove */}
                        <button
                          onClick={() => rmEq(loc.key, eq.key)}
                          style={{
                            background: 'transparent', border: 'none', cursor: 'pointer',
                            color: C.error, fontSize: 14, padding: 2, lineHeight: 1, borderRadius: 4,
                          }}
                        >
                          <DeleteOutlined />
                        </button>
                      </div>

                      {/* template row */}
                      <div style={{
                        padding: '8px 14px 12px 52px',
                        borderTop: `1px solid ${C.hairlineSoft}`,
                      }}>
                        <Select
                          mode="multiple" size="small" style={{ width: '100%' }}
                          placeholder="绑定巡检模板（可多选，合并检查项）"
                          value={eq.template_ids}
                          onChange={v => updEq(loc.key, eq.key, 'template_ids', v)}
                          showSearch={{ optionFilterProp: 'label' }} options={tplOptions}
                        />
                      </div>
                    </div>
                  ))}

                  {loc.equipments.length === 0 && (
                    <div style={{
                      padding: '24px 0', textAlign: 'center',
                      color: C.muted, fontSize: 13, border: `2px dashed ${C.hairlineSoft}`,
                      borderRadius: 8,
                    }}>
                      此地点暂无设备 — 点击上方「添加设备」开始配置
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {locationRows.length === 0 && (
          <div style={{
            padding: '48px 0', textAlign: 'center',
            color: C.muted, fontSize: 14,
          }}>
            尚未配置巡检地点 — 点击底部按钮添加第一个巡检地点
          </div>
        )}
      </div>

      {/* ═══ STICKY FOOTER ═══ */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0,
        padding: '14px 24px',
        background: C.canvas,
        borderTop: `1px solid ${C.hairline}`,
        display: 'flex', gap: 10,
        boxShadow: '0 -4px 16px rgba(0,0,0,0.06)',
      }}>
        <button
          onClick={addLoc}
          style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            background: C.canvas, border: `2px dashed ${C.purple}`,
            borderRadius: 8, padding: '10px 0', cursor: 'pointer',
            fontFamily: 'inherit', fontSize: 13, fontWeight: 600, color: C.purple,
            transition: 'all 0.15s',
          }}
        >
          <PlusOutlined /> 添加巡检地点
        </button>
        <button
          onClick={closeRouteEquipmentDrawer}
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
          onClick={handleSave} disabled={saving}
          style={{
            padding: '10px 28px',
            background: C.purple, color: '#fff', border: 'none',
            borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            fontFamily: 'inherit',
            opacity: saving ? 0.7 : 1,
            boxShadow: `0 2px 8px rgba(86,69,212,0.3)`,
          }}
        >
          {saving ? '保存中...' : '保存配置'}
        </button>
      </div>
    </Drawer>
  )
}

/* ── stats sub-component ── */
function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
      <span style={{ fontSize: 11, fontWeight: 500, color: '#787671', textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </span>
      <span style={{ fontSize: 20, fontWeight: 700, color, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </span>
    </div>
  )
}

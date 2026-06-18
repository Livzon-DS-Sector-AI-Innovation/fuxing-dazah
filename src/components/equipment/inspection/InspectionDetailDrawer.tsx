'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { App, Drawer, Image, Typography } from 'antd'
import { ClockCircleOutlined, EnvironmentOutlined, CheckCircleOutlined, ExclamationCircleOutlined, CameraOutlined, FileTextOutlined } from '@ant-design/icons'
import { useInspectionStore } from '@/stores/inspection'
import { fetchInspectionHistoryDetail, getInspectionPhotoUrl } from '@/lib/api/inspection'
import type { InspectionTaskDetail, InspectionRecord } from '@/types/inspection'
import dayjs from 'dayjs'

const { Text } = Typography

const C = { navy: '#0a1530', purple: '#5645d4', ink: '#1a1a1a', charcoal: '#37352f', slate: '#5d5b54', steel: '#787671', stone: '#a4a097', muted: '#bbb8b1', hairline: '#e5e3df', hairlineSoft: '#ede9e4', surface: '#f6f5f4', surfaceSoft: '#fafaf9', canvas: '#ffffff', green: '#1aae39', error: '#e03131', lavender: '#e6e0f5' }

function groupByEquipment(records: InspectionRecord[]): Map<string, InspectionRecord[]> {
  const m = new Map<string, InspectionRecord[]>()
  for (const r of records) { const k = r.equipment_id || '__no__'; if (!m.has(k)) m.set(k, []); m.get(k)!.push(r) }
  return m
}

export function InspectionDetailDrawer() {
  const { message } = App.useApp()
  const { historyDetailOpen, detailTaskId, closeHistoryDetail } = useInspectionStore()
  const [detail, setDetail] = useState<InspectionTaskDetail | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!detailTaskId) return; setLoading(true)
    try { setDetail(await fetchInspectionHistoryDetail(detailTaskId)) }
    catch { message.error('加载详情失败') }
    finally { setLoading(false) }
  }, [detailTaskId, message])

  useEffect(() => { if (historyDetailOpen && detailTaskId) load() }, [historyDetailOpen, detailTaskId, load])

  const recordGroups = useMemo(() => {
    if (!detail?.records?.length) return []
    return Array.from(groupByEquipment(detail.records).entries()).map(([eid, recs]) => ({
      equipmentId: eid, equipmentName: recs[0]?.equipment_name || eid.slice(0, 8) + '…', records: recs,
    }))
  }, [detail])

  const resultBadge = (r: string) => {
    const ok = r === '正常'
    return { bg: ok ? '#d9f3e1' : '#fde0ec', color: ok ? C.green : C.error, icon: ok ? <CheckCircleOutlined /> : <ExclamationCircleOutlined /> }
  }

  return (
    <Drawer title={null} size={780} open={historyDetailOpen} onClose={closeHistoryDetail} destroyOnHidden
      styles={{ body: { padding: 0, background: C.surface } }}>
      {/* header */}
      <div style={{ background: C.navy, padding: '18px 28px', borderBottom: `3px solid ${C.purple}` }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 2, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', marginBottom: 2 }}>Inspection Record</div>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#fff', display: 'flex', alignItems: 'center', gap: 10 }}>
          巡检详情
          {detail && (
            <span style={{ padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600,
              background: detail.overall_result === '正常' ? 'rgba(26,174,57,0.2)' : 'rgba(224,49,49,0.2)',
              color: detail.overall_result === '正常' ? C.green : C.error }}>
              {detail.overall_result || detail.status}
            </span>
          )}
        </div>
      </div>

      {loading && <Text type="secondary" style={{ padding: 32, display: 'block', textAlign: 'center' }}>加载中...</Text>}
      {!loading && !detail && <Text type="secondary" style={{ padding: 32, display: 'block', textAlign: 'center' }}>无数据</Text>}

      {!loading && detail && (
        <div style={{ padding: '20px 28px 40px' }}>
          {/* metadata card */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12, marginBottom: 24 }}>
            <Meta label="任务编号" value={detail.task_no} />
            <Meta label="巡检类型" value={detail.plan_type} />
            <Meta label="路线/设备" value={detail.route_name || detail.equipment_name || '-'} />
            <Meta label="巡检人员" value={detail.assignee_name || '-'} />
            <Meta label="计划时间" value={detail.planned_time ? dayjs(detail.planned_time).format('YYYY-MM-DD HH:mm') : '-'} icon={<ClockCircleOutlined />} />
            <Meta label="开始时间" value={detail.started_at ? dayjs(detail.started_at).format('YYYY-MM-DD HH:mm') : '-'} />
            <Meta label="完成时间" value={detail.completed_at ? dayjs(detail.completed_at).format('YYYY-MM-DD HH:mm') : '-'} />
            <Meta label="状态" value={detail.status} />
          </div>

          {/* route summary */}
          {detail.route_summary && (
            <div style={{ padding: '14px 18px', marginBottom: 24, background: C.surfaceSoft, borderRadius: 10, border: `1px solid ${C.hairlineSoft}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <FileTextOutlined style={{ color: C.purple }} />
                <span style={{ fontSize: 13, fontWeight: 600, color: C.charcoal }}>现场描述</span>
              </div>
              <Text style={{ fontSize: 13, color: C.slate, whiteSpace: 'pre-wrap' }}>{detail.route_summary}</Text>
            </div>
          )}

          {/* photos */}
          {detail.photos && detail.photos.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <CameraOutlined style={{ color: C.purple }} />
                <span style={{ fontSize: 13, fontWeight: 600, color: C.charcoal }}>到位照片 · {detail.photos.length} 张</span>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {detail.photos.map(p => (
                  <Image key={p.id} src={getInspectionPhotoUrl(p.id)} alt={p.file_name}
                    width={120} height={120} style={{ objectFit: 'cover', borderRadius: 8, border: `1px solid ${C.hairline}` }}
                    fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTIwIiBoZWlnaHQ9IjEyMCIgZmlsbD0iI2YwZWVlYyIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0ibWlkZGxlIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjYTRhMDk3IiBmb250LXNpemU9IjEyIj7lm77niYflpLHotKU8L3RleHQ+PC9zdmc+" />
                ))}
              </div>
            </div>
          )}

          {/* records by equipment */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: C.charcoal }}>检查记录</span>
              <span style={{ fontSize: 11, color: C.stone, fontWeight: 500 }}>({detail.records?.length || 0} 项)</span>
            </div>

            {recordGroups.length === 0 && (
              <div style={{ padding: '24px 0', textAlign: 'center', color: C.muted, fontSize: 13 }}>
                {detail.plan_type === '线路巡检' ? '线路巡检模式，无逐设备检查记录' : '无记录'}
              </div>
            )}

            {recordGroups.map((group, gi) => (
              <div key={group.equipmentId} style={{ marginBottom: gi < recordGroups.length - 1 ? 20 : 0 }}>
                {/* equipment header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, padding: '0 4px' }}>
                  <div style={{ width: 28, height: 28, borderRadius: 8, background: C.navy, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{gi + 1}</div>
                  <EnvironmentOutlined style={{ color: C.purple, fontSize: 13 }} />
                  <span style={{ fontWeight: 600, fontSize: 14, color: C.ink }}>{group.equipmentName}</span>
                  <span style={{ fontSize: 11, color: C.stone }}>{group.records.length} 项</span>
                </div>

                {/* record rows */}
                <div style={{ borderRadius: 10, overflow: 'hidden', border: `1px solid ${C.hairlineSoft}`, background: C.canvas }}>
                  {group.records.map((rec, ri) => {
                    const b = resultBadge(rec.result)
                    return (
                      <div key={rec.id} style={{
                        padding: '12px 16px',
                        borderBottom: ri < group.records.length - 1 ? `1px solid ${C.hairlineSoft}` : 'none',
                        background: ri % 2 === 0 ? C.canvas : C.surfaceSoft,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                              <span style={{ fontWeight: 600, fontSize: 13, color: C.ink }}>{rec.item_name || '检查项'}</span>
                              <span style={{ padding: '1px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600, background: b.bg, color: b.color, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                                {b.icon}{rec.result}
                              </span>
                            </div>
                            {rec.expected_result && <div style={{ fontSize: 12, color: C.stone, marginBottom: 2 }}>预期标准：{rec.expected_result}</div>}
                            <div style={{ display: 'flex', gap: 16, marginTop: 4, fontSize: 12 }}>
                              {rec.actual_value && <span style={{ color: C.charcoal }}>实测：<strong>{rec.actual_value}</strong></span>}
                              {rec.remark && <span style={{ color: C.steel }}>备注：{rec.remark}</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Drawer>
  )
}

function Meta({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div style={{ padding: '10px 14px', background: C.canvas, borderRadius: 8, border: `1px solid ${C.hairlineSoft}` }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: C.stone, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 500, color: C.ink, display: 'flex', alignItems: 'center', gap: 4 }}>
        {icon}{value}
      </div>
    </div>
  )
}

'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Drawer, Segmented, Spin, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import { PageHeader } from './PageHeader'
import { SectionCard } from './ui/SectionCard'
import { StatusTag } from './ui/StatusTag'
import type { Tone } from './ui/tokens'

const BASE = '/api/v1/warehouse'

interface LocationMapItem {
  id: string
  code: string
  name: string
  zone: string
  aisle: string
  location_type: string
  occupied_rows: number
  total_qty: number
}

type OccupancyLevel = 'idle' | 'low' | 'mid' | 'high'

function occupancyLevel(occupied: number): OccupancyLevel {
  if (occupied === 0) return 'idle'
  if (occupied <= 2) return 'low'
  if (occupied <= 5) return 'mid'
  return 'high'
}

const LEVEL_META: Record<OccupancyLevel, { label: string; tone: Tone }> = {
  idle: { label: '空闲', tone: 'default' },
  low: { label: '低占用', tone: 'ok' },
  mid: { label: '中占用', tone: 'warn' },
  high: { label: '高占用', tone: 'danger' },
}

/** 库位格子：占用语义底色 + 编码/数量，点击弹详情 */
function LocationCell({ loc, onPick }: { loc: LocationMapItem; onPick: (loc: LocationMapItem) => void }) {
  const level = occupancyLevel(loc.occupied_rows)
  const toneBg: Record<OccupancyLevel, string> = {
    idle: 'var(--color-surface)',
    low: 'var(--wh-ok-bg)',
    mid: 'var(--wh-warn-bg)',
    high: 'var(--wh-danger-bg)',
  }
  return (
    <button
      type="button"
      onClick={() => onPick(loc)}
      className="cursor-pointer rounded-lg border border-[var(--color-hairline)] px-1.5 py-2 text-center transition-shadow hover:shadow-md"
      style={{ background: toneBg[level] }}
      title={`${loc.code} ${loc.name} · ${LEVEL_META[level].label}`}
    >
      <div className="truncate text-[12px] font-semibold text-[var(--color-charcoal)]">{loc.code}</div>
      <div className="text-[11px] tabular-nums text-[var(--color-steel)]">{loc.total_qty}</div>
    </button>
  )
}

export function LocationMap() {
  const [selectedZone, setSelectedZone] = useState<string | null>(null)
  const [selectedLoc, setSelectedLoc] = useState<LocationMapItem | null>(null)

  const { data: map, isLoading } = useQuery({
    queryKey: ['warehouse', 'locations', 'map'],
    queryFn: async () => {
      const resp = await fetch(`${BASE}/locations/map`)
      const body = await resp.json()
      return body.data as LocationMapItem[]
    },
  })

  if (isLoading || !map) return <Spin className="block w-full text-center" />

  const zoneLabel = (z: string) => (z && z !== '-' ? z : '未分区')
  const zones = [...new Set(map.map(l => l.zone))].sort()
  const activeZone = selectedZone ?? zones[0] ?? ''
  const zoneItems = map.filter(l => l.zone === activeZone)
  const aisles = [...new Set(zoneItems.map(l => l.aisle))].sort()
  const occupiedCount = zoneItems.filter(l => l.occupied_rows > 0).length
  const occupancyRate = zoneItems.length > 0 ? Math.round((occupiedCount / zoneItems.length) * 100) : 0

  return (
    <div>
      <PageHeader
        breadcrumb={['仓储管理', '库位地图']}
        title="库位地图"
        description="按库区/巷道可视化查看占用情况"
        actions={
          <Segmented
            value={activeZone}
            onChange={value => setSelectedZone(value as string)}
            options={zones.map(z => ({ value: z, label: zoneLabel(z) }))}
          />
        }
      />

      <SectionCard
        title={`库区：${zoneLabel(activeZone)}`}
        description={`${zoneItems.length} 个库位 · ${occupiedCount} 个有货 · 占用率 ${occupancyRate}%`}
        action={
          <div className="flex items-center gap-3">
            {(Object.keys(LEVEL_META) as OccupancyLevel[]).map(level => (
              <span key={level} className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-steel)]">
                <span
                  aria-hidden
                  className="h-2.5 w-2.5 rounded-full border border-[var(--color-hairline)]"
                  style={{
                    background:
                      level === 'idle'
                        ? 'var(--color-surface)'
                        : level === 'low'
                          ? 'var(--wh-ok-bg)'
                          : level === 'mid'
                            ? 'var(--wh-warn-bg)'
                            : 'var(--wh-danger-bg)',
                  }}
                />
                {LEVEL_META[level].label}
              </span>
            ))}
          </div>
        }
      >
        {zoneItems.length === 0 ? (
          <div className="py-10 text-center text-[13px] text-[var(--color-stone)]">该库区暂无库位</div>
        ) : (
          <div className="flex flex-col gap-6">
            {aisles.map(aisle => (
              <section key={aisle}>
                <div className="mb-2 text-[13px] font-medium text-[var(--color-slate)]">
                  巷道 {aisle && aisle !== '-' ? aisle : '未分配'}
                  <span className="ml-2 text-[12px] font-normal text-[var(--color-stone)]">
                    {zoneItems.filter(l => l.aisle === aisle).length} 位
                  </span>
                </div>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2">
                  {zoneItems
                    .filter(l => l.aisle === aisle)
                    .map(loc => (
                      <LocationCell key={loc.id} loc={loc} onPick={setSelectedLoc} />
                    ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </SectionCard>

      {selectedLoc && (
        <Drawer
          title={`库位 ${selectedLoc.code} ${selectedLoc.name}`}
          open
          width={480}
          onClose={() => setSelectedLoc(null)}
          destroyOnHidden
        >
          <div className="mb-3 flex items-center gap-2">
            <StatusTag
              tone={LEVEL_META[occupancyLevel(selectedLoc.occupied_rows)].tone}
              label={LEVEL_META[occupancyLevel(selectedLoc.occupied_rows)].label}
            />
            <span className="text-[13px] text-[var(--color-steel)]">
              占用 {selectedLoc.occupied_rows} 行 · 库存 {selectedLoc.total_qty}
            </span>
          </div>
          <LocationDetailTable locationId={selectedLoc.id} />
        </Drawer>
      )}
    </div>
  )
}

function LocationDetailTable({ locationId }: { locationId: string }) {
  const { data: res } = useQuery({
    queryKey: ['warehouse', 'stocks', { location: locationId }],
    queryFn: async () => {
      const resp = await fetch(`/api/v1/warehouse/stocks?location_id=${locationId}&page_size=100`)
      const body = await resp.json()
      return body.data as { id: string; material_code: string; material_name: string; batch_no: string; quantity: number; unit: string }[]
    },
  })
  const columns: TableColumnsType<NonNullable<typeof res>[0]> = [
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '批次', dataIndex: 'batch_no', width: 80, render: (v: string) => v || '-' },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
  ]
  return <Table rowKey="id" size="small" columns={columns} dataSource={res ?? []} pagination={false} />
}

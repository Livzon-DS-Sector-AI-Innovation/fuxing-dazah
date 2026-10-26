'use client'

/**
 * 厂区风险分区 · 当日分布图卡（3.x 平台关联 F2）。
 *
 * 底图：64 分区轮廓静态资产（src/data/tiji-risk-districts.json，经纬度坐标，
 * 一次性快照），SVG 直绘无地图库——经纬差投影到 viewBox（纬度按 cos(25.46°)
 * 纠正 N-S 比例，y 轴翻转北上）；浅灰填充 + hover 名称。
 * 落点：当日作业票（动火红/受限橙/其他蓝）+ 今日消防/中控报警（黄），
 * 多票计数徽标挂分区质心；点击分区出当日明细 Modal。
 * 底部「未映射 N 处」可展开清单（纯展示，AI 建议入口另议）。
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Modal, Spin, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import { MapPinned } from 'lucide-react'
import { EmptyGuide, SectionCard } from '@/components/ui-kit'
import {
  fetchFacilityMapPins,
  type FacilityMapDistrictPin,
  type FacilityMapPinRef,
} from '@/lib/api/safety/facility-map'
import asset from '@/data/tiji-risk-districts.json'

interface RailAsset {
  name: string
  polygon: number[][]
}

interface DistrictAsset {
  distId: string
  distName: string
  riskLevel: number | null
  riskLevelDesc: string
  rails: RailAsset[]
}

const DISTRICTS: DistrictAsset[] = asset.districts

// ── 投影：经纬差 → viewBox（模块级一次计算）──────────────────────────
const VIEW_W = 1000
// 厂区纬度 ~25.46°N，cos 纠正纬度跨度后 N-S 比例接近真实
const LAT_SCALE = Math.cos((25.46 * Math.PI) / 180)

const GEOM = (() => {
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const d of DISTRICTS) {
    for (const r of d.rails) {
      for (const [x, y] of r.polygon) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }
  const spanX = Math.max(maxX - minX, 1e-9)
  const spanY = Math.max(maxY - minY, 1e-9)
  const viewH = (VIEW_W * spanY * LAT_SCALE) / spanX
  return {
    viewH,
    /** 经纬度 → viewBox 坐标（y 翻转北上） */
    project(lng: number, lat: number): [number, number] {
      return [
        ((lng - minX) / spanX) * VIEW_W,
        viewH - ((lat - minY) / spanY) * viewH * LAT_SCALE,
      ]
    },
  }
})()

interface RenderedDistrict {
  dist: DistrictAsset
  /** 每 rail 的 points 串（预投影） */
  shapes: string[]
  /** 徽标挂点：最大 rail 的 bbox 中心 */
  anchor: [number, number]
}

const RENDERED: RenderedDistrict[] = (() => {
  const out: RenderedDistrict[] = []
  for (const dist of DISTRICTS) {
    const shapes: string[] = []
    let best: { area: number; anchor: [number, number] } | null = null
    for (const rail of dist.rails) {
      if (rail.polygon.length < 3) continue
      let sx = Infinity
      let bx = -Infinity
      let sy = Infinity
      let by = -Infinity
      const pts: string[] = []
      for (const [lng, lat] of rail.polygon) {
        const [x, y] = GEOM.project(lng, lat)
        pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
        if (x < sx) sx = x
        if (x > bx) bx = x
        if (y < sy) sy = y
        if (y > by) by = y
      }
      shapes.push(pts.join(' '))
      const area = (bx - sx) * (by - sy)
      if (!best || area > best.area) {
        best = { area, anchor: [(sx + bx) / 2, (sy + by) / 2] }
      }
    }
    if (!shapes.length) continue
    out.push({ dist, shapes, anchor: best!.anchor })
  }
  return out
})()

const BY_DIST_ID = new Map(RENDERED.map(r => [r.dist.distId, r]))

// 徽标色（动火红/受限橙/其他蓝/报警黄）
const BADGES = [
  { key: 'hot', label: '火', fill: '#d92d20' },
  { key: 'confined', label: '受', fill: '#f79009' },
  { key: 'other', label: '其', fill: '#2e90fa' },
] as const

const ALARM_FILL = '#f2c94c'
const ALARM_STROKE = '#b5860a'

const KIND_LABEL: Record<string, string> = {
  job: '作业票',
  fire: '消防报警',
  central: '中控报警',
}

const TICKET_TYPE_LABEL: Record<string, string> = {
  hot_work: '动火',
  confined_space: '受限',
  height_work: '高处',
  lifting: '吊装',
  temporary_electricity: '临电',
  excavation: '动土',
  road_breaking: '断路',
  blind_plate: '盲板',
}

/** 徽标组：作业桶（非零）+ 报警合计，横向串排 */
function BadgeGroup({ pin, anchor }: { pin: FacilityMapDistrictPin; anchor: [number, number] }) {
  const alarms = pin.alarms.fire + pin.alarms.central
  const chips: { label: string; fill: string }[] = []
  for (const b of BADGES) {
    const n = pin.jobs[b.key]
    if (n > 0) chips.push({ label: `${b.label}${n}`, fill: b.fill })
  }
  if (alarms > 0) chips.push({ label: `警${alarms}`, fill: ALARM_FILL })
  if (!chips.length) return null
  const [cx, cy] = anchor
  const w = 34
  const total = chips.length * w
  return (
    <g data-testid={`district-badge-${pin.dist_id}`} pointerEvents="none">
      {chips.map((chip, i) => (
        <g key={chip.label} transform={`translate(${cx - total / 2 + i * w}, ${cy - 10})`}>
          <rect width={w - 4} height={20} rx={10} fill="#fff" stroke={chip.fill} strokeWidth={1.5} />
          <text
            x={(w - 4) / 2}
            y={14}
            textAnchor="middle"
            fontSize={12}
            fontWeight={600}
            fill={chip.fill === ALARM_FILL ? ALARM_STROKE : chip.fill}
          >
            {chip.label}
          </text>
        </g>
      ))}
    </g>
  )
}

const JOB_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  {
    title: '类型',
    dataIndex: 'ticket_type',
    width: 70,
    render: (v: string | null) => (v ? TICKET_TYPE_LABEL[v] ?? v : '—'),
  },
  { title: '票号', dataIndex: 'ticket_no', width: 150 },
  { title: '作业地点', dataIndex: 'work_site', width: 160, render: (v: string | null) => v || '—' },
  { title: '作业内容', dataIndex: 'work_content', ellipsis: true },
]

const ALARM_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  {
    title: '来源',
    dataIndex: 'kind',
    width: 80,
    render: (v: string) => KIND_LABEL[v] ?? v,
  },
  {
    title: '时间',
    width: 90,
    render: (_, r) => (r.kind === 'fire' ? r.alarm_time?.slice(5, 16) : r.alarm_date) || '—',
  },
  {
    title: '类型/描述',
    render: (_, r) =>
      r.kind === 'fire'
        ? `${r.alarm_type ?? '报警'} · ${r.location ?? ''}`
        : `${r.workshop ?? ''} ${r.alarm_description ?? ''}`,
  },
]

function DistrictModal({
  pin,
  distName,
  date,
  onClose,
}: {
  pin: FacilityMapDistrictPin | null
  distName: string
  date: string
  onClose: () => void
}) {
  const jobs = pin?.refs.filter(r => r.kind === 'job') ?? []
  const alarms = pin?.refs.filter(r => r.kind !== 'job') ?? []
  return (
    <Modal
      open={pin !== null}
      title={pin ? `${distName} · ${date} 当日明细` : ''}
      footer={null}
      width={760}
      onCancel={onClose}
    >
      {pin && (
        <div className="flex flex-col gap-4 pt-2">
          <div>
            <div className="mb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
              特殊作业票 {jobs.length} 张{pin.truncated ? '（明细超 50 条已截断，计数完整）' : ''}
            </div>
            <Table
              rowKey={(_, i) => `j${i}`}
              size="small"
              columns={JOB_COLUMNS}
              dataSource={jobs}
              pagination={false}
              locale={{ emptyText: '本分区当日无作业票' }}
            />
          </div>
          <div>
            <div className="mb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
              今日报警 {alarms.length} 条
            </div>
            <Table
              rowKey={(_, i) => `a${i}`}
              size="small"
              columns={ALARM_COLUMNS}
              dataSource={alarms}
              pagination={false}
              locale={{ emptyText: '本分区今日无报警' }}
            />
          </div>
        </div>
      )}
    </Modal>
  )
}

export function FacilityMapCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['safety', 'facility-map-pins'],
    queryFn: fetchFacilityMapPins,
  })
  const [openDist, setOpenDist] = useState<FacilityMapDistrictPin | null>(null)
  const [showUnmapped, setShowUnmapped] = useState(false)

  const pinById = useMemo(
    () => new Map((data?.pins ?? []).map(p => [p.dist_id, p])),
    [data],
  )
  const unmappedEvents = useMemo(
    () => (data?.unmapped ?? []).reduce((n, u) => n + u.count, 0),
    [data],
  )

  return (
    <SectionCard
      title="厂区风险分区 · 当日分布"
      description={`64 分区底图（3.x 平台快照）· ${data?.date ?? '—'} 特殊作业票与消防/中控报警落点，点击分区看明细`}
      action={
        <div className="flex items-center gap-2 text-[11px] text-[var(--color-steel)]">
          {BADGES.map(b => (
            <span key={b.key} className="inline-flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: b.fill }}
              />
              {b.label === '火' ? '动火' : b.label === '受' ? '受限' : '其他作业'}
            </span>
          ))}
          <span className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: ALARM_FILL, border: `1px solid ${ALARM_STROKE}` }}
            />
            报警
          </span>
        </div>
      }
    >
      {isError ? (
        <EmptyGuide
          compact
          icon={<MapPinned size={18} />}
          title="分区数据暂时不可用"
          description="落点数据拉取失败（平台或表格抖动），稍后自动恢复；分区底图不受影响"
        />
      ) : isLoading || !data ? (
        <div className="flex h-[380px] items-center justify-center">
          <Spin />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {data.errors.length > 0 && (
            <div className="rounded-md bg-[var(--wh-warn-bg)] px-3 py-1.5 text-[12px] text-[var(--wh-warn)]">
              部分数据源降级：{data.errors.join('；')}
            </div>
          )}
          <svg
            viewBox={`0 0 ${VIEW_W} ${GEOM.viewH.toFixed(1)}`}
            className="h-auto w-full"
            style={{ maxHeight: 460 }}
            role="img"
            aria-label="厂区风险分区底图"
          >
            {RENDERED.map(({ dist, shapes }) => {
              const pin = pinById.get(dist.distId)
              return (
                <g
                  key={dist.distId}
                  data-testid={`district-poly-${dist.distId}`}
                  className="cursor-pointer [&:hover_polygon]:fill-[#ded9d0]"
                  onClick={() =>
                    setOpenDist(
                      pin ?? {
                        dist_id: dist.distId,
                        jobs: { hot: 0, confined: 0, other: 0 },
                        alarms: { fire: 0, central: 0 },
                        refs: [],
                        truncated: false,
                      },
                    )
                  }
                >
                  <title>{`${dist.distName}${pin ? ` · 作业 ${pin.jobs.hot + pin.jobs.confined + pin.jobs.other} / 报警 ${pin.alarms.fire + pin.alarms.central}` : ''}`}</title>
                  {shapes.map((points, i) => (
                    <polygon
                      key={i}
                      points={points}
                      fill={pin ? '#e8e4dd' : '#f0eeea'}
                      stroke={pin ? '#9c948a' : '#d8d4cd'}
                      strokeWidth={1}
                    />
                  ))}
                </g>
              )
            })}
            {data.pins.map(pin => {
              const rendered = BY_DIST_ID.get(pin.dist_id)
              if (!rendered) return null
              return <BadgeGroup key={pin.dist_id} pin={pin} anchor={rendered.anchor} />
            })}
          </svg>
          <div className="flex items-start justify-between gap-3 border-t border-[var(--color-hairline-soft)] pt-2 text-[12px] text-[var(--color-steel)]">
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-[var(--color-surface)]"
              onClick={() => setShowUnmapped(v => !v)}
            >
              未映射 {data.unmapped.length} 处（{unmappedEvents} 条事件）
              <span className="text-[10px]">{showUnmapped ? '▲' : '▼'}</span>
            </button>
            <span>未映射=地点文本未能对应分区（映射底座只读，补充映射另行处理）</span>
          </div>
          {showUnmapped && (
            <div className="flex max-h-32 flex-col gap-1 overflow-y-auto rounded-md bg-[var(--color-surface)] px-3 py-2">
              {data.unmapped.map(u => (
                <div key={u.text} className="flex items-center justify-between gap-2 text-[12px]">
                  <span className="truncate text-[var(--color-charcoal)]">{u.text}</span>
                  <span className="flex shrink-0 items-center gap-1">
                    {u.kinds.map(k => (
                      <Tag key={k} className="m-0" style={{ fontSize: 10, lineHeight: '16px' }}>
                        {KIND_LABEL[k] ?? k}
                      </Tag>
                    ))}
                    <span>×{u.count}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <DistrictModal
        pin={openDist}
        distName={openDist ? BY_DIST_ID.get(openDist.dist_id)?.dist.distName ?? openDist.dist_id : ''}
        date={data?.date ?? ''}
        onClose={() => setOpenDist(null)}
      />
    </SectionCard>
  )
}

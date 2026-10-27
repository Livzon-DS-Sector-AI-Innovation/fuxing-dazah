'use client'

/**
 * 厂区风险分区 · 当日分布图卡（3.x 平台关联 F2）。
 *
 * 底图：64 分区轮廓静态资产（src/data/tiji-risk-districts.json，经纬度坐标，
 * 一次性快照），SVG 直绘无地图库——经纬差投影到 viewBox（纬度按 cos(25.46°)
 * 纠正 N-S 比例，y 轴翻转北上）；当日有落点的分区淡靛底色强调，其余暖灰。
 * 交互：滚轮/触控板缩放（以光标为锚）+ 拖动平移（viewBox 实现，拖动后不触发
 * 分区点击）+ 右上角放大/缩小/重置按钮；徽标与名称标注按 1/zoom 缩放保持
 * 屏幕等大，名称标注随放大逐级显现（放得下才显示）。
 * 落点：当日作业票（动火红/受限橙/其他蓝）+ 今日消防/中控报警（黄），
 * 多票计数徽标挂分区质心；点击分区出当日明细 Modal。
 * 布局：svg 按底图宽高比自适应居中（不留横向空白）；名称标注贪心避让
 * （标签×标签、标签×徽标矩形相交即跳过，相邻重叠分区不全画）；底部
 * 「未映射」栏清单直出 + AI 建议确认入口（#2）。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Modal, Spin, Table, Tag, message } from 'antd'
import type { TableColumnsType } from 'antd'
import { MapPinned, Maximize, Minus, Plus } from 'lucide-react'
import { EmptyGuide, SectionCard } from '@/components/ui-kit'
import {
  fetchDistrictSuggestions,
  fetchFacilityMapPins,
  confirmDistrictSuggestion,
  confirmHighDistrictSuggestions,
  ignoreDistrictSuggestion,
  scanDistrictSuggestions,
  type DistrictSuggestionRow,
  type FacilityMapDistrictPin,
  type FacilityMapPinRef,
} from '@/lib/api/safety/facility-map'
import {
  AiSuggestionConfirmModal,
  ConfidenceTag,
} from '@/components/safety/aiConfirm/AiSuggestionConfirmModal'
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

// 画布内边距：边缘分区的名称标注不被 viewBox 裁切
const CANVAS_PAD = 18

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
  // 内容区内接于 padding 后的画布；纬度按 cos(25.46°) 纠正 N-S 比例
  const innerW = VIEW_W - CANVAS_PAD * 2
  const innerH = (innerW * spanY * LAT_SCALE) / spanX
  const viewH = innerH + CANVAS_PAD * 2
  return {
    viewH,
    /** 经纬度 → viewBox 坐标（y 翻转北上） */
    project(lng: number, lat: number): [number, number] {
      return [
        CANVAS_PAD + ((lng - minX) / spanX) * innerW,
        CANVAS_PAD + innerH - ((lat - minY) / spanY) * innerH,
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
  /** 最大 rail 的 bbox [x, y, w, h]（viewBox 单位，名称标注放得下判断用） */
  bbox: [number, number, number, number]
}

const RENDERED: RenderedDistrict[] = (() => {
  const out: RenderedDistrict[] = []
  for (const dist of DISTRICTS) {
    const shapes: string[] = []
    let best: { area: number; anchor: [number, number]; bbox: [number, number, number, number] } | null = null
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
        best = { area, anchor: [(sx + bx) / 2, (sy + by) / 2], bbox: [sx, sy, bx - sx, by - sy] }
      }
    }
    if (!shapes.length) continue
    out.push({ dist, shapes, anchor: best!.anchor, bbox: best!.bbox })
  }
  return out
})()

const BY_DIST_ID = new Map(RENDERED.map(r => [r.dist.distId, r]))

// ── 视图（viewBox 缩放平移）──────────────────────────────────────────
interface ViewBox {
  x: number
  y: number
  w: number
  h: number
}

const INITIAL_VB: ViewBox = { x: 0, y: 0, w: VIEW_W, h: GEOM.viewH }
const MAX_ZOOM = 12
const ZOOM_STEP = 1.4

function clampVb(v: ViewBox): ViewBox {
  const w = Math.min(Math.max(v.w, VIEW_W / MAX_ZOOM), VIEW_W)
  const h = w * (GEOM.viewH / VIEW_W)
  const x = Math.min(Math.max(v.x, 0), VIEW_W - w)
  const y = Math.min(Math.max(v.y, 0), GEOM.viewH - h)
  return { x, y, w, h }
}

// ── 配色 ────────────────────────────────────────────────────────────
// 底图：当日有落点=淡靛强调，其余暖灰；hover 统一加深
const FILL_BASE = '#f5f4f1'
const STROKE_BASE = '#d7d3cb'
const FILL_ACTIVE = '#e9eefb'
const STROKE_ACTIVE = '#8ba3e8'
const FILL_HOVER = '#dce6fa'
const LABEL_FILL = '#7a766d'
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

/** 徽标组内容（作业桶非零 + 报警合计）；BadgeGroup 与标注避让共用 */
function badgeChips(pin: FacilityMapDistrictPin): { label: string; fill: string }[] {
  const chips: { label: string; fill: string }[] = []
  for (const b of BADGES) {
    const n = pin.jobs[b.key]
    if (n > 0) chips.push({ label: `${b.label}${n}`, fill: b.fill })
  }
  const alarms = pin.alarms.fire + pin.alarms.central
  if (alarms > 0) chips.push({ label: `警${alarms}`, fill: ALARM_FILL })
  return chips
}

/** 徽标组：横向串排；按 1/zoom 缩放保持屏幕等大 */
function BadgeGroup({
  pin,
  anchor,
  zoom,
}: {
  pin: FacilityMapDistrictPin
  anchor: [number, number]
  zoom: number
}) {
  const chips = badgeChips(pin)
  if (!chips.length) return null
  const w = 38
  const total = chips.length * w
  return (
    <g
      data-testid={`district-badge-${pin.dist_id}`}
      pointerEvents="none"
      transform={`translate(${anchor[0]} ${anchor[1]}) scale(${1 / zoom}) translate(${-total / 2} ${-11})`}
    >
      {chips.map((chip, i) => (
        <g key={chip.label} transform={`translate(${i * w}, 0)`}>
          <rect width={w - 4} height={22} rx={11} fill="#fff" stroke={chip.fill} strokeWidth={1.5} />
          <text
            x={(w - 4) / 2}
            y={15}
            textAnchor="middle"
            fontSize={13}
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

const MAP_BTN_CLS =
  'flex h-7 w-7 items-center justify-center rounded-md border border-[var(--color-hairline)] bg-white/90 text-[var(--color-charcoal)] shadow-sm transition-colors hover:bg-[var(--color-surface)]'

// ── #2 AI 建议确认列表业务列 ────────────────────────────────────────
const SUGGESTION_COLUMNS: TableColumnsType<DistrictSuggestionRow> = [
  {
    title: '地点文本',
    dataIndex: 'location_text',
    width: 180,
    ellipsis: true,
  },
  { title: '次数', dataIndex: 'count', width: 64 },
  {
    title: '来源',
    dataIndex: 'kinds',
    width: 140,
    render: (kinds: string[]) =>
      kinds.map(k => (
        <Tag key={k} className="m-0" style={{ fontSize: 10, lineHeight: '16px' }}>
          {KIND_LABEL[k] ?? k}
        </Tag>
      )),
  },
  {
    title: 'AI 建议分区',
    dataIndex: 'dist_name',
    width: 140,
    render: (v: string | null) =>
      v ? <span className="font-medium">{v}</span> : (
        <span className="text-[var(--color-steel)]">无法判断</span>
      ),
  },
  {
    title: '置信度',
    dataIndex: 'confidence',
    width: 76,
    render: (v: string) => <ConfidenceTag value={v} />,
  },
  {
    title: '理由',
    dataIndex: 'reason',
    ellipsis: true,
  },
]

export function FacilityMapCard() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['safety', 'facility-map-pins'],
    queryFn: fetchFacilityMapPins,
  })
  const [openDist, setOpenDist] = useState<FacilityMapDistrictPin | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [vb, setVb] = useState<ViewBox>(INITIAL_VB)
  const [panning, setPanning] = useState(false)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const vbRef = useRef(vb)
  vbRef.current = vb
  const dragRef = useRef<{ cx: number; cy: number; vb: ViewBox; moved: boolean } | null>(null)
  const suppressClickRef = useRef(false)

  // #2 确认页工作集（打开才拉）
  const suggestionsQuery = useQuery({
    queryKey: ['safety', 'facility-map-suggestions'],
    queryFn: () => fetchDistrictSuggestions('pending'),
    enabled: confirmOpen,
  })

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['safety', 'facility-map-suggestions'] })
    void queryClient.invalidateQueries({ queryKey: ['safety', 'facility-map-pins'] })
  }

  const scanMutation = useMutation({
    mutationFn: () => scanDistrictSuggestions(30),
    onSuccess: r => {
      message.success(
        `扫描完成：候选 ${r.candidates} 条，AI 建议 ${r.suggested} 条（无法判断 ${r.no_judgement}）`,
      )
      invalidateAll()
    },
    onError: e => message.error(e instanceof Error ? e.message : '扫描失败，请稍后重试'),
  })

  const confirmMutation = useMutation({
    mutationFn: (id: string) => confirmDistrictSuggestion(id),
    onSuccess: () => {
      message.success('已确认并写入映射')
      invalidateAll()
    },
    onError: e => message.error(e instanceof Error ? e.message : '确认失败'),
  })

  const ignoreMutation = useMutation({
    mutationFn: (id: string) => ignoreDistrictSuggestion(id),
    onSuccess: () => {
      message.success('已忽略')
      invalidateAll()
    },
    onError: e => message.error(e instanceof Error ? e.message : '忽略失败'),
  })

  const confirmHighMutation = useMutation({
    mutationFn: confirmHighDistrictSuggestions,
    onSuccess: r => {
      message.success(`已批量确认 ${r.confirmed} 条`)
      invalidateAll()
    },
    onError: e => message.error(e instanceof Error ? e.message : '批量确认失败'),
  })

  const zoom = VIEW_W / vb.w
  const pinById = useMemo(
    () => new Map((data?.pins ?? []).map(p => [p.dist_id, p])),
    [data],
  )
  const unmappedEvents = useMemo(
    () => (data?.unmapped ?? []).reduce((n, u) => n + u.count, 0),
    [data],
  )

  /** 客户端坐标 → viewBox 坐标（含 preserveAspectRatio 留白修正） */
  function clientToView(clientX: number, clientY: number): { x: number; y: number } {
    const svg = svgRef.current
    if (!svg) return { x: 0, y: 0 }
    const rect = svg.getBoundingClientRect()
    const cur = vbRef.current
    const scale = Math.min(rect.width / cur.w, rect.height / cur.h)
    const ox = (rect.width - cur.w * scale) / 2
    const oy = (rect.height - cur.h * scale) / 2
    return {
      x: cur.x + (clientX - rect.left - ox) / scale,
      y: cur.y + (clientY - rect.top - oy) / scale,
    }
  }

  /** 以 viewBox 锚点 (ax, ay) 为中心缩放；factor>1 放大 */
  function zoomAt(factor: number, ax: number, ay: number) {
    setVb(prev => {
      const w = Math.min(Math.max(prev.w / factor, VIEW_W / MAX_ZOOM), VIEW_W)
      const eff = prev.w / w
      const h = w * (GEOM.viewH / VIEW_W)
      return clampVb({ x: ax - (ax - prev.x) / eff, y: ay - (ay - prev.y) / eff, w, h })
    })
  }

  const zoomBy = (factor: number) => {
    const cur = vbRef.current
    zoomAt(factor, cur.x + cur.w / 2, cur.y + cur.h / 2)
  }

  // 滚轮/触控板缩放：React onWheel 为 passive，需原生监听 preventDefault
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const p = clientToView(e.clientX, e.clientY)
      zoomAt(Math.exp(-e.deltaY * 0.002), p.x, p.y)
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if (e.button !== 0) return
    // 新按压周期：作废上一周期可能残留的吞点击标记（pointerup 后浏览器
    // 未派发 click 时标记会留存，否则误吞本次真实点击）
    suppressClickRef.current = false
    dragRef.current = { cx: e.clientX, cy: e.clientY, vb: vbRef.current, moved: false }
    setPanning(true)
    // 注意：这里不能 setPointerCapture——支持该 API 的浏览器会把后续
    // click 一并重定向到 svg，<g onClick> 收不到，点击分区永远不弹
    // Modal（真机 bug 2026-10-27）；capture 延迟到真正拖动时再做
  }

  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    const d = dragRef.current
    const svg = svgRef.current
    if (!d || !svg) return
    if (Math.abs(e.clientX - d.cx) + Math.abs(e.clientY - d.cy) > 4) {
      if (!d.moved) {
        d.moved = true
        // 越过拖动阈值才捕获指针：单击（含轻微抖动）不捕获，click 正常
        // 派发到分区多边形；真拖动则锁住指针获得 viewport 外的连续平移
        try {
          svg.setPointerCapture(e.pointerId)
        } catch {
          // happy-dom 等环境无实现，拖动降级为仅视图内移动
        }
      }
    }
    if (!d.moved) return
    const rect = svg.getBoundingClientRect()
    const scale = Math.min(rect.width / d.vb.w, rect.height / d.vb.h)
    const dx = (e.clientX - d.cx) / scale
    const dy = (e.clientY - d.cy) / scale
    setVb(clampVb({ ...d.vb, x: d.vb.x - dx, y: d.vb.y - dy }))
  }

  function onPointerUp(e: React.PointerEvent<SVGSVGElement>) {
    if (dragRef.current?.moved) suppressClickRef.current = true
    dragRef.current = null
    setPanning(false)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // 同上，环境不支持时忽略
    }
  }

  /** 拖动过的松手不当作分区点击（否则平移结束会误开 Modal） */
  function onClickCapture(e: React.MouseEvent) {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      e.stopPropagation()
      e.preventDefault()
    }
  }

  // 名称标注：字号按 1/zoom 保持屏幕 13px。贪心避让：先占位全部落点徽标
  // 矩形，再按分区面积降序尝试放标签——与已放标签/徽标相交即跳过
  // （相邻重叠分区如米尔贝/提四米贝锚点几乎重合，全画必叠；放大后字号
  // 变小、放得下的变多，逐级显现）
  const labels = useMemo(() => {
    const fs = 13 / zoom
    const placed: { x1: number; y1: number; x2: number; y2: number }[] = []
    for (const pin of data?.pins ?? []) {
      const rendered = BY_DIST_ID.get(pin.dist_id)
      if (!rendered) continue
      const w = (badgeChips(pin).length * 38 - 4) / zoom
      placed.push({
        x1: rendered.anchor[0] - w / 2,
        y1: rendered.anchor[1] - 11 / zoom,
        x2: rendered.anchor[0] + w / 2,
        y2: rendered.anchor[1] + 11 / zoom,
      })
    }
    const cands = RENDERED.filter(
      ({ dist, bbox }) => bbox[2] >= dist.distName.length * fs * 0.85,
    ).sort((a, b) => b.bbox[2] * b.bbox[3] - a.bbox[2] * a.bbox[3])
    const out: RenderedDistrict[] = []
    for (const item of cands) {
      const w = item.dist.distName.length * fs * 0.95
      const h = fs * 1.3
      const cy = item.anchor[1] + (pinById.get(item.dist.distId) ? 24 : 5) / zoom
      const rect = {
        x1: item.anchor[0] - w / 2,
        y1: cy - h / 2,
        x2: item.anchor[0] + w / 2,
        y2: cy + h / 2,
      }
      if (
        placed.some(
          p => rect.x1 < p.x2 && rect.x2 > p.x1 && rect.y1 < p.y2 && rect.y2 > p.y1,
        )
      )
        continue
      placed.push(rect)
      out.push(item)
    }
    return out
  }, [zoom, pinById, data])

  return (
    <SectionCard
      title="厂区风险分区 · 当日分布"
      description={`64 分区底图（3.x 平台快照）· ${data?.date ?? '—'} 特殊作业票与消防/中控报警落点 · 滚轮缩放 / 拖动平移`}
      action={
        <div className="flex items-center gap-2 text-[11px] text-[var(--color-steel)]">
          <span className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-[2px]"
              style={{ background: FILL_ACTIVE, border: `1px solid ${STROKE_ACTIVE}` }}
            />
            当日有落点
          </span>
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
        <div className="flex h-[420px] items-center justify-center">
          <Spin />
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {data.errors.length > 0 && (
            <div className="rounded-md bg-[var(--wh-warn-bg)] px-3 py-1.5 text-[12px] text-[var(--wh-warn)]">
              部分数据源降级：{data.errors.join('；')}
            </div>
          )}
          <div className="flex justify-center">
            <div className="relative">
              <svg
                ref={svgRef}
                viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
                className="select-none"
                style={{
                  height: 'clamp(460px, 62vh, 760px)',
                  aspectRatio: `${VIEW_W} / ${GEOM.viewH}`,
                  touchAction: 'none',
                  cursor: panning ? 'grabbing' : 'grab',
                }}
                role="img"
                aria-label="厂区风险分区底图"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onClickCapture={onClickCapture}
              >
                {RENDERED.map(({ dist, shapes }) => {
                  const pin = pinById.get(dist.distId)
                  return (
                    <g
                      key={dist.distId}
                      data-testid={`district-poly-${dist.distId}`}
                      className="cursor-pointer [&:hover_polygon]:fill-[#dce6fa]"
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
                          fill={pin ? FILL_ACTIVE : FILL_BASE}
                          stroke={pin ? STROKE_ACTIVE : STROKE_BASE}
                          strokeWidth={pin ? 1.4 : 1}
                        />
                      ))}
                    </g>
                  )
                })}
                {labels.map(({ dist, anchor }) => (
                  <text
                    key={`lb-${dist.distId}`}
                    data-testid={`district-label-${dist.distId}`}
                    x={anchor[0]}
                    y={anchor[1] + (pinById.get(dist.distId) ? 24 : 5) / zoom}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={13 / zoom}
                    fontWeight={500}
                    fill={LABEL_FILL}
                    stroke="#ffffff"
                    strokeWidth={3 / zoom}
                    strokeLinejoin="round"
                    paintOrder="stroke"
                    pointerEvents="none"
                  >
                    {dist.distName}
                  </text>
                ))}
                {data.pins.map(pin => {
                  const rendered = BY_DIST_ID.get(pin.dist_id)
                  if (!rendered) return null
                  return (
                    <BadgeGroup
                      key={pin.dist_id}
                      pin={pin}
                      anchor={rendered.anchor}
                      zoom={zoom}
                    />
                  )
                })}
              </svg>
              <div className="absolute right-2 top-2 flex flex-col gap-1">
                <button type="button" aria-label="放大" className={MAP_BTN_CLS} onClick={() => zoomBy(ZOOM_STEP)}>
                  <Plus size={14} />
                </button>
                <button type="button" aria-label="缩小" className={MAP_BTN_CLS} onClick={() => zoomBy(1 / ZOOM_STEP)}>
                  <Minus size={14} />
                </button>
                <button
                  type="button"
                  aria-label="重置视图"
                  className={MAP_BTN_CLS}
                  onClick={() => setVb(INITIAL_VB)}
                >
                  <Maximize size={13} />
                </button>
              </div>
              <div className="pointer-events-none absolute bottom-2 left-3 rounded bg-white/80 px-1.5 py-0.5 text-[11px] text-[var(--color-steel)]">
                {Math.round(zoom * 100)}%
              </div>
            </div>
          </div>
          <div className="rounded-lg border border-[var(--color-hairline-soft)] bg-[var(--color-surface)] px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
                未映射 {data.unmapped.length} 处
                <span className="ml-1 font-normal text-[var(--color-steel)]">
                  （{unmappedEvents} 条事件）
                </span>
              </span>
              <span className="flex items-center gap-3">
                <span className="text-[11px] text-[var(--color-steel)]">
                  未映射=地点文本未能对应分区；AI 建议经人工确认后写入映射（只增不改）
                </span>
                <Button type="primary" ghost size="small" onClick={() => setConfirmOpen(true)}>
                  AI 建议映射 →
                </Button>
              </span>
            </div>
            {data.unmapped.length > 0 && (
              <div className="mt-2 grid max-h-36 grid-cols-1 gap-x-8 gap-y-1 overflow-y-auto border-t border-[var(--color-hairline-soft)] pt-2 md:grid-cols-2 xl:grid-cols-3">
                {data.unmapped.slice(0, 60).map(u => (
                  <div key={u.text} className="flex items-center justify-between gap-2 text-[12px]">
                    <span className="truncate text-[var(--color-charcoal)]" title={u.text}>
                      {u.text}
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {u.kinds.map(k => (
                        <Tag key={k} className="m-0" style={{ fontSize: 10, lineHeight: '16px' }}>
                          {KIND_LABEL[k] ?? k}
                        </Tag>
                      ))}
                      <span className="text-[var(--color-steel)]">×{u.count}</span>
                    </span>
                  </div>
                ))}
                {data.unmapped.length > 60 && (
                  <span className="text-[11px] text-[var(--color-steel)]">
                    其余 {data.unmapped.length - 60} 条在确认列表内查看
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}
      <DistrictModal
        pin={openDist}
        distName={openDist ? BY_DIST_ID.get(openDist.dist_id)?.dist.distName ?? openDist.dist_id : ''}
        date={data?.date ?? ''}
        onClose={() => setOpenDist(null)}
      />
      <AiSuggestionConfirmModal<DistrictSuggestionRow>
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="未映射地点 · AI 分区建议确认"
        description="扫描近 30 天作业票/消防/中控的未映射地点文本，AI 逐条给出分区建议与置信度；确认后写入映射资产（location_district_map，只增不改），忽略后不再建议。"
        rows={suggestionsQuery.data ?? []}
        loading={suggestionsQuery.isLoading}
        columns={SUGGESTION_COLUMNS}
        canConfirm={row => row.dist_id !== null}
        onConfirm={row => confirmMutation.mutateAsync(row.id)}
        onIgnore={row => ignoreMutation.mutateAsync(row.id)}
        batchConfirmHigh={{ run: confirmHighMutation.mutateAsync }}
        extraFooter={
          <span className="flex items-center gap-2 text-[12px] text-[var(--color-steel)]">
            <Button
              size="small"
              loading={scanMutation.isPending}
              disabled={scanMutation.isPending}
              onClick={() => scanMutation.mutate()}
            >
              扫描近 30 天生成建议
            </Button>
            <span>含 AI 批量调用，候选多时需数分钟</span>
          </span>
        }
      />
    </SectionCard>
  )
}

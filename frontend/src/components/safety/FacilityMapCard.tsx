'use client'

/**
 * 厂区风险分区 · 当日分布图卡（3.x 平台关联 F2 · 建筑级两级模型）。
 *
 * 视图（2026-10 分区大改，旧 64 分区视图退役）：33 栋建筑（图上唯一编号
 * 1-33，一建筑一号）+ 建筑内子单元；建筑定义与 distId 归并为前端静态配置
 * （src/data/f2-buildings.ts），映射/落点后端链路不动。底图为 64 分区轮廓
 * 静态资产（src/data/tiji-risk-districts.json，经纬度快照），SVG 直绘无地图
 * 库——经纬差投影到 viewBox（纬度按 cos(25.46°) 纠正 N-S 比例，y 轴翻转
 * 北上）。
 *
 * 几何合成：平台按建筑建模，多个分区共用同一轮廓（shapesKey 同轮廓组）；
 * 每组轮廓归属=组内多数成员所在建筑（平票取小建筑号），画一次代表轮廓——
 * 母建筑多片轮廓标同号；少数派成员（雷帕 dist29，几何画进 2 号楼轮廓组）
 * 收数据不收轮廓：数据/落点/弹窗全归 1 号楼（拍板特例）。
 * 色系：按主责部门归并 11 族（BUILDING_FAMILIES），当日有落点用各族
 * active 态强调；徽标/计数/弹窗七路明细全部按建筑聚合。
 * 交互：滚轮/触控板缩放（光标锚）+ 拖动平移（拖动吞点击）+ 右上角放大/
 * 缩小/重置；徽标与编号标注按 1/zoom 缩放保持屏幕等大，标注随放大逐级显现。
 * 布局：地图盒高度封顶 min(75vh,760px)、宽度=高×宽高比（min() 显式算而非
 * aspect-ratio——部分渲染内核对 svg 容器不生效）；「未映射」栏 xl 起固定
 * 300px 与地图并排等高（清单滚轮滚动），整卡一屏可见。编号标注贪心避让。
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
import {
  BUILDINGS,
  BUILDING_FAMILIES,
  DIST_TO_BUILDING,
  type BuildingDef,
} from '@/data/f2-buildings'

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

// 画布内边距：边缘建筑的编号标注不被 viewBox 裁切
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
  /** 轮廓签（points 串拼接）——同建筑多分区判定键 */
  shapesKey: string
  /** 徽标挂点：最大 rail 的 bbox 中心 */
  anchor: [number, number]
  /** 最大 rail 的 bbox [x, y, w, h]（viewBox 单位，编号标注放得下判断用） */
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
    out.push({ dist, shapes, anchor: best!.anchor, bbox: best!.bbox, shapesKey: shapes.join('|') })
  }
  return out
})()

// ── 同轮廓分组：平台按建筑建模，多个分区（产线/功能区）共用同一轮廓。
// 组轮廓归属=组内多数成员所在建筑（平票取小建筑号）；少数派成员收数据
// 不收轮廓（雷帕 dist29：几何画进 2 号楼轮廓组，数据全归 1 号楼）。
const GEOM_GROUPS: RenderedDistrict[][] = (() => {
  const byKey = new Map<string, RenderedDistrict[]>()
  for (const r of RENDERED) {
    const list = byKey.get(r.shapesKey)
    if (list) list.push(r)
    else byKey.set(r.shapesKey, [r])
  }
  return [...byKey.values()]
})()

interface BuildingPiece {
  /** 一片轮廓=该建筑名下一个同轮廓组的代表 rail 集（各 rail 同形状只画一次） */
  shapes: string[]
  anchor: [number, number]
  bbox: [number, number, number, number]
}

interface BuildingGeo {
  id: number
  /** 轮廓片（面积降序；[0] 为主片=徽标/标注锚点） */
  pieces: BuildingPiece[]
  anchor: [number, number]
  bbox: [number, number, number, number]
}

const BUILDING_GEOS: BuildingGeo[] = (() => {
  const byBuilding = new Map<number, BuildingPiece[]>()
  for (const group of GEOM_GROUPS) {
    // 多数成员归属（平票取小建筑号：按建筑号升序遍历、严格大于才接管）
    const counts = new Map<number, number>()
    for (const r of group) {
      const b = DIST_TO_BUILDING.get(r.dist.distId)
      if (b != null) counts.set(b, (counts.get(b) ?? 0) + 1)
    }
    let owner = -1
    let best = 0
    for (const b of [...counts.keys()].sort((a, z) => a - z)) {
      const n = counts.get(b)!
      if (n > best) {
        best = n
        owner = b
      }
    }
    const rep =
      group.find(r => DIST_TO_BUILDING.get(r.dist.distId) === owner) ?? group[0]
    const list = byBuilding.get(owner)
    if (list) list.push({ shapes: rep.shapes, anchor: rep.anchor, bbox: rep.bbox })
    else byBuilding.set(owner, [{ shapes: rep.shapes, anchor: rep.anchor, bbox: rep.bbox }])
  }
  return BUILDINGS.map(def => {
    const pieces = (byBuilding.get(def.id) ?? []).sort(
      (a, b) => b.bbox[2] * b.bbox[3] - a.bbox[2] * a.bbox[3],
    )
    const main = pieces[0]
    return {
      id: def.id,
      pieces,
      anchor: main?.anchor ?? [0, 0],
      bbox: main?.bbox ?? [0, 0, 0, 0],
    }
  }).filter(g => g.pieces.length > 0)
})()

const GEO_BY_ID = new Map(BUILDING_GEOS.map(g => [g.id, g] as const))

/** 建筑数据成员（资产分区级，含数据-only 成员如雷帕 29） */
const MEMBERS_BY_BUILDING = new Map<number, RenderedDistrict[]>(
  BUILDINGS.map(def => [
    def.id,
    RENDERED.filter(r => DIST_TO_BUILDING.get(r.dist.distId) === def.id),
  ] as const),
)

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

// ── 一屏可见：地图盒高度封顶，宽度=高×底图宽高比且封顶 100%。宽高比用
// min() 显式算而非 CSS aspect-ratio——部分渲染内核对 svg 容器不生效
// （未映射栏收窄为固定 300px 后高度上限 60vh→75vh，图随之放大）
const MAP_MAX_H_VH = 75
const MAP_MAX_H_PX = 760
const MAP_RATIO = VIEW_W / GEOM.viewH
const MAP_BOX_STYLE = {
  height: `min(${MAP_MAX_H_VH}vh, ${MAP_MAX_H_PX}px)`,
  width: `min(100%, ${(MAP_MAX_H_VH * MAP_RATIO).toFixed(2)}vh, ${Math.round(MAP_MAX_H_PX * MAP_RATIO)}px)`,
} as const

// ── 配色 ────────────────────────────────────────────────────────────
// 建筑底色=色系族（BUILDING_FAMILIES，11 族按主责部门归并）；当日有落点
// 用各族 active 态。徽标色不变（动火红/受限橙/其他蓝/报警黄等）。
const LABEL_FILL = '#7a766d'
const BADGES = [
  { key: 'hot', label: '火', fill: '#d92d20' },
  { key: 'confined', label: '受', fill: '#f79009' },
  { key: 'other', label: '其', fill: '#2e90fa' },
] as const

const ALARM_FILL = '#f2c94c'
const ALARM_STROKE = '#b5860a'

// 关键风险作业徽标（紫，区别于作业票三桶与报警黄）
const RISK_FILL = '#7a5af8'

// 超储物料徽标（青，当前态快照）
const OVER_LIMIT_FILL = '#0e9388'

// 今日新增隐患徽标（深红）
const HAZARD_NEW_FILL = '#b42318'

// 未整改隐患徽标（紫红，当前态快照）
const HAZARD_OPEN_FILL = '#c2255c'

// 消防设施到期徽标（橙，当前态快照：已到期+30 天临期）
const FIRE_EXT_FILL = '#e8590c'

const KIND_LABEL: Record<string, string> = {
  job: '作业票',
  fire: '消防报警',
  central: '中控报警',
  key_risk: '关键风险作业',
  over_limit: '超储物料',
  hazard_new: '今日新增隐患',
  hazard_open: '未整改隐患',
  fire_ext_due: '消防设施到期',
}

const HAZARD_LEVEL_LABEL: Record<string, string> = {
  general: '一般',
  serious: '较大',
  major: '重大',
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

/** 徽标组内容（作业桶非零 + 关键风险 + 超储 + 隐患双口径 + 消防到期 + 报警合计）；BadgeGroup 与标注避让共用 */
function badgeChips(pin: FacilityMapDistrictPin): { label: string; fill: string }[] {
  const chips: { label: string; fill: string }[] = []
  for (const b of BADGES) {
    const n = pin.jobs[b.key]
    if (n > 0) chips.push({ label: `${b.label}${n}`, fill: b.fill })
  }
  if (pin.key_risks > 0) chips.push({ label: `险${pin.key_risks}`, fill: RISK_FILL })
  if (pin.over_limits > 0) chips.push({ label: `储${pin.over_limits}`, fill: OVER_LIMIT_FILL })
  if (pin.hazard_news > 0) chips.push({ label: `患${pin.hazard_news}`, fill: HAZARD_NEW_FILL })
  if (pin.hazard_opens > 0) chips.push({ label: `改${pin.hazard_opens}`, fill: HAZARD_OPEN_FILL })
  if (pin.fire_ext_dues > 0) chips.push({ label: `消到${pin.fire_ext_dues}`, fill: FIRE_EXT_FILL })
  const alarms = pin.alarms.fire + pin.alarms.central
  if (alarms > 0) chips.push({ label: `警${alarms}`, fill: ALARM_FILL })
  return chips
}

// 徽标片尺寸（BadgeGroup 渲染与标注避让占位共用同一口径）
const CHIP_W = 38
const CHIP_HALF_H = 11

/** 徽标组：横向串排；按 1/zoom 缩放保持屏幕等大 */
function BadgeGroup({
  buildingId,
  pin,
  anchor,
  zoom,
}: {
  buildingId: number
  pin: FacilityMapDistrictPin
  anchor: [number, number]
  zoom: number
}) {
  const chips = badgeChips(pin)
  if (!chips.length) return null
  const total = chips.length * CHIP_W
  return (
    <g
      data-testid={`building-badge-${buildingId}`}
      pointerEvents="none"
      transform={`translate(${anchor[0]} ${anchor[1]}) scale(${1 / zoom}) translate(${-total / 2} ${-CHIP_HALF_H})`}
    >
      {chips.map((chip, i) => (
        <g key={chip.label} transform={`translate(${i * CHIP_W}, 0)`}>
          <rect width={CHIP_W - 4} height={CHIP_HALF_H * 2} rx={CHIP_HALF_H} fill="#fff" stroke={chip.fill} strokeWidth={1.5} />
          <text
            x={(CHIP_W - 4) / 2}
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

const KEY_RISK_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  {
    title: '开始时间',
    dataIndex: 'start_time',
    width: 110,
    render: (v: string | null) => (v ? v.slice(5, 16).replace('T', ' ') : '—'),
  },
  { title: '区域', dataIndex: 'area', width: 170, render: (v: string | null) => v || '—' },
  {
    title: '审批状态',
    dataIndex: 'apply_status',
    width: 90,
    render: (v: string | null) => v || '—',
  },
  { title: '作业内容', dataIndex: 'operation_content', ellipsis: true },
]

const OVER_LIMIT_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  { title: '物料', dataIndex: 'material_name', width: 110 },
  {
    title: '存储位置',
    dataIndex: 'storage_location',
    width: 170,
    render: (v: string | null) => v || '—',
  },
  { title: '部门', dataIndex: 'department', width: 90, render: (v: string | null) => v || '—' },
  {
    title: '当前库存',
    width: 110,
    render: (_, r) =>
      `${r.total_quantity_t ?? '—'} ${r.unit ?? ''}`.trim(),
  },
  { title: '超储阈值', dataIndex: 'max_limit', width: 100, render: (v: number | null) => (v ?? '—') },
]

// 隐患双口径共用列（今日新增/未整改；描述即位置载体）
const HAZARD_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  {
    title: '级别',
    dataIndex: 'hazard_level',
    width: 64,
    render: (v: string | null) => {
      if (!v) return '—'
      const label = HAZARD_LEVEL_LABEL[v] ?? v
      return v === 'major' ? (
        <span className="font-medium text-[#b42318]">{label}</span>
      ) : label
    },
  },
  { title: '编号', dataIndex: 'hazard_no', width: 140, render: (v: string | null) => v || '—' },
  { title: '隐患描述', dataIndex: 'hazard_desc', ellipsis: true },
  {
    title: '目前进展',
    dataIndex: 'progress',
    width: 150,
    ellipsis: true,
    render: (v: string | null) => v || '—',
  },
]

const FIRE_EXT_COLUMNS: TableColumnsType<FacilityMapPinRef> = [
  {
    title: '位置',
    width: 190,
    render: (_, r) => [r.workshop, r.location].filter(Boolean).join(' · ') || '—',
  },
  { title: '类型', dataIndex: 'ext_type', width: 150, render: (v: string | null) => v || '—' },
  { title: '数量', dataIndex: 'ext_count', width: 64, render: (v: number | null) => v ?? '—' },
  { title: '到期日', dataIndex: 'due_date', width: 100 },
  {
    title: '状态',
    dataIndex: 'is_overdue',
    width: 76,
    render: (v: boolean | null) =>
      v ? <span className="font-medium text-[#b42318]">已到期</span> : (
        <span className="text-[#e8590c]">临期</span>
      ),
  },
]

/** 弹窗当日七路段（按建筑聚合：全部成员 refs 合并，计数完整） */
function BuildingDetailSection({ pin }: { pin: FacilityMapDistrictPin }) {
  const jobs = pin.refs.filter(r => r.kind === 'job')
  const keyRisks = pin.refs.filter(r => r.kind === 'key_risk')
  const overLimits = pin.refs.filter(r => r.kind === 'over_limit')
  const hazardsNew = pin.refs.filter(r => r.kind === 'hazard_new')
  const hazardsOpen = pin.refs.filter(r => r.kind === 'hazard_open')
  const fireExts = pin.refs.filter(r => r.kind === 'fire_ext_due')
  const alarms = pin.refs.filter(r => r.kind === 'fire' || r.kind === 'central')
  const sections: { label: string; columns: TableColumnsType<FacilityMapPinRef>; rows: FacilityMapPinRef[]; empty: string; key: string }[] = [
    {
      label: `特殊作业票 ${jobs.length} 张${pin.truncated ? '（明细超 50 条已截断，计数完整）' : ''}`,
      columns: JOB_COLUMNS, rows: jobs, empty: '本建筑当日无作业票', key: 'j',
    },
    {
      label: `关键风险作业 ${keyRisks.length} 项（当日已通过/审批中）`,
      columns: KEY_RISK_COLUMNS, rows: keyRisks, empty: '本建筑当日无关键风险作业', key: 'k',
    },
    {
      label: `超储物料 ${overLimits.length} 项（当前库存态）`,
      columns: OVER_LIMIT_COLUMNS, rows: overLimits, empty: '本建筑无超储物料', key: 'o',
    },
    {
      label: `今日新增隐患 ${hazardsNew.length} 条（检查日期=今日）`,
      columns: HAZARD_COLUMNS, rows: hazardsNew, empty: '本建筑今日无新增隐患', key: 'hn',
    },
    {
      label: `未整改隐患 ${hazardsOpen.length} 条（当前未闭环）`,
      columns: HAZARD_COLUMNS, rows: hazardsOpen, empty: '本建筑无未整改隐患', key: 'ho',
    },
    {
      label: `消防设施到期 ${fireExts.length} 处（已到期+30 天内临期）`,
      columns: FIRE_EXT_COLUMNS, rows: fireExts, empty: '本建筑无到期/临期消防设施', key: 'fe',
    },
    {
      label: `今日报警 ${alarms.length} 条`,
      columns: ALARM_COLUMNS, rows: alarms, empty: '本建筑今日无报警', key: 'a',
    },
  ]
  return (
    <div className="flex flex-col gap-4">
      {sections.map(s => (
        <div key={s.key}>
          <div className="mb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
            {s.label}
          </div>
          <Table
            rowKey={(_, i) => `${s.key}${i}`}
            size="small"
            columns={s.columns}
            dataSource={s.rows}
            pagination={false}
            locale={{ emptyText: s.empty }}
          />
        </div>
      ))}
    </div>
  )
}

const EMPTY_PIN = (distId: string): FacilityMapDistrictPin => ({
  dist_id: distId,
  jobs: { hot: 0, confined: 0, other: 0 },
  alarms: { fire: 0, central: 0 },
  key_risks: 0,
  over_limits: 0,
  hazard_news: 0,
  hazard_opens: 0,
  fire_ext_dues: 0,
  refs: [],
  truncated: false,
})

interface BuildingMemberView {
  distId: string
  distName: string
  pin: FacilityMapDistrictPin
}

interface BuildingView {
  def: BuildingDef
  members: BuildingMemberView[]
  agg: Pick<
    FacilityMapDistrictPin,
    'jobs' | 'alarms' | 'key_risks' | 'over_limits' | 'hazard_news' | 'hazard_opens' | 'fire_ext_dues'
  >
  hasPin: boolean
}

/** 建筑聚合 pin（计数口径，徽标/标注避让共用） */
function buildingCountsPin(b: BuildingView): FacilityMapDistrictPin {
  return { ...EMPTY_PIN(String(b.def.id)), ...b.agg }
}

/** 建筑弹窗：建筑信息头（名称/责任部门/产线/子单元/收编分区）+ 七路聚合明细 */
function BuildingModal({
  building,
  date,
  onClose,
}: {
  building: BuildingView | null
  date: string
  onClose: () => void
}) {
  const pin = useMemo<FacilityMapDistrictPin>(() => {
    if (!building) return EMPTY_PIN('')
    return {
      ...buildingCountsPin(building),
      refs: building.members.flatMap(m => m.pin.refs),
      truncated: building.members.some(m => m.pin.truncated),
    }
  }, [building])
  const def = building?.def
  return (
    <Modal
      open={building !== null}
      title={def ? `${def.id} ${def.name ?? '待命名'} · ${date} 当日明细` : ''}
      footer={null}
      width={760}
      onCancel={onClose}
    >
      {def && building && (
        <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto pt-2">
          <div className="flex flex-col gap-1 rounded-md border border-[var(--color-hairline-soft)] bg-[var(--color-surface)] px-3 py-2">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="text-[14px] font-semibold text-[var(--color-charcoal)]">
                {def.id} {def.name ?? '待命名'}
              </span>
              <span className="text-[12px] text-[var(--color-charcoal)]">
                责任部门：{def.depts.join(' / ')}
              </span>
            </div>
            <div className="text-[12px] text-[var(--color-charcoal)]">产线/岗位：{def.lines}</div>
            {def.subunits.map(su => (
              <div key={su.name} className="text-[12px] text-[var(--color-charcoal)]">
                └ 子单元：{su.name}（{su.dept}）
              </div>
            ))}
            <div className="text-[11px] text-[var(--color-steel)]">
              收编分区：{building.members.map(m => m.distName).join(' / ')}
            </div>
          </div>
          <BuildingDetailSection pin={pin} />
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

// 色系族图例（11 族方点）+ 徽标图例（圆点）；族内深色=当日有落点
const FAMILY_LEGEND = Object.values(BUILDING_FAMILIES).map(f => ({
  key: f.key,
  label: f.label,
  fill: f.fillActive,
  stroke: f.strokeBase,
}))
const BADGE_LEGEND = [
  ...BADGES.map(b => ({
    label: b.label === '火' ? '动火' : b.label === '受' ? '受限' : '其他作业',
    fill: b.fill as string,
  })),
  { label: '关键风险作业', fill: RISK_FILL },
  { label: '超储物料', fill: OVER_LIMIT_FILL },
  { label: '今日新增隐患', fill: HAZARD_NEW_FILL },
  { label: '未整改隐患', fill: HAZARD_OPEN_FILL },
  { label: '消防设施到期', fill: FIRE_EXT_FILL },
  { label: '报警', fill: ALARM_FILL },
]

export function FacilityMapCard() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['safety', 'facility-map-pins'],
    queryFn: fetchFacilityMapPins,
  })
  const [openId, setOpenId] = useState<number | null>(null)
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
  /** 建筑视图：成员分区 pin（缺省空）按 distId 归并聚合；徽标/弹窗按建筑走 */
  const buildings = useMemo<BuildingView[]>(
    () =>
      BUILDINGS.map(def => {
        const members: BuildingMemberView[] = (MEMBERS_BY_BUILDING.get(def.id) ?? []).map(r => ({
          distId: r.dist.distId,
          distName: r.dist.distName,
          pin: pinById.get(r.dist.distId) ?? EMPTY_PIN(r.dist.distId),
        }))
        const agg = members.reduce(
          (acc, { pin }) => {
            acc.jobs.hot += pin.jobs.hot
            acc.jobs.confined += pin.jobs.confined
            acc.jobs.other += pin.jobs.other
            acc.alarms.fire += pin.alarms.fire
            acc.alarms.central += pin.alarms.central
            acc.key_risks += pin.key_risks
            acc.over_limits += pin.over_limits
            acc.hazard_news += pin.hazard_news
            acc.hazard_opens += pin.hazard_opens
            acc.fire_ext_dues += pin.fire_ext_dues
            return acc
          },
          {
            jobs: { hot: 0, confined: 0, other: 0 },
            alarms: { fire: 0, central: 0 },
            key_risks: 0,
            over_limits: 0,
            hazard_news: 0,
            hazard_opens: 0,
            fire_ext_dues: 0,
          },
        )
        return {
          def,
          members,
          agg,
          hasPin: members.some(m => pinById.has(m.distId)),
        }
      }),
    [pinById],
  )
  const buildingById = useMemo(
    () => new Map(buildings.map(b => [b.def.id, b])),
    [buildings],
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
    // click 一并重定向到 svg，<g onClick> 收不到，点击建筑永远不弹
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
        // 派发到建筑多边形；真拖动则锁住指针获得 viewport 外的连续平移
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

  /** 拖动过的松手不当作建筑点击（否则平移结束会误开 Modal） */
  function onClickCapture(e: React.MouseEvent) {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      e.stopPropagation()
      e.preventDefault()
    }
  }

  // 编号/名称标注：字号按 1/zoom 保持屏幕 13px。贪心避让：先占位全部落点
  // 徽标矩形（每建筑一枚、挂主片锚点），再按轮廓片面积降序放标签；母建筑
  // 多片轮廓各自尝试放同号标注（放得下才显示，放大后逐级显现）；每个标签
  // 依次尝试首选位（有落点主片=徽标下方、其余=质心下方）与备选位（质心
  // 上方），全碰撞才跳过
  const labels = useMemo<
    { id: number; text: string; x: number; y: number }[]
  >(() => {
    const fs = 13 / zoom
    const placed: { x1: number; y1: number; x2: number; y2: number }[] = []
    for (const b of buildings) {
      if (!b.hasPin) continue
      const geo = GEO_BY_ID.get(b.def.id)
      if (!geo) continue
      const chips = badgeChips(buildingCountsPin(b))
      if (!chips.length) continue
      const w = (chips.length * CHIP_W - 4) / zoom
      placed.push({
        x1: geo.anchor[0] - w / 2,
        y1: geo.anchor[1] - CHIP_HALF_H / zoom,
        x2: geo.anchor[0] + w / 2,
        y2: geo.anchor[1] + CHIP_HALF_H / zoom,
      })
    }
    const hits = (r: { x1: number; y1: number; x2: number; y2: number }) =>
      placed.some(p => r.x1 < p.x2 && r.x2 > p.x1 && r.y1 < p.y2 && r.y2 > p.y1)
    const cands = BUILDING_GEOS.flatMap(geo => {
      const b = buildingById.get(geo.id)
      if (!b) return []
      const text = b.def.name ? `${b.def.id} ${b.def.name}` : `${b.def.id}`
      return geo.pieces
        .filter(p => p.bbox[2] >= text.length * fs * 0.85)
        .map((piece, i) => ({
          geo,
          piece,
          text,
          main: i === 0,
          area: piece.bbox[2] * piece.bbox[3],
        }))
    }).sort((a, b) => b.area - a.area)
    const out: { id: number; text: string; x: number; y: number }[] = []
    for (const item of cands) {
      const w = item.text.length * fs * 0.95
      const h = fs * 1.3
      const pinned = item.main && (buildingById.get(item.geo.id)?.hasPin ?? false)
      let settled: number | null = null
      for (const dy of pinned ? [24] : [5, -16]) {
        const cy = item.piece.anchor[1] + dy / zoom
        const rect = {
          x1: item.piece.anchor[0] - w / 2,
          y1: cy - h / 2,
          x2: item.piece.anchor[0] + w / 2,
          y2: cy + h / 2,
        }
        if (!hits(rect)) {
          settled = dy
          placed.push(rect)
          break
        }
      }
      if (settled !== null) {
        out.push({
          id: item.geo.id,
          text: item.text,
          x: item.piece.anchor[0],
          y: item.piece.anchor[1] + settled / zoom,
        })
      }
    }
    return out
  }, [zoom, buildings, buildingById])

  return (
    <SectionCard
      title="厂区风险分区 · 当日分布"
      description={`33 栋建筑两级模型（建筑级视图，分区大改 2026-10）· ${data?.date ?? '—'} 作业票/关键风险/超储/隐患（新增+未整改）/消防设施到期与消防/中控报警按建筑落点 · 滚轮缩放 / 拖动平移`}
    >
      {isError ? (
        <EmptyGuide
          compact
          icon={<MapPinned size={18} />}
          title="分区数据暂时不可用"
          description="落点数据拉取失败（平台或表格抖动），稍后自动恢复；建筑底图不受影响"
        />
      ) : isLoading || !data ? (
        <div className="flex items-center justify-center" style={{ height: MAP_BOX_STYLE.height }}>
          <Spin />
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {data.errors.length > 0 && (
            <div className="rounded-md bg-[var(--wh-warn-bg)] px-3 py-1.5 text-[12px] text-[var(--wh-warn)]">
              部分数据源降级：{data.errors.join('；')}
            </div>
          )}
          {/* 图例横条两段：色系族（方点，族内深色=当日有落点）+ 徽标（圆点） */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {FAMILY_LEGEND.map(l => (
              <span
                key={l.key}
                className="inline-flex items-center gap-1 text-[11px] text-[var(--color-steel)]"
              >
                <span
                  className="inline-block h-2 w-2 rounded-[2px]"
                  style={{ background: l.fill, border: `1px solid ${l.stroke}` }}
                />
                {l.label}
              </span>
            ))}
            <span className="text-[var(--color-hairline)]">|</span>
            {BADGE_LEGEND.map(l => (
              <span
                key={l.label}
                className="inline-flex items-center gap-1 text-[11px] text-[var(--color-steel)]"
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: l.fill }} />
                {l.label}
              </span>
            ))}
          </div>
          {/* 地图盒：高度封顶一屏可见；宽度=高×宽高比贴合绘制区（svg 绝对
              填充，preserveAspectRatio 居中兜底）。xl 起与固定宽未映射栏并排
              （栏高拉伸与地图等高），窄 xl 视口下地图再让出栏宽防溢出 */}
          <div className="flex flex-col gap-3 xl:flex-row xl:justify-center">
            <div
              className="relative mx-auto w-full flex-none xl:mx-0 xl:max-w-[calc(100%-312px)]"
              style={MAP_BOX_STYLE}
            >
              <svg
                ref={svgRef}
                viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
                className="absolute left-0 top-0 h-full w-full select-none"
                style={{
                  touchAction: 'none',
                  cursor: panning ? 'grabbing' : 'grab',
                }}
                role="img"
                aria-label="厂区建筑底图"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onClickCapture={onClickCapture}
              >
                {BUILDING_GEOS.map(geo => {
                  const b = buildingById.get(geo.id)
                  if (!b) return null
                  const fam = BUILDING_FAMILIES[b.def.family]
                  const active = b.hasPin
                  const counts = active
                    ? ` · 作业 ${b.agg.jobs.hot + b.agg.jobs.confined + b.agg.jobs.other} / 关键风险 ${b.agg.key_risks} / 超储 ${b.agg.over_limits} / 新增隐患 ${b.agg.hazard_news} / 未整改 ${b.agg.hazard_opens} / 消防到期 ${b.agg.fire_ext_dues} / 报警 ${b.agg.alarms.fire + b.agg.alarms.central}`
                    : ''
                  return (
                    <g
                      key={geo.id}
                      data-testid={`building-poly-${geo.id}`}
                      className="cursor-pointer [&:hover_polygon]:stroke-[2.2]"
                      onClick={() => setOpenId(geo.id)}
                    >
                      <title>{`${b.def.id} ${b.def.name ?? '待命名'} · ${b.def.depts.join(' / ')}${counts}`}</title>
                      {geo.pieces.flatMap((piece, pi) =>
                        piece.shapes.map((points, i) => (
                          <polygon
                            key={`${pi}-${i}`}
                            points={points}
                            fill={active ? fam.fillActive : fam.fillBase}
                            stroke={active ? fam.strokeActive : fam.strokeBase}
                            strokeWidth={active ? 1.4 : 1}
                          />
                        )),
                      )}
                    </g>
                  )
                })}
                {labels.map(l => (
                  <text
                    key={`lb-${l.id}-${l.x.toFixed(1)}-${l.y.toFixed(1)}`}
                    data-testid={`building-label-${l.id}`}
                    x={l.x}
                    y={l.y}
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
                    {l.text}
                  </text>
                ))}
                {buildings.map(b => {
                  const geo = GEO_BY_ID.get(b.def.id)
                  if (!geo) return null
                  const pin = buildingCountsPin(b)
                  if (!badgeChips(pin).length) return null
                  return (
                    <BadgeGroup
                      key={`bg-${b.def.id}`}
                      buildingId={b.def.id}
                      pin={pin}
                      anchor={geo.anchor}
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
            {/* 未映射栏：xl 固定 300px 窄栏，高度=地图高度表达式（与
                MAP_MAX_H_* 常量同步改），清单在栏内滚轮滚动（不设高度时
                行高会被清单内容撑开） */}
            <aside className="flex min-w-0 flex-col xl:h-[min(75vh,760px)] xl:flex-none xl:w-[300px]">
              <div className="flex flex-col rounded-lg border border-[var(--color-hairline-soft)] bg-[var(--color-surface)] px-3 py-2 xl:min-h-0 xl:flex-1">
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <span className="text-[13px] font-medium text-[var(--color-charcoal)]">
                    未映射 {data.unmapped.length} 处
                    <span className="ml-1 font-normal text-[var(--color-steel)]">
                      （{unmappedEvents} 条事件）
                    </span>
                  </span>
                  <Button type="primary" ghost size="small" onClick={() => setConfirmOpen(true)}>
                    AI 建议映射 →
                  </Button>
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--color-steel)]">
                  未映射=地点文本未能对应分区；AI 建议经人工确认后写入映射（只增不改）
                </div>
                {data.unmapped.length > 0 ? (
                  <div className="mt-2 grid min-h-0 max-h-48 flex-1 grid-cols-1 gap-y-1 overflow-y-auto border-t border-[var(--color-hairline-soft)] pt-2 xl:max-h-none">
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
                ) : (
                  <div className="mt-2 border-t border-[var(--color-hairline-soft)] pt-2 text-[12px] text-[var(--color-steel)]">
                    当日无未映射事件
                  </div>
                )}
              </div>
            </aside>
          </div>
        </div>
      )}
      <BuildingModal
        building={openId === null ? null : (buildingById.get(openId) ?? null)}
        date={data?.date ?? ''}
        onClose={() => setOpenId(null)}
      />
      <AiSuggestionConfirmModal<DistrictSuggestionRow>
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="未映射地点 · AI 分区建议确认"
        description="扫描近 30 天作业票/报警/隐患/消防设施等来源的未映射地点文本，AI 逐条给出分区建议与置信度；确认后写入映射资产（location_district_map，只增不改），忽略后不再建议。"
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

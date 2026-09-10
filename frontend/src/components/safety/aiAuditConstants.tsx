// AI 调用审计页 UI 常量、格式化工具与微型展示组件
// 配色全部取自 dazah-frontend/DESIGN.md tokens（Notion 风设计系统）
// 含 JSX（ScenarioTag / StatusDot），故为 .tsx

import { Tooltip } from 'antd'

// ── 场景 → 视觉映射（soft tag 浅底深字 + 趋势图柱色） ──
export interface ScenarioUi {
  label: string
  bg: string
  text: string
  chart: string
}

export const SCENARIO_UI: Record<string, ScenarioUi> = {
  agent_chat: {
    label: '助手对话',
    bg: '#e6e0f5', // card-tint-lavender
    text: '#391c57', // brand-purple-800
    chart: '#7b3ff2', // brand-purple
  },
  knowledge_chat: {
    label: '知识库问答',
    bg: '#dcecfa', // card-tint-sky
    text: '#005bab', // link-blue-pressed
    chart: '#0075de', // link-blue
  },
  hazard_identification: {
    label: '隐患识别',
    bg: '#ffe8d4', // card-tint-peach
    text: '#793400', // brand-orange-deep
    chart: '#dd5b00', // brand-orange
  },
  hazard_id_bitable: {
    label: '危险源辨识',
    bg: '#fef7d6', // card-tint-yellow
    text: '#0a1530', // brand-navy (高对比，区别于隐患识别 peach/orange)
    chart: '#f5d75e', // brand-yellow
  },
  rectification_review: {
    label: '整改初审',
    bg: '#d9f3e1', // card-tint-mint
    text: '#1aae39', // brand-green
    chart: '#1aae39',
  },
  graph_build: {
    label: '图谱构建',
    bg: '#f8f5e8', // card-tint-cream
    text: '#523410', // brand-brown
    chart: '#2a9d99', // brand-teal
  },
  regulation_crawl: {
    label: '法规筛选',
    bg: '#fde0ec', // card-tint-rose
    text: '#a02e6d', // brand-pink-deep
    chart: '#ff64c8', // brand-pink
  },
  drill_plan_generation: {
    label: '演练预案生成',
    bg: '#e6e0f5', // card-tint-lavender
    text: '#391c57', // brand-purple-800
    chart: '#7b3ff2', // brand-purple
  },
  drill_report_generation: {
    label: '演练报告生成',
    bg: '#d9f3e1', // card-tint-mint
    text: '#1aae39', // brand-green
    chart: '#1aae39',
  },
  drill_issue_parsing: {
    label: '演练问题解析',
    bg: '#fdf0d9', // card-tint-amber
    text: '#7a5d00', // amber-deep
    chart: '#c49d00', // amber
  },
  drill_plan_parsing: {
    label: '演练计划解析',
    bg: '#e0e2f5', // card-tint-indigo
    text: '#2d2f7a', // indigo-deep
    chart: '#5c5fcc', // indigo
  },
  drill_eval_parsing: {
    label: '演练评估解析',
    bg: '#d9f3e1', // card-tint-mint
    text: '#1aae39', // brand-green
    chart: '#1aae39',
  },
  embedding: {
    label: '向量嵌入',
    bg: '#e0e2f5', // card-tint-indigo
    text: '#2d2f7a', // indigo-deep
    chart: '#5c5fcc', // indigo
  },
  rerank: {
    label: '相关性重排',
    bg: '#fdf0d9', // card-tint-amber
    text: '#7a5d00', // amber-deep
    chart: '#c49d00', // amber
  },
  memory_extraction: {
    label: '记忆提取',
    bg: '#fce4d6', // warm-coral-tint
    text: '#8b3a1a', // warm-coral-deep
    chart: '#e07b4a', // warm-coral
  },
  daily_report_analysis: {
    label: '日报AI分析',
    bg: '#e6e0f5', // purple-tint
    text: '#5e3f94', // purple-deep
    chart: '#7b3ff2', // brand-purple
  },
  ehs_change_review: {
    label: 'EHS变更审核',
    bg: '#d5ecf7', // info-tint
    text: '#0f5c82', // info-deep
    chart: '#1677ff', // brand-blue
  },
  contractor_admission_review: {
    label: '相关方准入审核',
    bg: '#d9f3e1', // card-tint-mint
    text: '#0f5c4f', // teal-deep（衍生自 brand-teal）
    chart: '#2a9d99', // brand-teal
  },
  msds_extraction: {
    label: 'MSDS提取',
    bg: '#d5ecf7', // info-tint
    text: '#0f5c82', // info-deep
    chart: '#1677ff', // brand-blue
  },
  sop_generation: {
    label: '操规AI补全',
    bg: '#d5ecf7', // info-tint
    text: '#0f5c82', // info-deep
    chart: '#1677ff', // brand-blue
  },
  sop_review: {
    label: '操规AI审核',
    bg: '#d9f3e1', // card-tint-mint
    text: '#0f5c4f', // teal-deep（衍生自 brand-teal）
    chart: '#2a9d99', // brand-teal
  },
  regulation_ocr: {
    label: '法规扫描件OCR',
    bg: '#fdf0e4', // card-tint-peach
    text: '#9a4b0f', // orange-deep
    chart: '#e8813a', // brand-orange
  },
  oh_transfer_hazard_diff: {
    label: '转岗危害差异',
    bg: '#d9f3e1', // card-tint-mint
    text: '#0f5c4f', // teal-deep（衍生自 brand-teal）
    chart: '#2a9d99', // brand-teal
  },
  oh_exam_report_parsing: {
    label: '体检AI解析',
    bg: '#d5ecf7', // info-tint（与 msds_extraction 同 info 族，AI 解析类场景归组）
    text: '#0f5c82', // info-deep
    chart: '#1677ff', // brand-blue
  },
  fire_alarm_analysis: {
    label: '消防报警分析',
    bg: '#fde0ec', // card-tint-rose（消防/error 语义底色）
    text: '#e03131', // semantic-error
    chart: '#e03131', // semantic-error
  },
  central_alarm_analysis: {
    label: '中控报警分析',
    bg: '#dcecfa', // card-tint-sky（中控/工艺语义底色）
    text: '#005bab', // link-blue-pressed
    chart: '#005bab',
  },
  unknown: {
    label: '未归因',
    bg: '#f0eeec', // card-tint-gray
    text: '#787671', // steel
    chart: '#a4a097', // stone
  },
}

export function scenarioUi(scenario: string): ScenarioUi {
  return SCENARIO_UI[scenario] ?? { ...SCENARIO_UI.unknown, label: scenario }
}

// ── 渠道 → 视觉映射（比场景 tag 更低调的中性配色） ──
export const CHANNEL_UI: Record<string, { label: string; bg: string; text: string }> = {
  web: { label: 'Web', bg: '#f0eeec', text: '#5d5b54' }, // card-tint-gray / slate
  feishu: { label: '飞书', bg: '#d9f3e1', text: '#1aae39' }, // card-tint-mint / brand-green
  system: { label: '系统', bg: '#f8f5e8', text: '#523410' }, // card-tint-cream / brand-brown
}

// ── 通用色 tokens ──
export const UI = {
  hairline: '#e5e3df',
  hairlineSoft: '#ede9e4',
  surface: '#f6f5f4',
  surfaceSoft: '#fafaf9',
  canvas: '#ffffff',
  ink: '#1a1a1a',
  charcoal: '#37352f',
  slate: '#5d5b54',
  steel: '#787671',
  stone: '#a4a097',
  success: '#1aae39',
  warning: '#dd5b00',
  error: '#e03131',
  roseTint: '#fde0ec', // 失败卡浅底
  grayTint: '#f0eeec', // system 气泡底
  skyTint: '#dcecfa', // user 气泡底
} as const

export const MONO_FONT =
  'ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace'

// ── 耗时三档染色阈值（ms） ──
export const LATENCY_WARN_MS = 5_000
export const LATENCY_SLOW_MS = 15_000

export function latencyColor(ms: number | null | undefined): string | undefined {
  if (ms == null) return undefined
  if (ms > LATENCY_SLOW_MS) return UI.error
  if (ms > LATENCY_WARN_MS) return UI.warning
  return undefined
}

export function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return `${(ms / 1000).toFixed(1)}s`
}

// ── Token 缩写：1234 → 1.2k；2_100_000 → 2.1M ──
export function formatTokensAbbrev(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

// ── 前缀缓存命中率：hit / (hit + miss)，双方均无数据时返回 null ──
export function cacheHitRate(
  hit: number | null | undefined,
  miss: number | null | undefined,
): number | null {
  const h = hit ?? 0
  const m = miss ?? 0
  const total = h + m
  if (total <= 0) return null
  return h / total
}

export function formatCacheRate(
  hit: number | null | undefined,
  miss: number | null | undefined,
): string {
  const rate = cacheHitRate(hit, miss)
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(0)}%`
}

// ── 相对时间：<1min 刚刚；<1h N分钟前；<24h N小时前；否则 MM-DD HH:mm ──
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`
  const d = new Date(t)
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN')
}

// ── input_text 是 messages JSON（后端 json.dumps(messages)）→ 解析为对话气泡 ──
export interface ChatMessage {
  role: string
  content: string
}

export function parseMessages(text: string | null | undefined): ChatMessage[] | null {
  if (!text) return null
  try {
    const parsed: unknown = JSON.parse(text)
    if (!Array.isArray(parsed) || parsed.length === 0) return null
    const messages: ChatMessage[] = []
    for (const item of parsed) {
      if (typeof item !== 'object' || item === null) return null
      const role = (item as { role?: unknown }).role
      const content = (item as { content?: unknown }).content
      if (typeof role !== 'string') return null
      // vision 消息 content 可能是数组，取其中文本部分；否则序列化兜底
      let contentStr: string
      if (typeof content === 'string') {
        contentStr = content
      } else if (Array.isArray(content)) {
        contentStr = content
          .map((part) => {
            if (typeof part === 'object' && part !== null) {
              const p = part as { type?: string; text?: string; image_url?: unknown }
              if (p.type === 'text' && typeof p.text === 'string') return p.text
              if (p.type === 'image_url') return '[图片]'
            }
            return ''
          })
          .filter(Boolean)
          .join('\n')
      } else {
        contentStr = JSON.stringify(content)
      }
      messages.push({ role, content: contentStr })
    }
    return messages
  } catch {
    return null
  }
}

// ═══════════════════════════════════════════════════════════════
// 微型展示组件（表格与详情抽屉共用）
// ═══════════════════════════════════════════════════════════════

/** 场景 soft tag：浅底深字、6px 圆角（DESIGN.md badge-tag-* 模式） */
export function ScenarioTag({ scenario }: { scenario: string }) {
  const ui = scenarioUi(scenario)
  return (
    <span
      style={{
        display: 'inline-block',
        background: ui.bg,
        color: ui.text,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: '20px',
        padding: '0 8px',
        borderRadius: 6,
        whiteSpace: 'nowrap',
      }}
    >
      {ui.label}
    </span>
  )
}

/** 渠道 soft tag：Web / 飞书 / 系统；未知渠道显示原值，空值显示 — */
export function ChannelTag({ channel }: { channel: string | null | undefined }) {
  if (!channel) return <span style={{ color: UI.stone, fontSize: 12 }}>—</span>
  const ui = CHANNEL_UI[channel] ?? { label: channel, bg: UI.grayTint, text: UI.steel }
  return (
    <span
      style={{
        display: 'inline-block',
        background: ui.bg,
        color: ui.text,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: '20px',
        padding: '0 8px',
        borderRadius: 6,
        whiteSpace: 'nowrap',
      }}
    >
      {ui.label}
    </span>
  )
}

/** 状态色点：成功绿 / 失败红，降级时附警示字样；tooltip 显示完整状态 */
export function StatusDot({
  status,
  degradationLevel,
}: {
  status: string
  degradationLevel?: string | null
}) {
  const ok = status === 'success'
  const degraded = !!degradationLevel && degradationLevel !== 'full'
  const tip = `${ok ? '成功' : '失败'}${degraded ? ` · 检索降级(${degradationLevel})` : ''}`
  return (
    <Tooltip title={tip}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: ok ? UI.success : UI.error,
          }}
        />
        {degraded && (
          <span style={{ fontSize: 11, color: UI.warning, fontWeight: 600 }}>降级</span>
        )}
      </span>
    </Tooltip>
  )
}

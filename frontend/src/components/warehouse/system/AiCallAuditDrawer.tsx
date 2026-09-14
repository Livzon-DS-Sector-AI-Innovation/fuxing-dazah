'use client'

// AI 调用审计详情抽屉（对齐 safety/AiAuditDetailDrawer 的信息架构，按仓库行结构适配）
// 输入/输出为 JSON 全文（input_json.messages / output_json.content+tool_calls+
// reasoning_content）；64K 截断形态为 {truncated:true,preview}，渲染时标注。

import { Alert, Collapse, Drawer, Space, Tag, Typography } from 'antd'
import type { WarehouseAiAuditListItem } from '@/types/warehouse'
import {
  MONO_FONT,
  UI,
  formatLatency,
  formatNumber,
  formatTime,
  scenarioLabel,
} from './systemConfigConstants'

const { Text } = Typography

interface AiCallAuditDrawerProps {
  open: boolean
  detail: WarehouseAiAuditListItem | null
  loading?: boolean
  onClose: () => void
}

/** 输入/输出 JSON 块（滚动展示 + truncated 标注） */
function JsonBlock({
  title,
  json,
  height = 320,
}: {
  title: React.ReactNode
  json: Record<string, unknown> | null
  height?: number
}) {
  if (!json) return null
  const truncated = json.truncated === true
  const body = truncated
    ? String(json.preview ?? '')
    : JSON.stringify(json, null, 2)
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 6, display: 'flex', alignItems: 'center' }}>
        {title}
        {truncated ? (
          <Tag color="orange" style={{ marginLeft: 8 }}>
            已截断（64K）
          </Tag>
        ) : null}
      </div>
      <pre
        style={{
          margin: 0,
          fontFamily: MONO_FONT,
          fontSize: 12,
          lineHeight: 1.6,
          color: UI.charcoal,
          background: UI.surface,
          border: `1px solid ${UI.hairlineSoft}`,
          borderRadius: 8,
          padding: 12,
          maxHeight: height,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {body || '（空）'}
      </pre>
    </div>
  )
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.5, color: UI.steel, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, color: UI.ink, wordBreak: 'break-all' }}>{children}</div>
    </div>
  )
}

export default function AiCallAuditDrawer({ open, detail, loading, onClose }: AiCallAuditDrawerProps) {
  const inputJson = detail?.input_json ?? null
  const outputJson = detail?.output_json ?? null
  const toolCalls = Array.isArray(outputJson?.tool_calls) ? (outputJson?.tool_calls as unknown[]) : []
  const reasoning =
    typeof outputJson?.reasoning_content === 'string' && outputJson.reasoning_content
      ? String(outputJson.reasoning_content)
      : null
  const toolNames = detail?.tool_names ?? []

  return (
    <Drawer
      width={760}
      open={open}
      onClose={onClose}
      loading={loading && !detail}
      title={
        detail ? (
          <Space size={8} wrap>
            <Tag
              color={detail.status === 'success' ? 'success' : 'error'}
              style={{ borderRadius: 6, fontWeight: 600 }}
            >
              {detail.status === 'success' ? '成功' : '失败'}
            </Tag>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{scenarioLabel(detail.scenario)}</span>
            {detail.resource ? (
              <span style={{ fontFamily: MONO_FONT, fontSize: 12, color: UI.steel }}>
                {detail.resource}
              </span>
            ) : null}
            <span style={{ fontSize: 12, color: UI.slate }}>{formatTime(detail.created_at)}</span>
          </Space>
        ) : (
          'AI 调用详情'
        )
      }
    >
      {detail && (
        <>
          {/* 元信息网格 */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '12px 16px',
              background: UI.surface,
              borderRadius: 8,
              padding: '12px 16px',
            }}
          >
            <MetaItem label="模型">{detail.model}</MetaItem>
            <MetaItem label="TOKEN 入 / 出">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatNumber(detail.input_tokens)} / {formatNumber(detail.output_tokens)}
              </span>
            </MetaItem>
            <MetaItem label="缓存命中">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatNumber(detail.cache_hit_tokens)}
              </span>
            </MetaItem>
            <MetaItem label="耗时">
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatLatency(detail.latency_ms)}</span>
            </MetaItem>
            <MetaItem label="降级">{detail.degradation_level || '—'}</MetaItem>
            <MetaItem label="PROMPT 版本">
              <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>
                {detail.prompt_version ?? '—'}
              </span>
            </MetaItem>
            <MetaItem label="TRACE ID">
              {detail.trace_id ? (
                <Text copyable={{ text: detail.trace_id }} style={{ fontFamily: MONO_FONT, fontSize: 12 }}>
                  {detail.trace_id.slice(0, 16)}
                  {detail.trace_id.length > 16 ? '…' : ''}
                </Text>
              ) : (
                '—'
              )}
            </MetaItem>
            <MetaItem label="CHAT ID">
              <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>{detail.chat_id ?? '—'}</span>
            </MetaItem>
            <MetaItem label="用户 OPEN ID">
              <span style={{ fontFamily: MONO_FONT, fontSize: 12 }}>
                {detail.user_open_id ?? '—'}
              </span>
            </MetaItem>
          </div>

          {/* 失败原因 */}
          {detail.error ? (
            <Alert
              type="error"
              showIcon
              style={{ marginTop: 16 }}
              message="调用失败"
              description={<span style={{ whiteSpace: 'pre-wrap' }}>{detail.error}</span>}
            />
          ) : null}

          {/* 工具清单 */}
          {toolNames.length > 0 ? (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 6 }}>
                本轮请求工具（tool_names）
              </div>
              <Space size={4} wrap>
                {toolNames.map((t) => (
                  <Tag key={t} style={{ fontFamily: MONO_FONT, borderRadius: 6 }}>
                    {t}
                  </Tag>
                ))}
              </Space>
            </div>
          ) : null}

          {/* 输入全文 */}
          <JsonBlock title="输入（input_json · messages）" json={inputJson} height={360} />

          {/* 推理内容 */}
          {reasoning ? (
            <Collapse
              ghost
              style={{ marginTop: 8, background: UI.gray, borderRadius: 8, padding: '0 12px' }}
              items={[
                {
                  key: 'reasoning',
                  label: (
                    <span style={{ fontSize: 12, fontWeight: 600, color: UI.slate }}>
                      reasoning_content（思考过程）
                    </span>
                  ),
                  children: (
                    <div
                      style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontSize: 12,
                        lineHeight: 1.6,
                        color: UI.slate,
                        maxHeight: 240,
                        overflow: 'auto',
                      }}
                    >
                      {reasoning}
                    </div>
                  ),
                },
              ]}
            />
          ) : null}

          {/* 输出全文（含 tool_calls） */}
          <JsonBlock
            title={
              <span>
                输出（output_json）
                {toolCalls.length > 0 ? (
                  <Tag style={{ marginLeft: 8 }} color="purple">
                    tool_calls × {toolCalls.length}
                  </Tag>
                ) : null}
              </span>
            }
            json={outputJson}
            height={360}
          />
        </>
      )}
    </Drawer>
  )
}

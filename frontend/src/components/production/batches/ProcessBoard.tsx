'use client'

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Empty, Popover, Select, Skeleton, Tag } from 'antd'
import {
  ArrowRightOutlined,
  ReloadOutlined,
  ScheduleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { fetchProcessBoardClient, fetchRoutesClient } from '@/lib/api/production-client'
import type {
  NodeExecutionListItem,
  ProcessBoardData,
  ProcessBoardExecution,
  ProcessBoardNode,
  ProcessBoardPlannedItem,
} from '@/types/production'
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer'
import { BatchHoverCard, PlannedHoverCard, BOARD_STATE_META } from './BatchHoverCard'
import { STATUS_META as ROUTE_STATUS_META } from '../process/RouteVersionBar'

// 动效常量：统一缓动曲线，保证"丝滑"一致的节奏
const EASE_OUT: [number, number, number, number] = [0.22, 0.61, 0.36, 1]
const COL_WIDTH = 200
const BOARD_HEIGHT = 520
const BOARD_HEADER_H = 64

/** 骨架屏呼吸动画 */
const FLOW_STYLE = `
@keyframes board-pulse {
  0%, 100% { opacity: 0.45; }
  50% { opacity: 0.9; }
}
.board-pulse { animation: board-pulse 1.5s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .board-pulse { animation: none; }
}
`

function countBoard(board: ProcessBoardData | undefined) {
  let running = 0
  let aborted = 0
  let waiting = 0
  for (const items of Object.values(board?.columns ?? {})) {
    for (const it of items) {
      if (it.board_state === 'in_progress') running++
      else if (it.board_state === 'aborted') aborted++
      else waiting++
    }
  }
  return { running, aborted, waiting, planned: board?.planned.length ?? 0 }
}

function CountBadge({ count }: { count: number }) {
  return (
    <motion.span
      key={count}
      initial={{ scale: 1.35 }}
      animate={{ scale: 1 }}
      transition={{ type: 'spring', stiffness: 520, damping: 24 }}
      style={{
        minWidth: 22,
        height: 18,
        padding: '0 6px',
        borderRadius: 9,
        background: 'var(--color-surface)',
        color: 'var(--color-slate)',
        fontSize: 11,
        fontWeight: 600,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginLeft: 'auto',
      }}
    >
      {count}
    </motion.span>
  )
}

function FlowConnector() {
  return (
    <div
      style={{
        width: 22,
        flexShrink: 0,
        alignSelf: 'stretch',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: BOARD_HEADER_H / 2 - 9,
          left: 0,
          right: 0,
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <ArrowRightOutlined style={{ color: '#c8c4be', fontSize: 12 }} />
      </div>
    </div>
  )
}

interface ChipProps {
  batchNo: string
  dot?: string
  delay: number
  children: ReactNode
  onClick?: () => void
}

function Chip({ batchNo, dot, delay, children, onClick }: ChipProps) {
  return (
    <Popover
      content={children}
      trigger="hover"
      mouseEnterDelay={0.12}
      mouseLeaveDelay={0.15}
      placement="right"
      styles={{ content: { padding: 10, borderRadius: 10 } }}
    >
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{
          opacity: 1,
          y: 0,
          transition: { duration: 0.26, ease: EASE_OUT, delay },
        }}
        exit={{ opacity: 0, transition: { duration: 0.15, ease: 'easeIn' } }}
        whileHover={{ y: -2, transition: { duration: 0.16, ease: 'easeOut' } }}
        onClick={onClick}
        style={{
          height: 34,
          maxWidth: '100%',
          flex: '0 0 auto',
          display: 'flex',
          alignItems: 'center',
          padding: '0 10px',
          background: '#fff',
          border: '1px solid var(--color-hairline-soft)',
          borderLeft: dot ? `3px solid ${dot}` : undefined,
          borderRadius: 8,
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--color-charcoal)',
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1,
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          cursor: onClick ? 'pointer' : 'default',
          boxShadow: '0 1px 2px rgba(15,15,15,0.03)',
        }}
      >
        {batchNo}
      </motion.div>
    </Popover>
  )
}

function PlannedColumn({
  items,
  delay,
}: {
  items: ProcessBoardPlannedItem[]
  delay: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.34, ease: EASE_OUT, delay } }}
      style={{
        width: COL_WIDTH,
        flexShrink: 0,
        height: BOARD_HEIGHT,
        display: 'flex',
        flexDirection: 'column',
        background: 'linear-gradient(180deg, #f7f4fd 0%, #fbf9ff 100%)',
        border: '1px dashed #cfc6ee',
        borderRadius: 12,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: BOARD_HEADER_H,
          padding: '10px 12px',
          borderBottom: '1px dashed #e0d9f2',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <ScheduleOutlined style={{ color: '#7b5fd9', fontSize: 13 }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink)' }}>
            计划批次
          </span>
          <CountBadge count={items.length} />
        </div>
        <div style={{ fontSize: 11, color: '#9a8fd0', marginTop: 2 }}>
          已分配 · 待开工
        </div>
      </div>
      <div
        style={{
          padding: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          flex: 1,
          overflowY: 'auto',
        }}
      >
        {items.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#b3a9da', fontSize: 12, padding: '18px 0' }}>
            暂无
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {items.map((item, i) => (
              <Chip
                key={item.batch_id}
                batchNo={item.batch_no}
                delay={Math.min(delay + i * 0.03, 0.6)}
              >
                <PlannedHoverCard item={item} />
              </Chip>
            ))}
          </AnimatePresence>
        )}
      </div>
    </motion.div>
  )
}

function NodeColumn({
  node,
  items,
  delay,
  onOpen,
}: {
  node: ProcessBoardNode
  items: ProcessBoardExecution[]
  delay: number
  onOpen: (item: ProcessBoardExecution) => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.34, ease: EASE_OUT, delay } }}
      style={{
        width: COL_WIDTH,
        flexShrink: 0,
        height: BOARD_HEIGHT,
        display: 'flex',
        flexDirection: 'column',
        background: '#fff',
        border: '1px solid var(--color-hairline)',
        borderRadius: 12,
        overflow: 'hidden',
        boxShadow: '0 1px 2px rgba(15,15,15,0.04)',
      }}
    >
      <div
        style={{
          height: BOARD_HEADER_H,
          padding: '10px 12px',
          borderBottom: '1px solid var(--color-hairline-soft)',
          background: 'linear-gradient(180deg, #fff 0%, #fafaf9 100%)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--color-ink)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {node.name}
          </span>
          <CountBadge count={items.length} />
        </div>
        <div
          style={{
            fontSize: 11,
            color: 'var(--color-stone)',
            marginTop: 2,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {node.node_code}
          {node.stage_name ? ` · ${node.stage_name}` : ''}
        </div>
      </div>
      <div
        style={{
          padding: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          flex: 1,
          overflowY: 'auto',
        }}
      >
        {items.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              color: 'var(--color-stone)',
              fontSize: 12,
              padding: '18px 0',
            }}
          >
            暂无
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {items.map((item, i) => (
              <Chip
                key={item.execution_id}
                batchNo={item.batch_no}
                dot={BOARD_STATE_META[item.board_state]?.dot ?? '#a4a097'}
                delay={Math.min(delay + i * 0.03, 0.6)}
                onClick={() => onOpen(item)}
              >
                <BatchHoverCard item={item} />
              </Chip>
            ))}
          </AnimatePresence>
        )}
      </div>
    </motion.div>
  )
}

function BoardSkeleton() {
  return (
    <div style={{ display: 'flex', gap: 12, overflow: 'hidden' }}>
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          style={{
            width: COL_WIDTH,
            flexShrink: 0,
            height: BOARD_HEIGHT,
            border: '1px solid var(--color-hairline)',
            borderRadius: 12,
            padding: 10,
            background: '#fff',
          }}
        >
          <Skeleton active paragraph={{ rows: 1 }} title={false} style={{ marginBottom: 10 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[0, 1, 2, 3].map(j => (
              <div
                key={j}
                className="board-pulse"
                style={{
                  height: 34,
                  borderRadius: 8,
                  background: 'var(--color-surface-soft)',
                }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ProcessBoard({ productId }: { productId: string }) {
  const [routeId, setRouteId] = useState<string | null>(null)
  const [detail, setDetail] = useState<NodeExecutionListItem | null>(null)

  const { data: routes } = useQuery({
    queryKey: ['production-routes', productId],
    queryFn: () => fetchRoutesClient(productId),
  })

  const { data: board, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['production-process-board', routeId],
    queryFn: () => fetchProcessBoardClient(routeId!),
    enabled: !!routeId,
  })

  const { running, aborted, waiting, planned } = useMemo(() => countBoard(board), [board])

  const handleOpenDetail = (item: ProcessBoardExecution) => {
    setDetail({
      id: item.execution_id,
      batch_id: item.batch_id,
      batch_no: item.batch_no,
      execution_seq: item.execution_seq,
      status: item.status,
      owner_name: item.owner_name,
      started_at: item.started_at,
      finished_at: item.finished_at,
      is_deviation: item.is_deviation,
      abnormal_count: item.abnormal_count,
    })
  }

  return (
    <MotionConfig reducedMotion="user">
      <style>{FLOW_STYLE}</style>

      {/* 工具栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <Select
          placeholder="选择工艺路线"
          style={{ width: 264 }}
          value={routeId}
          onChange={setRouteId}
          options={(routes ?? []).map(r => ({
            value: r.id,
            label: `${r.route_name}（${ROUTE_STATUS_META[r.status]?.label ?? r.status}）`,
          }))}
        />
        <div style={{ flex: 1 }} />
        {routeId && (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 12,
                color: 'var(--color-steel)',
              }}
            >
              {Object.entries(BOARD_STATE_META).map(([state, meta]) => (
                <span key={state} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: meta.dot }} />
                  {meta.label}
                </span>
              ))}
            </div>
            <Button
              size="small"
              icon={<ReloadOutlined spin={isFetching} />}
              onClick={() => refetch()}
            >
              刷新
            </Button>
          </>
        )}
      </div>

      {!routeId ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>请选择工艺路线版本</span>}
          style={{ marginTop: 90 }}
        />
      ) : isLoading ? (
        <BoardSkeleton />
      ) : isError ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>看板数据加载失败</span>}
          style={{ marginTop: 90 }}
        >
          <Button size="small" onClick={() => refetch()}>重试</Button>
        </Empty>
      ) : board && board.nodes.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>该路线暂无工序节点</span>}
          style={{ marginTop: 90 }}
        />
      ) : board ? (
        <>
          {/* 摘要条 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              marginBottom: 12,
              fontSize: 12,
              color: 'var(--color-stone)',
            }}
          >
            <span style={{ fontWeight: 600, color: 'var(--color-ink)', fontSize: 13 }}>
              {board.route_name}
            </span>
            <Tag
              color={ROUTE_STATUS_META[board.route_status]?.color}
              style={{ marginInlineEnd: 0, lineHeight: '18px' }}
            >
              {ROUTE_STATUS_META[board.route_status]?.label ?? board.route_status}
            </Tag>
            <span>计划 {planned}</span>
            <span>· 进行中 {running}</span>
            <span>· 待流转 {waiting}</span>
            <span>· 已中止 {aborted}</span>
          </div>

          {/* 看板主体 */}
          <div style={{ overflowX: 'auto', paddingBottom: 6 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 0,
                width: 'max-content',
                minWidth: '100%',
              }}
            >
              <PlannedColumn items={board.planned} delay={0} />
              {board.nodes.map((node, i) => (
                <div key={node.id} style={{ display: 'contents' }}>
                  <FlowConnector />
                  <NodeColumn
                    node={node}
                    items={board.columns[node.id] ?? []}
                    delay={0.08 + i * 0.07}
                    onOpen={handleOpenDetail}
                  />
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {detail && (
        <ExecutionDetailDrawer item={detail} onClose={() => setDetail(null)} />
      )}
    </MotionConfig>
  )
}

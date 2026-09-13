'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Empty, Popover, Select, Skeleton, Tag, Tooltip } from 'antd'
import {
  ArrowRightOutlined,
  LeftOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  RightOutlined,
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
import styles from './ProcessBoard.module.css'

// 动效常量：统一缓动曲线，保证"丝滑"一致的节奏
const EASE_OUT: [number, number, number, number] = [0.22, 0.61, 0.36, 1]
const COL_WIDTH = 200
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
      className={styles.countBadge}
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
        <div
          style={{
            position: 'absolute',
            top: 10,
            left: 2,
            right: 2,
            height: 1,
            background: 'linear-gradient(90deg, rgba(200,196,190,0), rgba(200,196,190,0.8), rgba(200,196,190,0))',
          }}
        />
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
        className={`${styles.chip} ${onClick ? styles.chipClickable : ''}`}
        initial={{ opacity: 0, y: 8 }}
        animate={{
          opacity: 1,
          y: 0,
          transition: { duration: 0.26, ease: EASE_OUT, delay },
        }}
        exit={{ opacity: 0, transition: { duration: 0.15, ease: 'easeIn' } }}
        whileHover={{ y: -2, z: 7, transition: { duration: 0.16, ease: 'easeOut' } }}
        onClick={onClick}
        tabIndex={onClick ? 0 : undefined}
        role={onClick ? 'button' : undefined}
        onKeyDown={event => {
          if (onClick && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault()
            onClick()
          }
        }}
        style={dot ? { borderLeft: `3px solid ${dot}` } : undefined}
      >
        <span className={styles.batchNo}>{batchNo}</span>
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
      className={`${styles.column} ${styles.plannedColumn}`}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.34, ease: EASE_OUT, delay } }}
      whileHover={{ y: -3, rotateX: 1, transition: { duration: 0.2, ease: 'easeOut' } }}
    >
      <div className={styles.columnHeader}>
        <div className={styles.columnTitleRow}>
          <ScheduleOutlined style={{ color: '#7b5fd9', fontSize: 13 }} />
          <span className={styles.columnTitle}>计划批次</span>
          <CountBadge count={items.length} />
        </div>
        <div className={`${styles.columnMeta} ${styles.plannedMeta}`}>已分配 · 待开工</div>
      </div>
      <div className={styles.columnBody}>
        {items.length === 0 ? (
          <div className={`${styles.emptyColumn} ${styles.plannedEmptyColumn}`}>暂无</div>
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
  index,
  items,
  delay,
  onOpen,
}: {
  node: ProcessBoardNode
  index: number
  items: ProcessBoardExecution[]
  delay: number
  onOpen: (item: ProcessBoardExecution) => void
}) {
  return (
    <motion.div
      className={styles.column}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.34, ease: EASE_OUT, delay } }}
      whileHover={{ y: -3, rotateX: 1, transition: { duration: 0.2, ease: 'easeOut' } }}
    >
      <div className={styles.columnHeader}>
        <div className={styles.columnTitleRow}>
          <span className={styles.stepBadge}>{index + 1}</span>
          <span className={styles.columnTitle}>{node.name}</span>
          <CountBadge count={items.length} />
        </div>
        <div className={styles.columnMeta}>
          {node.node_code}
          {node.stage_name ? ` · ${node.stage_name}` : ''}
        </div>
      </div>
      <div className={styles.columnBody}>
        {items.length === 0 ? (
          <div className={styles.emptyColumn}>暂无</div>
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
    <div className={styles.track} style={{ gap: 12, overflow: 'hidden' }}>
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          className={styles.column}
          style={{ padding: 10 }}
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const [scrollState, setScrollState] = useState({ left: false, right: false })

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

  const updateScrollState = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const maxScrollLeft = Math.max(0, el.scrollWidth - el.clientWidth)
    const nextState = {
      left: el.scrollLeft > 4,
      right: el.scrollLeft < maxScrollLeft - 4,
    }
    setScrollState(prev => (
      prev.left === nextState.left && prev.right === nextState.right ? prev : nextState
    ))
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    updateScrollState()
    el.addEventListener('scroll', updateScrollState, { passive: true })
    const observer = new ResizeObserver(updateScrollState)
    observer.observe(el)
    return () => {
      el.removeEventListener('scroll', updateScrollState)
      observer.disconnect()
    }
  }, [routeId, board?.nodes.length, board?.planned.length, updateScrollState])

  const scrollByColumns = useCallback((direction: -1 | 1) => {
    scrollRef.current?.scrollBy({
      left: direction * (COL_WIDTH + 22) * 2,
      behavior: 'smooth',
    })
  }, [])

  const handleBoardWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    // 卡片内容有自己的纵向滚动容器：滚轮落在卡片内时交给它处理，
    // 避免禁用横向滚轮时影响批次较多时的纵向浏览。
    const isColumnBody = event.target instanceof Element && event.target.closest(`.${styles.columnBody}`)
    if (isColumnBody) {
      if (Math.abs(event.deltaX) > 0) event.preventDefault()
      return
    }
    // 横向视角只由左右按钮控制，阻止鼠标/触控板的横向 wheel 手势。
    if (Math.abs(event.deltaX) > 0) {
      event.preventDefault()
    }
  }

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
      estimated_duration_seconds: item.estimated_duration_seconds,
      expected_finish_at: item.expected_finish_at,
      timeout_monitor_status: item.timeout_monitor_status,
      timeout_notified_at: item.timeout_notified_at,
    })
  }

  return (
    <MotionConfig reducedMotion="user">
      <style>{FLOW_STYLE}</style>

      <div className={styles.processBoard}>
        <div className={styles.toolbar}>
          <div className={styles.toolbarTitle}>
            <div className={styles.toolbarEyebrow}>PROCESS FLOW</div>
            <div className={styles.toolbarHeading}>工序流转看板</div>
          </div>
          <Select
            className={styles.routeSelect}
            placeholder="选择工艺路线"
            value={routeId}
            onChange={setRouteId}
            options={(routes ?? []).map(r => ({
              value: r.id,
              label: `${r.route_name}（${ROUTE_STATUS_META[r.status]?.label ?? r.status}）`,
            }))}
          />
          <div className={styles.toolbarSpacer} />
          {routeId && (
            <>
              <div className={styles.legend} aria-label="批次状态图例">
                {Object.entries(BOARD_STATE_META).map(([state, meta]) => (
                  <span key={state} className={styles.legendItem}>
                    <span className={styles.legendDot} style={{ background: meta.dot }} />
                    {meta.label}
                  </span>
                ))}
              </div>
              <Tooltip title="刷新看板数据">
                <Button
                  size="small"
                  aria-label="刷新看板数据"
                  icon={<ReloadOutlined spin={isFetching} />}
                  onClick={() => refetch()}
                >
                  刷新
                </Button>
              </Tooltip>
            </>
          )}
        </div>

        {!routeId ? (
          <div className={styles.emptyState}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>请选择工艺路线版本</span>}
            />
          </div>
        ) : isLoading ? (
          <div className={styles.boardShell}>
            <div className={styles.viewport}>
              <BoardSkeleton />
            </div>
          </div>
        ) : isError ? (
          <div className={styles.emptyState}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>看板数据加载失败</span>}
            >
              <Button size="small" onClick={() => refetch()}>重试</Button>
            </Empty>
          </div>
        ) : board && board.nodes.length === 0 ? (
          <div className={styles.emptyState}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<span style={{ color: 'var(--color-steel)', fontSize: 14 }}>该路线暂无工序节点</span>}
            />
          </div>
        ) : board ? (
          <div className={styles.boardShell}>
            <div className={styles.summary}>
              <span className={styles.routeName}>{board.route_name}</span>
              <Tag
                color={ROUTE_STATUS_META[board.route_status]?.color}
                style={{ marginInlineEnd: 0, lineHeight: '18px' }}
              >
                {ROUTE_STATUS_META[board.route_status]?.label ?? board.route_status}
              </Tag>
              <div className={styles.summaryStats}>
                <span className={styles.stat}>计划 <strong>{planned}</strong></span>
                <span className={styles.stat}>进行中 <strong>{running}</strong></span>
                <span className={styles.stat}>待流转 <strong>{waiting}</strong></span>
                <span className={styles.stat}>已中止 <strong>{aborted}</strong></span>
              </div>
            </div>

            <button
              type="button"
              className={`${styles.navButton} ${styles.navButtonLeft}`}
              aria-label="向前查看工序"
              disabled={!scrollState.left}
              onClick={() => scrollByColumns(-1)}
            >
              <LeftOutlined />
            </button>
            <button
              type="button"
              className={`${styles.navButton} ${styles.navButtonRight}`}
              aria-label="向后查看工序"
              disabled={!scrollState.right}
              onClick={() => scrollByColumns(1)}
            >
              <RightOutlined />
            </button>
            {scrollState.left && <div className={`${styles.edgeFade} ${styles.edgeFadeLeft}`} />}
            {scrollState.right && <div className={`${styles.edgeFade} ${styles.edgeFadeRight}`} />}

            <div
              ref={scrollRef}
              className={styles.viewport}
              role="region"
              aria-label="工序流程看板，可横向浏览"
              onWheel={handleBoardWheel}
            >
              <div className={styles.track}>
                <PlannedColumn items={board.planned} delay={0} />
                {board.nodes.map((node, i) => (
                  <div key={node.id} style={{ display: 'contents' }}>
                    <FlowConnector />
                    <NodeColumn
                      node={node}
                      index={i}
                      items={board.columns[node.id] ?? []}
                      delay={0.08 + i * 0.07}
                      onOpen={handleOpenDetail}
                    />
                  </div>
                ))}
              </div>
            </div>
            <div className={styles.boardHint}>
              <span>点击左右方向按钮浏览后续工序</span>
            </div>
          </div>
        ) : null}

        {detail && (
          <ExecutionDetailDrawer item={detail} onClose={() => setDetail(null)} />
        )}
      </div>
    </MotionConfig>
  )
}

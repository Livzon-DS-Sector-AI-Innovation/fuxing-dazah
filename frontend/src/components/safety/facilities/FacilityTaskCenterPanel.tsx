'use client'

/**
 * 校验任务中心（facilities-p1 票 03）。
 *
 * 分桶 StatCard（待闭环/已闭环/已取消/逾期）→ 两视图：
 * ① 任务列表（筛选+分页，逾期在前）；② 部门/分组聚合视图（分组进度
 * 已闭环/总数，对应滚动批次卡口径）。详情抽屉：任务快照 + 事件流时间线
 * （含锚点前后值）+ 管理员操作（reopen/cancel，票 04 接通）。
 * 闭环由表格更新自动触发，页面只读反映（拍板口径：无 submit）。
 */
import { useMemo, useState } from 'react'
import { Button, Drawer, Input, Modal, Progress, Select, Table, Tag, Timeline, Tooltip, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelFacilityTask,
  fetchFacilityTaskDetail,
  fetchFacilityTaskSummary,
  fetchFacilityTasks,
  reopenFacilityTask,
} from '@/lib/api/safety/facilities'
import type { FacilityTask, FacilityTaskSummary } from '@/types/safety/facilities'
import { EmptyGuide, SectionCard, StatCard } from '@/components/ui-kit'
import {
  FACILITY_TASK_STATUS_UI,
  OVERDUE_WARN,
  facilityStatusUI,
  overdueColor,
} from './facilitiesConstants'

const TRIGGER_UI: Record<string, string> = {
  event: '表格变更事件',
  poll: '每日对账',
  manual: '管理员',
}

const EVENT_UI: Record<string, { label: string; color: string }> = {
  issued: { label: '派发', color: 'blue' },
  closed: { label: '闭环', color: 'green' },
  cancelled: { label: '取消', color: 'gray' },
  reminded: { label: '催办', color: 'orange' },
  escalated: { label: '逾期升级', color: 'red' },
  reopened: { label: '重新打开', color: 'purple' },
}

const BIZ_OPTIONS = [
  { value: 'accessory', label: '安全附件' },
  { value: 'fire_equipment', label: '消防器材' },
  { value: 'special_equipment', label: '特种设备' },
]

function fmtDate(value: string | null): string {
  return value ? value.slice(0, 10) : '—'
}

function StatusTagCell({ status, bizType }: { status: string; bizType?: string | null }) {
  const ui = facilityStatusUI(status, bizType)
  return <Tag color={ui.color}>{ui.label}</Tag>
}

export default function FacilityTaskCenterPanel() {
  const queryClient = useQueryClient()
  const [view, setView] = useState<'list' | 'group'>('list')
  // 默认只见未完成（「已闭环不再展示」拍板）；已闭环/已取消经筛选器显式查看
  const [status, setStatus] = useState<string | undefined>('issued')
  const [department, setDepartment] = useState('')
  const [bizType, setBizType] = useState<string | undefined>()
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [acting, setActing] = useState(false)

  const listQuery = useQuery({
    queryKey: ['facility-tasks', { status, department, bizType, overdueOnly, page, pageSize }],
    queryFn: () =>
      fetchFacilityTasks({
        status,
        department: department || undefined,
        biz_type: bizType,
        overdue: overdueOnly || undefined,
        page,
        page_size: pageSize,
      }),
    enabled: view === 'list',
  })
  const summaryQuery = useQuery({
    queryKey: ['facility-tasks-summary'],
    queryFn: fetchFacilityTaskSummary,
  })
  const detailQuery = useQuery({
    queryKey: ['facility-task-detail', detailId],
    queryFn: () => fetchFacilityTaskDetail(detailId as string),
    enabled: !!detailId,
  })

  const summary: FacilityTaskSummary | undefined = summaryQuery.data
  const rows: FacilityTask[] = listQuery.data?.items ?? []

  const departmentOptions = useMemo(() => {
    const depts = new Set<string>()
    summary?.by_department?.forEach((b) => depts.add(b.department))
    return Array.from(depts).sort().map((d) => ({ value: d, label: d }))
  }, [summary])

  const columns: ColumnsType<FacilityTask> = [
    {
      title: '设备编号',
      dataIndex: 'equipment_no',
      width: 110,
      render: (v: string | null, row) => (
        <a onClick={() => setDetailId(row.id)}>{v ?? row.ledger_key.slice(0, 8)}</a>
      ),
    },
    { title: '名称', dataIndex: 'equipment_name', width: 130, render: (v) => v ?? '—' },
    {
      title: '类型',
      dataIndex: 'biz_label',
      width: 90,
      render: (v: string, row) => (
        <Tooltip title={row.task_kind}>
          <Tag className="m-0">{v}</Tag>
        </Tooltip>
      ),
    },
    { title: '分组', dataIndex: 'group_key', width: 120 },
    { title: '部门', dataIndex: 'department', width: 100, render: (v) => v ?? '未填写' },
    { title: '责任人', dataIndex: 'assignee_name', width: 80, render: (v) => v ?? '—' },
    { title: '到期日', dataIndex: 'due_date', width: 100, render: fmtDate },
    {
      title: '剩余天数',
      dataIndex: 'remaining_days',
      width: 90,
      render: (v: number | null, row) => {
        if (row.status !== 'issued' || v === null || v === undefined) return '—'
        if (v < 0) {
          const color = overdueColor(v)
          if (color) return <span style={{ color, fontWeight: 600 }}>逾期 {Math.abs(v)} 天</span>
        }
        if (v <= 7) return <span style={{ color: OVERDUE_WARN, fontWeight: 600 }}>{v} 天</span>
        return `${v} 天`
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 88,
      render: (v: string, row) => <StatusTagCell status={v} bizType={row.biz_type} />,
    },
    {
      title: '闭环通道',
      dataIndex: 'closed_trigger',
      width: 100,
      render: (v: string | null) => (v ? TRIGGER_UI[v] ?? v : '—'),
    },
    { title: '催办', dataIndex: 'remind_count', width: 60 },
    {
      title: '记录',
      dataIndex: 'record_url',
      width: 88,
      render: (v: string | null) =>
        v ? (
          <a
            href={v}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            打开记录
          </a>
        ) : null,
    },
  ]

  const detail = detailQuery.data
  const detailTask = detail?.task

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['facility-task-detail', detailId] })
    queryClient.invalidateQueries({ queryKey: ['facility-tasks'] })
    queryClient.invalidateQueries({ queryKey: ['facility-tasks-summary'] })
  }

  const handleReopen = async () => {
    if (!detailId) return
    setActing(true)
    try {
      await reopenFacilityTask(detailId)
      message.success('已重新打开（回到待闭环）')
      invalidateAll()
    } catch {
      message.error('重新打开失败，请稍后重试')
    } finally {
      setActing(false)
    }
  }

  const handleCancel = async () => {
    if (!detailId || !cancelReason.trim()) return
    setActing(true)
    try {
      await cancelFacilityTask(detailId, cancelReason.trim())
      message.success('任务已取消')
      setCancelOpen(false)
      setCancelReason('')
      invalidateAll()
    } catch {
      message.error('取消失败，请稍后重试')
    } finally {
      setActing(false)
    }
  }

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="待闭环"
          value={summary ? String(summary.open) : '—'}
          tone={summary && summary.open > 0 ? 'warn' : 'default'}
          sub={`共 ${summary?.total ?? '—'} 条任务`}
          loading={summaryQuery.isLoading}
        />
        <StatCard
          label="已闭环"
          value={summary ? String(summary.closed) : '—'}
          tone="ok"
          sub="表格更新自动闭环"
          loading={summaryQuery.isLoading}
        />
        <StatCard
          label="逾期"
          value={summary ? String(summary.overdue) : '—'}
          tone={summary && summary.overdue > 0 ? 'danger' : 'default'}
          sub="每日 17:10 升级催办"
          loading={summaryQuery.isLoading}
        />
        <StatCard
          label="已取消"
          value={summary ? String(summary.cancelled) : '—'}
          tone="default"
          sub="行删除/停用自动取消"
          loading={summaryQuery.isLoading}
        />
        <StatCard
          label="闭环口径"
          value="盯表检测"
          tone="info"
          sub="责任人在多维表格更新校验时间"
        />
      </div>

      <SectionCard
        title="校验任务"
        description="到期前派发 · 责任人更新表格校验时间后自动闭环"
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              size="small"
              style={{ width: 110 }}
              allowClear
              placeholder="状态"
              value={status}
              onChange={(v) => {
                setStatus(v)
                setPage(1)
              }}
              options={Object.entries(FACILITY_TASK_STATUS_UI).map(([value, ui]) => ({
                value,
                label: ui.label,
              }))}
            />
            <Select
              size="small"
              style={{ width: 110 }}
              allowClear
              placeholder="台账类型"
              value={bizType}
              onChange={(v) => {
                setBizType(v)
                setPage(1)
              }}
              options={BIZ_OPTIONS}
            />
            <Select
              size="small"
              style={{ width: 130 }}
              allowClear
              showSearch
              placeholder="部门"
              value={department || undefined}
              onChange={(v) => {
                setDepartment(v ?? '')
                setPage(1)
              }}
              options={departmentOptions}
            />
            <Button
              size="small"
              type={overdueOnly ? 'primary' : 'default'}
              danger={overdueOnly}
              onClick={() => {
                setOverdueOnly(!overdueOnly)
                setPage(1)
              }}
            >
              仅逾期
            </Button>
            <Button
              size="small"
              type={view === 'group' ? 'primary' : 'default'}
              onClick={() => setView(view === 'list' ? 'group' : 'list')}
            >
              {view === 'list' ? '聚合视图' : '列表视图'}
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => {
                listQuery.refetch()
                summaryQuery.refetch()
              }}
            />
          </div>
        }
      >
        {view === 'list' ? (
          <Table
            columns={columns}
            dataSource={rows}
            rowKey="id"
            size="small"
            loading={listQuery.isLoading}
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: (
                <EmptyGuide
                  compact
                  title="暂无校验任务"
                  description="每日 08:10 自动派发临期校验任务；台账连接登记后生效"
                />
              ),
            }}
            onRow={(record) => ({ onClick: () => setDetailId(record.id) })}
            pagination={{
              current: page,
              pageSize,
              total: listQuery.data?.total ?? 0,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: (nextPage, nextPageSize) => {
                setPage(nextPage)
                setPageSize(nextPageSize)
              },
            }}
          />
        ) : (
          <div className="space-y-4">
            {(summary?.by_department ?? []).map((dept) => (
              <div key={dept.department}>
                <div className="mb-2 flex items-center gap-3">
                  <span style={{ fontWeight: 600 }}>{dept.department}</span>
                  <Tag color={dept.open > 0 ? 'orange' : 'green'}>
                    待闭环 {dept.open} / 共 {dept.total}
                  </Tag>
                  <Progress
                    style={{ maxWidth: 200, margin: 0 }}
                    size="small"
                    percent={dept.total ? Math.round((dept.closed * 100) / dept.total) : 0}
                    status={dept.open > 0 ? 'active' : 'success'}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {dept.groups.map((g) => (
                    <Tag
                      key={g.group_key}
                      color={g.closed >= g.total ? 'green' : 'blue'}
                      style={{ borderRadius: 6 }}
                    >
                      {g.group_key}：{g.closed}/{g.total}
                    </Tag>
                  ))}
                </div>
              </div>
            ))}
            {summary && summary.by_department.length === 0 && (
              <EmptyGuide
                compact
                title="暂无任务数据"
                description="任务派发编排交付且台账连接登记后，此处按部门/分组展示闭环进度"
              />
            )}
          </div>
        )}
      </SectionCard>

      <Drawer
        title={detailTask ? `任务详情 · ${detailTask.equipment_no ?? detailTask.ledger_key}` : '任务详情'}
        width={560}
        open={!!detailId}
        onClose={() => setDetailId(null)}
      >
        {detailTask ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1" style={{ fontSize: 13 }}>
              <span>设备：<b>{detailTask.equipment_no ?? '—'}</b>（{detailTask.equipment_name ?? '—'}）</span>
              <span>状态：<StatusTagCell status={detailTask.status} bizType={detailTask.biz_type} /></span>
              <span>台账类型：{detailTask.biz_label} · {detailTask.task_kind}</span>
              <span>分组：{detailTask.group_key}</span>
              <span>部门：{detailTask.department ?? '未填写'}</span>
              <span>责任人：{detailTask.assignee_name ?? '—'}</span>
              <span>到期日：{fmtDate(detailTask.due_date)}</span>
              <span>派发日：{fmtDate(detailTask.issued_on)}</span>
              <span>派发时锚点：{fmtDate(detailTask.anchor_at_dispatch)}</span>
              <span>闭环通道：{detailTask.closed_trigger ? TRIGGER_UI[detailTask.closed_trigger] ?? detailTask.closed_trigger : '—'}</span>
              {detailTask.closed_reason && <span>关闭原因：{detailTask.closed_reason}</span>}
            </div>
            <SectionCard title="事件流" description="append-only 审计（closed 事件含锚点前后值）">
              <Timeline
                items={(detail?.events ?? []).map((e) => {
                  const p = (e.payload ?? {}) as Record<string, string | undefined>
                  return {
                  color: EVENT_UI[e.event_type]?.color ?? 'blue',
                  children: (
                    <div style={{ fontSize: 13 }}>
                      <b>{EVENT_UI[e.event_type]?.label ?? e.event_type}</b>
                      <span style={{ color: '#a4a097', marginLeft: 8 }}>
                        {e.created_at ? new Date(e.created_at).toLocaleString('zh-CN') : ''}
                        {e.closed_trigger ? ` · ${TRIGGER_UI[e.closed_trigger] ?? e.closed_trigger}` : ''}
                      </span>
                      {p.anchor_before && (
                        <div style={{ color: '#6b675e' }}>
                          锚点 {p.anchor_before} → {p.anchor_after ?? '—'}
                        </div>
                      )}
                      {p.reason && (
                        <div style={{ color: '#6b675e' }}>原因：{p.reason}</div>
                      )}
                    </div>
                  ),
                  }
                })}
              />
            </SectionCard>
            <div style={{ color: '#a4a097', fontSize: 12 }}>
              闭环口径：责任人在多维表格更新校验时间（下次/上次校验日期），平台检测锚点前移后自动闭环；页面不收表单。
            </div>
            <div className="flex gap-2">
              {detailTask.status === 'issued' && (
                <Button danger loading={acting} onClick={() => setCancelOpen(true)}>
                  取消任务
                </Button>
              )}
              {detailTask.status !== 'issued' && (
                <Button loading={acting} onClick={handleReopen}>
                  重新打开（误关恢复）
                </Button>
              )}
            </div>
          </div>
        ) : (
          <span style={{ color: '#a4a097' }}>加载中…</span>
        )}
      </Drawer>

      <Modal
        title="取消校验任务"
        open={cancelOpen}
        confirmLoading={acting}
        okText="确认取消"
        okButtonProps={{ danger: true }}
        cancelText="返回"
        onOk={handleCancel}
        onCancel={() => {
          setCancelOpen(false)
          setCancelReason('')
        }}
      >
        <div style={{ marginBottom: 8, fontSize: 13, color: '#6b675e' }}>
          取消原因必填（事件留痕）；台账行已删除/停用时系统会自动取消，无需手动操作。
        </div>
        <Input.TextArea
          rows={3}
          maxLength={500}
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
          placeholder="如：设备已淘汰报废 / 重复派发"
        />
      </Modal>
    </div>
  )
}

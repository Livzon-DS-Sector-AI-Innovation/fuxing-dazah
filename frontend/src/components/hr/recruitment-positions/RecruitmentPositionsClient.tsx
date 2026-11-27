'use client'

// 招聘岗位信息页：岗位库里每个岗位保存一份「岗位职责 / 任职要求」，配置一次长期复用。
// 全量岗位一次拉回（几百个），部门 / 关键字 / 仅看未配置都在前端筛。

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Button, Checkbox, Empty, Input, Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { SearchOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import PageHeader from '@/components/hr/PageHeader'
import { useHasPermission } from '@/hooks/hr'
import { fetchRecruitmentPositionInfos } from '@/actions/hr'
import type { RecruitmentPositionInfo, RecruitmentPositionInfoSummary } from '@/types/hr'
import RecruitmentPositionInfoModal, { type RecruitmentPositionTarget } from './RecruitmentPositionInfoModal'
import styles from './recruitmentPositions.module.css'

type Row = RecruitmentPositionInfoSummary

/** 一次加载的结果。tick 记的是发起时的第几次加载，和当前的对不上就说明还在路上 */
interface LoadResult {
  tick: number
  rows: Row[]
  error: string | null
}

const formatTime = (value: string | null) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—')

export default function RecruitmentPositionsClient() {
  const canManage = useHasPermission('hr:recruitment:manage')
  const [reloadTick, setReloadTick] = useState(0)
  const [result, setResult] = useState<LoadResult | null>(null)
  const [department, setDepartment] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [onlyMissing, setOnlyMissing] = useState(false)
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState<RecruitmentPositionTarget | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)

  const loading = result?.tick !== reloadTick
  const rows = useMemo(() => result?.rows ?? [], [result])
  const loadError = loading ? null : (result?.error ?? null)

  // 请求写在 effect 内部；慢响应回来时若已有更新的请求，靠 tick 丢弃这份旧数据
  useEffect(() => {
    let cancelled = false
    const tick = reloadTick
    ;(async () => {
      try {
        const res = await fetchRecruitmentPositionInfos()
        if (!cancelled) setResult({ tick, rows: res.data || [], error: null })
      } catch (err) {
        if (!cancelled) {
          setResult({ tick, rows: [], error: err instanceof Error ? err.message : '招聘岗位信息加载失败' })
        }
      }
    })()
    return () => { cancelled = true }
  }, [reloadTick])

  // 部门选项按接口返回的顺序（已按部门排好）；每个部门带岗位数，未配置完的另外标出还剩几个
  const departmentOptions = useMemo(() => {
    const counts = new Map<string, { total: number; missing: number }>()
    rows.forEach((row) => {
      const count = counts.get(row.department) ?? { total: 0, missing: 0 }
      count.total += 1
      if (!row.configured) count.missing += 1
      counts.set(row.department, count)
    })
    return [...counts].map(([name, count]) => ({
      value: name,
      label: count.missing ? `${name}（${count.total} 个岗位，${count.missing} 个未配置）` : `${name}（${count.total} 个岗位）`,
    }))
  }, [rows])

  const configuredCount = rows.filter((row) => row.configured).length

  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    const matched = rows.filter((row) => (!department || row.department === department)
      && (!onlyMissing || !row.configured)
      && (!kw || row.position_name.toLowerCase().includes(kw) || row.department.toLowerCase().includes(kw)))
    // 部门先后沿用接口顺序（组织架构顺序）；部门内按名称排
    const groups = new Map<string, Row[]>()
    matched.forEach((row) => {
      const group = groups.get(row.department)
      if (group) group.push(row)
      else groups.set(row.department, [row])
    })
    return [...groups.values()].flatMap((group) => [...group].sort((a, b) => a.position_name.localeCompare(b.position_name, 'zh-CN')))
  }, [rows, department, keyword, onlyMissing])

  const openEditor = (row: Row) => {
    setTarget({ id: row.position_id, department: row.department, name: row.position_name })
    setOpen(true)
  }

  const handleSaved = (info: RecruitmentPositionInfo) => {
    setHighlightId(info.position_id)
    setReloadTick((n) => n + 1)
  }

  // 高亮只留一小会儿
  useEffect(() => {
    if (!highlightId) return
    const timer = window.setTimeout(() => setHighlightId(null), 2600)
    return () => window.clearTimeout(timer)
  }, [highlightId])

  const clearFilters = () => {
    setDepartment(undefined)
    setKeyword('')
    setOnlyMissing(false)
  }

  const columns: ColumnsType<Row> = [
    {
      title: '部门',
      dataIndex: 'department',
      width: 180,
      ellipsis: true,
      render: (value: string) => <span className="text-[var(--color-slate)]">{value}</span>,
    },
    {
      title: '岗位',
      dataIndex: 'position_name',
      width: 180,
      ellipsis: true,
      render: (value: string) => <span className="font-medium text-[var(--color-ink)]">{value}</span>,
    },
    {
      title: '岗位描述',
      key: 'info',
      render: (_, row) => (row.configured ? (
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={`${styles.chip} ${styles.chipDone}`}>已配置</span>
            <span className="text-[13px] text-[var(--color-stone)]">
              职责 {row.duties_length} 字 · 要求 {row.requirements_length} 字
            </span>
          </div>
          {row.excerpt && (
            <div className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-[var(--color-steel)]">{row.excerpt}</div>
          )}
        </div>
      ) : <span className={`${styles.chip} ${styles.chipTodo}`}>未配置</span>),
    },
    {
      title: '最后修改',
      key: 'updated',
      width: 210,
      render: (_, row) => (row.configured ? (
        <span className="text-[13px] text-[var(--color-steel)]">
          {formatTime(row.updated_at)}
          {row.updated_by_name && <span className="ml-2 text-[var(--color-stone)]">{row.updated_by_name}</span>}
        </span>
      ) : (
        <span className="text-[var(--color-stone)]">—</span>
      )),
    },
  ]
  if (canManage || rows.some((row) => row.configured)) {
    columns.push({
      title: '操作',
      key: 'action',
      width: 88,
      // 没有招聘管理权限的只能看已配置的；没配置的没有可看的
      render: (_, row) => (canManage || row.configured ? (
        <Button type="link" size="small" className="px-0" onClick={() => openEditor(row)}>
          {!canManage ? '查看' : row.configured ? '编辑' : '配置'}
        </Button>
      ) : null),
    })
  }

  const filtered = department !== undefined || keyword.trim() !== '' || onlyMissing
  let emptyText: ReactNode
  if (rows.length === 0) {
    emptyText = <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="岗位库里还没有岗位，请先在「岗位管理」里新增" />
  } else if (onlyMissing && !keyword.trim() && department === undefined) {
    emptyText = <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所有岗位都已配置招聘岗位信息" />
  } else {
    // antd v6 的 Empty 没有 action 属性，按钮放在 children 里（渲染在说明文字下方）
    emptyText = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={onlyMissing ? '这个范围内没有未配置的岗位' : '没有匹配的岗位'}
      >
        <Button onClick={clearFilters}>清除筛选</Button>
      </Empty>
    )
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="招聘岗位信息"
        description="为每个岗位保存一份岗位职责和任职要求；新建招聘需求选中岗位后自动带出，不必每次重填。"
      />

      <div className="overflow-hidden rounded-[var(--rounded-lg)] border border-[var(--color-hairline)] bg-[var(--color-canvas)]">
        <header className="flex flex-wrap items-center gap-3 border-b border-[var(--color-hairline)] px-4 py-3">
          <Select
            style={{ width: 'min(280px, 100%)' }}
            aria-label="按部门筛选"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部部门"
            value={department}
            onChange={(value: string | undefined) => setDepartment(value)}
            options={departmentOptions}
          />
          <Input
            allowClear
            aria-label="搜索岗位"
            prefix={<SearchOutlined />}
            placeholder="搜索岗位或部门"
            style={{ width: 'min(220px, 100%)' }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Checkbox
            checked={onlyMissing}
            onChange={(e) => setOnlyMissing(e.target.checked)}
          >
            仅看未配置
          </Checkbox>
          {/* 首屏数据没回来之前没有可报的数，先不显示 */}
          {result && !loadError && (
            <span className="ml-auto text-[13px] text-[var(--color-steel)]">
              共 {rows.length} 个岗位，已配置 {configuredCount} 个
              {rows.length - configuredCount > 0 && canManage ? `，还有 ${rows.length - configuredCount} 个待配置` : ''}
            </span>
          )}
        </header>

        {loadError ? (
          <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
            <span className="flex size-12 items-center justify-center rounded-full bg-[var(--color-tint-peach)]">
              <WarningOutlined className="text-xl text-[var(--color-warning)]" />
            </span>
            <p className="text-[14px] font-medium text-[var(--color-charcoal)]">招聘岗位信息加载失败</p>
            <p className="max-w-sm text-[13px] leading-relaxed text-[var(--color-steel)]">{loadError}</p>
            <Button className="mt-2" onClick={() => setReloadTick((n) => n + 1)}>重试</Button>
          </div>
        ) : (
          // key 带上筛选条件：筛选一变表格重建，页码回到第 1 页
          <Table<Row>
            key={`${department ?? ''}|${keyword.trim()}|${onlyMissing}`}
            className={styles.table}
            rowKey="position_id"
            size="middle"
            loading={loading}
            columns={columns}
            dataSource={visible}
            rowClassName={(row) => (row.position_id === highlightId ? styles.rowFlash : '')}
            scroll={{ x: 860 }}
            locale={{ emptyText }}
            pagination={{
              defaultPageSize: 20,
              showSizeChanger: true,
              pageSizeOptions: [20, 50, 100],
              showTotal: (total) => `共 ${total} 个岗位${filtered ? '（已筛选）' : ''}`,
            }}
          />
        )}
      </div>

      <RecruitmentPositionInfoModal
        open={open}
        position={target}
        readOnly={!canManage}
        onClose={() => setOpen(false)}
        onSaved={handleSaved}
      />
    </div>
  )
}

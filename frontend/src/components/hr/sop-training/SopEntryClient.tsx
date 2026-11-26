'use client'

// SOP 培训二级表：总表「转培训」后，任务按涉及部门派发到这里，各部门培训管理员在这里转训、定分类人员。
// 一个部门一张表：部门页签上直接显示待转训数；勾选后可批量转培训，多条 SOP 可合并生成一套材料。

import { useEffect, useMemo, useReducer, useState } from 'react'
import type { ReactNode } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { App, Button, Empty, Input, Popconfirm, Segmented, Select, Space, Table, Tabs, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { DownloadOutlined, FileZipOutlined, ReloadOutlined, SearchOutlined, SendOutlined } from '@ant-design/icons'
import {
  batchTransferSopEntries,
  exportSopTrainingEntries,
  fetchSopTrainingEntries,
  generateSopTrainingMaterials,
  transferSopTrainingEntry,
} from '@/actions/hr'
import { downloadBase64File, ORPHAN_TAG_CHIP_COLOR, classificationChipColors } from '@/lib/hr'
import { useHasPermission } from '@/hooks/hr'
import type { SopTrainingEntry } from '@/types/hr'
import PageHeader from '@/components/hr/PageHeader'
import { ClassificationChip } from '@/components/hr/training-roster/classificationChip'
import SopEntryPersonnelModal from './SopEntryPersonnelModal'
import { FileCell, MethodTimeCell, SoftTag, entryStatusTagMeta } from './cells'
import styles from './sop-training.module.css'

const ALL_DEPARTMENTS = '__all__'
const PAGE_SIZE = 20

type StatusFilter = 'all' | '待转训' | '已转训'

const isPending = (e: SopTrainingEntry) => e.status !== '已转训'

const byZh = (a: string, b: string) => a.localeCompare(b, 'zh-CN')

function withCount(text: string, count: number): ReactNode {
  return (
    <span>
      {text}
      <span className={styles.segCount}>{count}</span>
    </span>
  )
}

function TabLabel({ name, pending }: { name: string; pending: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      {name}
      {pending > 0 && <span className={styles.tabCount}>{pending}</span>}
    </span>
  )
}

const SEARCH_BY_LABEL = (input: string, option?: { label?: string }) =>
  (option?.label ?? '').toLowerCase().includes(input.toLowerCase())

export default function SopEntryClient() {
  const { message, modal } = App.useApp()
  const canManage = useHasPermission('hr:training:manage')
  const canGenerateDoc = useHasPermission('hr:training:document')

  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()

  const [entries, setEntries] = useState<SopTrainingEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [reloadSeq, bumpReload] = useReducer((n: number) => n + 1, 0)
  const [dept, setDept] = useState(() => searchParams.get('department') ?? ALL_DEPARTMENTS)
  // 总表进度列带 ?record= 进来：只看这一条登记派发到各部门的记录
  const [recordId, setRecordId] = useState<string | undefined>(() => searchParams.get('record') ?? undefined)
  const [status, setStatus] = useState<StatusFilter>('all')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)
  const [transferringId, setTransferringId] = useState<string | null>(null)
  const [batchTransferring, setBatchTransferring] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [personnelEntry, setPersonnelEntry] = useState<SopTrainingEntry | null>(null)
  const [personnelOpen, setPersonnelOpen] = useState(false)
  // 每次打开换 key：弹窗整体重新挂载，初值不用靠 effect 重置
  const [personnelSeq, setPersonnelSeq] = useState(0)

  // 一次取全（后端已按数据范围过滤），部门页签/状态/文件筛选都在前端做
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchSopTrainingEntries({})
        if (cancelled) return
        setEntries(r.data || [])
        // 重新取数后，被删掉的记录不能再留在勾选里
        const ids = new Set((r.data || []).map((e) => e.id))
        setSelectedKeys((keys) => keys.filter((k) => ids.has(k)))
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载二级表失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadSeq])

  const departments = useMemo(
    () => [...new Set(entries.map((e) => e.department))].sort(byZh),
    [entries],
  )
  const pendingByDept = useMemo(() => {
    const map: Record<string, number> = {}
    for (const e of entries) {
      if (isPending(e)) map[e.department] = (map[e.department] ?? 0) + 1
    }
    return map
  }, [entries])

  // 网址里的部门在当前数据范围内没有记录时，退回「全部部门」，否则页签没有选中项
  const activeDept = departments.includes(dept) ? dept : ALL_DEPARTMENTS

  const scoped = useMemo(
    () => (activeDept === ALL_DEPARTMENTS ? entries : entries.filter((e) => e.department === activeDept)),
    [entries, activeDept],
  )

  const recordOptions = useMemo(() => {
    const seen = new Map<string, SopTrainingEntry>()
    for (const e of scoped) {
      if (e.record_id && !seen.has(e.record_id)) seen.set(e.record_id, e)
    }
    return [...seen.values()].map((e) => ({
      value: e.record_id as string,
      label: `${e.file_name ?? '（登记记录已删除）'}${e.file_no ? `（${e.file_no}）` : ''}`,
    }))
  }, [scoped])

  const kw = keyword.trim().toLowerCase()
  // 部门页签 + 登记文件筛选之后的集合：状态筛选上的计数按它算（关键词不参与计数）
  const base = useMemo(
    () => (recordId ? scoped.filter((e) => e.record_id === recordId) : scoped),
    [scoped, recordId],
  )
  const basePending = useMemo(() => base.filter(isPending).length, [base])
  const visible = useMemo(
    () =>
      base
        .filter((e) => {
          if (status !== 'all' && e.status !== status) return false
          if (kw && !`${e.file_name ?? ''}\n${e.file_no ?? ''}`.toLowerCase().includes(kw)) return false
          return true
        })
        // 待转训的排在前面（要处理的先看到），同状态内保持后端的「新收录在前」
        .sort((a, b) => Number(isPending(b)) - Number(isPending(a))),
    [base, status, kw],
  )

  const selectedRows = useMemo(
    () => visible.filter((e) => selectedKeys.includes(e.id)),
    [visible, selectedKeys],
  )
  const selectedPending = useMemo(() => selectedRows.filter(isPending), [selectedRows])

  const chipColors = useMemo(
    () =>
      classificationChipColors(
        [...new Set(entries.map((e) => e.classification).filter((c): c is string => !!c))].sort(byZh),
      ),
    [entries],
  )

  const refresh = () => {
    setLoading(true)
    bumpReload()
  }

  // 筛选条件镜像到网址（replace，不新增历史）：默认值不带参数，保持链接干净
  const syncUrl = (params: { department?: string; record?: string }) => {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(params)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    const qs = next.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  const changeDept = (key: string) => {
    setDept(key)
    setSelectedKeys([])
    setPage(1)
    syncUrl({ department: key === ALL_DEPARTMENTS ? undefined : key })
  }

  const changeRecord = (id: string | undefined) => {
    setRecordId(id)
    setPage(1)
    syncUrl({ record: id })
  }

  const clearFilters = () => {
    setRecordId(undefined)
    setStatus('all')
    setKeyword('')
    setPage(1)
    syncUrl({ record: undefined })
  }

  const openPersonnel = (e: SopTrainingEntry) => {
    setPersonnelEntry(e)
    setPersonnelSeq((s) => s + 1)
    setPersonnelOpen(true)
  }

  const handleTransfer = async (e: SopTrainingEntry) => {
    setTransferringId(e.id)
    try {
      const r = await transferSopTrainingEntry(e.id)
      message.success(`已转培训（培训师：${r.data?.trainer || '未配置'}）`)
      refresh()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '转培训失败')
    } finally {
      setTransferringId(null)
    }
  }

  const confirmBatchTransfer = () => {
    const ids = selectedPending.map((e) => e.id)
    const depts = [...new Set(selectedPending.map((e) => e.department))].sort(byZh)
    modal.confirm({
      title: `把选中的 ${ids.length} 条转为培训？`,
      width: 500,
      content: (
        <div className="space-y-2 pt-1">
          <div className="flex flex-wrap gap-1.5">
            {depts.map((d) => (
              <span key={d} className={styles.deptChip}>
                {d}
              </span>
            ))}
          </div>
          <div className="text-[13px] text-[var(--color-steel)]">
            转培训会自动带出各部门当前的一级培训师；已选分类人员的记录，人员会同步归入对应分类。
          </div>
        </div>
      ),
      okText: '确认转培训',
      cancelText: '取消',
      onOk: async () => {
        setBatchTransferring(true)
        try {
          const r = await batchTransferSopEntries(ids)
          message.success(`已转培训 ${r.data?.transferred ?? ids.length} 条`)
          setSelectedKeys([])
          refresh()
        } catch (err) {
          message.error(err instanceof Error ? err.message : '批量转培训失败')
        } finally {
          setBatchTransferring(false)
        }
      },
    })
  }

  const handleBatchMaterials = async () => {
    if (!selectedRows.length) return
    setGenerating(true)
    try {
      const { base64, filename } = await generateSopTrainingMaterials(selectedRows.map((e) => e.id))
      downloadBase64File(base64, filename)
      message.success('已生成一套培训材料（按分类人员）')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { base64, filename } = await exportSopTrainingEntries({
        record_id: recordId,
        department: activeDept === ALL_DEPARTMENTS ? undefined : activeDept,
        status: status === 'all' ? undefined : status,
      })
      downloadBase64File(base64, filename)
      message.success('培训清单已导出')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const columns: ColumnsType<SopTrainingEntry> = [
    // 只看单个部门时每个值都一样，这列就不占位了
    ...(activeDept === ALL_DEPARTMENTS
      ? [{ title: '部门', dataIndex: 'department', width: 148, ellipsis: true }]
      : []),
    {
      title: '培训文件',
      key: 'file',
      render: (_, e) => (
        <FileCell
          name={e.file_name ?? '（登记记录已删除）'}
          title={e.file_name ?? undefined}
          meta={<span className={styles.num}>{e.file_no || '无编号'}</span>}
        />
      ),
    },
    {
      title: '培训完成 / 培训师',
      key: 'complete',
      width: 190,
      render: (_, e) => (
        <MethodTimeCell
          method={e.method}
          completeTime={e.complete_time}
          withYear
          footnote={
            isPending(e) ? (
              <>培训师 <span className={styles.placeholder}>转培训时带出</span></>
            ) : e.trainer ? (
              <>培训师 {e.trainer}</>
            ) : (
              <>
                培训师 <span className={styles.placeholder}>本部门未配置</span>
              </>
            )
          }
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 88,
      render: (s: string) => (
        <SoftTag meta={entryStatusTagMeta(s)} dot>
          {s}
        </SoftTag>
      ),
    },
    {
      title: '分类人员',
      key: 'personnel',
      render: (_, e) => {
        if (!e.classification) return <span className={styles.placeholder}>未设置分类</span>
        const names = e.personnel.map((p) => p.name)
        const known = !!chipColors[e.classification]
        return (
          <div className="min-w-0">
            <ClassificationChip
              name={e.classification}
              color={known ? chipColors[e.classification] : ORPHAN_TAG_CHIP_COLOR}
              orphan={!known}
            />
            <div className={`${styles.cellSecondary} mt-1`} title={names.join('、')}>
              {names.length > 0
                ? `${names.slice(0, 3).join('、')}${names.length > 3 ? ` 等 ${names.length} 人` : ''}`
                : '未选择人员'}
            </div>
          </div>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, e) =>
        canManage ? (
          <Space size={4}>
            <Button type="text" size="small" onClick={() => openPersonnel(e)}>
              分类人员
            </Button>
            {isPending(e) && (
              <Popconfirm
                title="确认转培训？"
                description="将自动带出本部门当前的一级培训师。"
                okText="转培训"
                cancelText="取消"
                onConfirm={() => { void handleTransfer(e) }}
              >
                <Button
                  size="small"
                  color="primary"
                  variant="outlined"
                  loading={transferringId === e.id}
                >
                  转培训
                </Button>
              </Popconfirm>
            )}
          </Space>
        ) : (
          <span className={styles.placeholder}>—</span>
        ),
    },
  ]

  const emptyText =
    entries.length === 0
      ? '还没有收录到二级表的培训文件'
      : scoped.length === 0
        ? '该部门暂无培训记录'
        : '没有符合当前筛选条件的记录'

  return (
    <div className="space-y-4">
      <PageHeader
        title="SOP培训二级表"
        description="总表「转培训」后，任务按涉及部门派发到这里；转训时带出本部门一级培训师，勾选多条 SOP 可合并生成一套培训材料"
        actions={
          <Space>
            <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => { void handleExport() }}>
              导出培训清单
            </Button>
            {canManage && (
              <Tooltip title={selectedPending.length ? undefined : '先勾选待转训的记录'}>
                <span>
                  <Button
                    icon={<SendOutlined />}
                    disabled={!selectedPending.length}
                    loading={batchTransferring}
                    onClick={confirmBatchTransfer}
                  >
                    批量转培训
                  </Button>
                </span>
              </Tooltip>
            )}
            {canGenerateDoc && (
              <Tooltip title={selectedRows.length ? undefined : '先勾选记录，可多选合并成一套'}>
                <span>
                  <Button
                    type="primary"
                    icon={<FileZipOutlined />}
                    disabled={!selectedRows.length}
                    loading={generating}
                    onClick={() => { void handleBatchMaterials() }}
                  >
                    生成一套材料
                  </Button>
                </span>
              </Tooltip>
            )}
          </Space>
        }
      />

      {departments.length > 0 && (
        <Tabs
          activeKey={activeDept}
          onChange={changeDept}
          tabBarStyle={{ marginBottom: 0 }}
          items={[
            { key: ALL_DEPARTMENTS, label: <TabLabel name="全部部门" pending={entries.filter(isPending).length} /> },
            ...departments.map((d) => ({
              key: d,
              label: <TabLabel name={d} pending={pendingByDept[d] ?? 0} />,
            })),
          ]}
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="按登记文件筛选"
          style={{ width: 300 }}
          options={recordOptions}
          value={recordId}
          filterOption={SEARCH_BY_LABEL}
          onChange={changeRecord}
        />
        <Segmented
          value={status}
          onChange={(v) => {
            setStatus(v as StatusFilter)
            setPage(1)
          }}
          options={[
            { value: 'all', label: withCount('全部', base.length) },
            { value: '待转训', label: withCount('待转训', basePending) },
            { value: '已转训', label: withCount('已转训', base.length - basePending) },
          ]}
        />
        <Input
          className="ml-auto"
          style={{ width: 220 }}
          allowClear
          prefix={<SearchOutlined className="text-[var(--color-stone)]" />}
          placeholder="搜索文件名称 / 编号"
          value={keyword}
          onChange={(e) => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
        <Tooltip title="刷新">
          <Button aria-label="刷新" icon={<ReloadOutlined />} onClick={refresh} />
        </Tooltip>
      </div>

      <Table<SopTrainingEntry>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={visible}
        scroll={{ x: 1000 }}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          // rowKey 是字符串 id，统一成 string 再存，后面按 id 比对
          onChange: (keys) => setSelectedKeys(keys.map(String)),
          columnWidth: 44,
        }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: visible.length,
          showSizeChanger: false,
          showTotal: (t) =>
            `共 ${t} 条${selectedRows.length > 0 ? `，已选 ${selectedRows.length} 条` : ''}`,
          onChange: setPage,
        }}
        locale={{
          emptyText: (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText}>
              {entries.length > 0 && scoped.length > 0 ? (
                <Button type="link" style={{ padding: 0 }} onClick={clearFilters}>
                  清空筛选条件
                </Button>
              ) : (
                entries.length === 0 && (
                  <span className="text-[13px] text-[var(--color-steel)]">
                    登记表「转培训」后，涉及部门的记录会自动出现在这里
                  </span>
                )
              )}
            </Empty>
          ),
        }}
      />

      <SopEntryPersonnelModal
        key={personnelSeq}
        open={personnelOpen}
        entry={personnelEntry}
        onClose={() => setPersonnelOpen(false)}
        onSaved={() => {
          setPersonnelOpen(false)
          refresh()
        }}
      />
    </div>
  )
}

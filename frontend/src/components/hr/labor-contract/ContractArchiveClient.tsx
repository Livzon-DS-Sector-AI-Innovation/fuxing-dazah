'use client'

// 电子档案库（P2）：归档视角台账——归档状态 / 在职离职范围 / 部门筛选、补扫清单导出、批量挂接。
// 劳动合同页的第二个页签；扫描件上传与原件预览在合同详情抽屉内完成。
// 概览、补扫清单与批量挂接仅 HR 可用（后端按数据范围把关），这里按概览是否可用来控制入口显隐。

import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Button, Input, Segmented, Select, Space, Table, Tag, Tooltip } from 'antd'
import { DownloadOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import PageHeader from '@/components/hr/PageHeader'
import ContractDetailDrawer from '@/components/hr/ContractDetailDrawer'
import ContractArchiveBatchImportModal from '@/components/hr/labor-contract/ContractArchiveBatchImportModal'
import {
  exportUnarchivedContracts,
  fetchContractArchive,
  fetchContractArchiveDepartments,
  fetchContractArchiveFilterOptions,
  fetchContractArchiveStats,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr/download'
import { formatDateTime } from '@/lib/hr/format'
import { useHasPermission } from '@/hooks/hr'
import { usePermission } from '@/hooks/usePermission'
import type {
  ContractArchiveDepartment,
  ContractArchiveRow,
  ContractArchiveStats,
} from '@/types/hr'

type ArchiveFilter = 'unarchived' | 'archived' | 'all'
type Population = 'in_service' | 'departed' | 'all'

/** 「本科及以上」快捷选择：按档案里常见的学历取值 */
const BACHELOR_PLUS = ['本科', '硕士', '博士', '研究生', '硕士研究生', '博士研究生', '双学位', 'MBA', 'EMBA']

interface Props {
  /** 外层通知刷新（台账里归档了合同后切回来） */
  refreshKey?: number
  /** 档案库里归档了合同之后通知外层（台账的「归档」列要刷新） */
  onChanged?: () => void
}

export default function ContractArchiveClient({ refreshKey = 0, onChanged }: Props) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  // 水合安全的权限判断：页面在 Suspense 边界内
  const canApprove = useHasPermission('hr:contract:approve')
  const canManage = hasPermission('hr:contract:manage')

  const [rows, setRows] = useState<ContractArchiveRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [archiveFilter, setArchiveFilter] = useState<ArchiveFilter>('unarchived')
  const [population, setPopulation] = useState<Population>('in_service')
  const [keyword, setKeyword] = useState('')
  const [department, setDepartment] = useState<string | undefined>()
  const [education, setEducation] = useState<string[]>([])
  const [educationOptions, setEducationOptions] = useState<string[]>([])
  const [stats, setStats] = useState<ContractArchiveStats | null>(null)
  const [departments, setDepartments] = useState<ContractArchiveDepartment[]>([])
  const [exporting, setExporting] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const seqRef = useRef(0)
  const pageSize = 20

  const paramsOf = (targetPage: number) => ({
    archive_status: archiveFilter === 'all' ? undefined : archiveFilter,
    population,
    keyword: keyword || undefined,
    department,
    education: education.length ? education.join(',') : undefined,
    page: targetPage,
    page_size: pageSize,
  })

  // 事件驱动的刷新（翻页 / 刷新按钮 / 归档后）：可以直接进 loading
  const load = useCallback(
    async (targetPage = page) => {
      // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
      const seq = ++seqRef.current
      setLoading(true)
      try {
        const r = await fetchContractArchive(paramsOf(targetPage))
        if (seq !== seqRef.current) return // 过期响应丢弃
        setRows(r.data)
        setTotal(r.meta.total)
      } catch (e) {
        if (seq === seqRef.current) message.error(e instanceof Error ? e.message : '加载档案库失败')
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    },
    // paramsOf 是每次渲染新建的函数，它用到的筛选值已经逐个列在依赖里
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [archiveFilter, population, department, keyword, education, page, message],
  )

  // 筛选变化重新拉取第一页：请求参数直接取本次渲染的筛选值（没有旧闭包问题）；
  // setState 全部在 await 之后，不在 effect 里同步触发级联渲染（回到第一页由筛选控件的 onChange 负责）
  useEffect(() => {
    const seq = ++seqRef.current
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchContractArchive(paramsOf(1))
        if (cancelled || seq !== seqRef.current) return
        setRows(r.data)
        setTotal(r.meta.total)
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载档案库失败')
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [archiveFilter, population, department, keyword, education])

  // 概览与部门 / 学历下拉：首次挂载加载，之后的刷新走事件驱动的 loadStats
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const [statsRes, deptRes, optionsRes] = await Promise.allSettled([
        fetchContractArchiveStats(),
        fetchContractArchiveDepartments(),
        fetchContractArchiveFilterOptions(),
      ])
      if (cancelled) return
      // 非全量数据范围读不到概览（403）：列表照常，HR 专属入口不显示
      setStats(statsRes.status === 'fulfilled' ? statsRes.value.data : null)
      setDepartments(deptRes.status === 'fulfilled' ? (deptRes.value.data || []) : [])
      setEducationOptions(optionsRes.status === 'fulfilled' ? (optionsRes.value.data.education || []) : [])
    })()
    return () => { cancelled = true }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      setStats((await fetchContractArchiveStats()).data)
    } catch {
      setStats(null)
    }
  }, [])

  // 外层通知刷新（台账里归档了合同）：首次挂载的那一下（0）跳过
  const firstRefreshKey = useRef(refreshKey)
  useEffect(() => {
    if (refreshKey === firstRefreshKey.current) return
    firstRefreshKey.current = refreshKey
    void load()
    void loadStats()
  }, [refreshKey, load, loadStats])

  // 概览仅 HR 可读，顺带作为「可归档」的判定来源
  const isHr = stats?.can_archive === true

  const refreshAll = () => {
    void load()
    void loadStats()
    onChanged?.()
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const r = await exportUnarchivedContracts(department, education.length ? education.join(',') : undefined)
      downloadBase64File(r.base64, r.filename || '合同补扫清单.xlsx')
      message.success('补扫清单已导出')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const unarchived = stats ? stats.in_service_unarchived + stats.departed_unarchived : 0
  const archived = stats ? stats.in_service_archived + stats.departed_archived : 0

  // 列宽合计 1090：「人员」并入姓名单元格、「归档时间」并入归档列，1440 宽度下不横向滚动即可看全
  const columns: ColumnsType<ContractArchiveRow> = [
    {
      title: '姓名 / 工号',
      width: 150,
      render: (_, r) => (
        <div>
          <div className="font-medium">
            {r.name}
            {r.is_departed && <Tag className="ml-1">离职</Tag>}
          </div>
          <div className="text-xs text-gray-500">{r.employee_number}</div>
        </div>
      ),
    },
    { title: '部门', dataIndex: 'department', width: 124, ellipsis: { showTitle: true } },
    { title: '岗位', dataIndex: 'position', width: 96, render: (v) => v || '-', ellipsis: { showTitle: true } },
    { title: '学历', dataIndex: 'education', width: 64, render: (v) => v || '-' },
    { title: '签订次序', dataIndex: 'seq_label', width: 104, ellipsis: { showTitle: true } },
    { title: '合同期限', dataIndex: 'term_label', width: 88 },
    {
      title: '起始 ~ 到期',
      width: 196,
      render: (_, r) => (
        <span className="text-[13px]">{r.start_date || '-'} ~ {r.end_date || '无固定期限'}</span>
      ),
    },
    { title: '合同状态', dataIndex: 'status_label', width: 100 },
    {
      title: '归档',
      width: 140,
      render: (_, r) => (
        <Tooltip title={r.archive_status === 'archived' ? r.archive_file_name || undefined : undefined}>
          <div>
            <Tag color={r.archive_status === 'archived' ? 'green' : 'orange'}>
              {r.archive_status === 'archived' ? '已归档' : '未归档'}
            </Tag>
            {r.archive_status === 'archived' && r.archive_uploaded_at && (
              <div className="text-xs text-gray-500 -mt-0.5">{formatDateTime(r.archive_uploaded_at)}</div>
            )}
          </div>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      width: 76,
      fixed: 'right',
      render: (_, r) => <Button type="link" size="small" onClick={() => setDetailId(r.id)}>详情</Button>,
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="电子档案库"
        description="劳动合同扫描件归档视角：未归档筛选、补扫清单导出、存量电子档批量挂接（一人一事一档）。落地顺序：先补本科及以上人员，再逐步补齐一般员工。"
      />

      <div className="flex flex-wrap gap-3 items-center">
        <Segmented
          value={archiveFilter}
          onChange={(v) => { setArchiveFilter(v as ArchiveFilter); setPage(1) }}
          options={[
            { label: '未归档', value: 'unarchived' },
            { label: '已归档', value: 'archived' },
            { label: '全部', value: 'all' },
          ]}
        />
        <Select
          style={{ width: 140 }}
          value={population}
          onChange={(v) => { setPopulation(v); setPage(1) }}
          options={[
            { label: '在职人员', value: 'in_service' },
            { label: '离职人员', value: 'departed' },
            { label: '全部人员', value: 'all' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="部门"
          style={{ width: 210 }}
          value={department}
          onChange={(v) => { setDepartment(v); setPage(1) }}
          options={departments.map((d) => ({
            value: d.department,
            label: `${d.department}（未归档 ${d.unarchived}）`,
          }))}
        />
        <Select
          mode="multiple"
          allowClear
          maxTagCount="responsive"
          placeholder="学历"
          style={{ minWidth: 150, maxWidth: 280 }}
          value={education}
          onChange={(v) => { setEducation(v); setPage(1) }}
          options={educationOptions.map((e) => ({ value: e, label: e }))}
          aria-label="学历"
        />
        <Button
          size="small"
          type="link"
          className="!px-0"
          onClick={() => {
            // 「先本科及以上」：只选档案里实际出现过的取值
            setEducation(BACHELOR_PLUS.filter((e) => educationOptions.includes(e)))
            setPage(1)
          }}
        >
          选本科及以上
        </Button>
        <Input.Search
          allowClear
          placeholder="姓名 / 工号"
          style={{ width: 180 }}
          onSearch={(v) => {
            // 只更新筛选状态：拉取由上面的 effect 负责
            setKeyword(v.trim())
            setPage(1)
          }}
        />
        <Tooltip title="刷新">
          <Button aria-label="刷新" icon={<ReloadOutlined />} onClick={() => { void load(); void loadStats() }} />
        </Tooltip>
        <Space className="ml-auto">
          {isHr && (
            <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void handleExport()}>
              导出补扫清单
            </Button>
          )}
          {isHr && (
            <Button type="primary" icon={<InboxOutlined />} onClick={() => setImportOpen(true)}>
              批量挂接
            </Button>
          )}
        </Space>
      </div>

      {stats && (
        <div className="rounded-md border border-[var(--color-hairline)] bg-[var(--color-bg-gray, #f5f5f5)] px-3 py-2 text-[13px] flex flex-wrap gap-x-5 gap-y-1">
          <span>
            未归档 <b className="text-orange-600">{unarchived}</b> 份（在职 {stats.in_service_unarchived} · 离职{' '}
            {stats.departed_unarchived}）
          </span>
          <span>
            已归档 <b className="text-green-700">{archived}</b> 份
          </span>
          <span className="text-gray-500">
            每周一自动汇总未归档清单给 HR；离职人员合同在「离职台账 → 合同台账」归档。
          </span>
        </div>
      )}

      <Table<ContractArchiveRow>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1090 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 份合同`,
          onChange: (p) => {
            setPage(p)
            void load(p)
          },
        }}
      />

      <ContractDetailDrawer
        contractId={detailId}
        canManage={canManage}
        canApprove={canApprove}
        onClose={() => setDetailId(null)}
        onChanged={refreshAll}
      />

      <ContractArchiveBatchImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={refreshAll}
      />
    </div>
  )
}

'use client'

import styles from "./lifecycleTable.module.css"
import { useState, useCallback, useEffect, useRef } from 'react'
import { App, Button, Card, Table, Space, Input, Tag, Select, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { SearchOutlined, PlusOutlined, ImportOutlined } from '@ant-design/icons'
import { OnboardingRecord } from '@/types/hr'
import {
  fetchOnboardingRecords,
  fetchOnboardingFilterOptionsAction,
  fetchDepartmentsAction,
  exportOnboardingRecords,
} from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { LedgerImportModal } from '@/components/hr'
import { useDebouncedCallback } from '@/hooks/hr'
import { usePermission } from '@/hooks/usePermission'
import EmployeeForm from './EmployeeForm'
import PageHeader from './PageHeader'

interface OnboardingClientProps {
  initialRecords: OnboardingRecord[]
  initialTotal: number
}

export default function OnboardingClient({ initialRecords, initialTotal }: OnboardingClientProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canImport = hasPermission('hr:onboarding:manage')
  const [records, setRecords] = useState<OnboardingRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  // 输入框即时回显；防抖 300ms 后才写入 searchKeyword 触发查询（此前每敲一个字发一次请求）
  const [keywordInput, setKeywordInput] = useState('')
  const [filterDepartment, setFilterDepartment] = useState<string | undefined>()
  const [filterYear, setFilterYear] = useState<number>(new Date().getFullYear())
  // 服务端排序：分页在服务端，前端 sorter 只会重排当前页 20 条（此前即如此，升降序结果不对）
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend'>('descend')
  const loadSeq = useRef(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [hireYears, setHireYears] = useState<number[]>([])
  const [exporting, setExporting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const { run: debouncedSetKeyword, cancel: cancelKeywordDebounce } = useDebouncedCallback((val: string) => {
    setPage(1)
    setSearchKeyword(val)
  }, 300)

  const commitKeyword = (val: string) => {
    cancelKeywordDebounce()
    setPage(1)
    setSearchKeyword(val.trim())
  }

  useEffect(() => {
    fetchDepartmentsAction({ page_size: 100 }).then(res => {
      setDepartments((res.data || []).map((d: any) => ({ value: d.name, label: d.name })))
    }).catch(() => {})
    fetchOnboardingFilterOptionsAction().then(res => {
      setHireYears(res.years || [])
    }).catch(() => {})
  }, [])

  const loadData = useCallback(async () => {
    // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      const res = await fetchOnboardingRecords({
        department: filterDepartment || undefined,
        year: filterYear || undefined,
        keyword: searchKeyword || undefined,
        sort_by: 'hire_date',
        sort_order: sortOrder === 'ascend' ? 'asc' : 'desc',
        page, page_size: pageSize })
      if (seq !== loadSeq.current) return
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      if (seq === loadSeq.current) message.error(err.message || '加载数据失败')
    }
    finally { if (seq === loadSeq.current) setLoading(false) }
  }, [filterDepartment, filterYear, searchKeyword, sortOrder, page, pageSize, message])

  useEffect(() => { loadData() }, [filterDepartment, filterYear, searchKeyword, sortOrder, page, pageSize])

  // 导出与列表筛选同口径（部门/年份/关键词；默认仅在职的口径也与列表一致）
  const handleExport = async () => {
    setExporting(true)
    try {
      const r = await exportOnboardingRecords({
        department: filterDepartment || undefined,
        year: filterYear || undefined,
        keyword: searchKeyword || undefined,
      })
      downloadBase64File(r.base64, r.filename)
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setExporting(false) }
  }

  const columns: ColumnsType<OnboardingRecord> = [
    { title: '工号', dataIndex: 'employee_number', width: 100 },
    { title: '姓名', dataIndex: 'name', width: 80 },
    { title: '部门', dataIndex: 'department', width: 140, ellipsis: true },
    { title: '岗位', dataIndex: 'position', width: 120, ellipsis: true },
    { title: '入职日期', dataIndex: 'hire_date', width: 110,
      sortOrder, sorter: true },
    { title: '学历', dataIndex: 'education', width: 70 },
    { title: '毕业院校', dataIndex: 'school', width: 140, ellipsis: true },
    { title: '手机', dataIndex: 'phone', width: 120 },
    { title: '是否在职', dataIndex: 'is_employed', width: 80,
      render: (v: string) => <Tag color={v === '是' ? 'green' : 'default'}>{v || '-'}</Tag> },
    { title: '来源', dataIndex: 'source', width: 90,
      render: (v: string) => v === 'approval' ? <Tag color="blue">系统审批</Tag>
        : v === 'feishu' ? <Tag color="purple">飞书同步</Tag>
        : v === 'recruitment' ? <Tag color="cyan">招聘入职</Tag>
        : <Tag>员工档案</Tag> },
  ]

  return (
    <div className="space-y-4">
      <PageHeader title="入职台账" description="按入职日期归档的员工入职记录，可按年份与部门筛选" />

      <div className="flex flex-wrap gap-3 items-center">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建入职</Button>
        {/* 导入是写操作，按入职台账写权限显隐（只读用户点了只会得到 403） */}
        {canImport && <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入</Button>}
        <Input placeholder="搜索姓名或工号" value={keywordInput}
          onChange={e => { setKeywordInput(e.target.value); debouncedSetKeyword(e.target.value.trim()) }}
          onPressEnter={e => commitKeyword((e.target as HTMLInputElement).value)}
          prefix={<SearchOutlined />}
          style={{ width: 220 }} allowClear />
        <Select placeholder="部门筛选" allowClear value={filterDepartment} showSearch optionFilterProp="label"
          onChange={(v) => { setFilterDepartment(v); setPage(1) }} options={departments} style={{ width: 180 }} />
        <Select placeholder="入职年份" allowClear value={filterYear}
          onChange={(v) => { setFilterYear(v); setPage(1) }}
          options={Array.from(new Set([new Date().getFullYear(), ...hireYears]))
            .sort((a, b) => b - a)
            .map((y) => ({ value: y, label: `${y} 年入职` }))}
          style={{ width: 140 }} />
        <Tooltip title="按当前筛选（部门/年份/关键词）导出全部匹配记录">
          <Button loading={exporting} onClick={handleExport} className="ml-auto">导出Excel</Button>
        </Tooltip>
      </div>

      <Table className={styles.tableLg} columns={columns} dataSource={records} rowKey="id" loading={loading}
        // 排序循环须为「降序→升序→取消」：antd 默认是升→降→取消，从默认的降序点一下会落到「取消」，
        // 被下面的兜底映射回降序后状态就永远推进不到升序
        sortDirections={['descend', 'ascend']}
        onChange={(_pagination, _filters, sorter) => {
          // 入职日期列排序：交给服务端（取消排序时回到默认的倒序）
          const order = (Array.isArray(sorter) ? sorter[0] : sorter)?.order
          setSortOrder(order === 'ascend' ? 'ascend' : 'descend')
          setPage(1)
        }}
        pagination={{ current: page, pageSize, total, showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`, onChange: (p, ps) => { setPage(p); setPageSize(ps) } }}
        scroll={{ x: 1050 }} />

      <EmployeeForm open={createOpen} employee={null} onClose={() => setCreateOpen(false)}
        onSuccess={() => { setCreateOpen(false); loadData() }} />

      <LedgerImportModal
        open={importOpen}
        ledger="onboarding"
        label="入职台账"
        onClose={() => setImportOpen(false)}
        onSuccess={loadData}
      />
    </div>
  )
}

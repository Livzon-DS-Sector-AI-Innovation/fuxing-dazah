'use client'

import styles from "./lifecycleTable.module.css"
import { useState, useCallback, useEffect } from 'react'
import { App, Button, Card, Table, Space, Input, Tag, Select } from 'antd'
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
import EmployeeForm from './EmployeeForm'

interface OnboardingClientProps {
  initialRecords: OnboardingRecord[]
  initialTotal: number
}

export default function OnboardingClient({ initialRecords, initialTotal }: OnboardingClientProps) {
  const { message } = App.useApp()
  const [records, setRecords] = useState<OnboardingRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [filterDepartment, setFilterDepartment] = useState<string | undefined>()
  const [filterYear, setFilterYear] = useState<number>(new Date().getFullYear())
  const [createOpen, setCreateOpen] = useState(false)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [hireYears, setHireYears] = useState<number[]>([])
  const [exporting, setExporting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  useEffect(() => {
    fetchDepartmentsAction({ page_size: 100 }).then(res => {
      setDepartments((res.data || []).map((d: any) => ({ value: d.name, label: d.name })))
    }).catch(() => {})
    fetchOnboardingFilterOptionsAction().then(res => {
      setHireYears(res.years || [])
    }).catch(() => {})
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchOnboardingRecords({
        department: filterDepartment || undefined,
        year: filterYear || undefined,
        keyword: searchKeyword || undefined,
        page, page_size: pageSize })
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) { message.error(err.message || '加载数据失败') }
    finally { setLoading(false) }
  }, [filterDepartment, filterYear, searchKeyword, page, pageSize])

  useEffect(() => { loadData() }, [filterDepartment, filterYear, searchKeyword, page, pageSize])

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
    { title: '入职日期', dataIndex: 'hire_date', width: 110, defaultSortOrder: 'descend',
      sorter: (a, b) => new Date(b.hire_date || '').getTime() - new Date(a.hire_date || '').getTime() },
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
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">入职台账</h1>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建入职</Button>
        <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入</Button>
        <Input placeholder="搜索姓名或工号" value={searchKeyword}
          onChange={e => { setSearchKeyword(e.target.value); setPage(1) }} prefix={<SearchOutlined />}
          className="w-48" allowClear />
        <Select placeholder="部门筛选" allowClear value={filterDepartment}
          onChange={(v) => { setFilterDepartment(v); setPage(1) }} options={departments} style={{ width: 180 }} />
        <Select placeholder="入职年份" allowClear value={filterYear}
          onChange={(v) => { setFilterYear(v); setPage(1) }}
          options={Array.from(new Set([new Date().getFullYear(), ...hireYears]))
            .sort((a, b) => b - a)
            .map((y) => ({ value: y, label: `${y} 年入职` }))}
          style={{ width: 140 }} />
        <Button loading={exporting} onClick={handleExport} className="ml-auto"
          title="按当前筛选（部门/年份/关键词）导出全部匹配记录">导出Excel</Button>
      </div>

      <Table className={styles.tableLg} columns={columns} dataSource={records} rowKey="id" loading={loading}
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

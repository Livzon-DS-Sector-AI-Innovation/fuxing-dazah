'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Input, Tag, Select, Popconfirm } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { SearchOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { OnboardingRecord } from '@/types/hr'
import { fetchOnboardingRecords, fetchDepartments } from '@/lib/api/hr'
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
  const [createOpen, setCreateOpen] = useState(false)
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])

  useEffect(() => {
    fetchDepartments({ page_size: 100 }).then(res => {
      setDepartments((res.data || []).map((d: any) => ({ value: d.name, label: d.name })))
    }).catch(() => {})
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchOnboardingRecords({
        department: filterDepartment || undefined,
        keyword: searchKeyword || undefined,
        page, page_size: pageSize })
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) { message.error(err.message || '加载数据失败') }
    finally { setLoading(false) }
  }, [filterDepartment, searchKeyword, page, pageSize])

  useEffect(() => { loadData() }, [filterDepartment, searchKeyword, page, pageSize])

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
    { title: '操作', key: 'action', width: 80,
      render: (_: any, record: OnboardingRecord) => (
        <Popconfirm title="确认删除？" onConfirm={async () => {
          const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/hr/onboarding-records/${record.id}`, { method: 'DELETE' })
          if (res.ok) { message.success('已删除'); loadData() }
          else message.error('删除失败')
        }}>
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      )},
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">入职台账</h1>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建入职</Button>
        <Input placeholder="搜索姓名或工号" value={searchKeyword}
          onChange={e => setSearchKeyword(e.target.value)} prefix={<SearchOutlined />}
          className="w-48" allowClear />
        <Select placeholder="部门筛选" allowClear value={filterDepartment}
          onChange={setFilterDepartment} options={departments} style={{ width: 180 }} />
      </div>

      <Table columns={columns} dataSource={records} rowKey="id" loading={loading}
        pagination={{ current: page, pageSize, total, showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`, onChange: (p, ps) => { setPage(p); setPageSize(ps) } }}
        scroll={{ x: 900 }} size="small" />

      <EmployeeForm open={createOpen} employee={null} onClose={() => setCreateOpen(false)}
        onSuccess={() => { setCreateOpen(false); loadData() }} />
    </div>
  )
}

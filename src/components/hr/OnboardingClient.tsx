'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Input, Tag, Modal, Form, DatePicker, Select } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  EyeOutlined,
  PlusOutlined } from '@ant-design/icons'
import { OnboardingRecord } from '@/types/hr'
import { fetchOnboardingRecords, fetchDepartments } from '@/lib/api/hr'
import OnboardingDetailModal from './OnboardingDetailModal'
import EmployeeForm from './EmployeeForm'

interface OnboardingClientProps {
  initialRecords: OnboardingRecord[]
  initialTotal: number
  fetchAction?: typeof fetchOnboardingRecords
}

export default function OnboardingClient({
  initialRecords,
  initialTotal,
  fetchAction }: OnboardingClientProps) {
  const { message } = App.useApp()
  const [records, setRecords] = useState<OnboardingRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterPosition, setFilterPosition] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailRecord, setDetailRecord] = useState<OnboardingRecord | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const handleFormSuccess = () => {
    setCreateOpen(false)
    loadData()
  }

  const doFetch = fetchAction || fetchOnboardingRecords

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await doFetch({
        department: filterDepartment || undefined,
        position: filterPosition || undefined,
        keyword: searchKeyword || undefined,
        page,
        page_size: pageSize })
      setRecords(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [filterDepartment, filterPosition, searchKeyword, page, pageSize, doFetch])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleViewDetail = (record: OnboardingRecord) => {
    setDetailRecord(record)
    setDetailOpen(true)
  }

  useEffect(() => {
    loadData()
  }, [filterDepartment, filterPosition, searchKeyword, page, pageSize])

  const employedColorMap: Record<string, string> = {
    '是': 'success',
    '否': 'default' }

  const columns: ColumnsType<OnboardingRecord> = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100 },
    {
      title: '部门',
      dataIndex: 'department',
      key: 'department',
      width: 120,
      filters: [
        { text: '生产制造部', value: '生产制造部' },
        { text: '质量管理部', value: '质量管理部' },
        { text: '设备动力部', value: '设备动力部' },
        { text: '发酵工程部', value: '发酵工程部' },
        { text: '提炼一部', value: '提炼一部' },
        { text: '提炼二部', value: '提炼二部' },
        { text: '提炼三部', value: '提炼三部' },
        { text: '安全环保部', value: '安全环保部' },
        { text: '采购部', value: '采购部' },
        { text: '人事行政部', value: '人事行政部' },
        { text: '肠激酶车间', value: '肠激酶车间' },
        { text: '财务部', value: '财务部' },
      ],
      onFilter: (value, record: OnboardingRecord) => record.department === String(value) },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '入职时间',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 120,
      defaultSortOrder: 'descend',
      sorter: (a: OnboardingRecord, b: OnboardingRecord) =>
        new Date(b.hire_date || '').getTime() - new Date(a.hire_date || '').getTime() },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '毕业学校',
      dataIndex: 'school',
      key: 'school',
      width: 160,
      ellipsis: true },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 120 },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
      render: (_: any, record: OnboardingRecord) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          {/* 预留按钮位置 */}
        </Space>
      ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          入职台账
        </h1>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建入职</Button>
        <Input
          placeholder="搜索姓名或工号"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
        <Input
          placeholder="部门筛选"
          value={filterDepartment}
          onChange={(e) => setFilterDepartment(e.target.value)}
          className="w-40"
          allowClear
        />
        <Input
          placeholder="岗位筛选"
          value={filterPosition}
          onChange={(e) => setFilterPosition(e.target.value)}
          className="w-40"
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: handlePageChange }}
        scroll={{ x: 1200 }}
        size="small"
      />

      <OnboardingDetailModal
        open={detailOpen}
        record={detailRecord}
        onClose={() => setDetailOpen(false)}
      />

      <EmployeeForm open={createOpen} employee={null} onClose={() => setCreateOpen(false)}
        onSuccess={handleFormSuccess} />

    </div>
  )
}

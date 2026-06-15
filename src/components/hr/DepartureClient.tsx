'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Input, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  SearchOutlined,
  SyncOutlined,
  EyeOutlined } from '@ant-design/icons'
import { DepartureRecord } from '@/types/hr'
import {
  fetchDepartureRecords,
  syncDepartureFromFeishu } from '@/lib/api/hr'
import HrChatbot from './HrChatbot'

interface DepartureClientProps {
  initialRecords: DepartureRecord[]
  initialTotal: number
  fetchAction?: typeof fetchDepartureRecords
}

export default function DepartureClient({
  initialRecords,
  initialTotal,
  fetchAction }: DepartureClientProps) {
  const { message } = App.useApp()
  const [records, setRecords] = useState<DepartureRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [filterDepartment, setFilterDepartment] = useState('')
  const [filterOffboardingType, setFilterOffboardingType] = useState('')

  const doFetch = fetchAction || fetchDepartureRecords

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await doFetch({
        department: filterDepartment || undefined,
        offboarding_type: filterOffboardingType || undefined,
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
  }, [filterDepartment, filterOffboardingType, searchKeyword, page, pageSize, doFetch])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncDepartureFromFeishu()
      message.success(res.message)
      loadData()
    } catch (err: any) {
      message.error(err.message || '同步失败')
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [filterDepartment, filterOffboardingType, searchKeyword, page, pageSize])

  const offboardingTypeColorMap: Record<string, string> = {
    '辞职': 'default',
    '辞退': 'error',
    '合同到期': 'warning',
    '退休': 'success',
    '其他': 'processing' }

  const columns: ColumnsType<DepartureRecord> = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100,
      fixed: 'left' },
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
      onFilter: (value, record: DepartureRecord) => record.department === String(value) },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '职位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 120,
      defaultSortOrder: 'descend',
      sorter: (a: DepartureRecord, b: DepartureRecord) =>
        new Date(b.offboarding_date || '').getTime() - new Date(a.offboarding_date || '').getTime() },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 100,
      render: (val: string) => (
        <Tag color={offboardingTypeColorMap[val] || 'default'}>{val || '-'}</Tag>
      ),
      filters: [
        { text: '辞职', value: '辞职' },
        { text: '辞退', value: '辞退' },
        { text: '合同到期', value: '合同到期' },
        { text: '退休', value: '退休' },
        { text: '其他', value: '其他' },
      ],
      onFilter: (value, record: DepartureRecord) => record.offboarding_type === String(value) },
    {
      title: '离职时司龄',
      dataIndex: 'company_tenure_at_leave',
      key: 'company_tenure_at_leave',
      width: 100 },
    {
      title: '入丽珠时间',
      dataIndex: 'livo_entry_date',
      key: 'livo_entry_date',
      width: 120 },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 120 },
    {
      title: '离职原因',
      dataIndex: 'offboarding_reason',
      key: 'offboarding_reason',
      width: 160,
      ellipsis: true,
      render: (val: string[]) => val?.join(', ') || '-' },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right',
      render: (_: any, record: DepartureRecord) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => message.info(`查看 ${record.name} 的详情（待实现）`)}
          >
            详情
          </Button>
        </Space>
      ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          老厂离职台账
        </h1>
        <Button
          type="primary"
          icon={<SyncOutlined spin={syncing} />}
          onClick={handleSync}
          loading={syncing}
        >
          从飞书同步
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索姓名/部门/职位"
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
          placeholder="离职类型筛选"
          value={filterOffboardingType}
          onChange={(e) => setFilterOffboardingType(e.target.value)}
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
        scroll={{ x: 1400 }}
        size="small"
      />

      <HrChatbot />
    </div>
  )
}

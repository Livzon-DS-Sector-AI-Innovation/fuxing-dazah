'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Popconfirm, Input, Tag } from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { OffboardingRecord } from '@/types/hr'
import { fetchOffboardingRecordsAction, deleteOffboardingRecord } from '@/actions/hr'
import OffboardingForm from './OffboardingForm'
import HrChatbot from './HrChatbot'

interface OffboardingClientProps {
  initialRecords: OffboardingRecord[]
  initialTotal: number
}

export default function OffboardingClient({
  initialRecords,
  initialTotal }: OffboardingClientProps) {
  const { message } = App.useApp()
  const [records, setRecords] = useState<OffboardingRecord[]>(initialRecords)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<OffboardingRecord | null>(null)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchOffboardingRecordsAction({
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
  }, [searchKeyword, page, pageSize])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleRefresh = () => {
    loadData()
  }

  const handleEdit = (record: OffboardingRecord) => {
    setEditingRecord(record)
    setFormOpen(true)
  }

  const handleAdd = () => {
    setEditingRecord(null)
    setFormOpen(true)
  }

  const handleFormSuccess = () => {
    loadData()
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteOffboardingRecord(id)
      message.success('删除成功')
      loadData()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  useEffect(() => {
    loadData()
  }, [searchKeyword, page, pageSize])

  const typeColorMap: Record<string, string> = {
    辞职: 'default',
    辞退: 'red',
    合同到期: 'orange',
    退休: 'blue',
    其他: 'purple' }

  const handoverColorMap: Record<string, string> = {
    待交接: 'warning',
    交接中: 'processing',
    已完成: 'success' }

  const columns = [
    {
      title: '员工姓名',
      key: 'employee_name',
      width: 120,
      render: (_: any, record: OffboardingRecord) => record.employee?.name || '-' },
    {
      title: '工号',
      key: 'employee_number',
      width: 120,
      render: (_: any, record: OffboardingRecord) => record.employee?.employee_number || '-' },
    {
      title: '离职日期',
      dataIndex: 'offboarding_date',
      key: 'offboarding_date',
      width: 120 },
    {
      title: '离职类型',
      dataIndex: 'offboarding_type',
      key: 'offboarding_type',
      width: 100,
      render: (type: string) => <Tag color={typeColorMap[type] || 'default'}>{type}</Tag> },
    {
      title: '离职原因',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true },
    {
      title: '交接状态',
      dataIndex: 'handover_status',
      key: 'handover_status',
      width: 100,
      render: (status: string) => <Tag color={handoverColorMap[status] || 'default'}>{status}</Tag> },
    {
      title: '备注',
      dataIndex: 'notes',
      key: 'notes',
      ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: OffboardingRecord) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="确定要删除该离职记录吗？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          离职管理
        </h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
          新增离职记录
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索姓名或工号"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
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
        scroll={{ x: 1000 }}
      />

      <OffboardingForm
        open={formOpen}
        record={editingRecord}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

      <HrChatbot />
    </div>
  )
}

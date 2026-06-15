'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Table, Space, Popconfirm, Input, Modal } from 'antd'
import { PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, TeamOutlined } from '@ant-design/icons'
import { Department } from '@/types/hr'
import { fetchDepartmentsAction, deleteDepartment } from '@/actions/hr'
import DepartmentForm from './DepartmentForm'
import TeamClient from './TeamClient'
import HrChatbot from './HrChatbot'

interface DepartmentClientProps {
  initialDepartments: Department[]
  initialTotal: number
  fetchAction?: typeof fetchDepartmentsAction
}

export default function DepartmentClient({
  initialDepartments,
  initialTotal,
  fetchAction }: DepartmentClientProps) {
  const { message } = App.useApp()
  const [departments, setDepartments] = useState<Department[]>(initialDepartments)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [formOpen, setFormOpen] = useState(false)
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [teamModalOpen, setTeamModalOpen] = useState(false)
  const [selectedDepartment, setSelectedDepartment] = useState<Department | null>(null)

  const doFetch = fetchAction || fetchDepartmentsAction

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await doFetch({
        keyword: searchKeyword || undefined,
        page,
        page_size: pageSize })
      setDepartments(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [searchKeyword, page, pageSize, doFetch])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleRefresh = () => {
    loadData()
  }

  const handleEdit = (department: Department) => {
    setEditingDepartment(department)
    setFormOpen(true)
  }

  const handleAdd = () => {
    setEditingDepartment(null)
    setFormOpen(true)
  }

  const handleFormSuccess = () => {
    loadData()
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteDepartment(id)
      message.success('删除成功')
      loadData()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleOpenTeams = (department: Department) => {
    setSelectedDepartment(department)
    setTeamModalOpen(true)
  }

  useEffect(() => {
    loadData()
  }, [searchKeyword, page, pageSize])

  const columns = [
    {
      title: '部门编码',
      dataIndex: 'code',
      key: 'code',
      width: 120 },
    {
      title: '部门名称',
      dataIndex: 'name',
      key: 'name',
      width: 160 },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: any, record: Department) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<TeamOutlined />}
            onClick={() => handleOpenTeams(record)}
          >
            班组
          </Button>
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
            description={`确定要删除部门 ${record.name} 吗？`}
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
          老厂部门管理
        </h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
          新增部门
        </Button>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索部门名称或编码"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
      </div>

      <Table
        columns={columns}
        dataSource={departments}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: handlePageChange }}
      />

      <DepartmentForm
        open={formOpen}
        department={editingDepartment}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />

      <Modal
        open={teamModalOpen}
        onCancel={() => setTeamModalOpen(false)}
        footer={null}
        width={800}
      >
        {selectedDepartment && (
          <TeamClient
            departmentId={selectedDepartment.id}
            departmentName={selectedDepartment.name}
          />
        )}
      </Modal>

      <HrChatbot />
    </div>
  )
}

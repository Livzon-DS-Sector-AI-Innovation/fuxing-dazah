'use client'

import { useMemo, useCallback } from 'react'
import { App, Table, Tag, Space, Button, Input, Select } from 'antd'
import { EditOutlined, DeleteOutlined, SearchOutlined } from '@ant-design/icons'
import { Equipment, EquipmentStatus, EquipmentCategory, Location } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteEquipment } from '@/actions/equipment'

const statusConfig: Record<EquipmentStatus, { color: string; label: string; bgColor: string }> = {
  '在用': { color: '#1aae39', label: '在用', bgColor: '#e6f7e6' },
  '备用': { color: '#7b3ff2', label: '备用', bgColor: '#e6e0f5' },
  '维修中': { color: '#dd5b00', label: '维修中', bgColor: '#fff7e6' },
  '停用': { color: '#787671', label: '停用', bgColor: '#f0eeec' },
  '报废': { color: '#e03131', label: '报废', bgColor: '#fff1f0' },
}

// 默认状态配置，用于未知状态
const defaultStatusConfig = { color: '#787671', label: '', bgColor: '#f0eeec' }

const statusOptions = Object.entries(statusConfig).map(([value, { label }]) => ({
  label,
  value,
}))

interface EquipmentTableProps {
  loading?: boolean
  onRefresh?: () => void
}

// 扁平化树结构，创建 ID -> Name 的映射
function buildIdNameMap(items: EquipmentCategory[] | Location[]): Record<string, string> {
  const map: Record<string, string> = {}
  function traverse(nodes: EquipmentCategory[] | Location[]) {
    for (const node of nodes) {
      map[node.id] = node.name
      if ('children' in node && node.children?.length) {
        traverse(node.children as any)
      }
    }
  }
  traverse(items)
  return map
}

export function EquipmentTable({ loading = false, onRefresh }: EquipmentTableProps) {
  const { message, modal } = App.useApp()
  const {
    equipments,
    categories,
    locations,
    total,
    page,
    pageSize,
    statusFilter,
    keyword,
    setPage,
    setPageSize,
    setStatusFilter,
    setKeyword,
    openEquipmentDrawer,
  } = useEquipmentStore()

  // 构建 ID -> Name 映射
  const categoryNameMap = useMemo(() => buildIdNameMap(categories), [categories])
  const locationNameMap = useMemo(() => buildIdNameMap(locations), [locations])

  const handleDelete = useCallback((record: Equipment) => {
    modal.confirm({
      title: '确认删除',
      content: `确定要删除设备 "${record.name}" 吗？`,
      okText: '确认',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteEquipment(record.id)
          message.success('删除设备成功')
          onRefresh?.()
        } catch (error: any) {
          // 显示后端返回的具体错误信息
          const errorMsg = error?.message || '删除设备失败'
          message.error(errorMsg)
        }
      },
    })
  }, [modal, message, onRefresh])

  const columns = [
    {
      title: '设备编号',
      dataIndex: 'equipment_no',
      key: 'equipment_no',
      width: 130,
      fixed: 'start' as const,
    },
    {
      title: '设备名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      fixed: 'start' as const,
    },
    {
      title: '设备分类',
      dataIndex: 'category_id',
      key: 'category',
      width: 110,
      render: (categoryId: string) => categoryNameMap[categoryId] || '-',
    },
    {
      title: '设备位置',
      dataIndex: 'location_id',
      key: 'location',
      width: 110,
      render: (locationId: string) => locationNameMap[locationId] || '-',
    },
    {
      title: '设备状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: EquipmentStatus) => {
        const config = statusConfig[status] || { ...defaultStatusConfig, label: status }
        return (
          <Tag
            style={{
              color: config.color,
              background: config.bgColor,
              border: 'none',
              borderRadius: 4,
              fontWeight: 500,
            }}
          >
            {config.label || status}
          </Tag>
        )
      },
    },
    {
      title: '型号',
      dataIndex: 'model',
      key: 'model',
      width: 120,
    },
    {
      title: '供应商',
      dataIndex: 'supplier',
      key: 'supplier',
      width: 140,
    },
    {
      title: '投用日期',
      dataIndex: 'commissioning_date',
      key: 'commissioning_date',
      width: 110,
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      fixed: 'end' as const,
      render: (_: unknown, record: Equipment) => (
        <Space>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => openEquipmentDrawer(record)}
            style={{ padding: 0 }}
          >
            编辑
          </Button>
          <Button
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
            style={{ padding: 0 }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', gap: 12 }}>
        <Select
          placeholder="设备状态"
          allowClear
          style={{ width: 120 }}
          value={statusFilter || undefined}
          onChange={(value) => setStatusFilter(value || '')}
          options={statusOptions}
        />
        <Input
          placeholder="搜索设备编号或名称"
          prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          style={{ width: 240 }}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
        />
      </div>
      <Table
        columns={columns}
        dataSource={equipments}
        rowKey="id"
        size="small"
        loading={loading}
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (newPage, newPageSize) => {
            setPage(newPage)
            setPageSize(newPageSize)
          },
        }}
      />
    </div>
  )
}

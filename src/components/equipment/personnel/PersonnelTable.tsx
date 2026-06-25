'use client'

import { useState } from 'react'
import { App, Table, Tag, Button, Input, Popconfirm, Typography } from 'antd'
import { DeleteOutlined, TeamOutlined, ApartmentOutlined, SearchOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchPersonnelList } from '@/lib/api/equipment-personnel'
import { deletePersonnel } from '@/actions/equipment-personnel'
import { PersonnelInfo } from './PersonnelInfo'
import type { EquipmentRole, Personnel } from '@/types/equipment-personnel'
import type { ColumnsType } from 'antd/es/table'

const { Text } = Typography

interface Props {
  roles: EquipmentRole[]
  onAddClick: () => void
  onRoleClick: (personnel: Personnel) => void
  onCategoryClick: (personnel: Personnel) => void
}

const STATUS_PILL: Record<string, React.CSSProperties> = {
  'true': {
    display: 'inline-flex', alignItems: 'center',
    padding: '2px 10px', borderRadius: 4,
    fontSize: 12, fontWeight: 600, lineHeight: '20px',
    color: '#1aae39', background: '#d9f3e1',
  },
  'false': {
    display: 'inline-flex', alignItems: 'center',
    padding: '2px 10px', borderRadius: 4,
    fontSize: 12, fontWeight: 600, lineHeight: '20px',
    color: '#787671', background: '#f0eeec',
  },
}

export function PersonnelTable({ roles, onAddClick, onRoleClick, onCategoryClick }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const { data, isLoading } = useQuery({
    queryKey: ['equipment-personnel', { keyword, page, pageSize }],
    queryFn: () => fetchPersonnelList({ keyword: keyword || undefined, page, page_size: pageSize }),
  })

  const handleDelete = async (id: string) => {
    try {
      await deletePersonnel(id)
      message.success('人员已移除')
      queryClient.invalidateQueries({ queryKey: ['equipment-personnel'] })
    } catch {
      message.error('移除失败')
    }
  }

  const columns: ColumnsType<Personnel> = [
    {
      title: '人员',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      render: (_: string, record: Personnel) => <PersonnelInfo personnel={record} />,
    },
    { title: '工号', dataIndex: 'employee_no', key: 'employee_no', width: 100, render: (v: string | null) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', width: 140, ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '角色',
      dataIndex: 'roles',
      key: 'roles',
      width: 200,
      render: (items: Personnel['roles']) => (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {items.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>未分配</Text>
          ) : (
            items.map(r => (
              <Tag key={r.id} color="purple" style={{ margin: 0, borderRadius: 4 }}>{r.name}</Tag>
            ))
          )}
        </div>
      ),
    },
    {
      title: '分类约束',
      dataIndex: 'categories',
      key: 'categories',
      width: 140,
      render: (items: Personnel['categories']) =>
        items.length > 0 ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
            {items.slice(0, 2).map(c => (
              <Tag key={`${c.role_id}-${c.category_id}`} color="orange" style={{ margin: 0, borderRadius: 4, fontSize: 11 }}>
                {c.category_name}
              </Tag>
            ))}
            {items.length > 2 && (
              <Text type="secondary" style={{ fontSize: 11 }}>+{items.length - 2}</Text>
            )}
          </div>
        ) : (
          <Tag style={{ borderRadius: 4, color: '#787671', background: '#f0eeec', border: 'none' }}>全部</Tag>
        ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 70,
      render: (v: boolean) => (
        <span style={STATUS_PILL[String(v)]}>{v ? '在岗' : '离岗'}</span>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 190,
      render: (_: unknown, record: Personnel) => (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            size="small"
            icon={<TeamOutlined />}
            onClick={() => onRoleClick(record)}
            style={{ borderRadius: 8, fontWeight: 500, fontSize: 12 }}
          >
            角色
          </Button>
          <Button
            size="small"
            icon={<ApartmentOutlined />}
            onClick={() => onCategoryClick(record)}
            style={{ borderRadius: 8, fontWeight: 500, fontSize: 12 }}
          >
            分类
          </Button>
          <Popconfirm
            title="确认移除该人员？"
            onConfirm={() => handleDelete(record.id)}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              style={{ borderRadius: 8, fontWeight: 500, fontSize: 12 }}
            />
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <div>
      {/* 搜索栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20,
      }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          placeholder="搜索姓名"
          allowClear
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{
            width: 240,
            borderRadius: 8,
            background: '#f6f5f4',
            border: '1px solid #e5e3df',
          }}
        />
        <Text type="secondary" style={{ fontSize: 13 }}>
          共 {data?.total ?? 0} 人
        </Text>
      </div>

      <Table<Personnel>
        columns={columns}
        dataSource={data?.items ?? []}
        rowKey="id"
        size="middle"
        loading={isLoading}
        scroll={{ x: 960 }}
        pagination={{
          current: data?.page ?? page,
          pageSize: data?.page_size ?? pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (t: number) => (
            <Text style={{ color: '#a4a097', fontSize: 13 }}>共 {t} 条</Text>
          ),
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
        style={{ borderRadius: 0 }}
      />
    </div>
  )
}

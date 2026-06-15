'use client'

import { useRouter } from 'next/navigation'
import { Table, Tag, Space, Popconfirm } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EyeOutlined, DeleteOutlined } from '@ant-design/icons'
import { Candidate } from '@/types/hr'

interface CandidateListViewProps {
  candidates: Candidate[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  onPageChange: (page: number, pageSize: number) => void
  onDelete: (id: string) => void
}

export default function CandidateListView({
  candidates,
  total,
  page,
  pageSize,
  loading,
  onPageChange,
  onDelete,
}: CandidateListViewProps) {
  const router = useRouter()

  const handleRowClick = (record: Candidate) => {
    const ids = candidates.map((c) => c.id)
    const currentIndex = ids.indexOf(record.id)
    sessionStorage.setItem(
      'candidate_list_context',
      JSON.stringify({ ids, currentIndex })
    )
    router.push(`/hr/recruitment/${record.id}`)
  }

  const recommendationColors: Record<string, string> = {
    '强烈推荐': 'green',
    '推荐': 'blue',
    '待定': 'orange',
    '不推荐': 'red',
  }

  const syncStatusMap: Record<string, { text: string; color: string }> = {
    synced: { text: '已同步', color: 'success' },
    failed: { text: '同步失败', color: 'error' },
  }

  const columns: ColumnsType<Candidate> = [
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 100,
    },
    {
      title: '应聘职位',
      dataIndex: 'position',
      key: 'position',
      width: 140,
    },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 80,
    },
    {
      title: '学校',
      dataIndex: 'school',
      key: 'school',
      width: 160,
      ellipsis: true,
    },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80,
    },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120,
      ellipsis: true,
    },
    {
      title: '推荐等级',
      dataIndex: 'recommendation_level',
      key: 'recommendation_level',
      width: 100,
      render: (val: string) =>
        val ? (
          <Tag color={recommendationColors[val] || 'default'}>{val}</Tag>
        ) : (
          '-'
        ),
    },
    {
      title: '飞书同步',
      dataIndex: 'feishu_sync_status',
      key: 'feishu_sync_status',
      width: 100,
      render: (val: string | null | undefined) => {
        const status = val ? syncStatusMap[val] : { text: '未同步', color: 'default' }
        return <Tag color={status.color}>{status.text}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      fixed: 'right',
      render: (_: any, record: Candidate) => (
        <Space size="small">
          <a onClick={() => handleRowClick(record)}>
            <EyeOutlined /> 查看
          </a>
          <Popconfirm
            title="确认删除"
            description={`确定要删除候选人「${record.name}」的简历吗？`}
            onConfirm={() => onDelete(record.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <a className="text-red-500" onClick={(e) => e.stopPropagation()}>
              <DeleteOutlined /> 删除
            </a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={candidates}
      rowKey="id"
      loading={loading}
      pagination={{
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
        onChange: onPageChange,
      }}
      scroll={{ x: 900 }}
      size="small"
    />
  )
}

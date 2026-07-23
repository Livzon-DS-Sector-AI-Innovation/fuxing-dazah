'use client'

import { useRouter } from 'next/navigation'
import { Table, Tag, Space, Popconfirm, Input, Modal, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EyeOutlined, DeleteOutlined, SendOutlined } from '@ant-design/icons'
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
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

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
      title: '操作',
      key: 'action',
      width: 140,
      fixed: 'right',
      render: (_: any, record: Candidate) => (
        <Space size="small">
          <a onClick={() => handleRowClick(record)}>
            <EyeOutlined /> 查看
          </a>
          <a onClick={(e) => {
            e.stopPropagation()
            let email = record.email || ''
            Modal.confirm({
              title: `发放入职 Offer — ${record.name}`,
              content: (
                <div className="space-y-3 pt-2">
                  <div>岗位：{record.position || '—'} / 部门：{record.department || '—'}</div>
                  <Input defaultValue={email} onChange={(ev) => { email = ev.target.value }} placeholder="candidate@example.com" />
                </div>
              ),
              onOk: async () => {
                if (!email) { message.warning('请填写邮箱'); return Promise.reject() }
                const fd = new FormData(); fd.append('candidate_email', email)
                try {
                  const r = await fetch(`${API_BASE}/api/v1/hr/candidates/${record.id}/send-offer`, { method: 'POST', body: fd, credentials: 'include' })
                  const d = await r.json()
                  if (!r.ok) throw new Error(d.message || '发送失败')
                  message.success('Offer 已发送')
                } catch (err: any) { message.error(err.message || '发送失败') }
              },
            })
          }}>
            <SendOutlined /> 发Offer
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

'use client'

import { useRouter } from 'next/navigation'
import { Card, Tag, Pagination, Spin, Empty, Popconfirm, Button } from 'antd'
import { UserOutlined, DeleteOutlined } from '@ant-design/icons'
import { Candidate } from '@/types/hr'

interface CandidateCardViewProps {
  candidates: Candidate[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  onPageChange: (page: number, pageSize: number) => void
  onDelete: (id: string) => void
}

export default function CandidateCardView({
  candidates,
  total,
  page,
  pageSize,
  loading,
  onPageChange,
  onDelete,
}: CandidateCardViewProps) {
  const router = useRouter()

  const handleCardClick = (id: string) => {
    const ids = candidates.map((c) => c.id)
    const currentIndex = ids.indexOf(id)
    sessionStorage.setItem(
      'candidate_list_context',
      JSON.stringify({ ids, currentIndex })
    )
    router.push(`/hr/recruitment/${id}`)
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

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <Spin size="large" />
      </div>
    )
  }

  if (candidates.length === 0) {
    return <Empty description="暂无候选人数据" className="py-20" />
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {candidates.map((candidate) => (
          <Card
            key={candidate.id}
            hoverable
            onClick={() => handleCardClick(candidate.id)}
            className="cursor-pointer"
            bodyStyle={{ padding: '16px' }}
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center">
                <UserOutlined className="text-lg text-gray-500" />
              </div>
              <div>
                <div className="font-medium text-base">{candidate.name}</div>
                <div className="text-sm text-gray-500">{candidate.position}</div>
              </div>
            </div>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">性别</span>
                <span>{candidate.gender || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">学历</span>
                <span>{candidate.education || '-'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">学校</span>
                <span className="truncate max-w-[120px]" title={candidate.school}>
                  {candidate.school || '-'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">专业</span>
                <span className="truncate max-w-[120px]" title={candidate.major}>
                  {candidate.major || '-'}
                </span>
              </div>
            </div>
            <div className="mt-3 pt-3 border-t border-gray-100 flex items-center justify-between">
              <div className="flex gap-2">
                {candidate.recommendation_level && (
                  <Tag color={recommendationColors[candidate.recommendation_level] || 'default'}>
                    {candidate.recommendation_level}
                  </Tag>
                )}
                <Tag color={candidate.feishu_sync_status ? syncStatusMap[candidate.feishu_sync_status]?.color || 'default' : 'default'}>
                  {candidate.feishu_sync_status ? syncStatusMap[candidate.feishu_sync_status]?.text || candidate.feishu_sync_status : '未同步'}
                </Tag>
              </div>
              <Popconfirm
                title="确认删除"
                description={`确定要删除候选人「${candidate.name}」的简历吗？`}
                onConfirm={() => onDelete(candidate.id)}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                >
                  删除
                </Button>
              </Popconfirm>
            </div>
          </Card>
        ))}
      </div>
      <div className="flex justify-end">
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger
          showTotal={(t) => `共 ${t} 条`}
          onChange={onPageChange}
        />
      </div>
    </div>
  )
}

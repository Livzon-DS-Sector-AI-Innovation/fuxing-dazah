'use client'

import { useState } from 'react'
import { Alert, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { feedbackKeys, fetchMyFeedbacks } from '@/lib/api/feedback'
import type { Feedback, FeedbackType } from '@/types/feedback'
import {
  FeedbackContentCell,
  FeedbackMeta,
  FeedbackStatusTag,
  FeedbackTypeTag,
} from './FeedbackCells'
import { FeedbackAttachmentStrip } from './FeedbackAttachmentStrip'

const COLUMNS: TableColumnsType<Feedback> = [
  {
    title: '类型',
    dataIndex: 'type',
    width: 96,
    onCell: () => ({ style: { verticalAlign: 'top' } }),
    render: (type: FeedbackType) => <FeedbackTypeTag type={type} />,
  },
  {
    title: '反馈内容',
    dataIndex: 'content',
    render: (_: unknown, row) => (
      <div className="min-w-0">
        <FeedbackContentCell content={row.content} />
        {/* 未处理前本人可补传/删除；已处理后只读且无图时不占位 */}
        {(row.attachments.length > 0 || !row.is_handled) && (
          <div className="mt-1.5">
            <FeedbackAttachmentStrip
              feedback={row}
              allowUpload={!row.is_handled}
              allowDelete={!row.is_handled}
              size={40}
            />
          </div>
        )}
        <FeedbackMeta feedback={row} showSubmitter={false} />
      </div>
    ),
  },
  {
    title: '状态',
    dataIndex: 'is_handled',
    width: 96,
    onCell: () => ({ style: { verticalAlign: 'top', paddingTop: 6 } }),
    render: (_: unknown, row) => <FeedbackStatusTag feedback={row} />,
  },
]

/** 我的反馈：本人提交的记录及其处理状态。 */
export function FeedbackMineList() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const params = { page, page_size: pageSize }
  const query = useQuery({
    queryKey: feedbackKeys.mine(params),
    queryFn: () => fetchMyFeedbacks(params),
  })

  return (
    <div className="flex flex-col gap-3">
      {query.isError && (
        <Alert type="error" showIcon title={query.error.message || '我的反馈加载失败'} />
      )}
      <Table<Feedback>
        rowKey="id"
        size="small"
        columns={COLUMNS}
        dataSource={query.data?.items ?? []}
        loading={query.isPending}
        scroll={{ x: 480 }}
        pagination={{
          current: page,
          pageSize,
          total: query.data?.total ?? 0,
          size: 'small',
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage)
            setPageSize(nextSize)
          },
        }}
        locale={{ emptyText: '你还没有提交过反馈' }}
      />
    </div>
  )
}

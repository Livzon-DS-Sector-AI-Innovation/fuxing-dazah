'use client'

import { useState } from 'react'
import { Alert, App, Segmented, Select, Table } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { setFeedbackHandled } from '@/actions/feedback'
import { feedbackKeys, fetchFeedbackList } from '@/lib/api/feedback'
import {
  FEEDBACK_TYPE_OPTIONS,
  type Feedback,
  type FeedbackListParams,
  type FeedbackType,
} from '@/types/feedback'
import {
  FeedbackContentCell,
  FeedbackHandledToggle,
  FeedbackMeta,
  FeedbackTypeTag,
} from './FeedbackCells'
import { FeedbackAttachmentStrip } from './FeedbackAttachmentStrip'

type HandledFilter = 'pending' | 'handled' | 'all'

const HANDLED_OPTIONS: { value: HandledFilter; label: string }[] = [
  { value: 'pending', label: '待处理' },
  { value: 'handled', label: '已处理' },
  { value: 'all', label: '全部' },
]

/** 管理员视图：内容为主、来源为副，状态即处理开关。 */
export function FeedbackAdminList() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [handledFilter, setHandledFilter] = useState<HandledFilter>('pending')
  const [typeFilter, setTypeFilter] = useState<FeedbackType | undefined>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [togglingId, setTogglingId] = useState<string | null>(null)

  const params: FeedbackListParams = {
    page,
    page_size: pageSize,
    is_handled: handledFilter === 'all' ? null : handledFilter === 'handled',
    type: typeFilter ?? null,
  }
  const query = useQuery({
    queryKey: feedbackKeys.list(params),
    queryFn: () => fetchFeedbackList(params),
  })

  const toggleHandled = async (row: Feedback) => {
    setTogglingId(row.id)
    try {
      const result = await setFeedbackHandled(row.id, !row.is_handled)
      if (!result.success) {
        message.error(result.error)
        return
      }
      message.success(row.is_handled ? '已取消标记' : '已标记为已处理')
      // 当前筛选下该行会离开列表；若它是本页最后一条，回退一页避免落在空页
      const leavesFilter =
        (handledFilter === 'pending' && !row.is_handled) ||
        (handledFilter === 'handled' && row.is_handled)
      if (leavesFilter && page > 1 && query.data?.items.length === 1) {
        setPage(page - 1)
      }
      void queryClient.invalidateQueries({ queryKey: feedbackKeys.all })
    } finally {
      setTogglingId(null)
    }
  }

  const columns: TableColumnsType<Feedback> = [
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
          {row.attachments.length > 0 && (
            <div className="mt-1.5">
              <FeedbackAttachmentStrip feedback={row} allowDelete size={40} />
            </div>
          )}
          <FeedbackMeta feedback={row} />
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_handled',
      width: 96,
      onCell: () => ({ style: { verticalAlign: 'top', paddingTop: 6 } }),
      render: (_: unknown, row) => (
        <FeedbackHandledToggle
          feedback={row}
          loading={togglingId === row.id}
          onToggle={() => void toggleHandled(row)}
        />
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented
          size="small"
          value={handledFilter}
          options={HANDLED_OPTIONS}
          onChange={(value) => {
            setHandledFilter(value as HandledFilter)
            setPage(1)
          }}
        />
        <Select
          allowClear
          size="small"
          placeholder="全部类型"
          style={{ width: 132 }}
          value={typeFilter}
          options={FEEDBACK_TYPE_OPTIONS}
          onChange={(value) => {
            setTypeFilter(value)
            setPage(1)
          }}
        />
      </div>
      {query.isError && (
        <Alert type="error" showIcon title={query.error.message || '反馈列表加载失败'} />
      )}
      <Table<Feedback>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={query.data?.items ?? []}
        loading={query.isPending}
        scroll={{ x: 600 }}
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
        locale={{ emptyText: handledFilter === 'pending' ? '没有待处理的反馈' : '暂无反馈' }}
      />
    </div>
  )
}

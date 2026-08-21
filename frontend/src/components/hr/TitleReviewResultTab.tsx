'use client'

import { useCallback, useEffect, useState } from 'react'
import { Alert, App, Button, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import type { TitleReviewResultRow } from '@/types/hr'
import { fetchTitleResults } from '@/actions/hr'

interface Props {
  activityId: string
  canViewScores: boolean
}

const RESULT_META: Record<string, { label: string; color: string }> = {
  passed: { label: '投票通过', color: 'success' },
  failed: { label: '投票未通过', color: 'error' },
  final_passed: { label: '终审通过', color: 'success' },
  final_failed: { label: '终审驳回', color: 'error' },
}

export default function TitleReviewResultTab({ activityId, canViewScores }: Props) {
  const { message } = App.useApp()
  const [results, setResults] = useState<TitleReviewResultRow[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    if (!canViewScores) return
    setLoading(true)
    fetchTitleResults(activityId)
      .then((d) => setResults(d?.data || []))
      .catch((err: any) => message.error(err.message || '加载评审结果失败'))
      .finally(() => setLoading(false))
  }, [activityId, canViewScores, message])

  useEffect(() => {
    load()
  }, [load])

  const columns = [
    { title: '申报人', key: 'name', width: 130, render: (_: unknown, r: TitleReviewResultRow) => `${r.application.name}（${r.application.employee_no}）` },
    { title: '部门', key: 'dept', width: 120, ellipsis: true, render: (_: unknown, r: TitleReviewResultRow) => r.application.department || '-' },
    {
      title: '序列/职级', key: 'level', width: 150,
      render: (_: unknown, r: TitleReviewResultRow) => `${r.application.sequence || '-'} · ${r.application.apply_level || '-'}`,
    },
    {
      title: '票数', key: 'votes', width: 120,
      render: (_: unknown, r: TitleReviewResultRow) => `${r.application.agree_votes} / ${r.application.oppose_votes} / ${r.application.abstain_votes}`,
    },
    {
      title: '通过比例', key: 'ratio', width: 100,
      render: (_: unknown, r: TitleReviewResultRow) =>
        r.vote_ratio != null ? `${(r.vote_ratio * 100).toFixed(1)}%` : '-',
    },
    {
      title: '结果', key: 'result', width: 110,
      render: (_: unknown, r: TitleReviewResultRow) => {
        const meta = RESULT_META[r.application.status]
        return meta ? <Tag color={meta.color}>{meta.label}</Tag> : (r.application.status === 'voting' ? <Tag>投票中</Tag> : r.application.status)
      },
    },
  ]

  const expandedRowRender = (row: TitleReviewResultRow) => (
    <div className="px-6 pb-2 space-y-2">
      {row.judges.map((j) => (
        <div key={j.id} className="text-[13px]">
          <Typography.Text strong>
            {j.judge_code} · {j.judge_name}（{j.judge_role || '-'}）
          </Typography.Text>
          <Tag color={j.vote_result === '同意' ? 'success' : j.vote_result === '不同意' ? 'error' : 'default'} className="ml-2">
            {j.vote_result || '未投'}
          </Tag>
          {j.comprehensive_grade && <Tag>{j.comprehensive_grade}</Tag>}
          {j.voted_at && <span className="ml-1 text-[var(--color-steel)]">{new Date(j.voted_at).toLocaleString()}</span>}
          {j.scores.length > 0 && (
            <span className="ml-2 text-[var(--color-steel)]">
              {j.scores.map((s) => `${s.dimension_name}: ${s.grade ?? '-'}`).join(' ／ ')}
            </span>
          )}
          {j.review_comment && (
            <div className="mt-1 text-[var(--color-steel)]">评审意见：{j.review_comment}</div>
          )}
        </div>
      ))}
      {row.application.final_opinion && (
        <div className="text-[13px] text-[var(--color-steel)]">附件4评审综合意见：{row.application.final_opinion}</div>
      )}
    </div>
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Typography.Text type="secondary">
          票数判定：同意÷(同意+不同意) 达通过比例即通过，弃权不计入分母；评委在内网系统投票；投票明细仅授权人员可见
        </Typography.Text>
        {canViewScores && <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
      </div>

      {canViewScores ? (
        <Table
          rowKey={(r) => r.application.id}
          size="middle"
          loading={loading}
          columns={columns}
          dataSource={results}
          pagination={false}
          expandable={{ expandedRowRender }}
          scroll={{ x: 900 }}
        />
      ) : (
        <Alert type="info" showIcon message="您没有查看评审结果与投票明细的权限（hr:title:scores:read），如需查看请联系管理员配置。" />
      )}
    </div>
  )
}

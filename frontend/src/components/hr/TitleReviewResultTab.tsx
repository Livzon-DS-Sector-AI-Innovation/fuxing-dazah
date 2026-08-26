'use client'

import { useCallback, useEffect, useState } from 'react'
import { Alert, App, Button, Card, Checkbox, Modal, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined, TeamOutlined } from '@ant-design/icons'
import type { TitleReviewResultRow } from '@/types/hr'
import { downloadTitleResultsExport, downloadTitleRosterExport, fetchTitleResults, fetchTitleSummary } from '@/actions/hr'

interface Props {
  activityId: string
  canViewScores: boolean
}

const RESULT_META: Record<string, { label: string; color: string }> = {
  passed: { label: '评审合格', color: 'success' },
  failed: { label: '评审未通过', color: 'error' },
  final_passed: { label: '终审通过', color: 'success' },
  final_failed: { label: '终审驳回', color: 'error' },
}

export default function TitleReviewResultTab({ activityId, canViewScores }: Props) {
  const { message } = App.useApp()
  const [results, setResults] = useState<TitleReviewResultRow[]>([])
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<any>(null)
  const [exporting, setExporting] = useState(false)
  const [rosterOpen, setRosterOpen] = useState(false)
  const [rosterIds, setRosterIds] = useState<string[]>([])
  const [rosterSaving, setRosterSaving] = useState(false)

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
    if (canViewScores) {
      fetchTitleSummary(activityId)
        .then((d) => setSummary(d?.data || null))
        .catch(() => setSummary(null))
    }
  }, [load, canViewScores, activityId])

  const passedRows = results.filter((r) => r.application.status === 'passed')
  // 名单候选：排除评审未通过/信息异常，其余均可勾选（默认勾评审合格）
  const rosterRows = results.filter((r) => !['failed', 'final_failed', 'invalid'].includes(r.application.status))

  const openRoster = () => {
    setRosterIds(passedRows.map((r) => r.application.id))
    setRosterOpen(true)
  }

  const handleRosterExport = async () => {
    if (!rosterIds.length) return message.warning('请至少选择一人')
    setRosterSaving(true)
    try {
      const { base64, filename } = await downloadTitleRosterExport(activityId, rosterIds)
      const link = document.createElement('a')
      link.href = `data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${base64}`
      link.download = filename || '职级认定结果名单.docx'
      link.click()
      setRosterOpen(false)
    } catch (err: any) {
      message.error(err.message || '生成名单失败')
    } finally {
      setRosterSaving(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { base64, filename } = await downloadTitleResultsExport(activityId)
      const link = document.createElement('a')
      link.href = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${base64}`
      link.download = filename || '职称评审结果汇总.xlsx'
      link.click()
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setExporting(false)
    }
  }

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
        <div className="flex gap-2">
          {canViewScores && <Button size="small" icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>导出汇总</Button>}
          {canViewScores && rosterRows.length > 0 && (
            <Button size="small" type="primary" icon={<TeamOutlined />} onClick={openRoster}>生成名单</Button>
          )}
          {canViewScores && <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
        </div>
      </div>

      <Modal
        title="生成职级认定结果名单"
        open={rosterOpen}
        width={480}
        confirmLoading={rosterSaving}
        onCancel={() => setRosterOpen(false)}
        onOk={handleRosterExport}
        okText="生成名单（docx）"
      >
        <div className="mt-4 space-y-2">
          <Typography.Text type="secondary">
            勾选进入最终名单的人员（默认勾选评审合格者，可手动调整）；生成表格含：序号 / 部门 / 职务 / 姓名 / 本年度认定职称。
          </Typography.Text>
          <Checkbox.Group
            className="flex flex-col gap-1"
            value={rosterIds}
            onChange={(v) => setRosterIds(v as string[])}
          >
            {rosterRows.map((r) => (
              <Checkbox key={r.application.id} value={r.application.id}>
                <span className="inline-flex items-center gap-2">
                  {r.application.name}（{r.application.employee_no}）· {r.application.department || '-'} · 申报{r.application.apply_level || '-'}
                  {RESULT_META[r.application.status] && (
                    <Tag color={RESULT_META[r.application.status].color}>{RESULT_META[r.application.status].label}</Tag>
                  )}
                </span>
              </Checkbox>
            ))}
          </Checkbox.Group>
        </div>
      </Modal>

      {canViewScores && summary && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Card size="small" title="按职级分组">
            <Table
              rowKey={(r: any) => `${r.sequence}-${r.level_name}`}
              size="small"
              pagination={false}
              dataSource={summary.by_level || []}
              columns={[
                { title: '序列', dataIndex: 'sequence', width: 90 },
                { title: '职级', dataIndex: 'level_name', width: 100 },
                { title: '申报', dataIndex: 'applications', width: 60 },
                { title: '通过', dataIndex: 'passed', width: 60 },
                { title: '未通过', dataIndex: 'failed', width: 70 },
                { title: '评审中', dataIndex: 'pending', width: 70 },
                {
                  title: '通过率', dataIndex: 'pass_rate', width: 70,
                  render: (v: number | null) => (v != null ? `${v}%` : '-'),
                },
              ]}
            />
          </Card>
          <Card size="small" title="按部门分组">
            <Table
              rowKey="department"
              size="small"
              pagination={false}
              dataSource={summary.by_department || []}
              columns={[
                { title: '部门', dataIndex: 'department', ellipsis: true },
                { title: '申报', dataIndex: 'applications', width: 60 },
                { title: '通过', dataIndex: 'passed', width: 60 },
                { title: '未通过', dataIndex: 'failed', width: 70 },
                { title: '评审中', dataIndex: 'pending', width: 70 },
                {
                  title: '通过率', dataIndex: 'pass_rate', width: 70,
                  render: (v: number | null) => (v != null ? `${v}%` : '-'),
                },
              ]}
            />
          </Card>
        </div>
      )}

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

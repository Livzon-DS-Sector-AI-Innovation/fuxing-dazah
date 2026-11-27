'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Card, Popconfirm, Space, Table, Tag, Tooltip } from 'antd'
import { EditOutlined, DeleteOutlined, SearchOutlined, BellOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { fetchQaAssessments, fetchQaAssessmentDetail, downloadQaAssessmentRecord, deleteQaAssessment } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'
import { usePermission } from '@/hooks/usePermission'
import { QaAssessment, QaAssessmentScore } from '@/types/hr'
import PageHeader from './PageHeader'

export default function QaAssessmentClient() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  // 仅「考核历史」权限的用户不展示必然 403 的记录表下载与删除入口
  const canExport = hasPermission('hr:training:export')
  const canManage = hasPermission('hr:training:manage')
  const [list, setList] = useState<QaAssessment[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailScores, setDetailScores] = useState<QaAssessmentScore[]>([])
  const [currentSubject, setCurrentSubject] = useState('')
  // 行内「记录表」下载按钮的 loading，按记录 id 区分
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  const loadList = useCallback(async (p = 1) => {
    setLoading(true)
    try {
      const res = await fetchQaAssessments({ page: p, page_size: 20 })
      setList(res.data || [])
      setTotal(res.meta?.total || 0)
      setPage(p)
    } catch (err: any) { message.error(err.message || '加载失败') }
    finally { setLoading(false) }
  }, [message])

  useEffect(() => { loadList() }, [loadList])

  const viewDetail = async (a: QaAssessment) => {
    try {
      const res = await fetchQaAssessmentDetail(a.id)
      setDetailScores(res.data.scores || [])
      setCurrentSubject(a.subject)
      setDetailOpen(true)
    } catch (err: any) { message.error(err.message || '加载详情失败') }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="考核历史"
        description="历史考核场次及成绩查询"
        actions={
          <Link href="/hr/training/notification">
            <Button type="primary" icon={<BellOutlined />}>去培训通知发起考核</Button>
          </Link>
        }
      />
      <Card>
        <Table
          rowKey="id" loading={loading} dataSource={list}
          pagination={{ current: page, pageSize: 20, total, onChange: (p) => loadList(p) }}
          columns={[
            { title: '培训内容', dataIndex: 'subject', ellipsis: true },
            { title: '部门', dataIndex: 'department', width: 130 },
            { title: '日期', dataIndex: 'training_date', width: 110 },
            { title: '方式', dataIndex: 'training_method', width: 80 },
            { title: '题数', dataIndex: 'question_count', width: 60, align: 'center' as const },
            { title: '操作', width: 230,
              render: (_: any, a: QaAssessment) => (
                <Space size="small" wrap>
                  <Button size="small" icon={<SearchOutlined />} onClick={() => viewDetail(a)}>成绩</Button>
                  {canExport && (
                    <Button size="small" icon={<EditOutlined />} loading={downloadingId === a.id}
                      onClick={async () => {
                        setDownloadingId(a.id)
                        try { const r = await downloadQaAssessmentRecord(a.id); downloadBase64File(r.base64, r.filename); message.success('已下载') }
                        catch (err: any) { message.error(err.message || '下载失败') }
                        finally { setDownloadingId(null) }
                      }}>
                      记录表
                    </Button>
                  )}
                  {canManage && (
                    <Popconfirm title="确认删除？" onConfirm={async () => {
                      try { await deleteQaAssessment(a.id); message.success('已删除'); loadList(page) }
                      catch (err: any) { message.error(err.message || '删除失败') }
                    }}>
                      <Tooltip title="删除">
                        <Button size="small" danger icon={<DeleteOutlined />} aria-label="删除" />
                      </Tooltip>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Card
        title={detailOpen ? `成绩详情 — ${currentSubject}` : '成绩详情'}
        style={{ display: detailOpen ? 'block' : 'none' }}
        extra={<Button size="small" onClick={() => setDetailOpen(false)}>关闭</Button>}
      >
        <Table
          rowKey="id" size="small" dataSource={detailScores}
          pagination={false}
          columns={[
            { title: '姓名', dataIndex: 'employee_name', width: 100 },
            { title: '工号', dataIndex: 'employee_number', width: 100 },
            { title: '错题', dataIndex: 'wrong_questions',
              render: (v: number[] | null) => (v && v.length > 0) ? v.join(', ') : '全对' },
            { title: '总分', dataIndex: 'total_score', width: 70, align: 'center' as const },
            { title: '等级', dataIndex: 'grade', width: 80, align: 'center' as const,
              render: (v: string) => <Tag color={v === '优秀' ? 'green' : v === '合格' ? 'blue' : 'red'}>{v}</Tag> },
            { title: '得分情况', dataIndex: 'result_text', ellipsis: true },
            { title: '考核日期', dataIndex: 'assessed_date', width: 110 },
          ]}
        />
      </Card>
    </div>
  )
}

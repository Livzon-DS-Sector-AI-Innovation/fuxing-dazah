'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Form, Input, Radio, Segmented, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { fetchMyJudgeTasks, submitJudgeVote } from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import PageHeader from '@/components/hr/PageHeader'
import TitleReviewAttachments from './TitleReviewAttachments'
import TitleReviewProfile from './TitleReviewProfile'
import TitleReviewWorkValue from './TitleReviewWorkValue'

/** 附表5 规则：综合等级与投票结果由 7 项维度评价自动计算（两档，与后端一致） */
function computeAutoResult(
  grades: Record<string, string> | undefined,
  dimensions: { name: string }[],
): { grade: string | null; result: string | null } {
  const values = dimensions.map((d) => grades?.[d.name])
  if (values.some((v) => !v)) return { grade: null, result: null }
  const qualified = values.filter((v) => v === '合格').length
  const grade = qualified >= 5 ? '合格' : '不合格'
  return { grade, result: grade === '不合格' ? '不同意' : '同意' }
}

const GRADES = ['合格', '不合格']

interface JudgeTask {
  judge_id: string
  judge_code: string
  status: string
  vote_result?: string
  comprehensive_grade?: string
  review_comment?: string
  dimension_grades: Record<string, string | null>
  grade_tier: 'high' | 'low'
  dimensions: { name: string; standard: string }[]
  activity_name: string
  application: {
    id: string
    name: string
    employee_no: string
    department?: string
    sequence?: string
    tech_domain?: string
    apply_level?: string
    current_level?: string
    is_exception: boolean
    exception_reason?: string
    self_evaluations?: Record<string, string>
    work_statements?: Record<string, string>
    attachments?: Record<string, { file_token: string; name: string; size: number }[]>
    profile?: Record<string, string> | null
    status: string
  }
}

export default function TitleJudgeClient() {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [tasks, setTasks] = useState<JudgeTask[]>([])
  const [loading, setLoading] = useState(false)
  const [voting, setVoting] = useState<JudgeTask | null>(null)
  const [saving, setSaving] = useState(false)
  // 抽屉里有未提交的评价/意见：关闭（点遮罩、ESC、取消）前先确认，此前点遮罩即丢
  const [votingDirty, setVotingDirty] = useState(false)
  const closeVote = useCallback(() => { setVoting(null); setVotingDirty(false) }, [])
  const guardClose = useUnsavedConfirm(votingDirty, closeVote, {
    content: '抽屉里的维度评价和评审意见还没提交，关闭后会丢失，确定放弃吗？',
    // 抽屉关闭后页面不离开；beforeunload 拦截在抽屉打开且未保存时仍然需要
    guardBeforeUnload: true,
  })
  // 任务表筛选：全部 / 待投票 / 已投票
  const [voteFilter, setVoteFilter] = useState<'all' | 'pending' | 'voted'>('all')
  const watchedDims = Form.useWatch('dimension_grades', form)
  const auto = computeAutoResult(
    watchedDims as Record<string, string> | undefined,
    voting?.dimensions || [],
  )

  const load = useCallback(() => {
    setLoading(true)
    fetchMyJudgeTasks()
      .then((d) => setTasks(d?.data || []))
      .catch((err: any) => message.error(err.message || '加载投票任务失败'))
      .finally(() => setLoading(false))
  }, [message])

  useEffect(() => {
    load()
  }, [load])

  const openVote = (task: JudgeTask) => {
    setVotingDirty(false)
    setVoting(task)
    form.setFieldsValue({
      review_comment: task.review_comment,
      dimension_grades: task.dimension_grades || {},
    })
  }

  const handleSubmit = async () => {
    // 校验失败只走表单行内提示（7 项评价必填）
    let values: { dimension_grades?: Record<string, string>; review_comment?: string }
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    if (!voting) return
    setSaving(true)
    try {
      const d = await submitJudgeVote(voting.judge_id, {
        dimension_grades: values.dimension_grades || {},
        review_comment: values.review_comment,
      })
      message.success(d.message || '投票提交成功')
      setVoting(null)
      setVotingDirty(false)
      load()
    } catch (err: any) {
      message.error(err.message || '提交失败')
    } finally {
      setSaving(false)
    }
  }

  // 后端任务状态只有 voted / pending 两种：与状态列同口径，非 voted 一律算待投票
  const votedCount = tasks.filter((t) => t.status === 'voted').length
  const pendingCount = tasks.length - votedCount
  const filteredTasks =
    voteFilter === 'all' ? tasks : tasks.filter((t) => (t.status === 'voted') === (voteFilter === 'voted'))

  const columns = [
    {
      title: '申报人', key: 'applicant', width: 130,
      render: (_: unknown, r: JudgeTask) => `${r.application.name}（${r.application.employee_no}）`,
    },
    { title: '部门', key: 'dept', width: 120, ellipsis: true, render: (_: unknown, r: JudgeTask) => r.application.department || '-' },
    {
      title: '序列/职级', key: 'level', width: 160,
      render: (_: unknown, r: JudgeTask) => `${r.application.sequence || '-'} · ${r.application.apply_level || '-'}`,
    },
    { title: '活动', key: 'activity', width: 180, ellipsis: true, render: (_: unknown, r: JudgeTask) => r.activity_name },
    {
      title: '状态', key: 'status', width: 100,
      render: (_: unknown, r: JudgeTask) =>
        r.status === 'voted' ? <Tag color="success">已投票</Tag> : <Tag color="processing">待投票</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_: unknown, r: JudgeTask) => (
        <Button size="small" type={r.status === 'voted' ? 'default' : 'primary'} onClick={() => openVote(r)}>
          {r.status === 'voted' ? '查看/修改' : '去投票'}
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <PageHeader
        title="评审投票"
        description={`评委投票${tasks[0]?.judge_code ? `（匿名编号 ${tasks[0].judge_code}）` : ''}：请审阅申报材料后完成 7 项维度评价，综合等级与投票结果自动计算`}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          value={voteFilter}
          onChange={(v) => setVoteFilter(v as typeof voteFilter)}
          options={[
            { value: 'all', label: '全部' },
            { value: 'pending', label: '待投票' },
            { value: 'voted', label: '已投票' },
          ]}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Typography.Text type="secondary">待投票 {pendingCount} 人 / 已投票 {votedCount} 人</Typography.Text>
          <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        </div>
      </div>

      <Table rowKey="judge_id" size="middle" loading={loading} columns={columns} dataSource={filteredTasks} pagination={false} scroll={{ x: 900 }} />

      <Drawer
        title={voting ? `投票：${voting.application.name}（${voting.application.employee_no}）` : '投票'}
        open={!!voting}
        size={680}
        onClose={guardClose}
        mask={{ closable: false }}
        footer={
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
            {voting && (
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
                <Typography.Text type="secondary" className="text-[12px]">投票结果（由维度评价自动计算）</Typography.Text>
                <div className="flex items-center gap-6">
                  <div>
                    <Typography.Text type="secondary" className="text-[12px]">综合等级</Typography.Text>
                    <div className="mt-1">{auto.grade || '待 7 项评价填齐'}</div>
                  </div>
                  <div>
                    <Typography.Text type="secondary" className="text-[12px]">投票结果</Typography.Text>
                    <div className="mt-1">
                      {auto.result
                        ? <Tag color={auto.result === '不同意' ? 'error' : 'success'}>{auto.result}</Tag>
                        : '-'}
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div className="flex items-center ml-auto">
              <Button onClick={guardClose} className="mr-2">取消</Button>
              <Button type="primary" loading={saving} onClick={handleSubmit}>提交投票</Button>
            </div>
          </div>
        }
      >
        {voting && (
          <div className="space-y-4">
            <div>
              <Typography.Text strong>申报信息</Typography.Text>
              <Descriptions column={2} size="small" bordered className="mt-2">
                <Descriptions.Item label="部门">{voting.application.department || '-'}</Descriptions.Item>
                <Descriptions.Item label="申报序列">{voting.application.sequence || '-'}</Descriptions.Item>
                <Descriptions.Item label="申报职级">{voting.application.apply_level || '-'}</Descriptions.Item>
                <Descriptions.Item label="现任职级">{voting.application.current_level || '-'}</Descriptions.Item>
                <Descriptions.Item label="是否破格">{voting.application.is_exception ? '是' : '否'}</Descriptions.Item>
                {voting.application.exception_reason && (
                  <Descriptions.Item label="破格理由" span={2}>{voting.application.exception_reason}</Descriptions.Item>
                )}
              </Descriptions>
            </div>
            <TitleReviewProfile profile={voting.application.profile} />
            {voting.application.self_evaluations && Object.keys(voting.application.self_evaluations).length > 0 && (
              <div>
                <Typography.Text strong>申报人自我评价</Typography.Text>
                <Descriptions column={1} size="small" bordered className="mt-2">
                  {Object.entries(voting.application.self_evaluations).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>
                  ))}
                </Descriptions>
              </div>
            )}
            {voting.application.work_statements && Object.keys(voting.application.work_statements).length > 0 && (
              <div>
                <Typography.Text strong>业绩陈述</Typography.Text>
                <Descriptions column={1} size="small" bordered className="mt-2">
                  {Object.entries(voting.application.work_statements).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      <TitleReviewWorkValue name={k} value={v} />
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </div>
            )}
            {voting.application.attachments && (
              <TitleReviewAttachments
                applicationId={voting.application.id}
                attachments={voting.application.attachments}
              />
            )}

            <Form form={form} layout="vertical" onValuesChange={() => setVotingDirty(true)}>
              {/* 投票结果（综合等级 / 同意与否）已移到抽屉底栏常驻：原先排在这里，填到最后一项时已滚出视口 */}
              <Typography.Text strong>
                维度评价（{voting.dimensions.length} 项，必填）{voting.grade_tier === 'high' ? '｜高档标准（工程/技师及以上）' : '｜低档标准'}
              </Typography.Text>
              <Typography.Text type="secondary" className="block mt-1 text-[12px]">
                规则（附表5）：合格＝7项中≥5项合格；不合格＝7项中3项以上不合格。合格→同意，不合格→不同意。
              </Typography.Text>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-2">
                {voting.dimensions.map((dim, idx) => (
                  <Form.Item
                    key={dim.name}
                    name={['dimension_grades', dim.name]}
                    label={
                      <span>
                        {idx + 1}. {dim.name}
                        <Typography.Text type="secondary" className="block text-[12px] font-normal">
                          合格标准：{dim.standard || '-'}
                        </Typography.Text>
                      </span>
                    }
                    className="!mb-2"
                    rules={[{ required: true, message: '请完成该项评价' }]}
                  >
                    <Radio.Group buttonStyle="solid" style={{ display: 'flex', width: '100%' }}>
                      {GRADES.map((g) => (
                        <Radio.Button key={g} value={g} style={{ flex: 1, textAlign: 'center' }}>
                          {g}
                        </Radio.Button>
                      ))}
                    </Radio.Group>
                  </Form.Item>
                ))}
              </div>
              <Form.Item name="review_comment" label="评审意见">
                <Input.TextArea rows={3} placeholder="选填" />
              </Form.Item>
            </Form>
          </div>
        )}
      </Drawer>
    </div>
  )
}

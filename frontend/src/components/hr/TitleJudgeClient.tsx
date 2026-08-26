'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Form, Input, Radio, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { fetchMyJudgeTasks, submitJudgeVote } from '@/actions/hr'
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
    setVoting(task)
    form.setFieldsValue({
      review_comment: task.review_comment,
      dimension_grades: task.dimension_grades || {},
    })
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    if (!voting) return
    setSaving(true)
    try {
      const d = await submitJudgeVote(voting.judge_id, {
        dimension_grades: values.dimension_grades || {},
        review_comment: values.review_comment,
      })
      message.success(d.message || '投票提交成功')
      setVoting(null)
      load()
    } catch (err: any) {
      message.error(err.message || '提交失败')
    } finally {
      setSaving(false)
    }
  }

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
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">职称评审投票</h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          评委投票（匿名编号 {tasks[0]?.judge_code || ''}）：请审阅申报材料后完成 7 项维度评价，综合等级与投票结果自动计算
        </p>
      </div>

      <div className="flex justify-end">
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </div>

      <Table rowKey="judge_id" size="middle" loading={loading} columns={columns} dataSource={tasks} pagination={false} scroll={{ x: 900 }} />

      <Drawer
        title={voting ? `投票：${voting.application.name}（${voting.application.employee_no}）` : '投票'}
        open={!!voting}
        width={680}
        onClose={() => setVoting(null)}
        footer={
          <div className="flex justify-end">
            <Button onClick={() => setVoting(null)} className="mr-2">取消</Button>
            <Button type="primary" loading={saving} onClick={handleSubmit}>提交投票</Button>
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
              <div>
                <Typography.Text strong>附件材料</Typography.Text>
                <div className="mt-1 space-y-1">
                  {Object.entries(voting.application.attachments).map(([k, files]) => (
                    <div key={k} className="text-[13px]">{k}：{(files || []).map((f) => f.name).join('、') || '无'}</div>
                  ))}
                </div>
              </div>
            )}

            <Form form={form} layout="vertical">
              <div className="bg-[var(--color-surface)] border border-[var(--color-hairline)] rounded p-3 mb-3">
                <Typography.Text type="secondary" className="text-[12px]">投票结果（由维度评价自动计算）</Typography.Text>
                <div className="mt-1 flex items-center gap-8">
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
                <Typography.Text type="secondary" className="block mt-2 text-[12px]">
                  规则（附表5）：合格＝7项中≥5项合格；不合格＝7项中3项以上不合格。合格→同意，不合格→不同意。
                </Typography.Text>
              </div>
              <Typography.Text strong>
                维度评价（{voting.dimensions.length} 项，必填）{voting.grade_tier === 'high' ? '｜高档标准（工程/技师及以上）' : '｜低档标准'}
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

'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Form, Input, Radio, Select, Table, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { fetchMyJudgeTasks, submitJudgeVote } from '@/actions/hr'

const DIMENSIONS = [
  '本职工作完成评价',
  '工作思想表现评价',
  '组织协调能力评价',
  '开拓创新能力评价',
  '科技项目成果评价',
  '培养指导人员评价',
  '论文专利著作评价',
]
const GRADES = ['优秀', '合格', '不合格']

interface JudgeTask {
  judge_id: string
  judge_code: string
  status: string
  vote_result?: string
  comprehensive_grade?: string
  review_comment?: string
  dimension_grades: Record<string, string | null>
  activity_name: string
  application: {
    id: string
    name: string
    employee_no: string
    department?: string
    sequence?: string
    apply_level?: string
    is_exception: boolean
    exception_reason?: string
    self_evaluations?: Record<string, string>
    work_statements?: Record<string, string>
    attachments?: Record<string, { file_token: string; name: string; size: number }[]>
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
      vote_result: task.vote_result,
      comprehensive_grade: task.comprehensive_grade,
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
        vote_result: values.vote_result,
        comprehensive_grade: values.comprehensive_grade,
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
          评委投票（匿名编号 {tasks[0]?.judge_code || ''}）：请审阅申报材料后，逐维度评价并给出投票结果
        </p>
      </div>

      <div className="flex justify-end">
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </div>

      <Table rowKey="judge_id" size="middle" loading={loading} columns={columns} dataSource={tasks} pagination={false} scroll={{ x: 900 }} />

      <Drawer
        title={voting ? `投票：${voting.application.name}（${voting.application.sequence}·${voting.application.apply_level}）` : '投票'}
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
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="部门">{voting.application.department || '-'}</Descriptions.Item>
              <Descriptions.Item label="是否破格">{voting.application.is_exception ? '是' : '否'}</Descriptions.Item>
              {voting.application.exception_reason && (
                <Descriptions.Item label="破格理由" span={2}>{voting.application.exception_reason}</Descriptions.Item>
              )}
            </Descriptions>
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
                    <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>
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
              <Form.Item name="vote_result" label="投票结果" rules={[{ required: true, message: '请选择投票结果' }]}>
                <Radio.Group>
                  <Radio value="同意">同意</Radio>
                  <Radio value="不同意">不同意</Radio>
                  <Radio value="弃权">弃权</Radio>
                </Radio.Group>
              </Form.Item>
              <Form.Item name="comprehensive_grade" label="综合等级">
                <Select allowClear placeholder="优秀/合格/不合格" options={GRADES.map((g) => ({ value: g, label: g }))} style={{ width: 180 }} />
              </Form.Item>
              <Typography.Text strong>维度评价（{DIMENSIONS.length} 项）</Typography.Text>
              <div className="grid grid-cols-1 gap-y-1 mt-2">
                {DIMENSIONS.map((dim) => (
                  <Form.Item key={dim} name={['dimension_grades', dim]} label={dim} className="!mb-2">
                    <Select allowClear placeholder="优秀/合格/不合格" options={GRADES.map((g) => ({ value: g, label: g }))} style={{ width: 200 }} />
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

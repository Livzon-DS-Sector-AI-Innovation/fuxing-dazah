'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { App, Button, Card, DatePicker, Descriptions, Empty, Form, Input, InputNumber, Modal, Popconfirm, Radio, Spin, Table, Tabs, Tag } from 'antd'
import { ArrowLeftOutlined, AuditOutlined, PlusOutlined } from '@ant-design/icons'
import { fetchEmployeeByIdAction } from '@/actions/hr'
import {
  createProbationSafetyExam,
  deleteProbationSafetyExam,
  fetchProbationReviews,
  fetchProbationSafetyExams,
} from '@/actions/hr'
import type { Employee, ProbationReviewItem, ProbationSafetyExamItem } from '@/types/hr'
import { EMPLOYEE_STATUS_TAG_COLORS } from '@/lib/hr/status-color'
import EmployeeCertificatesPanel from './EmployeeCertificatesPanel'
import ProbationReviewModal from './ProbationReviewModal'
import { usePermission } from '@/hooks/usePermission'

const STEP_LABELS = ['直属上级评估', '部门经理审批', '分管领导审批']
const CONCLUSION_COLOR: Record<string, string> = { 通过: 'green', 延长: 'orange', 不通过: 'red' }

/** 身份证 / 手机号默认脱敏，点「显示」看明文（纯前端交互；后端本身已按权限对无敏感权限的角色脱敏） */
function MaskedText({ value, keepHead, keepTail }: { value: string; keepHead: number; keepTail: number }) {
  const [show, setShow] = useState(false)
  const masked = value.length > keepHead + keepTail
    ? `${value.slice(0, keepHead)}${'*'.repeat(value.length - keepHead - keepTail)}${value.slice(-keepTail)}`
    : '*'.repeat(value.length)
  return (
    <span className="font-mono whitespace-nowrap">
      {show ? value : masked}
      <Button type="link" size="small" className="!px-1 !h-auto" onClick={() => setShow((s) => !s)}>
        {show ? '隐藏' : '显示'}
      </Button>
    </span>
  )
}

/** 员工完整档案页：基本信息 + 证件档案 / 安全考试 / 转正历史 */
export default function EmployeeDetailClient({ employeeId }: { employeeId: string }) {
  const router = useRouter()
  const { message: msg } = App.useApp()
  const { hasPermission } = usePermission()
  // 与列表页一致：有档案编辑权限才能发起转正评估
  const canEditProfile = hasPermission('hr:profile:update')
  const [employee, setEmployee] = useState<Employee | null>(null)
  const [loading, setLoading] = useState(true)
  const [probationOpen, setProbationOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const e = await fetchEmployeeByIdAction(employeeId)
        if (!cancelled) setEmployee(e)
      } catch (e) {
        if (!cancelled) msg.error(e instanceof Error ? e.message : '加载员工失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [employeeId, msg])

  // 返回：优先回上一页（保留列表的筛选与页码）；直接打开的深链没有上一页时回员工档案列表
  const goBack = () => {
    if (typeof window !== 'undefined' && window.history.length > 1) router.back()
    else router.push('/hr/profile')
  }

  if (loading) return <div className="text-center py-16"><Spin /></div>
  if (!employee) {
    return (
      <Empty description="员工不存在或已被删除" className="py-16">
        <Button type="primary" onClick={goBack}>返回</Button>
      </Empty>
    )
  }

  return (
    <div className="space-y-4">
      {/* 页头：返回 ｜ 姓名 · 工号 · 状态 · 部门岗位 ｜ 右侧操作区（此前只有一个「返回」按钮，没有页级操作） */}
      <div className="flex items-center gap-3 flex-wrap">
        <Button icon={<ArrowLeftOutlined />} onClick={goBack}>返回</Button>
        <h1 className="text-[22px] font-semibold leading-tight text-[var(--color-charcoal)] m-0">{employee.name}</h1>
        <span className="text-sm text-[var(--color-steel)]">{employee.employee_number}</span>
        <Tag color={EMPLOYEE_STATUS_TAG_COLORS[employee.status] || 'default'}>{employee.status}</Tag>
        {employee.is_key_position && <Tag color="purple">重点岗位</Tag>}
        <span className="text-sm text-[var(--color-steel)]">{employee.department} · {employee.position}</span>
        {canEditProfile && employee.status === '试用期' && (
          <Button className="ml-auto" type="primary" icon={<AuditOutlined />} onClick={() => setProbationOpen(true)}>
            发起转正评估
          </Button>
        )}
      </div>
      <ProbationReviewModal open={probationOpen} employee={employee} onClose={() => setProbationOpen(false)} />

      <Card size="small" title="基本信息">
        <Descriptions size="small" column={{ xs: 1, sm: 2, xl: 3 }} items={[
          { key: 'hire', label: '入职日期', children: employee.hire_date || '-' },
          { key: 'category', label: '用工性质', children: employee.status_category || '-' },
          { key: 'dm', label: '直属上级', children: employee.direct_manager_name || '未登记' },
          { key: 'key', label: '是否重点岗位', children: employee.is_key_position ? '是' : '否' },
          { key: 'idcard', label: '身份证号', children: employee.id_card ? <MaskedText value={employee.id_card} keepHead={3} keepTail={2} /> : '-' },
          { key: 'idexp', label: '身份证有效期', children: employee.id_card_expiry || '-' },
          { key: 'edu', label: '学历', children: `${employee.education || '-'}${employee.school ? ` · ${employee.school}` : ''}` },
          { key: 'phone', label: '手机', children: employee.phone ? <MaskedText value={employee.phone} keepHead={0} keepTail={4} /> : '-' },
          { key: 'contract', label: '合同期', children: employee.contract_start_date && employee.contract_end_date ? `${employee.contract_start_date} ~ ${employee.contract_end_date}` : '-' },
          ...(employee.status === '试用期' ? [{
            key: 'prob', label: '转正到期',
            children: `${employee.computed_probation_end || '-'}（剩 ${employee.computed_probation_days_left} 天）`,
          } as const] : []),
        ]} />
      </Card>

      <Card size="small">
        <Tabs items={[
          { key: 'certs', label: '证件档案', children: <EmployeeCertificatesPanel employeeId={employeeId} /> },
          { key: 'exams', label: '安全考试', children: <SafetyExamSection employeeId={employeeId} isKeyPosition={!!employee.is_key_position} /> },
          { key: 'probation', label: '转正历史', children: <ProbationHistorySection employeeId={employeeId} /> },
        ]} />
      </Card>
    </div>
  )
}

/** 安全考试记录（重点岗位 60 天节点，安全办录入） */
function SafetyExamSection({ employeeId, isKeyPosition }: { employeeId: string; isKeyPosition: boolean }) {
  const { message: msg } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:probation:exam:manage')
  const [items, setItems] = useState<ProbationSafetyExamItem[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    try {
      const r = await fetchProbationSafetyExams(employeeId)
      setItems(r.data || [])
    } catch { setItems([]) }
    finally { setLoading(false) }
  }, [employeeId])

  useEffect(() => { void load() }, [load])

  const hasPassed = items.some(i => i.passed)

  const handleSave = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await createProbationSafetyExam({
        employee_id: employeeId,
        exam_date: v.exam_date.format('YYYY-MM-DD'),
        passed: v.passed,
        score: v.score ?? undefined,
        remark: v.remark,
      })
      msg.success('已录入')
      setOpen(false); form.resetFields()
      void load()
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '录入失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      {isKeyPosition && (
        <div className={`rounded-md px-3 py-2 mb-3 text-[13px] ${hasPassed
          ? 'bg-green-50 text-green-700 border border-green-200'
          : 'bg-orange-50 text-orange-700 border border-orange-300'}`}>
          {hasPassed ? '已有合格记录，可发起转正审批。' : '重点岗位：须通过安全办安全考试（入职满 60 天提醒）后方可发起转正审批，当前无合格记录。'}
        </div>
      )}
      {canManage && (
        <div className="mb-3">
          <Button type="primary" size="small" icon={<PlusOutlined />}
            onClick={() => { form.setFieldsValue({ passed: true }); setOpen(true) }}>
            录入考试结果
          </Button>
        </div>
      )}
      <Table size="small" rowKey="id" loading={loading} dataSource={items}
        pagination={false} locale={{ emptyText: <Empty description="暂无考试记录" className="py-6" /> }}
        columns={[
          { title: '考试日期', dataIndex: 'exam_date', width: 120 },
          { title: '结果', dataIndex: 'passed', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '合格' : '不合格'}</Tag> },
          { title: '分数', dataIndex: 'score', width: 80, render: (v: number | null) => v ?? '-' },
          { title: '录入人', dataIndex: 'entered_by', width: 100, render: (v: string | null) => v || '-' },
          { title: '备注', dataIndex: 'remark', ellipsis: true },
          ...(canManage ? [{
            title: '操作', width: 80, render: (_: unknown, r: ProbationSafetyExamItem) => (
              <Popconfirm title="删除该记录？" onConfirm={async () => {
                try {
                  await deleteProbationSafetyExam(r.id)
                  msg.success('已删除')
                  void load()
                } catch (e) { msg.error(e instanceof Error ? e.message : '删除失败') }
              }}>
                <Button size="small" type="link" danger>删除</Button>
              </Popconfirm>
            ),
          }] : []),
        ]} />
      <Modal title="录入安全考试结果" open={open} onCancel={() => setOpen(false)}
        onOk={handleSave} okText="保存" confirmLoading={saving}>
        <Form form={form} layout="vertical" className="mt-2">
          <Form.Item name="exam_date" label="考试日期" rules={[{ required: true, message: '请选择考试日期' }]}>
            <DatePicker className="w-full" />
          </Form.Item>
          <Form.Item name="passed" label="结果" rules={[{ required: true }]}>
            <Radio.Group options={[{ label: '合格', value: true }, { label: '不合格', value: false }]} />
          </Form.Item>
          <Form.Item name="score" label="分数（选填）">
            <InputNumber className="w-full" min={0} max={200} precision={1} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={256} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

/** 转正评估历史（三级审批链全记录） */
function ProbationHistorySection({ employeeId }: { employeeId: string }) {
  const [items, setItems] = useState<ProbationReviewItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchProbationReviews()
        if (!cancelled) setItems((r.data || []).filter(i => i.employee_id === employeeId))
      } catch { if (!cancelled) setItems([]) }
      finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [employeeId])

  if (loading) return <div className="text-center py-8"><Spin /></div>

  return (
    <div className="space-y-3">
      {items.map(r => (
        <div key={r.id} className="rounded-md border border-[var(--color-hairline)] p-3">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <Tag color={r.status === 'effective' ? 'green' : r.status === 'rejected' ? 'red' : 'processing'}>
              {r.status_label}
            </Tag>
            {r.conclusion && <Tag color={CONCLUSION_COLOR[r.conclusion]}>{r.conclusion}</Tag>}
            {r.proposed_probation_end && r.conclusion === '延长' && (
              <span className="text-xs text-gray-500">新到期日 {r.proposed_probation_end}</span>
            )}
            <span className="text-xs text-gray-400 ml-auto">{r.created_at?.slice(0, 10)} 发起</span>
          </div>
          <Descriptions size="small" column={1} items={[
            { key: 's1', label: `① 直属上级 ${r.direct_manager_name}`,
              children: r.conclusion ? `${r.conclusion}：${r.comment || '—'}` : '待评估' },
            { key: 's2', label: `② 部门经理 ${r.dept_manager_name || '-'}`,
              children: r.dept_manager_decision ? `${r.dept_manager_decision}${r.dept_manager_comment ? `：${r.dept_manager_comment}` : ''}` : '待审批' },
            { key: 's3', label: `③ 分管领导 ${r.leader_name || '-'}`,
              children: r.leader_decision ? `${r.leader_decision}${r.leader_comment ? `：${r.leader_comment}` : ''}` : '待审批' },
            ...(r.hr_note ? [{ key: 'n', label: 'HR 附注', children: r.hr_note }] : []),
          ]} />
        </div>
      ))}
      {items.length === 0 && <Empty description="暂无转正评估记录" className="py-6" />}
    </div>
  )
}

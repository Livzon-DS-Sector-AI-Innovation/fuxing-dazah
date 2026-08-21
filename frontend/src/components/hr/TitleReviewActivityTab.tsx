'use client'

import { useState } from 'react'
import {
  App, Button, DatePicker, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography,
} from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined, SyncOutlined, TeamOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { usePermission } from '@/hooks/usePermission'
import type {
  Employee, TitleReviewActivityListItem, TitleReviewDeptCommittee, TitleReviewLevel,
} from '@/types/hr'
import {
  bindTitleTables, closeTitleActivity, createTitleActivity, deleteTitleActivity,
  fetchEmployeesAction, fetchTitleActivity, fetchTitleCommittees, fetchTitleDepartments,
  openTitleActivity, reconcileTitleActivity, saveTitleCommittee, deleteTitleCommittee,
  startTitleReview, updateTitleActivity,
} from '@/actions/hr' 

const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: '配置中', color: 'default' },
  open: { label: '申报中', color: 'processing' },
  reviewing: { label: '评审中', color: 'warning' },
  closed: { label: '已结束', color: 'default' },
}

const DEFAULT_LEVELS: TitleReviewLevel[] = [
  { sequence: '技术职级', level_name: '技术员', need_final_review: false },
  { sequence: '技术职级', level_name: '助理工程师', need_final_review: false },
  { sequence: '技术职级', level_name: '工程师', need_final_review: true },
  { sequence: '技术职级', level_name: '高级工程师', need_final_review: true },
  { sequence: '技术职级', level_name: '专家', need_final_review: true },
  { sequence: '职业技能', level_name: '中级工', need_final_review: false },
  { sequence: '职业技能', level_name: '高级工', need_final_review: false },
  { sequence: '职业技能', level_name: '技师', need_final_review: true },
  { sequence: '职业技能', level_name: '高级技师', need_final_review: true },
]

interface Props {
  activities: TitleReviewActivityListItem[]
  onRefresh: () => void
  onSelectActivity: (id: string) => void
}

export default function TitleReviewActivityTab({ activities, onRefresh, onSelectActivity }: Props) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [form] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<TitleReviewActivityListItem | null>(null)
  const [levels, setLevels] = useState<TitleReviewLevel[]>(DEFAULT_LEVELS)
  const [saving, setSaving] = useState(false)

  const [committeeOpen, setCommitteeOpen] = useState(false)
  const [committees, setCommittees] = useState<TitleReviewDeptCommittee[]>([])
  const [committeeForm] = Form.useForm()
  const [employeeOptions, setEmployeeOptions] = useState<Employee[]>([])
  const [departmentOptions, setDepartmentOptions] = useState<string[]>([])

  const canManage = hasPermission('hr:title:manage')

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ pass_ratio: 2 / 3 })
    setLevels(DEFAULT_LEVELS)
    setModalOpen(true)
  }

  const openEdit = async (activity: TitleReviewActivityListItem) => {
    setEditing(activity)
    setModalOpen(true)
    try {
      const d = await fetchTitleActivity(activity.id)
      const detail = d.data
      form.setFieldsValue({
        name: detail.name,
        pass_ratio: detail.pass_ratio,
        apply_deadline: detail.apply_deadline ? dayjs(detail.apply_deadline) : undefined,
        review_deadline: detail.review_deadline ? dayjs(detail.review_deadline) : undefined,
        feishu_app_token: detail.feishu_app_token,
        apply_table_id: detail.apply_table_id,
        vote_table_id: detail.vote_table_id,
        approval_code: detail.approval_code,
      })
      setLevels(detail.levels || [])
    } catch (err: any) {
      message.error(err.message || '加载活动详情失败')
      setModalOpen(false)
    }
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    const payload = {
      name: values.name,
      pass_ratio: values.pass_ratio,
      apply_deadline: values.apply_deadline ? (values.apply_deadline as Dayjs).toISOString() : undefined,
      review_deadline: values.review_deadline ? (values.review_deadline as Dayjs).toISOString() : undefined,
      feishu_app_token: values.feishu_app_token,
      apply_table_id: values.apply_table_id,
      vote_table_id: values.vote_table_id,
      approval_code: values.approval_code,
    }
    setSaving(true)
    try {
      if (editing) {
        const editable = editing.status === 'draft'
        const body: any = {
          name: editable ? payload.name : undefined,
          levels: editable ? levels : undefined,
          apply_deadline: payload.apply_deadline,
          review_deadline: payload.review_deadline,
          pass_ratio: payload.pass_ratio,
          feishu_app_token: editable ? payload.feishu_app_token : undefined,
          apply_table_id: editable ? payload.apply_table_id : undefined,
          vote_table_id: editable ? payload.vote_table_id : undefined,
          approval_code: editable ? payload.approval_code : undefined,
        }
        const d = await updateTitleActivity(editing.id, body)
        message.success(d.message || '活动已更新')
      } else {
        const d = await createTitleActivity({ ...payload, levels } as any)
        message.success(d.message || '活动创建成功')
      }
      setModalOpen(false)
      onRefresh()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const runAction = async (fn: (id: string) => Promise<any>, id: string, successMsg: string) => {
    try {
      const d = await fn(id)
      message.success(d.message || successMsg)
      onRefresh()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const openCommittees = async () => {
    setCommitteeOpen(true)
    try {
      const [c, e, d] = await Promise.all([
        fetchTitleCommittees(),
        fetchEmployeesAction({ status: '在职', page: 1, page_size: 200 }),
        fetchTitleDepartments(),
      ])
      setCommittees(c?.data || [])
      setEmployeeOptions(e?.data || [])
      setDepartmentOptions(d?.data || [])
    } catch (err: any) {
      message.error(err.message || '加载部门评审组失败')
    }
  }

  const handleSaveCommittee = async () => {
    const values = await committeeForm.validateFields()
    const memberIds: string[] = values.committee_members || []
    const payload = {
      department: values.department,
      manager_employee_id: values.manager_employee_id,
      manager_name: values.manager_name,
      leader_employee_id: values.leader_employee_id,
      leader_name: values.leader_name,
      committee_members: memberIds.map((id) => {
        const emp = employeeOptions.find((x) => x.id === id)
        return { employee_id: id, name: emp?.name || '', employee_no: emp?.employee_number }
      }),
    }
    try {
      const d = await saveTitleCommittee(payload)
      message.success(d.message || '已保存')
      committeeForm.resetFields()
      const c = await fetchTitleCommittees()
      setCommittees(c?.data || [])
    } catch (err: any) {
      message.error(err.message || '保存失败')
    }
  }

  const columns = [
    { title: '活动名称', dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => <Tag color={STATUS_META[s]?.color}>{STATUS_META[s]?.label || s}</Tag>,
    },
    { title: '通过比例', dataIndex: 'pass_ratio', key: 'pass_ratio', width: 90, render: (v: number) => (v * 100).toFixed(0) + '%' },
    { title: '申报数', dataIndex: 'application_count', key: 'application_count', width: 80 },
    {
      title: '投票进度', key: 'votes', width: 100,
      render: (_: unknown, r: TitleReviewActivityListItem) =>
        (r.total_judge_count || 0) > 0 ? `${r.voted_judge_count || 0}/${r.total_judge_count || 0}` : '-',
    },
    {
      title: '申报截止', dataIndex: 'apply_deadline', key: 'apply_deadline', width: 130,
      render: (v?: string) => (v ? dayjs(v).format('MM-DD HH:mm') : '-'),
    },
    {
      title: '操作', key: 'actions', width: 360,
      render: (_: unknown, r: TitleReviewActivityListItem) => (
        <Space size={4} wrap>
          {r.status === 'draft' && canManage && <Button size="small" onClick={() => openEdit(r)}>编辑</Button>}
          {r.status === 'draft' && canManage && (
            <Button size="small" icon={<ReloadOutlined />} onClick={() => runAction(bindTitleTables, r.id, '绑定成功')}>绑定表格</Button>
          )}
          {r.status === 'draft' && canManage && (
            <Button size="small" type="primary" onClick={() => runAction(openTitleActivity, r.id, '已开启申报')}>开启申报</Button>
          )}
          {r.status === 'open' && canManage && (
            <Button size="small" type="primary" onClick={() => runAction(startTitleReview, r.id, '已开启评审')}>开始评审</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && canManage && (
            <Button size="small" icon={<SyncOutlined />} onClick={() => runAction(reconcileTitleActivity, r.id, '对账完成')}>同步</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && canManage && (
            <Button size="small" danger onClick={() => runAction(closeTitleActivity, r.id, '活动已结束')}>结束</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && (
            <Button size="small" onClick={() => onSelectActivity(r.id)}>管理申报</Button>
          )}
          {r.status === 'draft' && canManage && (
            <Popconfirm
              title="确认删除该活动？"
              onConfirm={async () => {
                try {
                  await deleteTitleActivity(r.id)
                  message.success('已删除')
                  onRefresh()
                } catch (err: any) {
                  message.error(err.message || '删除失败')
                }
              }}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Typography.Text type="secondary">
          活动为 draft 时可配置职级组标准与飞书表格绑定；开启申报后员工即可在飞书表单提交
        </Typography.Text>
        <Space>
          {canManage && (
            <Button icon={<TeamOutlined />} onClick={openCommittees}>部门评审组</Button>
          )}
          {canManage && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建活动</Button>
          )}
        </Space>
      </div>

      <Table rowKey="id" size="middle" columns={columns} dataSource={activities} pagination={false} scroll={{ x: 1150 }} />

      {/* 活动创建/编辑 */}
      <Modal
        title={editing ? `编辑活动：${editing.name}` : '新建评定活动'}
        open={modalOpen}
        width={860}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        okText="保存"
      >
        <Form form={form} layout="vertical" className="mt-4">
          <div className="grid grid-cols-2 gap-x-4">
            <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入活动名称' }]}>
              <Input placeholder="如：2026年度技术职级评定" disabled={!!editing && editing.status !== 'draft'} />
            </Form.Item>
            <Form.Item name="pass_ratio" label="通过比例（同意÷(同意+不同意)）" rules={[{ required: true, message: '请输入通过比例' }]}>
              <InputNumber min={0.5} max={1} step={0.05} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="apply_deadline" label="申报截止时间">
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="review_deadline" label="评审截止时间">
              <DatePicker showTime style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="feishu_app_token" label="飞书多维表格 app_token（绑定现有表）">
              <Input placeholder="粘贴 /base/ 链接中的 token" disabled={!!editing && editing.status !== 'draft'} />
            </Form.Item>
            <div className="grid grid-cols-2 gap-x-4">
              <Form.Item name="apply_table_id" label="申报表 table_id">
                <Input placeholder="tbl 开头" disabled={!!editing && editing.status !== 'draft'} />
              </Form.Item>
              <Form.Item name="vote_table_id" label="投票表 table_id">
                <Input placeholder="tbl 开头" disabled={!!editing && editing.status !== 'draft'} />
              </Form.Item>
              <Form.Item name="approval_code" label="飞书审批定义编码（可选，审批先行模式）">
                <Input placeholder="如 3A2D82F4-xxx；填了则员工先走飞书审批，通过后自动同步" disabled={!!editing && editing.status !== 'draft'} />
              </Form.Item>
            </div>
          </div>

          <Typography.Title level={5} className="!mb-2">职级组评审标准（{levels.length} 组，仅 draft 可改）</Typography.Title>
          <div className="space-y-2 max-h-72 overflow-y-auto pr-2">
            {levels.map((lv, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <Select
                  style={{ width: 110 }}
                  value={lv.sequence}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(v) => setLevels(levels.map((x, i) => (i === idx ? { ...x, sequence: v } : x)))}
                  options={[{ value: '技术职级', label: '技术职级' }, { value: '职业技能', label: '职业技能' }]}
                />
                <Input
                  style={{ width: 110 }}
                  value={lv.level_name}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, level_name: e.target.value } : x)))}
                />
                <Input.TextArea
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  placeholder="基本条件"
                  value={lv.basic_conditions}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, basic_conditions: e.target.value } : x)))}
                />
                <Input.TextArea
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  placeholder="专业能力要求"
                  value={lv.ability_requirements}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, ability_requirements: e.target.value } : x)))}
                />
                <Input.TextArea
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  placeholder="业绩成果要求"
                  value={lv.achievement_requirements}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, achievement_requirements: e.target.value } : x)))}
                />
                <Input.TextArea
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  placeholder="评审要点"
                  value={lv.review_points}
                  disabled={!!editing && editing.status !== 'draft'}
                  onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, review_points: e.target.value } : x)))}
                />
                <Space size={4} direction="vertical" align="center">
                  <Switch
                    size="small"
                    checked={lv.need_final_review}
                    disabled={!!editing && editing.status !== 'draft'}
                    onChange={(v) => setLevels(levels.map((x, i) => (i === idx ? { ...x, need_final_review: v } : x)))}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>需终审</Typography.Text>
                </Space>
              </div>
            ))}
          </div>
        </Form>
      </Modal>

      {/* 部门评审组 */}
      <Modal title="部门评审组配置" open={committeeOpen} width={760} onCancel={() => setCommitteeOpen(false)} footer={null}>
        <div className="mt-4 space-y-3">
          <Form form={committeeForm} layout="vertical" className="grid grid-cols-2 gap-x-4">
            <Form.Item name="department" label="部门名称（与员工档案体现部门一致）" rules={[{ required: true, message: '请选择部门' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择部门"
                options={departmentOptions.map((d) => ({ value: d, label: d }))}
              />
            </Form.Item>
            <Form.Item name="committee_members" label="职级评定小组（默认评委）">
              <Select
                mode="multiple"
                showSearch
                optionFilterProp="label"
                placeholder="搜索在职员工多选"
                options={employeeOptions.map((e) => ({
                  value: e.id,
                  label: `${e.name}（${e.employee_number}）`,
                }))}
                onChange={(ids: string[]) => {
                  const members = ids.map((id) => {
                    const emp = employeeOptions.find((x) => x.id === id)
                    return { employee_id: id, name: emp?.name || '', employee_no: emp?.employee_number }
                  })
                  committeeForm.setFieldsValue({ committee_members: members })
                }}
                value={(committeeForm.getFieldValue('committee_members') || []).map((m: any) => m.employee_id)}
              />
            </Form.Item>
            <Form.Item name="manager_name" label="部门负责人（初审人）">
              <Select
                showSearch
                optionFilterProp="label"
                allowClear
                placeholder="搜索在职员工"
                options={employeeOptions.map((e) => ({ value: e.name, label: `${e.name}（${e.employee_number}）` }))}
                onChange={(name?: string) => {
                  const emp = employeeOptions.find((x) => x.name === name)
                  committeeForm.setFieldsValue({ manager_employee_id: emp?.id })
                }}
              />
            </Form.Item>
            <Form.Item name="leader_name" label="分管领导（终审人）">
              <Select
                showSearch
                optionFilterProp="label"
                allowClear
                placeholder="搜索在职员工"
                options={employeeOptions.map((e) => ({ value: e.name, label: `${e.name}（${e.employee_number}）` }))}
                onChange={(name?: string) => {
                  const emp = employeeOptions.find((x) => x.name === name)
                  committeeForm.setFieldsValue({ leader_employee_id: emp?.id })
                }}
              />
            </Form.Item>
            <div className="col-span-2 text-right">
              <Button type="primary" onClick={handleSaveCommittee}>保存评审组</Button>
            </div>
          </Form>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={committees}
            columns={[
              { title: '部门', dataIndex: 'department', key: 'department', width: 120 },
              { title: '部门负责人', dataIndex: 'manager_name', key: 'manager_name', width: 100, render: (v?: string) => v || '-' },
              { title: '分管领导', dataIndex: 'leader_name', key: 'leader_name', width: 100, render: (v?: string) => v || '-' },
              {
                title: '评定小组', key: 'members', ellipsis: true,
                render: (_: unknown, r: TitleReviewDeptCommittee) => (r.committee_members || []).map((m) => m.name).join('、') || '-',
              },
              {
                title: '操作', key: 'actions', width: 70,
                render: (_: unknown, r: TitleReviewDeptCommittee) => (
                  <Popconfirm
                    title="确认删除？"
                    onConfirm={async () => {
                      try {
                        await deleteTitleCommittee(r.id)
                        message.success('已删除')
                        setCommittees(await fetchTitleCommittees().then((c) => c?.data || []))
                      } catch (err: any) {
                        message.error(err.message || '删除失败')
                      }
                    }}
                  >
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                ),
              },
            ]}
          />
        </div>
      </Modal>
    </div>
  )
}

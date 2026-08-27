'use client'

import { useState } from 'react'
import {
  App, Button, DatePicker, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography,
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
  // 技术助理已取消（2026 年起不再设置）；评审标准文本与终审 v3 取消，只保留序列+职级名
  { sequence: '技术职级', level_name: '技术员' },
  { sequence: '技术职级', level_name: '助理工程师' },
  { sequence: '技术职级', level_name: '工程师' },
  { sequence: '技术职级', level_name: '高级工程师' },
  { sequence: '技术职级', level_name: '专家' },
  { sequence: '职业技能', level_name: '初级工' },
  { sequence: '职业技能', level_name: '中级工' },
  { sequence: '职业技能', level_name: '高级工' },
  { sequence: '职业技能', level_name: '技师' },
  { sequence: '职业技能', level_name: '高级技师' },
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
  // 已选评定小组成员（独立状态保存，避免远程搜索替换选项后已选标签丢失文字）
  const [selectedMembers, setSelectedMembers] = useState<
    { employee_id: string; name: string; employee_no?: string }[]
  >([])
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

  // 手动对账：弹窗展示本次同步明细（新增/更新/移除/票数），避免用户不知道发生了什么
  const handleReconcile = async (id: string) => {
    try {
      const d = await reconcileTitleActivity(id)
      const s: Record<string, any> = d?.data || {}
      const parts: string[] = []
      if (s.approval_synced) parts.push(`审批写入 ${s.approval_synced} 条`)
      if (s.approval_updated) parts.push(`审批更新 ${s.approval_updated} 条`)
      if (s.applications_created) parts.push(`新增申报 ${s.applications_created} 条`)
      if (s.applications_updated) parts.push(`更新申报 ${s.applications_updated} 条`)
      if (s.applications_removed) parts.push(`移除申报 ${s.applications_removed} 条`)
      if (s.votes_updated) parts.push(`票数更新 ${s.votes_updated} 条`)
      if (s.errors?.length) parts.push(`失败 ${s.errors.length} 项`)
      message.success(parts.length ? `对账完成：${parts.join('，')}` : '对账完成：本次无变化')
      onRefresh()
    } catch (err: any) {
      message.error(err.message || '对账失败')
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

  // 员工远程搜索（在职员工 1200+，仅前端过滤前 200 条会搜不到）
  const [employeeSearching, setEmployeeSearching] = useState(false)
  const searchEmployees = async (keyword: string) => {
    setEmployeeSearching(true)
    try {
      const d = await fetchEmployeesAction({
        status: '在职',
        keyword: keyword || undefined,
        page: 1,
        page_size: keyword ? 50 : 200,
      })
      setEmployeeOptions(d?.data || [])
    } catch (err: any) {
      message.error(err.message || '搜索员工失败')
    } finally {
      setEmployeeSearching(false)
    }
  }

  const handleSaveCommittee = async () => {
    const values = await committeeForm.validateFields()
    const memberIds: string[] = values.committee_members || []
    const payload = {
      department: values.department,
      committee_members: memberIds.map((id) => {
        const m = selectedMembers.find((x) => x.employee_id === id)
        return { employee_id: id, name: m?.name || '', employee_no: m?.employee_no || '' }
      }),
    }
    try {
      const d = await saveTitleCommittee(payload)
      message.success(d.message || '已保存')
      committeeForm.resetFields()
      setSelectedMembers([])
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
          {r.status !== 'closed' && canManage && (
            <Button size="small" icon={<ReloadOutlined />} onClick={() => runAction(bindTitleTables, r.id, '绑定成功')}>绑定表格</Button>
          )}
          {r.status === 'draft' && canManage && (
            <Button size="small" type="primary" onClick={() => runAction(openTitleActivity, r.id, '已开启申报')}>开启申报</Button>
          )}
          {r.status === 'open' && canManage && (
            <Button size="small" type="primary" onClick={() => runAction(startTitleReview, r.id, '已开启评审')}>开始评审</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && canManage && (
            <Button size="small" icon={<SyncOutlined />} onClick={() => handleReconcile(r.id)}>同步</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && canManage && (
            <Button size="small" danger onClick={() => runAction(closeTitleActivity, r.id, '活动已结束')}>结束</Button>
          )}
          {(r.status === 'open' || r.status === 'reviewing') && (
            <Button size="small" onClick={() => onSelectActivity(r.id)}>管理申报</Button>
          )}
          {canManage && (
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
          活动为 draft 时可配置职级组与飞书表格绑定；开启申报后员工即可在飞书表单提交
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
              <Form.Item name="approval_code" label="飞书审批定义编码（可选，审批先行模式）">
                <Input placeholder="如 3A2D82F4-xxx；填了则员工先走飞书审批，通过后自动同步" disabled={!!editing && editing.status !== 'draft'} />
              </Form.Item>
            </div>
          </div>

          <Typography.Title level={5} className="!mb-2">职级组（{levels.length} 组，仅 draft 可改）</Typography.Title>
          <div className="space-y-2 max-h-72 overflow-y-auto pr-2">
            {levels.map((lv, idx) => {
              const disabled = !!editing && editing.status !== 'draft'
              return (
                <div key={idx} className="flex items-center gap-2">
                  <Select
                    style={{ width: 120 }}
                    value={lv.sequence}
                    disabled={disabled}
                    onChange={(v) => setLevels(levels.map((x, i) => (i === idx ? { ...x, sequence: v } : x)))}
                    options={[{ value: '技术职级', label: '技术职级' }, { value: '职业技能', label: '职业技能' }]}
                  />
                  <Input
                    style={{ width: 160 }}
                    value={lv.level_name}
                    disabled={disabled}
                    placeholder="职级名"
                    onChange={(e) => setLevels(levels.map((x, i) => (i === idx ? { ...x, level_name: e.target.value } : x)))}
                  />
                </div>
              )
            })}
          </div>
        </Form>
      </Modal>

      {/* 部门评审组 */}
      <Modal title="部门评审组配置" open={committeeOpen} width={760} onCancel={() => setCommitteeOpen(false)} footer={null}>
        <div className="mt-4 space-y-3">
          <Form form={committeeForm} layout="vertical" className="grid grid-cols-2 gap-x-4">
            <Form.Item name="department" label="部门名称（与员工档案实际部门一致）" rules={[{ required: true, message: '请选择部门' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择部门"
                options={departmentOptions.map((d) => ({ value: d, label: d }))}
              />
            </Form.Item>
            <Form.Item name="committee_members" label="职级评定小组（默认评委）" className="col-span-2">
              <Select
                mode="multiple"
                showSearch
                filterOption={false}
                loading={employeeSearching}
                onSearch={searchEmployees}
                maxTagTextLength={40}
                placeholder="输入姓名/工号远程搜索在职员工"
                options={[
                  ...selectedMembers.map((m) => ({
                    value: m.employee_id,
                    label: `${m.name}（${m.employee_no || ''}）`,
                  })),
                  ...employeeOptions
                    .filter((e) => !selectedMembers.some((m) => m.employee_id === e.id))
                    .map((e) => ({
                      value: e.id,
                      label: `${e.name}（${e.employee_number}）`,
                    })),
                ]}
                onChange={(ids: string[]) => {
                  const next = ids.map((id) => {
                    const existing = selectedMembers.find((m) => m.employee_id === id)
                    if (existing) return existing
                    const emp = employeeOptions.find((x) => x.id === id)
                    return { employee_id: id, name: emp?.name || id, employee_no: emp?.employee_number }
                  })
                  setSelectedMembers(next)
                  // 表单只存 id（Select 的 value 必须与选项 value 同构才能显示标签文字）
                  committeeForm.setFieldsValue({ committee_members: next.map((m) => m.employee_id) })
                }}
                value={selectedMembers.map((m) => m.employee_id)}
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

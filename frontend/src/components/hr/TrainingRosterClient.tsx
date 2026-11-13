'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, App, Button, Checkbox, DatePicker, Form, Input, Modal, Popconfirm, Select, Space, Table, Tabs, Tag,
} from 'antd'
import { DeleteOutlined, DownloadOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, TagsOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { Dayjs } from 'dayjs'
import {
  fetchPositions,
  createEmployeeClassification,
  deleteEmployeeClassification,
  fetchClassificationMembers,
  fetchDepartmentsAction,
  fetchEmployeeClassifications,
  fetchEmployeeTagsByEmployee,
  fetchTrainingRoster,
  exportTrainingRoster,
  removeClassificationMembers,
  saveEmployeeTag,
  updateTrainingRosterEntry,
} from '@/actions/hr'
import type { TrainingRosterRow } from '@/actions/hr/employeeSync'
import { usePermission } from '@/hooks/usePermission'
import { downloadBase64File } from '@/lib/hr'
import type { Department } from '@/types/hr'

/** 固定选项（口径与员工档案表单一致） */
/** 状态配色与员工档案页一致 */
const STATUS_COLOR: Record<string, string> = {
  在职: 'success', 试用期: 'warning', 离职: 'default', 待审批: 'processing',
  病假: 'error', 产假: 'magenta', 产假复岗: 'purple',
}
const STATUS_OPTIONS = ['在职', '离职', '试用期', '待审批', '病假', '产假', '产假复岗']

const FIXED_OPTIONS: Record<string, { value: string; label: string }[]> = {
  // 职类随新数据源值域（源表「职能分类」文本列）
  job_category: [
    { value: '生产', label: '生产' },
    { value: '生产辅助', label: '生产辅助' },
    { value: '职能管理', label: '职能管理' },
    { value: '研发', label: '研发' },
    { value: '后勤辅助', label: '后勤辅助' },
  ],
  education: [
    { value: '博士', label: '博士' }, { value: '硕士', label: '硕士' },
    { value: '本科', label: '本科' }, { value: '大专', label: '大专' },
    { value: '中专', label: '中专' }, { value: '中专/中技', label: '中专/中技' },
    { value: '高中', label: '高中' }, { value: '初中', label: '初中' },
    { value: '其他', label: '其他' },
  ],
  // 用工性质随新数据源值域（源表「员工性质」单选）
  status_category: [
    { value: '转正员工', label: '转正员工' },
    { value: '试用期', label: '试用期' },
    { value: '实习转试用', label: '实习转试用' },
    { value: '实习生', label: '实习生' },
    { value: '退休返聘', label: '退休返聘' },
  ],
}


function dateText(v?: string | null): string {
  return v ? v.slice(0, 10) : '-'
}

function listText(v?: string[] | null): string {
  return v && v.length ? v.join('、') : '-'
}

interface EditFormValues {
  [key: string]: string | string[] | Dayjs | null | undefined
}

/** 编辑表单字段分组（工号只读，不在此列）
 * type: date=日期选择 / department=部门下拉 / position=岗位下拉 / options=固定选项 / list=逗号转数组；缺省=文本 */
const EDIT_GROUPS: { title: string; fields: { name: keyof TrainingRosterRow; label: string; type?: 'date' | 'department' | 'position' | 'options' | 'list' }[] }[] = [
  {
    title: '基本信息',
    fields: [
      { name: 'name', label: '姓名' },
      { name: 'department', label: '体现部门', type: 'department' },
      { name: 'actual_department', label: '实际部门', type: 'department' },
      { name: 'team', label: '班组' },
      { name: 'status_category', label: '用工性质', type: 'options' },
    ],
  },
  {
    title: '岗位信息',
    fields: [
      { name: 'position', label: '职位', type: 'position' },
      { name: 'duty', label: '职务' },
      { name: 'job_category', label: '岗位类别', type: 'options' },
      { name: 'concurrent_departments', label: '兼任部门' },
      { name: 'variety', label: '品种' },
      { name: 'concurrent_variety', label: '兼任品种' },
    ],
  },
  {
    title: '教育信息',
    fields: [
      { name: 'education', label: '学历', type: 'options' },
      { name: 'graduation_date', label: '毕业时间', type: 'date' },
    ],
  },
  {
    title: '日期信息',
    fields: [
      { name: 'hire_date', label: '入职日期', type: 'date' },
      { name: 'work_start_date', label: '参加工作时间', type: 'date' },
      { name: 'factory_entry_date', label: '进厂时间', type: 'date' },
      { name: 'livo_entry_date', label: '入丽珠时间', type: 'date' },
      { name: 'departure_date', label: '离职时间', type: 'date' },
    ],
  },
  {
    title: '培训信息',
    fields: [
      { name: 'training_id', label: '培训编号' },
      { name: 'dept_head_trainer', label: '部门负责人/一级培训师' },
      { name: 'safety_training_date', label: '入职安全培训日期', type: 'date' },
      { name: 'safety_training_score', label: '入职安全培训成绩' },
      { name: 'culture_training_date', label: '企业文化培训日期', type: 'date' },
      { name: 'gmp_training_date', label: 'GMP基础培训时间', type: 'date' },
      { name: 'certificates', label: '证书' },
      { name: 'qualifications', label: '资格（逗号分隔）', type: 'list' },
    ],
  },
]

export default function TrainingRosterClient() {
  const { message } = App.useApp()
  const [rows, setRows] = useState<TrainingRosterRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [activeTab, setActiveTab] = useState('all')
  const [departments, setDepartments] = useState<Department[]>([])
  const [scopedDepartments, setScopedDepartments] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<TrainingRosterRow | null>(null)
  const [positions, setPositions] = useState<{ name: string; department: string }[]>([])
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const seqRef = useRef(0)
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:training:manage')

  // ── 人员分类（培训专用，挂在名单上） ──
  const [classModalOpen, setClassModalOpen] = useState(false)
  const [classList, setClassList] = useState<{ id: string; name: string; count: number }[]>([])
  const [classOptions, setClassOptions] = useState<{ label: string; value: string }[]>([])
  const [newClassName, setNewClassName] = useState('')
  const [classSaving, setClassSaving] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [members, setMembers] = useState<{ name: string; employee_number: string; department: string; position: string }[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [selectedMembers, setSelectedMembers] = useState<Set<string>>(new Set())
  const [removing, setRemoving] = useState(false)

  const loadClassifications = useCallback(async () => {
    try {
      const r = await fetchEmployeeClassifications()
      setClassList(r.data || [])
      setClassOptions((r.data || []).map(c => ({ label: `${c.name}（${c.count}人）`, value: c.name })))
    } catch { setClassList([]) }
  }, [])

  const openClassModal = () => {
    setNewClassName('')
    setClassModalOpen(true)
    void loadClassifications()
  }

  const handleAddClassification = async () => {
    const name = newClassName.trim()
    if (!name) return
    setClassSaving(true)
    try {
      await createEmployeeClassification(name)
      setNewClassName('')
      message.success('分类已新增')
      void loadClassifications()
    } catch (err) { message.error(err instanceof Error ? err.message : '新增失败') }
    finally { setClassSaving(false) }
  }

  const handleDeleteClassification = async (id: string, name: string) => {
    try {
      await deleteEmployeeClassification(id)
      message.success(`分类「${name}」已删除`)
      if (expandedId === id) setExpandedId(null)
      void loadClassifications()
    } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
  }

  const fetchMembers = async (id: string) => {
    setMembersLoading(true)
    try {
      const r = await fetchClassificationMembers(id)
      setMembers(r.data || [])
    } catch (err) {
      message.error(err instanceof Error ? err.message : '获取人员失败')
      setMembers([])
    } finally { setMembersLoading(false) }
  }

  const toggleMembers = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null)
      setSelectedMembers(new Set())
      return
    }
    setExpandedId(id)
    setSelectedMembers(new Set())
    await fetchMembers(id)
  }

  const toggleMemberSelected = (no: string) => {
    setSelectedMembers(prev => {
      const next = new Set(prev)
      if (next.has(no)) next.delete(no)
      else next.add(no)
      return next
    })
  }

  const handleRemoveSelectedMembers = async () => {
    if (!expandedId) return
    setRemoving(true)
    try {
      await removeClassificationMembers(expandedId, Array.from(selectedMembers))
      message.success(`已移除 ${selectedMembers.size} 人`)
      setSelectedMembers(new Set())
      await fetchMembers(expandedId)
      void loadClassifications()
    } catch (err) { message.error(err instanceof Error ? err.message : '移除失败') }
    finally { setRemoving(false) }
  }

  const activeDepartment = useMemo(
    () => (activeTab === 'all' || activeTab === 'uncategorized'
      ? ''
      : departments.find(d => d.id === activeTab)?.name || ''),
    [activeTab, departments],
  )
  const tabDepartment = activeTab === 'uncategorized' ? '未分类' : activeDepartment

  const load = useCallback(async (p: number, ps: number, kw: string, dept: string) => {
    const seq = ++seqRef.current
    setLoading(true)
    try {
      const res = await fetchTrainingRoster({
        page: p, page_size: ps,
        keyword: kw || undefined,
        department: dept || undefined,
      })
      if (seq !== seqRef.current) return
      setRows(res.data || [])
      setTotal(res.meta?.total || 0)
      setScopedDepartments(res.meta?.scoped_departments ?? null)
    } catch (err) {
      if (seq === seqRef.current) message.error(err instanceof Error ? err.message : '加载失败')
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [message])

  // 初次加载也走 load 的 seqRef 序号协议：与快速切部门/搜索的请求统一竞态，
  // 旧的未过滤响应不会再覆盖新筛选结果（loading 初值即 true，effect 内无同步 setState）
  useEffect(() => {
    void load(1, 20, '', '')
    let cancelled = false
    void fetchDepartmentsAction({ page_size: 100 })
      .then(d => { if (!cancelled) setDepartments(d.data || []) })
      .catch(() => { if (!cancelled) setDepartments([]) })
    void fetchPositions()
      .then(r => { if (!cancelled) setPositions(r.map(p => ({ name: p.name, department: p.department }))) })
      .catch(() => { if (!cancelled) setPositions([]) })
    return () => { cancelled = true }
  }, [load])

  const handleSearch = useCallback((value: string) => {
    setKeyword(value)
    setPage(1)
    void load(1, pageSize, value, tabDepartment)
  }, [load, pageSize, tabDepartment])

  const handleTabChange = useCallback((key: string) => {
    setActiveTab(key)
    setPage(1)
    const dept = key === 'all' || key === 'uncategorized'
      ? (key === 'uncategorized' ? '未分类' : '')
      : departments.find(d => d.id === key)?.name || ''
    void load(1, pageSize, keyword, dept)
  }, [departments, keyword, load, pageSize])

  const handlePageChange = useCallback((p: number, ps: number) => {
    setPage(p)
    setPageSize(ps)
    void load(p, ps, keyword, tabDepartment)
  }, [keyword, load, tabDepartment])

  // ── 名单下载（按当前搜索/部门筛选导出全量） ──

  const [exporting, setExporting] = useState(false)
  const handleDownload = useCallback(async () => {
    setExporting(true)
    try {
      // server action 只取数；window 触发下载必须在客户端做
      const { base64, filename } = await exportTrainingRoster({
        keyword: keyword || undefined,
        department: tabDepartment || undefined,
      })
      downloadBase64File(base64, filename || '培训人员名单.xlsx')
      message.success('名单已下载')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '下载失败')
    } finally {
      setExporting(false)
    }
  }, [keyword, message, tabDepartment])

  // ── 编辑弹窗 ──

  const openEdit = useCallback((row: TrainingRosterRow) => {
    const values: EditFormValues = {}
    for (const group of EDIT_GROUPS) {
      for (const f of group.fields) {
        const raw = row[f.name]
        if (f.type === 'date') {
          values[f.name] = raw ? dayjs(String(raw).slice(0, 10)) : null
        } else if (f.type === 'list') {
          values[f.name] = Array.isArray(raw) ? raw.join(',') : (raw ?? '')
        } else {
          values[f.name] = (raw ?? '') as string
        }
      }
    }
    form.setFieldsValue(values)
    setEditing(row)
  }, [form])

  const watchedDept = Form.useWatch('department', form)
  const departmentOptions = departments.map(d => ({ value: d.name, label: d.name }))
  const positionOptions = (watchedDept
    ? positions.filter(p => p.department === watchedDept)
    : positions
  ).map(p => ({ value: p.name, label: p.name }))

  const handleSave = async () => {
    if (!editing) return
    const values = await form.validateFields()
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {}
      for (const group of EDIT_GROUPS) {
        for (const f of group.fields) {
          const v = values[f.name]
          if (f.type === 'date') {
            payload[f.name] = v ? (v as Dayjs).format('YYYY-MM-DD') : null
          } else if (f.type === 'list') {
            payload[f.name] = String(v || '')
              .split(/[,，、]/).map(s => s.trim()).filter(Boolean)
          } else {
            payload[f.name] = v === '' ? null : v
          }
        }
      }
      await updateTrainingRosterEntry(editing.employee_number, payload as Partial<TrainingRosterRow>)
      message.success('已保存（不会被员工档案同步覆盖）')
      setEditing(null)
      void load(page, pageSize, keyword, tabDepartment)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // ── 列定义（白名单列序与总台账一致） ──

  const columns: ColumnsType<TrainingRosterRow> = useMemo(() => {
    const base: ColumnsType<TrainingRosterRow> = [
      { title: '工号', dataIndex: 'employee_number', key: 'employee_number', width: 100, fixed: 'left' },
      { title: '姓名', dataIndex: 'name', key: 'name', width: 90, fixed: 'left' },
      ...(canManage ? [{
        title: '分类标签', key: 'tags', width: 150,
        render: (_: unknown, r: TrainingRosterRow) => (
          <TagCell employeeNumber={r.employee_number} employeeName={r.name} options={classOptions} onChanged={loadClassifications} />
        ),
      }] : []),
      { title: '体现部门', dataIndex: 'department', key: 'department', width: 130 },
      { title: '实际部门', dataIndex: 'actual_department', key: 'actual_department', width: 130 },
      { title: '班组', dataIndex: 'team', key: 'team', width: 90 },
      { title: '职位', dataIndex: 'position', key: 'position', width: 110 },
      { title: '职务', dataIndex: 'duty', key: 'duty', width: 90 },
      {
        title: '报表用职级', dataIndex: 'report_level', key: 'report_level', width: 120,
        render: (v: string | null | undefined) => v || '其他人员',
      },
      { title: '岗位类别', dataIndex: 'job_category', key: 'job_category', width: 100 },
      { title: '品种', dataIndex: 'variety', key: 'variety', width: 90, render: (v: string | null) => v || '-' },
      { title: '兼任品种', dataIndex: 'concurrent_variety', key: 'concurrent_variety', width: 110, ellipsis: true, render: (v: string | null) => v || '-' },
      { title: '学历', dataIndex: 'education', key: 'education', width: 80 },
      { title: '毕业时间', dataIndex: 'graduation_date', key: 'graduation_date', width: 110, render: dateText },
      { title: '用工性质', dataIndex: 'status_category', key: 'status_category', width: 90 },
      {
        title: '人员状态', dataIndex: 'status', key: 'status', width: 90,
        render: (v: string) => <Tag color={STATUS_COLOR[v] || 'default'}>{v || '-'}</Tag>,
      },
      { title: '入职日期', dataIndex: 'hire_date', key: 'hire_date', width: 110, render: dateText },
      { title: '离职时间', dataIndex: 'departure_date', key: 'departure_date', width: 110, render: dateText },
      { title: '证书', dataIndex: 'certificates', key: 'certificates', width: 120, ellipsis: true },
      { title: '资格', dataIndex: 'qualifications', key: 'qualifications', width: 120, ellipsis: true, render: listText },
      { title: '培训编号', dataIndex: 'training_id', key: 'training_id', width: 100 },
      { title: '部门负责人/一级培训师', dataIndex: 'dept_head_trainer', key: 'dept_head_trainer', width: 150, ellipsis: true },
      { title: '入职安全培训日期', dataIndex: 'safety_training_date', key: 'safety_training_date', width: 130, render: dateText },
      { title: '入职安全培训成绩', dataIndex: 'safety_training_score', key: 'safety_training_score', width: 120 },
      { title: '企业文化培训日期', dataIndex: 'culture_training_date', key: 'culture_training_date', width: 130, render: dateText },
      { title: 'GMP基础培训时间', dataIndex: 'gmp_training_date', key: 'gmp_training_date', width: 130, render: dateText },
    ]
    if (canManage) {
      base.push({
        title: '操作', key: 'action', width: 80, fixed: 'right',
        render: (_: unknown, record: TrainingRosterRow) => (
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
        ),
      })
    }
    return base
  }, [canManage, openEdit, classOptions, loadClassifications])

  const visibleDepartments = scopedDepartments
    ? departments.filter(d => scopedDepartments.includes(d.name))
    : departments
  const tabItems = [
    { key: 'all', label: '全部' },
    ...visibleDepartments.map(d => ({ key: d.id, label: d.name })),
    ...(scopedDepartments ? [] : [{ key: 'uncategorized', label: '未分类' }]),
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">培训人员名单</h1>
          <p className="text-[14px] text-[var(--color-steel)]">培训管理专用的人员名册（脱敏，可独立编辑）</p>
        </div>
        <Space>
          {canManage && (
            <Button icon={<TagsOutlined />} onClick={openClassModal}>分类管理</Button>
          )}
          <Button
            icon={<DownloadOutlined />}
            onClick={() => { void handleDownload() }}
            loading={exporting}
          >
            下载名单
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => load(page, pageSize, keyword, tabDepartment)}
            loading={loading}
          >
            刷新
          </Button>
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        title={scopedDepartments ? `独立维护的脱敏名册（当前可见部门：${scopedDepartments.join('、')}）` : '独立维护的脱敏名册'}
        description="人员随员工档案自动增减（总表只管进出）；名单上的信息由培训管理独立编辑，不会被总表同步覆盖。身份证、毕业学校、专业、出生年月、籍贯、政治面貌、婚姻状况、银行卡、手机/邮箱、紧急联系人、合同、级别等个人信息不在此页面出现；人员状态随员工档案自动同步，无需手动维护。"
      />

      <div className="flex gap-3 flex-wrap">
        <Input.Search
          placeholder="搜索姓名或工号"
          prefix={<SearchOutlined />}
          allowClear
          style={{ width: 260 }}
          onSearch={handleSearch}
        />
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
        type="card"
        items={tabItems.map(t => ({
          key: t.key,
          label: t.label,
          children: activeTab === t.key ? (
            <Table<TrainingRosterRow>
              rowKey="employee_number"
              columns={columns}
              dataSource={rows}
              loading={loading}
              scroll={{ x: 2620 }}
              pagination={{
                current: page,
                pageSize,
                total,
                showSizeChanger: true,
                showTotal: t => `共 ${t} 人`,
                // eslint-disable-next-line react-hooks/refs -- 事件处理器内经 seqRef 丢弃过期响应（非渲染期读写）
                onChange: handlePageChange,
              }}
            />
          ) : null,
        }))}
      />

      <Modal
        title={editing ? `编辑：${editing.name}（${editing.employee_number}）` : '编辑'}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={720}
        destroyOnHidden
      >
        {editing && (
          <Form form={form} layout="vertical" className="max-h-[60vh] overflow-auto pr-2">
            {EDIT_GROUPS.map(group => (
              <div key={group.title}>
                <div className="text-[14px] font-medium mb-2 mt-1 pb-1 border-b border-[var(--color-hairline)]">
                  {group.title}
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4">
                  {group.fields.map(f => (
                    <Form.Item key={String(f.name)} name={f.name as string} label={f.label}>
                      {f.type === 'date' ? (
                        <DatePicker className="w-full" allowClear />
                      ) : f.type === 'department' ? (
                        <Select options={departmentOptions} allowClear showSearch
                          filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                      ) : f.type === 'position' ? (
                        <Select options={positionOptions} allowClear showSearch
                          filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                      ) : f.type === 'options' ? (
                        <Select options={FIXED_OPTIONS[String(f.name)] || []} allowClear showSearch
                          filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                      ) : (
                        <Input allowClear autoComplete="off" />
                      )}
                    </Form.Item>
                  ))}
                </div>
              </div>
            ))}
          </Form>
        )}
      </Modal>

      <Modal title="分类管理" open={classModalOpen} onCancel={() => setClassModalOpen(false)} footer={null} width={480}>
        <div className="space-y-3 mt-2">
          <Space.Compact style={{ width: '100%' }}>
            <Input value={newClassName} onChange={(e) => setNewClassName(e.target.value)}
              onPressEnter={handleAddClassification} placeholder="新分类名称" />
            <Button type="primary" icon={<PlusOutlined />} loading={classSaving}
              onClick={handleAddClassification}>新增分类</Button>
          </Space.Compact>
          {classList.length === 0 ? (
            <p className="text-[var(--color-stone)] text-[13px]">还没有分类，先新增一个，再在名单里用下拉选择分类</p>
          ) : (
            <div className="space-y-2">
              {classList.map((c) => (
                <div key={c.id}>
                  <div className="flex justify-between items-center rounded-[var(--rounded-sm)] bg-[var(--color-surface)] px-3 py-2 cursor-pointer"
                    onClick={() => { void toggleMembers(c.id) }}>
                    <span>{c.name}<span className="text-[var(--color-stone)] text-[12px] ml-2">{c.count}人</span></span>
                    <Space size={4}>
                      <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); void toggleMembers(c.id) }}>
                        {expandedId === c.id ? '收起' : '查看人员'}
                      </Button>
                      <Popconfirm title={`删除分类「${c.name}」？该分类下所有人员会解除分类`} onConfirm={() => { void handleDeleteClassification(c.id, c.name) }}>
                        <Button type="text" size="small" danger icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()} />
                      </Popconfirm>
                    </Space>
                  </div>
                  {expandedId === c.id && (
                    <div className="mt-1 rounded-[var(--rounded-sm)] border border-[var(--color-hairline)] p-2 space-y-1">
                      {membersLoading ? (
                        <p className="text-[var(--color-stone)] text-[13px]">加载中...</p>
                      ) : members.length === 0 ? (
                        <p className="text-[var(--color-stone)] text-[13px]">该分类下暂无人员</p>
                      ) : (
                        <>
                          <div className="flex justify-between items-center pb-1 border-b border-[var(--color-hairline)]">
                            <Checkbox
                              checked={selectedMembers.size > 0 && selectedMembers.size === members.length}
                              indeterminate={selectedMembers.size > 0 && selectedMembers.size < members.length}
                              onChange={(e) => setSelectedMembers(e.target.checked ? new Set(members.map(m => m.employee_number)) : new Set())}>
                              全选
                            </Checkbox>
                            <Button type="link" size="small" danger loading={removing}
                              disabled={selectedMembers.size === 0}
                              onClick={() => { void handleRemoveSelectedMembers() }}>
                              移除所选（{selectedMembers.size}）
                            </Button>
                          </div>
                          {members.map((m) => (
                            <div key={m.employee_number} className="text-[13px] flex gap-2 items-center">
                              <Checkbox checked={selectedMembers.has(m.employee_number)}
                                onChange={() => toggleMemberSelected(m.employee_number)} />
                              <span className="font-medium">{m.name}</span>
                              <span className="text-[var(--color-stone)]">{m.employee_number}</span>
                              <span className="text-[var(--color-steel)]">{m.department}{m.position ? ` / ${m.position}` : ''}</span>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}

// ─── 内联分类下拉单元格 ───

function TagCell({ employeeNumber, disabled, options, onChanged }: {
  employeeNumber: string
  employeeName: string
  disabled?: boolean
  options: { label: string; value: string }[]
  onChanged?: () => void
}) {
  const { message } = App.useApp()
  const [tags, setTags] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    fetchEmployeeTagsByEmployee(employeeNumber).then(r => {
      setTags((r.data || []).map(t => t.tag_name))
    }).catch(() => {}).finally(() => setLoading(false))
  }, [employeeNumber])

  // 分类清单 + 人员已有分类（并集）作为下拉选项
  const mergedOptions = [...options]
  for (const t of tags) {
    if (!mergedOptions.some(o => o.value === t)) {
      mergedOptions.push({ label: t, value: t })
    }
  }

  const handleChange = async (vals: string[]) => {
    const prev = tags
    setTags(vals)
    const added = vals.filter(t => !prev.includes(t))
    const removed = prev.filter(t => !vals.includes(t))
    try {
      for (const t of added) {
        await saveEmployeeTag({ employee_number: employeeNumber, tag_name: t, action: 'add' })
      }
      for (const t of removed) {
        await saveEmployeeTag({ employee_number: employeeNumber, tag_name: t, action: 'remove' })
      }
      onChanged?.()
    } catch (e) {
      // 失败回滚乐观更新并提示，避免界面与实际数据分叉
      setTags(prev)
      message.error(e instanceof Error ? e.message : '标签保存失败，已还原')
    }
  }

  return (
    <div onClick={e => e.stopPropagation()} style={{ minWidth: 120 }}>
      {editing ? (
        <Select
          mode="multiple"
          size="small"
          autoFocus
          style={{ width: '100%' }}
          placeholder="选择分类"
          value={tags}
          options={mergedOptions}
          onChange={handleChange}
          loading={loading}
          disabled={disabled}
          maxTagCount={2}
          onBlur={() => setEditing(false)}
          filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
        />
      ) : (
        <div
          className="flex flex-wrap gap-0.5 cursor-pointer min-h-[22px] items-center"
          onClick={() => { if (!disabled) setEditing(true) }}
        >
          {tags.length === 0 ? (
            <span className="text-gray-300 text-xs">+选择分类</span>
          ) : (
            <>
              {tags.slice(0, 3).map(t => <Tag key={t} color="blue" style={{ fontSize: 11, margin: 0 }}>{t}</Tag>)}
              {tags.length > 3 && <span className="text-[11px] text-[var(--color-stone)]">+{tags.length - 3}</span>}
            </>
          )}
        </div>
      )}
    </div>
  )
}
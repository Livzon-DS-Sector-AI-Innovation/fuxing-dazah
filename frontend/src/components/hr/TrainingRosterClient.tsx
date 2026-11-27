'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, App, Button, DatePicker, Form, Input, Modal, Select, Space, Table, Tabs, Tag,
} from 'antd'
import { DownloadOutlined, EditOutlined, ReloadOutlined, TagsOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { Dayjs } from 'dayjs'
import {
  fetchPositions,
  createEmployeeClassification,
  fetchDepartmentsAction,
  fetchEmployeeClassifications,
  fetchTrainingRoster,
  exportTrainingRoster,
  saveEmployeeTag,
  updateTrainingRosterEntry,
} from '@/actions/hr'
import type { TrainingRosterRow } from '@/actions/hr/employeeSync'
import { usePermission } from '@/hooks/usePermission'
import { useUnsavedConfirm } from '@/hooks/hr'
import { downloadBase64File, EMPLOYEE_STATUS_TAG_COLORS, classificationChipColors, ORPHAN_TAG_CHIP_COLOR } from '@/lib/hr'
import type { Department, EmployeeClassification } from '@/types/hr'
import PageHeader from './PageHeader'
import RosterTagCell from './training-roster/RosterTagCell'
import ClassificationManagerDrawer from './training-roster/ClassificationManagerDrawer'

/** 固定选项（口径与员工档案表单一致） */
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
  // 编辑弹窗打开期间是否有字段被改动过（打开时重置）
  const [editTouched, setEditTouched] = useState(false)
  const [form] = Form.useForm()
  const seqRef = useRef(0)
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:training:manage')

  // ── 人员分类（培训专用，挂在名单上；按创建人隔离） ──
  // 标签本身随名单行下发（row.tags），这里只维护分类清单：它决定胶囊配色与可勾选项
  const [classifications, setClassifications] = useState<EmployeeClassification[]>([])
  const [classDrawerOpen, setClassDrawerOpen] = useState(false)

  const loadClassifications = useCallback(async () => {
    try {
      const r = await fetchEmployeeClassifications()
      setClassifications(r.data || [])
    } catch (err) {
      setClassifications([])
      message.error(err instanceof Error ? err.message : '获取分类清单失败')
    }
  }, [message])

  const chipColors = useMemo(
    () => classificationChipColors(classifications.map((c) => c.name)),
    [classifications],
  )
  const colorOf = useCallback(
    (name: string) => chipColors[name] ?? ORPHAN_TAG_CHIP_COLOR,
    [chipColors],
  )

  /** 某人的分类变化：先乐观更新，再逐项保存；没保存成功的那几项还原，成功的保留 */
  const handleTagsChange = useCallback(async (employeeNumber: string, nextTags: string[]) => {
    const prev = rows.find((r) => r.employee_number === employeeNumber)?.tags ?? []
    const added = nextTags.filter((t) => !prev.includes(t))
    const removed = prev.filter((t) => !nextTags.includes(t))
    if (!added.length && !removed.length) return

    const apply = (tags: string[]) => {
      setRows((rs) => rs.map((r) => (r.employee_number === employeeNumber ? { ...r, tags } : r)))
    }
    apply(nextTags)
    const results = await Promise.allSettled([
      ...added.map((tag_name) =>
        saveEmployeeTag({ employee_number: employeeNumber, tag_name, action: 'add' })),
      ...removed.map((tag_name) =>
        saveEmployeeTag({ employee_number: employeeNumber, tag_name, action: 'remove' })),
    ])
    let final = prev
    let failed = 0
    results.forEach((res, i) => {
      if (res.status !== 'fulfilled') {
        failed += 1
        return
      }
      if (i < added.length) final = [...final, added[i]]
      else final = final.filter((t) => t !== removed[i - added.length])
    })
    if (failed) {
      apply(final)
      message.error(`${failed} 项分类保存失败，已还原`)
    }
    void loadClassifications()
  }, [loadClassifications, message, rows])

  /** 勾选面板里就地新建分类：成功返回 true，调用方随即把它勾给当前人员 */
  const handleCreateClassification = useCallback(async (name: string): Promise<boolean> => {
    try {
      await createEmployeeClassification(name)
      await loadClassifications()
      return true
    } catch (err) {
      message.error(err instanceof Error ? err.message : '新增失败')
      return false
    }
  }, [loadClassifications, message])

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

  // 分类清单决定胶囊配色与可勾选项：进页面拉一次（分类列仅管理权限可见）
  useEffect(() => {
    if (!canManage) return
    let cancelled = false
    fetchEmployeeClassifications()
      .then((r) => { if (!cancelled) setClassifications(r.data || []) })
      .catch(() => { if (!cancelled) setClassifications([]) })
    return () => { cancelled = true }
  }, [canManage])

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

  // 有未保存修改时，关闭（× / Esc / 取消）需先确认；弹窗关闭后不算 dirty，避免误挂刷新拦截
  const guardCloseEdit = useUnsavedConfirm(editing !== null && editTouched, () => setEditing(null))

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
    setEditTouched(false)
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
        title: '分类', key: 'tags', width: 168,
        render: (_: unknown, r: TrainingRosterRow) => (
          <RosterTagCell
            employeeNumber={r.employee_number}
            employeeName={r.name}
            tags={r.tags ?? []}
            classifications={classifications}
            colorOf={colorOf}
            onTagsChange={handleTagsChange}
            onCreateClassification={handleCreateClassification}
          />
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
        render: (v: string) => <Tag color={EMPLOYEE_STATUS_TAG_COLORS[v] || 'default'}>{v || '-'}</Tag>,
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
  }, [canManage, openEdit, classifications, colorOf, handleTagsChange, handleCreateClassification])

  const visibleDepartments = scopedDepartments
    ? departments.filter(d => scopedDepartments.includes(d.name))
    : departments
  const tabItems = [
    { key: 'all', label: '全部' },
    ...visibleDepartments.map(d => ({ key: d.id, label: d.name })),
    // 部门表里已有「未分类」时不再追加同名兜底页签（此前会出现两个「未分类」，查询结果相同）
    ...(scopedDepartments || visibleDepartments.some(d => d.name === '未分类')
      ? []
      : [{ key: 'uncategorized', label: '未分类' }]),
  ]

  /** 分类管理抽屉里的写操作：改名/删除/增减人员都会改变名单上的标签，清单和当前页一起刷新 */
  const handleClassificationChanged = useCallback(async () => {
    await loadClassifications()
    void load(page, pageSize, keyword, tabDepartment)
  }, [loadClassifications, load, page, pageSize, keyword, tabDepartment])

  return (
    <div className="space-y-4">
      <PageHeader
        title="培训人员名单"
        description="培训管理专用的人员名册（脱敏，可独立编辑）"
        actions={
          <Space>
            <Input.Search
              placeholder="搜索姓名或工号"
              allowClear
              style={{ width: 260 }}
              onSearch={handleSearch}
            />
            {canManage && (
              <Button icon={<TagsOutlined />} onClick={() => setClassDrawerOpen(true)}>分类管理</Button>
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
        }
      />

      <Alert
        type="info"
        showIcon
        closable
        title={scopedDepartments ? `独立维护的脱敏名册（当前可见部门：${scopedDepartments.join('、')}）` : '独立维护的脱敏名册'}
        description="人员随员工档案自动增减（总表只管进出）；名单上的信息由培训管理独立编辑，不会被总表同步覆盖。身份证、毕业学校、专业、出生年月、籍贯、政治面貌、婚姻状况、银行卡、手机/邮箱、紧急联系人、合同、级别等个人信息不在此页面出现；人员状态随员工档案自动同步，无需手动维护。"
      />

      <Tabs
        activeKey={activeTab}
        onChange={handleTabChange}
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
        onCancel={guardCloseEdit}
        mask={{ closable: false }}
        onOk={handleSave}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={720}
        destroyOnHidden
      >
        {editing && (
          <Form form={form} layout="vertical" className="max-h-[60vh] overflow-auto pr-2"
            onValuesChange={() => setEditTouched(true)}>
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

      <ClassificationManagerDrawer
        open={classDrawerOpen}
        classifications={classifications}
        colorOf={colorOf}
        onClose={() => setClassDrawerOpen(false)}
        onChanged={handleClassificationChanged}
      />
    </div>
  )
}

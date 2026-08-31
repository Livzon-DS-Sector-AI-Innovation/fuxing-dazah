'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { App, Table, Button, Space, Tag, Input, Select, Modal, Form, DatePicker, Timeline, message, Popconfirm, Checkbox } from 'antd'
import { SearchOutlined, EditOutlined, EyeOutlined, SwapOutlined, PlusOutlined, CloseOutlined, TagsOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import {
  fetchPositions, fetchDepartmentsAction, fetchTransfers, createTransfer,
  saveEmployeeTag, fetchEmployeeTagsByEmployee,
  fetchEmployeeClassifications, createEmployeeClassification, deleteEmployeeClassification,
  fetchClassificationMembers, removeClassificationMembers,
} from '@/actions/hr'
import { useHrStore } from '@/stores/hr'
import { usePermission } from '@/hooks/usePermission'
import EmployeeInfoModal from './EmployeeInfoModal'

interface EmployeeTableProps {
  employees: Employee[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number, pageSize: number) => void
  onRefresh: () => void
  onEdit: (employee: Employee) => void
  loading?: boolean
}

const statusColorMap: Record<string, string> = {
  在职: 'success',
  试用期: 'warning',
  离职: 'default',
  待审批: 'processing',
  病假: 'error',
  产假: 'magenta',
  产假复岗: 'purple' }

export default function EmployeeTable({
  employees,
  total,
  page,
  pageSize,
  onPageChange,
  onRefresh,
  onEdit,
  loading = false }: EmployeeTableProps) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  // 员工档案基础信息不开放给培训管理员等无档案编辑权限的角色
  const canEditProfile = hasPermission('hr:profile:update')
  const canTransfer = hasPermission('hr:profile:transfer')
  const canManageClassification = hasPermission('hr:training:manage')

  // ─── 分类管理 Modal ───
  const [classModalOpen, setClassModalOpen] = useState(false)
  const [classList, setClassList] = useState<{ id: string; name: string; count: number }[]>([])
  const [classOptions, setClassOptions] = useState<{ label: string; value: string }[]>([])
  const [newClassName, setNewClassName] = useState('')
  const [classSaving, setClassSaving] = useState(false)

  const loadClassifications = useCallback(async () => {
    try {
      const r = await fetchEmployeeClassifications()
      setClassList(r.data || [])
      // 同步更新下拉选项，分类增删后所有行的下拉立即刷新
      setClassOptions((r.data || []).map(c => ({ label: `${c.name}（${c.count}人）`, value: c.name })))
    } catch { setClassList([]) }
  }, [])

  useEffect(() => {
    loadClassifications()
  }, [loadClassifications])

  const openClassModal = () => {
    setNewClassName('')
    setClassModalOpen(true)
    loadClassifications()
  }

  const handleAddClassification = async () => {
    const name = newClassName.trim()
    if (!name) return
    setClassSaving(true)
    try {
      await createEmployeeClassification(name)
      setNewClassName('')
      message.success('分类已新增')
      loadClassifications()
    } catch (e: any) { message.error(e.message || '新增失败') }
    finally { setClassSaving(false) }
  }

  const handleDeleteClassification = async (id: string, name: string) => {
    try {
      await deleteEmployeeClassification(id)
      message.success(`分类「${name}」已删除`)
      if (expandedId === id) setExpandedId(null)
      loadClassifications()
    } catch (e: any) { message.error(e.message || '删除失败') }
  }

  // ─── 查看/管理分类下的人员 ───
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [members, setMembers] = useState<{ name: string; employee_number: string; department: string; position: string }[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [selectedMembers, setSelectedMembers] = useState<Set<string>>(new Set())
  const [removing, setRemoving] = useState(false)

  const fetchMembers = async (id: string) => {
    setMembersLoading(true)
    try {
      const r = await fetchClassificationMembers(id)
      setMembers(r.data || [])
    } catch (e: any) {
      message.error(e.message || '获取人员失败')
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

  const handleRemoveSelectedMembers = async () => {
    if (!expandedId || selectedMembers.size === 0) return
    setRemoving(true)
    try {
      const res = await removeClassificationMembers(expandedId, Array.from(selectedMembers))
      message.success(res.message || '已移除')
      setSelectedMembers(new Set())
      await fetchMembers(expandedId)
      loadClassifications()
    } catch (e: any) { message.error(e.message || '移除失败') }
    finally { setRemoving(false) }
  }

  const toggleMemberSelected = (en: string) => {
    setSelectedMembers((prev) => {
      const next = new Set(prev)
      next.has(en) ? next.delete(en) : next.add(en)
      return next
    })
  }
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailEmp, setDetailEmp] = useState<Employee | null>(null)
  const { searchKeyword, setSearchKeyword, filterStatus, setFilterStatus } = useHrStore()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleSearchChange = (val: string) => {
    // 防抖：停止输入 300ms 后才触发搜索，避免逐键请求乱序
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchKeyword(val), 300)
  }

  // ─── 异动记录 Modal ───
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferEmp, setTransferEmp] = useState<Employee | null>(null)
  const [transfers, setTransfers] = useState<any[]>([])
  const [transferForm] = Form.useForm()
  const [positionOptions, setPositionOptions] = useState<Record<string, string[]>>({})
  const watchedFromDept = Form.useWatch('from_department', transferForm)
  const watchedToDept = Form.useWatch('to_department', transferForm)

  useEffect(() => {
    fetchPositions()
      .then(list => {
        const map: Record<string, string[]> = {}
        list.forEach((p) => {
          if (!map[p.department]) map[p.department] = []
          map[p.department].push(p.name)
        })
        setPositionOptions(map)
      }).catch(() => {})
  }, [])

  // 获取某部门下的职位列表
  const getPositions = (dept: string | undefined) => {
    const deptPositions = (dept && positionOptions[dept]) ? positionOptions[dept] : []
    const all = [...deptPositions]
    Object.values(positionOptions).forEach(arr => arr.forEach(p => { if (!all.includes(p)) all.push(p) }))
    return all.map(p => ({ label: p, value: p }))
  }

  const [deptOptions, setDeptOptions] = useState<string[]>([])
  useEffect(() => {
    fetchDepartmentsAction({ page_size: 200 })
      .then(d => setDeptOptions((d.data || []).map((x: any) => x.name)))
      .catch(() => {})
  }, [])

  const handleDeptChange = (deptField: string, value: string) => {
    const posField = deptField === 'from_department' ? 'from_position' : 'to_position'
    const currentPos = transferForm.getFieldValue(posField)
    if (currentPos && positionOptions[value] && !positionOptions[value].includes(currentPos)) {
      transferForm.setFieldValue(posField, undefined)
    }
  }

  const loadTransfers = async (employeeId: string) => {
    try {
      const d = await fetchTransfers({ employee_id: employeeId, page_size: 50 })
      setTransfers(d.data || [])
    } catch { setTransfers([]) }
  }

  const handleOpenTransfers = (emp: Employee) => {
    setTransferEmp(emp)
    setTransferOpen(true)
    transferForm.resetFields()
    // 自动填入当前部门和岗位
    transferForm.setFieldsValue({
      from_department: emp.department || undefined,
      from_position: emp.position || undefined,
    })
    loadTransfers(emp.id)
  }

  const handleCreateTransfer = async () => {
    const values = await transferForm.validateFields()
    try {
      await createTransfer({
        employee_id: transferEmp!.id,
        transfer_type: values.transfer_type,
        from_department: values.from_department || null,
        to_department: values.to_department || null,
        from_position: values.from_position || null,
        to_position: values.to_position || null,
        effective_date: values.effective_date.format('YYYY-MM-DD'),
        reason: values.reason || null,
      })
      message.success('异动记录已添加')
      transferForm.resetFields()
      loadTransfers(transferEmp!.id)
    } catch (err: any) { message.error(err.message || '创建失败') }
  }

  const allColumns: any[] = [
    {
      title: '工号',
      dataIndex: 'employee_number',
      key: 'employee_number',
      width: 110,
      fixed: 'left' as const },
    {
      title: '姓名',
      dataIndex: 'name',
      key: 'name',
      width: 90,
      fixed: 'left' as const },
    {
      title: '体现部门',
      dataIndex: 'department',
      key: 'department',
      width: 160 },
    {
      title: '实际部门',
      dataIndex: 'actual_department',
      key: 'actual_department',
      width: 140, ellipsis: true,
      render: (v: string) => v || '-' },
    {
      title: '班组',
      dataIndex: 'team',
      key: 'team',
      width: 100 },
    {
      title: '体现岗位',
      dataIndex: 'position',
      key: 'position',
      width: 140 },
    {
      title: '兼任部门',
      dataIndex: 'concurrent_departments',
      key: 'concurrent_departments',
      width: 130,
      render: (v: string) => v || '-' },
    {
      title: '兼任品种',
      dataIndex: 'variety',
      key: 'variety',
      width: 100,
      render: (v: string) => v || '-' },
    {
      title: '分类标签',
      key: 'tags',
      width: 200,
      render: (_: any, record: Employee) => (
        <TagCell employeeNumber={record.employee_number} employeeName={record.name}
          disabled={!canManageClassification} options={classOptions}
          onChanged={loadClassifications} />
      ),
    },
    {
      title: '性别',
      dataIndex: 'gender',
      key: 'gender',
      width: 70 },
    {
      title: '年龄',
      dataIndex: 'computed_age',
      key: 'age',
      width: 70,
      render: (_: unknown, record: Employee) => record.computed_age ?? record.age ?? '-',
    },
    {
      title: '学历',
      dataIndex: 'education',
      key: 'education',
      width: 80 },
    {
      title: '手机',
      dataIndex: 'phone',
      key: 'phone',
      width: 130 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>{status}</Tag>
      ) },
    {
      title: '入职日期',
      dataIndex: 'hire_date',
      key: 'hire_date',
      width: 110 },
    {
      title: '籍贯',
      dataIndex: 'native_place',
      key: 'native_place',
      width: 100 },
    {
      title: '政治面貌',
      dataIndex: 'political_status',
      key: 'political_status',
      width: 100 },
    {
      title: '婚姻状况',
      dataIndex: 'marital_status',
      key: 'marital_status',
      width: 100 },
    {
      title: '合同期限',
      dataIndex: 'contract_type',
      key: 'contract_type',
      width: 110 },
    {
      title: '职称类型',
      dataIndex: 'qualification_type',
      key: 'qualification_type',
      width: 100 },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 80 },
    {
      title: '司龄',
      dataIndex: 'computed_tenure',
      key: 'company_tenure',
      width: 100,
      render: (_: unknown, record: Employee) => record.computed_tenure ?? record.company_tenure ?? '-',
    },
    {
      title: '毕业学校',
      dataIndex: 'school',
      key: 'school',
      width: 150 },
    {
      title: '专业',
      dataIndex: 'major',
      key: 'major',
      width: 120 },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_: any, record: Employee) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => { setDetailEmp(record); setDetailOpen(true) }}
          >
            详情
          </Button>
          {canEditProfile && (
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            >
              编辑
            </Button>
          )}
          {canTransfer && (
            <Button type="text" size="small" icon={<SwapOutlined />}
              onClick={() => handleOpenTransfers(record)}>
              异动
            </Button>
          )}
        </Space>
      ) },
  ]

  // Hide columns where ALL rows have empty values (except key & important columns)
  const alwaysShow = new Set(['action', 'employee_number', 'name', 'department', 'actual_department', 'position', 'concurrent_departments', 'variety', 'tags'])
  const columns = allColumns.filter(col => {
    if (alwaysShow.has(col.key as string)) return true
    return employees.some((emp: any) => {
      const v = emp[col.dataIndex as string]
      return v !== null && v !== undefined && v !== ''
    })
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 items-center">
        <Input.Search
          placeholder="搜索姓名或工号"
          value={searchKeyword}
          onChange={(e) => handleSearchChange(e.target.value)}
          onSearch={(val) => {
            if (debounceRef.current) clearTimeout(debounceRef.current)
            setSearchKeyword(val)
          }}
          className="w-64"
          allowClear
        />
        <Select
          placeholder="状态筛选"
          value={filterStatus || undefined}
          onChange={(value) => setFilterStatus(value || '')}
          allowClear
          className="w-32"
          options={[
            { value: '在职', label: '在职' },
            { value: '试用期', label: '试用期' },
            { value: '离职', label: '离职' },
            { value: '待审批', label: '待审批' },
            { value: '病假', label: '病假' },
            { value: '产假', label: '产假' },
            { value: '产假复岗', label: '产假复岗' },
          ]}
        />
        {canManageClassification && (
          <Button icon={<TagsOutlined />} onClick={openClassModal}>分类管理</Button>
        )}
      </div>

      <Table
        columns={columns}
        dataSource={employees}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: onPageChange }}
        scroll={{ x: 2200 }}
        size="small"
      />

      <EmployeeInfoModal employee={detailEmp} open={detailOpen} onClose={() => setDetailOpen(false)} />

      {/* 异动记录 Modal */}
      <Modal
        title={transferEmp ? `${transferEmp.name} — 异动记录` : '异动记录'}
        open={transferOpen}
        onCancel={() => setTransferOpen(false)}
        footer={null}
        width={700}
      >
        <div className="space-y-4">
          {transfers.length > 0 ? (
            <Timeline
              items={transfers.map((t: any) => ({
                color: t.transfer_type === '晋升' ? 'green' : t.transfer_type === '降职' ? 'red' : 'blue',
                children: (
                  <div>
                    <div className="font-medium">
                      [{t.transfer_type}] {t.from_department || '—'} → {t.to_department || '—'}
                    </div>
                    <div className="text-gray-500 text-sm">
                      {t.from_position || '—'} → {t.to_position || '—'} · {t.effective_date}
                    </div>
                    {t.reason && <div className="text-gray-400 text-xs mt-1">原因：{t.reason}</div>}
                  </div>
                ),
              }))}
            />
          ) : (
            <p className="text-gray-400 text-center py-8">暂无异动记录</p>
          )}

          <div className="border-t pt-4 mt-4">
            <h4 className="font-medium mb-3">新增异动</h4>
            <Form form={transferForm} layout="inline" className="flex flex-wrap gap-2">
              <Form.Item name="transfer_type" label="类型" rules={[{ required: true }]}>
                <Select style={{ width: 110 }} options={[
                  { label: '晋升', value: '晋升' }, { label: '转岗', value: '转岗' },
                  { label: '产假复岗', value: '产假复岗' },
                ]} />
              </Form.Item>
              <Form.Item name="effective_date" label="日期" rules={[{ required: true }]}>
                <DatePicker style={{ width: 130 }} />
              </Form.Item>
              <Form.Item name="from_department" label="原部门">
                <Select showSearch allowClear placeholder="原部门" style={{ width: 120 }}
                  options={deptOptions.map(d => ({ label: d, value: d }))}
                  onChange={(v) => handleDeptChange('from_department', v)} />
              </Form.Item>
              <Form.Item name="to_department" label="新部门">
                <Select showSearch allowClear placeholder="新部门" style={{ width: 120 }}
                  options={deptOptions.map(d => ({ label: d, value: d }))}
                  onChange={(v) => handleDeptChange('to_department', v)} />
              </Form.Item>
              <Form.Item name="from_position" label="原岗位">
                <Select showSearch allowClear placeholder="原岗位" style={{ width: 120 }}
                  options={getPositions(watchedFromDept)} />
              </Form.Item>
              <Form.Item name="to_position" label="新岗位">
                <Select showSearch allowClear placeholder="新岗位" style={{ width: 120 }}
                  options={getPositions(watchedToDept)} />
              </Form.Item>
              <Form.Item name="reason" label="原因"><Input style={{ width: 120 }} /></Form.Item>
              <Form.Item><Button type="primary" onClick={handleCreateTransfer}>添加</Button></Form.Item>
            </Form>
          </div>
        </div>
      </Modal>

      <Modal title="分类管理" open={classModalOpen} onCancel={() => setClassModalOpen(false)} footer={null} width={480}>
        <div className="space-y-3 mt-2">
          <Space.Compact style={{ width: '100%' }}>
            <Input value={newClassName} onChange={(e) => setNewClassName(e.target.value)}
              onPressEnter={handleAddClassification} />
            <Button type="primary" icon={<PlusOutlined />} loading={classSaving}
              onClick={handleAddClassification}>新增分类</Button>
          </Space.Compact>
          {classList.length === 0 ? (
            <p className="text-[var(--color-stone)] text-[13px]">还没有分类，先新增一个，再在员工档案里用下拉选择分类</p>
          ) : (
            <div className="space-y-2">
              {classList.map((c) => (
                <div key={c.id}>
                  <div className="flex justify-between items-center rounded-[var(--rounded-sm)] bg-[var(--color-surface)] px-3 py-2 cursor-pointer"
                    onClick={() => toggleMembers(c.id)}>
                    <span>{c.name}<span className="text-[var(--color-stone)] text-[12px] ml-2">{c.count}人</span></span>
                    <Space size={4}>
                      <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); toggleMembers(c.id) }}>
                        {expandedId === c.id ? '收起' : '查看人员'}
                      </Button>
                      <Popconfirm title={`删除分类「${c.name}」？该分类下所有员工会解除分类`} onConfirm={() => handleDeleteClassification(c.id, c.name)}>
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
                              onClick={handleRemoveSelectedMembers}>
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

function TagCell({ employeeNumber, employeeName, disabled, options, onChanged }: {
  employeeNumber: string
  employeeName: string
  disabled?: boolean
  options: { label: string; value: string }[]
  onChanged?: () => void
}) {
  const [tags, setTags] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchEmployeeTagsByEmployee(employeeNumber).then(r => {
      setTags((r.data || []).map(t => t.tag_name))
    }).catch(() => {}).finally(() => setLoading(false))
  }, [employeeNumber])

  // 分类清单 + 员工已有分类（并集）作为下拉选项
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
      // 分类人数变化后刷新选项上的（N人）计数
      onChanged?.()
    } catch (e: any) {
      // 失败回滚乐观更新并提示，避免界面与实际数据分叉
      setTags(prev)
      message.error(e?.message || '标签保存失败，已还原')
    }
  }

  const [editing, setEditing] = useState(false)

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

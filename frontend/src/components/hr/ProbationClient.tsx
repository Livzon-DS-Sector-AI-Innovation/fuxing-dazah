'use client'

import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Modal, Select, Space, Table, Tag, message } from 'antd'
import { ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined, EditOutlined, HistoryOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchDepartments, API_BASE } from '@/lib/hr'

interface ProbationEmployee {
  id: string
  employee_number: string
  name: string
  department: string
  position: string
  hire_date: string | null
  probation_end_date: string | null
  regularization_date: string | null
  status: string
}

export default function ProbationClient() {
  const [employees, setEmployees] = useState<ProbationEmployee[]>([])
  const [loading, setLoading] = useState(false)
  const [departments, setDepartments] = useState<string[]>([])
  const [filterDept, setFilterDept] = useState<string | undefined>(undefined)
  const [expireDays, setExpireDays] = useState(0)
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])
  const [batchLoading, setBatchLoading] = useState(false)

  // 编辑
  const [editModal, setEditModal] = useState<{ open: boolean; record: ProbationEmployee | null }>({ open: false, record: null })
  const [editProbationEnd, setEditProbationEnd] = useState<any>(null)

  // 延期历史
  const [historyModal, setHistoryModal] = useState<{ open: boolean; record: ProbationEmployee | null }>({ open: false, record: null })
  const [extensions, setExtensions] = useState<any[]>([])

  const loadData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/employees/probation-expiring?days=${expireDays}${filterDept ? `&department=${encodeURIComponent(filterDept)}` : ''}`, { credentials: 'include' })
      const d = await res.json()
      setEmployees(d.data || [])
    } catch { message.error('加载失败') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    fetchDepartments({ page_size: 200 }).then(res => {
      setDepartments((res.data || []).map((d: any) => d.name))
    })
    loadData()
  }, [filterDept, expireDays])

  const daysLeft = (endDate: string | null) => {
    if (!endDate) return 999
    return dayjs(endDate).diff(dayjs(), 'day')
  }

  // 统计数据
  const totalCount = employees.length
  const urgent7 = employees.filter(e => daysLeft(e.probation_end_date) <= 7).length
  const urgent30 = employees.filter(e => daysLeft(e.probation_end_date) <= 30).length

  const handleRegularize = (record: ProbationEmployee) => {
    Modal.confirm({
      title: '确认转正',
      content: `确认将 ${record.name}（${record.employee_number}）转为正式员工？转正后自动写入培训台账。`,
      onOk: async () => {
        try {
          const res = await fetch(`${API_BASE}/api/v1/hr/employees/${record.id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: '在职', regularization_date: dayjs().format('YYYY-MM-DD') }),
            credentials: 'include',
          })
          if (!res.ok) throw new Error('操作失败')
          message.success(`${record.name} 已转正，已自动写入培训台账`)
          loadData()
        } catch (err: any) { message.error(err.message || '操作失败') }
      },
    })
  }

  const handleReject = (record: ProbationEmployee) => {
    Modal.confirm({
      title: '确认未通过',
      content: `${record.name}（${record.employee_number}）试用期未通过，将自动转为离职状态并记入离职台账。`,
      okText: '确认未通过',
      okType: 'danger',
      onOk: async () => {
        try {
          const res = await fetch(`${API_BASE}/api/v1/hr/employees/${record.id}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: '离职', departure_date: dayjs().format('YYYY-MM-DD') }),
            credentials: 'include',
          })
          if (!res.ok) throw new Error('操作失败')
          message.success(`${record.name} 已标记离职，离职台账+培训台账已自动生成`)
          loadData()
        } catch (err: any) { message.error(err.message || '操作失败') }
      },
    })
  }

  const handleBatchRegularize = () => {
    if (selectedRowKeys.length === 0) { message.warning('请先勾选要转正的员工'); return }
    Modal.confirm({
      title: '批量转正',
      content: `确认将已选的 ${selectedRowKeys.length} 人全部转为正式员工？`,
      onOk: async () => {
        setBatchLoading(true)
        try {
          const res = await fetch(`${API_BASE}/api/v1/hr/employees/batch-regularize`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(selectedRowKeys),
            credentials: 'include',
          })
          const d = await res.json()
          if (!res.ok) throw new Error(d.message || '操作失败')
          message.success(`已转正 ${d.data?.count || selectedRowKeys.length} 人，已自动写入培训台账`)
          setSelectedRowKeys([])
          loadData()
        } catch (err: any) { message.error(err.message || '操作失败') }
        finally { setBatchLoading(false) }
      },
    })
  }

  const handleEdit = (record: ProbationEmployee) => {
    setEditModal({ open: true, record })
    setEditProbationEnd(record.probation_end_date ? dayjs(record.probation_end_date) : null)
  }

  const handleEditSave = async () => {
    const record = editModal.record
    if (!record) return
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/employees/${record.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ probation_end_date: editProbationEnd ? editProbationEnd.format('YYYY-MM-DD') : null }),
        credentials: 'include',
      })
      if (!res.ok) throw new Error('保存失败')
      message.success('已更新（延期记录已自动保存）')
      setEditModal({ open: false, record: null })
      loadData()
    } catch (err: any) { message.error(err.message || '保存失败') }
  }

  const handleHistory = async (record: ProbationEmployee) => {
    setHistoryModal({ open: true, record })
    try {
      const res = await fetch(`${API_BASE}/api/v1/hr/employees/${record.id}/probation-extensions`, { credentials: 'include' })
      const d = await res.json()
      setExtensions(d.data || [])
    } catch { setExtensions([]) }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-1">试用期管理</h1>
          <p className="text-[14px] text-[var(--color-steel)]">到期预警 · 编辑截止日 · 一键转正 · 延期留痕</p>
        </div>
        <Space>
          <Select placeholder="全部部门" allowClear style={{ width: 140 }} value={filterDept} onChange={setFilterDept}
            options={departments.map(d => ({ value: d, label: d }))} />
          <Select value={expireDays} onChange={setExpireDays} style={{ width: 160 }}
            options={[
              { label: '全部试用期员工', value: 0 }, { label: '7天内到期', value: 7 },
              { label: '30天内到期', value: 30 }, { label: '60天内到期', value: 60 }, { label: '90天内到期', value: 90 },
            ]} />
          <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
        </Space>
      </div>

      {/* 预警汇总栏 */}
      {totalCount > 0 && (
        <Alert
          type={urgent7 > 0 ? 'error' : urgent30 > 0 ? 'warning' : 'info'}
          showIcon
          message={
            <Space size="large">
              <span>试用期总人数：<b>{totalCount}</b></span>
              {urgent7 > 0 && <span className="text-red-600">7天内到期：<b>{urgent7}</b> 人</span>}
              {urgent30 > 0 && <span>30天内到期：<b>{urgent30}</b> 人</span>}
            </Space>
          }
          action={selectedRowKeys.length > 0 && (
            <Button size="small" type="primary" icon={<CheckCircleOutlined />} loading={batchLoading} onClick={handleBatchRegularize}>
              批量转正（{selectedRowKeys.length}人）
            </Button>
          )}
        />
      )}

      <Card>
        <Table rowKey="id" loading={loading} dataSource={employees} size="small"
          rowSelection={{ selectedRowKeys, onChange: (keys) => setSelectedRowKeys(keys as string[]) }}
          columns={[
            { title: '工号', dataIndex: 'employee_number', width: 100 },
            { title: '姓名', dataIndex: 'name', width: 90 },
            { title: '部门', dataIndex: 'department', width: 120 },
            { title: '职位', dataIndex: 'position', width: 100 },
            { title: '入职日期', dataIndex: 'hire_date', width: 100 },
            { title: '截止日', dataIndex: 'probation_end_date', width: 110,
              sorter: (a: any, b: any) => dayjs(a.probation_end_date).unix() - dayjs(b.probation_end_date).unix(), defaultSortOrder: 'ascend' },
            { title: '剩余', dataIndex: 'probation_end_date', width: 80,
              render: (_: any, r: ProbationEmployee) => {
                const d = daysLeft(r.probation_end_date)
                return <Tag color={d <= 7 ? 'red' : d <= 30 ? 'orange' : 'green'}>{d} 天</Tag>
              }},
            { title: '操作', width: 200,
              render: (_: any, r: ProbationEmployee) => (
                <Space size="small">
                  <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => handleRegularize(r)}>转正</Button>
                  <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleReject(r)}>不通过</Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)}>编辑</Button>
                  <Button size="small" icon={<HistoryOutlined />} onClick={() => handleHistory(r)}>延期记录</Button>
                </Space>
              )},
          ]} />
      </Card>

      {/* 编辑 */}
      <Modal title="编辑试用期" open={editModal.open}
        onCancel={() => setEditModal({ open: false, record: null })} onOk={handleEditSave}
      >
        <div className="pt-3">
          <div className="mb-1 text-sm text-gray-500">试用期截止日（修改后自动记录延期）</div>
          <DatePicker value={editProbationEnd} onChange={setEditProbationEnd} style={{ width: '100%' }} />
        </div>
      </Modal>

      {/* 延期历史 */}
      <Modal title={`延期记录 — ${historyModal.record?.name || ''}`} open={historyModal.open}
        onCancel={() => setHistoryModal({ open: false, record: null })} footer={null} width={500}
      >
        {extensions.length === 0 ? (
          <p className="text-gray-400 py-4">暂无延期记录</p>
        ) : (
          <Table rowKey="created_at" size="small" dataSource={extensions} pagination={false}
            columns={[
              { title: '原截止日', dataIndex: 'old_date', width: 110 },
              { title: '新截止日', dataIndex: 'new_date', width: 110 },
              { title: '变更时间', dataIndex: 'created_at', width: 160 },
            ]} />
        )}
      </Modal>
    </div>
  )
}

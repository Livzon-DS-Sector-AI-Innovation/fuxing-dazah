'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  DatePicker,
  Spin,
  message,
  Input,
  Select,
  Space,
  Popconfirm,
  Statistic,
  Row,
  Col,
  Table,
} from 'antd'
import {
  PrinterOutlined,
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
  EditOutlined,
  ExportOutlined,
  SearchOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { exportTrainingLedger } from '@/lib/api/hr'
import dayjs from 'dayjs'
import { Employee, TrainingLedgerRecord } from '@/types/hr'
import {
  fetchEmployeeByNumber,
  fetchEmployees,
  fetchTrainingLedgers,
  fetchTrainingLedgersAdmin,
  batchUpdateScores,
  fetchTrainingLedgerStats,
  fetchLedgerDepartments,
  fetchLedgerSubjects,
  fetchDepartments,
  exportTrainingEvaluationReport,
  createTrainingLedger,
  updateTrainingLedger,
  deleteTrainingLedger,
} from '@/lib/api/hr'

interface TrainingLedgerClientProps {
  employeeNumber: string
}

interface AdminRecord {
  id: string
  employee_number: string
  employee_name: string
  department: string
  training_date: string
  training_subject: string
  training_method: string | null
  duration_hours: number | null
  location: string | null
  trainer: string | null
  assessment_result: string | null
  source_type: string
  remarks: string | null
}

interface StatsData {
  total_count: number
  assessed_count: number
  qualified_count: number
  unqualified_count: number
  pass_rate: string
  avg_score: number | null
}

const METHOD_OPTIONS = ['面授', '函授', '远程教育', '自学', '其他']

export default function TrainingLedgerClient({
  employeeNumber,
}: TrainingLedgerClientProps) {
  const isAdminMode = !employeeNumber

  // ─── Employee mode state ───
  const [employee, setEmployee] = useState<Employee | null>(null)
  const [records, setRecords] = useState<TrainingLedgerRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [dateFrom, setDateFrom] = useState<string | null>(null)
  const [dateTo, setDateTo] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<TrainingLedgerRecord>>({})
  const [saving, setSaving] = useState(false)
  const [searchEmpNo, setSearchEmpNo] = useState(employeeNumber || '')
  const [searching, setSearching] = useState(false)
  const [searchOptions, setSearchOptions] = useState<{ value: string; label: string }[]>([])

  // ─── Admin mode state ───
  const [adminRecords, setAdminRecords] = useState<AdminRecord[]>([])
  const [adminLoading, setAdminLoading] = useState(false)
  const [stats, setStats] = useState<StatsData | null>(null)
  const [departments, setDepartments] = useState<string[]>([])
  const [subjects, setSubjects] = useState<string[]>([])
  const [filterDept, setFilterDept] = useState<string | undefined>(undefined)
  const [filterSubject, setFilterSubject] = useState<string | undefined>(undefined)
  const [adminDateRange, setAdminDateRange] = useState<[string, string] | null>(null)
  const [adminPage, setAdminPage] = useState(1)
  const [adminPageSize, setAdminPageSize] = useState(20)
  const [adminTotal, setAdminTotal] = useState(0)
  const [adminEditMap, setAdminEditMap] = useState<Record<string, string>>({})
  const [adminDirtyIds, setAdminDirtyIds] = useState<Set<string>>(new Set())
  const [adminSaving, setAdminSaving] = useState(false)

  // ─── Employee mode: data loading ───
  const handleEmployeeSearch = async (keyword: string) => {
    if (!keyword || keyword.length < 1) { setSearchOptions([]); return }
    setSearching(true)
    try {
      const res = await fetchEmployees({ keyword, page_size: 20 })
      const emps = res.data || []
      setSearchOptions(emps.map((e: any) => ({
        value: e.employee_number,
        label: `${e.employee_number} — ${e.name} (${e.department || ''})`,
      })))
    } catch { setSearchOptions([]) }
    finally { setSearching(false) }
  }

  const loadEmployeeData = async () => {
    setLoading(true)
    try {
      if (employeeNumber) {
        const empRes = await fetchEmployeeByNumber(employeeNumber)
        setEmployee(empRes.data)
      }
      if (!employeeNumber) {
        setRecords([])
        setLoading(false)
        return
      }
      const ledgerRes = await fetchTrainingLedgers({
        employee_number: employeeNumber,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page_size: 100,
      })
      setRecords(ledgerRes.data || [])
    } catch (err: any) {
      message.error('加载数据失败: ' + (err.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!isAdminMode) loadEmployeeData()
  }, [employeeNumber, dateFrom, dateTo])

  // ─── Admin mode: data loading ───
  useEffect(() => {
    if (isAdminMode) {
      loadAdminDepartments()
      loadAdminData()
      loadAdminStats()
    }
  }, [isAdminMode])

  useEffect(() => {
    if (isAdminMode) {
      if (filterDept) loadAdminSubjects(filterDept)
      else setSubjects([])
    }
  }, [filterDept, isAdminMode])

  const loadAdminDepartments = async () => {
    try {
      const res = await fetchLedgerDepartments()
      setDepartments(res.data || [])
    } catch {
      try {
        const res = await fetchDepartments({ page_size: 200 })
        setDepartments((res.data || []).map((d: any) => d.name))
      } catch { /* ignore */ }
    }
  }

  const loadAdminSubjects = async (dept?: string) => {
    try {
      const res = await fetchLedgerSubjects(dept)
      setSubjects(res.data || [])
    } catch { /* ignore */ }
  }

  const loadAdminData = async () => {
    setAdminLoading(true)
    try {
      const res = await fetchTrainingLedgersAdmin({
        department: filterDept,
        training_subject: filterSubject,
        date_from: adminDateRange ? adminDateRange[0] : undefined,
        date_to: adminDateRange ? adminDateRange[1] : undefined,
        page: adminPage,
        page_size: adminPageSize,
      })
      setAdminRecords(res.data || [])
      setAdminTotal(res.meta?.total || 0)
      setAdminEditMap({})
      setAdminDirtyIds(new Set())
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally {
      setAdminLoading(false)
    }
  }

  const loadAdminStats = async () => {
    try {
      const res = await fetchTrainingLedgerStats({
        department: filterDept,
        training_subject: filterSubject,
        date_from: adminDateRange ? adminDateRange[0] : undefined,
        date_to: adminDateRange ? adminDateRange[1] : undefined,
      })
      setStats(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (isAdminMode) { loadAdminData(); loadAdminStats() }
  }, [filterDept, filterSubject, adminDateRange, adminPage, adminPageSize])

  // ─── Admin: score editing ───
  const handleAdminScoreChange = (recordId: string, value: string) => {
    setAdminEditMap((prev) => ({ ...prev, [recordId]: value }))
    setAdminDirtyIds((prev) => new Set(prev).add(recordId))
  }

  const handleAdminBatchSave = async () => {
    if (adminDirtyIds.size === 0) {
      message.info('没有需要保存的修改')
      return
    }
    const batchRecords = Array.from(adminDirtyIds).map((id) => ({
      id,
      assessment_result: adminEditMap[id] || '',
    }))
    setAdminSaving(true)
    try {
      await batchUpdateScores({ records: batchRecords })
      message.success(`成功保存 ${batchRecords.length} 条成绩`)
      setAdminDirtyIds(new Set())
      loadAdminData()
      loadAdminStats()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setAdminSaving(false)
    }
  }

  const handleExportEvaluation = async () => {
    if (!filterDept) {
      message.warning('请先选择部门')
      return
    }
    if (!filterSubject) {
      message.warning('请先选择培训主题')
      return
    }
    // 从当前已加载的记录中聚合培训信息
    const records = adminRecords
    const uniqueEmployees = [...new Set(records.map(r => r.employee_number))]
    const scores = records.filter(r => r.assessment_result).map(r => ({ name: r.employee_name || r.employee_number, result: r.assessment_result }))
    const excellentCount = scores.filter(s => Number(s.result) >= 90).length
    const qualifiedCount = scores.filter(s => Number(s.result) >= 60 && Number(s.result) < 90).length
    const unqualifiedCount = scores.filter(s => Number(s.result) < 60).length

    try {
      await exportTrainingEvaluationReport({
        department: filterDept,
        training_subject: filterSubject,
        training_date: adminDateRange ? adminDateRange[0] : (records[0]?.training_date || undefined),
        training_method: records[0]?.training_method || '',
        trainer_name: records[0]?.trainer || '',
        expected_count: uniqueEmployees.length,
        actual_count: uniqueEmployees.length,
        exam_count: scores.length,
        excellent_count: excellentCount,
        qualified_count: qualifiedCount,
        unqualified_count: unqualifiedCount,
      })
      message.success('评估表已导出')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
  }

  // ─── Employee: CRUD handlers ───
  const handlePrint = () => { window.print() }

  const handleExport = async () => {
    try {
      await exportTrainingLedger(employeeNumber)
      message.success('导出成功')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    }
  }

  const handleAdd = () => {
    const newRecord: TrainingLedgerRecord = {
      id: `new-${Date.now()}`,
      employee_number: employeeNumber,
      training_date: dayjs().format('YYYY-MM-DD'),
      training_subject: '',
      training_method: '',
      duration_hours: undefined,
      location: '',
      trainer: '',
      assessment_result: '',
      source_type: 'manual',
      remarks: '',
    }
    setRecords([newRecord, ...records])
    setEditingId(newRecord.id)
    setEditForm(newRecord)
  }

  const handleEdit = (record: TrainingLedgerRecord) => {
    setEditingId(record.id)
    setEditForm({ ...record })
  }

  const handleCancel = () => {
    setEditingId(null)
    setEditForm({})
    setRecords((prev) => prev.filter((r) => !r.id.startsWith('new-')))
  }

  const handleSave = async (record: TrainingLedgerRecord) => {
    if (!editForm.training_date || !editForm.training_subject) {
      message.warning('培训日期和培训课程不能为空')
      return
    }
    setSaving(true)
    try {
      const payload = {
        employee_number: employeeNumber,
        training_date: editForm.training_date!,
        training_subject: editForm.training_subject!,
        training_method: editForm.training_method || undefined,
        duration_hours: editForm.duration_hours || undefined,
        location: editForm.location || undefined,
        trainer: editForm.trainer || undefined,
        assessment_result: editForm.assessment_result || undefined,
        remarks: editForm.remarks || undefined,
      }

      if (record.id.startsWith('new-')) {
        const res = await createTrainingLedger(payload)
        setRecords((prev) => prev.map((r) => (r.id === record.id ? res.data : r)))
        message.success('创建成功')
      } else {
        const res = await updateTrainingLedger(record.id, payload)
        setRecords((prev) => prev.map((r) => (r.id === record.id ? res.data : r)))
        message.success('更新成功')
      }
      setEditingId(null)
      setEditForm({})
    } catch (err: any) {
      message.error(err.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: TrainingLedgerRecord) => {
    if (record.id.startsWith('new-')) {
      setRecords((prev) => prev.filter((r) => r.id !== record.id))
      setEditingId(null)
      return
    }
    try {
      await deleteTrainingLedger(record.id)
      setRecords((prev) => prev.filter((r) => r.id !== record.id))
      message.success('删除成功')
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const isEditing = (record: TrainingLedgerRecord) => editingId === record.id

  // ─── Employee view ───
  const displayRows = [...records]
  while (displayRows.length < 12) {
    displayRows.push({
      id: `blank-${displayRows.length}`,
      employee_number: employeeNumber,
      training_date: '',
      training_subject: '',
      source_type: 'manual',
    } as TrainingLedgerRecord)
  }

  // ══════════════════════════════════════════════════
  // Admin Mode
  // ══════════════════════════════════════════════════
  if (isAdminMode) {
    return (
      <div className="space-y-4">
        {/* 员工搜索入口 */}
        <Select
          showSearch
          placeholder="输入工号或姓名搜索员工，查看个人台账"
          value={undefined}
          style={{ width: 360 }}
          filterOption={false}
          onSearch={handleEmployeeSearch}
          onChange={(val) => { window.location.href = `/hr/training/ledger?employee_number=${val}` }}
          notFoundContent={searching ? <Spin size="small" /> : null}
          options={searchOptions}
          allowClear
        />

        {/* 筛选栏 */}
        <Card size="small">
          <Space wrap>
            <Select
              showSearch
              allowClear
              placeholder="部门筛选"
              value={filterDept}
              onChange={(v) => { setFilterDept(v); setFilterSubject(undefined); setAdminPage(1) }}
              options={departments.map((d) => ({ label: d, value: d }))}
              style={{ width: 180 }}
            />
            <Select
              showSearch
              allowClear
              placeholder="培训内容筛选"
              value={filterSubject}
              onChange={(v) => { setFilterSubject(v); setAdminPage(1) }}
              options={subjects.map((s) => ({ label: s, value: s }))}
              style={{ width: 240 }}
            />
            <DatePicker.RangePicker
              placeholder={['日期起', '日期止']}
              onChange={(dates) => {
                if (dates && dates[0] && dates[1]) {
                  setAdminDateRange([dates[0].format('YYYY-MM-DD'), dates[1].format('YYYY-MM-DD')])
                } else { setAdminDateRange(null) }
                setAdminPage(1)
              }}
            />
            <Button icon={<ReloadOutlined />} onClick={() => { loadAdminData(); loadAdminStats() }}>
              刷新
            </Button>
          </Space>
        </Card>

        {/* 统计卡片 */}
        {stats && (
          <Card size="small">
            <Row gutter={16}>
              <Col span={4}><Statistic title="总记录数" value={stats.total_count} /></Col>
              <Col span={4}><Statistic title="实到人数" value={stats.assessed_count} /></Col>
              <Col span={4}><Statistic title="合格人数" value={stats.qualified_count} valueStyle={{ color: '#3f8600' }} /></Col>
              <Col span={4}><Statistic title="不合格人数" value={stats.unqualified_count} valueStyle={{ color: stats.unqualified_count > 0 ? '#cf1322' : undefined }} /></Col>
              <Col span={4}><Statistic title="合格率" value={stats.pass_rate} /></Col>
              <Col span={4}><Statistic title="平均分" value={stats.avg_score ?? '-'} precision={1} /></Col>
            </Row>
          </Card>
        )}

        {/* 操作栏 */}
        <div className="flex justify-between items-center">
          <span className="text-gray-500 text-sm">
            共 {adminTotal} 条记录{adminDirtyIds.size > 0 ? `，${adminDirtyIds.size} 条已修改` : ''}
          </span>
          <Space>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleAdminBatchSave}
              loading={adminSaving} disabled={adminDirtyIds.size === 0}>
              批量保存成绩
            </Button>
            <Button icon={<ExportOutlined />} onClick={handleExportEvaluation} disabled={!filterDept}>
              导出效果评估表
            </Button>
          </Space>
        </div>

        {/* 台账表格 */}
        <Table
          dataSource={adminRecords}
          rowKey="id"
          loading={adminLoading}
          size="small"
          scroll={{ x: 1000 }}
          pagination={{
            current: adminPage,
            pageSize: adminPageSize,
            total: adminTotal,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: (p, ps) => { setAdminPage(p); setAdminPageSize(ps) },
            showTotal: (t) => `共 ${t} 条`,
          }}
          columns={[
            { title: '工号', dataIndex: 'employee_number', width: 90 },
            { title: '姓名', dataIndex: 'employee_name', width: 70 },
            { title: '部门', dataIndex: 'department', width: 100, ellipsis: true },
            { title: '培训日期', dataIndex: 'training_date', width: 100 },
            { title: '培训内容', dataIndex: 'training_subject', width: 180, ellipsis: true },
            { title: '培训方式', dataIndex: 'training_method', width: 80 },
            { title: '课时', dataIndex: 'duration_hours', width: 60, render: (v: number | null) => v ?? '' },
            { title: '培训师', dataIndex: 'trainer', width: 100, ellipsis: true },
            {
              title: '考核成绩', dataIndex: 'assessment_result', width: 120,
              render: (v: string | null, record: AdminRecord) => (
                <Input
                  size="small"
                  placeholder="成绩"
                  defaultValue={v || ''}
                  onChange={(e) => handleAdminScoreChange(record.id, e.target.value)}
                  style={adminDirtyIds.has(record.id) ? { borderColor: '#faad14' } : undefined}
                />
              ),
            },
            { title: '来源', dataIndex: 'source_type', width: 60, render: (v: string) => v === 'notification' ? '通知' : '手动' },
          ]}
        />
      </div>
    )
  }

  // ══════════════════════════════════════════════════
  // Employee Mode (原有逻辑)
  // ══════════════════════════════════════════════════
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" description="加载中..." />
      </div>
    )
  }

  if (!employee && employeeNumber) {
    return (
      <div className="space-y-4">
        <div className="flex flex-col items-center justify-center py-10 text-gray-400">
          <p>未找到工号为 {employeeNumber} 的员工，请重新搜索</p>
        </div>
        <div className="max-w-md mx-auto">
          <Select showSearch placeholder="输入工号或姓名搜索员工" style={{ width: '100%' }}
            value={undefined}
            filterOption={false}
            onSearch={handleEmployeeSearch}
            onChange={(val) => { window.location.href = `/hr/training/ledger?employee_number=${val}` }}
            notFoundContent={searching ? <Spin size="small" /> : null}
            options={searchOptions} />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 搜索员工 + 管理员入口 */}
      <div className="flex flex-wrap items-center gap-4">
        <Select
          showSearch
          placeholder="输入工号或姓名搜索员工"
          value={employeeNumber || undefined}
          style={{ width: 320 }}
          filterOption={false}
          onSearch={handleEmployeeSearch}
          onChange={(val) => { window.location.href = `/hr/training/ledger?employee_number=${val}` }}
          notFoundContent={searching ? '搜索中...' : null}
          options={searchOptions}
          allowClear
        />
      </div>

      <div className="no-print flex flex-wrap items-center gap-4">
        <Button icon={<PrinterOutlined />} onClick={handlePrint}>打印</Button>
        <Button icon={<ExportOutlined />} onClick={handleExport}>导出</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd} disabled={!!editingId}>
          添加培训记录
        </Button>
        <Space>
          <DatePicker placeholder="日期起" value={dateFrom ? dayjs(dateFrom) : null}
            onChange={(d) => setDateFrom(d ? d.format('YYYY-MM-DD') : null)} />
          <span>~</span>
          <DatePicker placeholder="日期止" value={dateTo ? dayjs(dateTo) : null}
            onChange={(d) => setDateTo(d ? d.format('YYYY-MM-DD') : null)} />
        </Space>
      </div>

      <div id="print-area" className="print-area">
        <Card className="training-ledger-preview" bordered={false}>
          <table className="w-full border-collapse text-sm" style={{ tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '10%' }} /><col style={{ width: '30%' }} /><col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} /><col style={{ width: '20%' }} /><col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
            </colgroup>
            <tbody>
              <tr><td colSpan={7} className="text-xs text-gray-500 text-right py-1">QR.SOP.PM.003/18（格式）P6/12</td></tr>
              <tr><td colSpan={7} className="text-center text-lg font-bold border border-gray-300 py-2">丽珠集团福州福兴医药有限公司</td></tr>
              <tr><td colSpan={7} className="text-center text-base font-semibold border border-gray-300 py-2">员工培训台账</td></tr>
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">姓　名</td>
                <td className="border border-gray-300 px-2 py-2 text-center">{employee?.name || ''}</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">性　别</td>
                <td className="border border-gray-300 px-2 py-2 text-center">{employee?.gender || ''}</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">工 作 卡 号</td>
                <td colSpan={2} className="border border-gray-300 px-2 py-2 text-center">{employee?.employee_number || ''}</td>
              </tr>
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">部　门</td>
                <td className="border border-gray-300 px-2 py-2 text-center">{employee?.department || ''}</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">岗 位/职 务</td>
                <td className="border border-gray-300 px-2 py-2 text-center">{employee?.position || ''}</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">入 厂 时 间</td>
                <td colSpan={2} className="border border-gray-300 px-2 py-2 text-center">{employee?.factory_entry_date || employee?.hire_date || ''}</td>
              </tr>
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">岗 位 变 动</td>
                <td colSpan={6} rowSpan={2} className="border border-gray-300 px-2 py-2 align-top">{employee?.transfer_history || '无'}</td>
              </tr>
              <tr><td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">记　录</td></tr>
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">年月日</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">培训课程</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">培训方式</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">课 时</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">培训单位/培训师</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">考核成绩</td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center no-print">操作</td>
              </tr>
              {displayRows.map((record) => {
                const editing = isEditing(record)
                const isBlank = record.id.startsWith('blank-')
                return (
                  <tr key={record.id}>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <DatePicker size="small" style={{ width: '100%' }}
                          value={editForm.training_date ? dayjs(editForm.training_date) : null}
                          onChange={(d) => setEditForm((prev) => ({ ...prev, training_date: d ? d.format('YYYY-MM-DD') : '' }))} />
                      ) : (<span className="px-1">{record.training_date || ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input size="small" value={editForm.training_subject || ''}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, training_subject: e.target.value }))} />
                      ) : (<span className="px-1">{record.training_subject || ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Select size="small" style={{ width: '100%' }} value={editForm.training_method || undefined}
                          onChange={(val) => setEditForm((prev) => ({ ...prev, training_method: val }))}
                          options={METHOD_OPTIONS.map((m) => ({ label: m, value: m }))} allowClear />
                      ) : (<span className="px-1">{record.training_method || ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input size="small" type="number" step={0.5} value={editForm.duration_hours ?? ''}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, duration_hours: e.target.value ? parseFloat(e.target.value) : undefined }))} />
                      ) : (<span className="px-1">{record.duration_hours ?? ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input size="small" value={editForm.trainer || ''}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, trainer: e.target.value }))} />
                      ) : (<span className="px-1">{record.trainer || ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input size="small" value={editForm.assessment_result || ''}
                          onChange={(e) => setEditForm((prev) => ({ ...prev, assessment_result: e.target.value }))} />
                      ) : (<span className="px-1">{record.assessment_result || ''}</span>)}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 text-center no-print">
                      {isBlank ? null : editing ? (
                        <Space size="small">
                          <Button type="primary" size="small" icon={<SaveOutlined />} loading={saving} onClick={() => handleSave(record)} />
                          <Button size="small" onClick={handleCancel}>取消</Button>
                        </Space>
                      ) : (
                        <Space size="small">
                          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
                          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record)}>
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </Space>
                      )}
                    </td>
                  </tr>
                )
              })}
              <tr><td colSpan={7} className="border border-gray-300 px-2 py-2 text-xs text-gray-500">备注：笔试考核设置为满分100分，考试合格线为80分。</td></tr>
            </tbody>
          </table>
        </Card>
      </div>

      <style jsx global>{`
        @media print { body * { visibility: hidden; } #print-area, #print-area * { visibility: visible; } #print-area { position: absolute; left: 0; top: 0; width: 100%; } .no-print { display: none !important; } .ant-card { border: none !important; box-shadow: none !important; } .ant-card-body { padding: 0 !important; } }
      `}</style>
    </div>
  )
}

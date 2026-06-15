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
} from 'antd'
import {
  PrinterOutlined,
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
  EditOutlined,
  ExportOutlined,
} from '@ant-design/icons'
import { exportTrainingLedger } from '@/lib/api/hr'
import dayjs from 'dayjs'
import { Employee, TrainingLedgerRecord } from '@/types/hr'
import {
  fetchEmployeeByNumber,
  fetchTrainingLedgers,
  createTrainingLedger,
  updateTrainingLedger,
  deleteTrainingLedger,
} from '@/lib/api/hr'

interface TrainingLedgerClientProps {
  employeeNumber: string
}

const METHOD_OPTIONS = ['面授', '函授', '远程教育', '自学', '其他']

export default function TrainingLedgerClient({
  employeeNumber,
}: TrainingLedgerClientProps) {
  const [employee, setEmployee] = useState<Employee | null>(null)
  const [records, setRecords] = useState<TrainingLedgerRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [dateFrom, setDateFrom] = useState<string | null>(null)
  const [dateTo, setDateTo] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Partial<TrainingLedgerRecord>>({})
  const [saving, setSaving] = useState(false)

  const loadData = async () => {
    setLoading(true)
    try {
      const empRes = await fetchEmployeeByNumber(employeeNumber)
      setEmployee(empRes.data)

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
    loadData()
  }, [employeeNumber, dateFrom, dateTo])

  const handlePrint = () => {
    window.print()
  }

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
    // Remove unsaved new rows
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

  // Pad to at least 12 visible rows
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

  const isEditing = (record: TrainingLedgerRecord) => editingId === record.id

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (!employee) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <p>未找到工号为 {employeeNumber} 的员工信息</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 控制栏 — 打印时隐藏 */}
      <div className="no-print flex flex-wrap items-center gap-4">
        <Button icon={<PrinterOutlined />} onClick={handlePrint}>
          打印
        </Button>
        <Button icon={<ExportOutlined />} onClick={handleExport}>
          导出
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleAdd}
          disabled={!!editingId}
        >
          添加培训记录
        </Button>
        <Space>
          <DatePicker
            placeholder="日期起"
            value={dateFrom ? dayjs(dateFrom) : null}
            onChange={(d) => setDateFrom(d ? d.format('YYYY-MM-DD') : null)}
          />
          <span>~</span>
          <DatePicker
            placeholder="日期止"
            value={dateTo ? dayjs(dateTo) : null}
            onChange={(d) => setDateTo(d ? d.format('YYYY-MM-DD') : null)}
          />
        </Space>
      </div>

      <div id="print-area" className="print-area">
        <Card className="training-ledger-preview" bordered={false}>
          <table className="w-full border-collapse text-sm" style={{ tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '10%' }} />
              <col style={{ width: '30%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '20%' }} />
              <col style={{ width: '10%' }} />
              <col style={{ width: '10%' }} />
            </colgroup>
            <tbody>
              {/* 第1行: 格式编号 */}
              <tr>
                <td colSpan={7} className="text-xs text-gray-500 text-right py-1">
                  QR.SOP.PM.003/18（格式）　P6/12
                </td>
              </tr>
              {/* 第2行: 公司名 */}
              <tr>
                <td
                  colSpan={7}
                  className="text-center text-lg font-bold border border-gray-300 py-2"
                >
                  丽珠集团新北江制药股份有限公司
                </td>
              </tr>
              {/* 第3行: 标题 */}
              <tr>
                <td
                  colSpan={7}
                  className="text-center text-base font-semibold border border-gray-300 py-2"
                >
                  员工培训台账
                </td>
              </tr>
              {/* 第4行: 姓名 性别 工作卡号 */}
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  姓　名
                </td>
                <td className="border border-gray-300 px-2 py-2 text-center">
                  {employee.name}
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  性　别
                </td>
                <td className="border border-gray-300 px-2 py-2 text-center">
                  {employee.gender || ''}
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  工 作 卡 号
                </td>
                <td
                  colSpan={2}
                  className="border border-gray-300 px-2 py-2 text-center"
                >
                  {employee.employee_number}
                </td>
              </tr>
              {/* 第5行: 部门 岗位/职务 入厂时间 */}
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  部　门
                </td>
                <td className="border border-gray-300 px-2 py-2 text-center">
                  {employee.department}
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  岗 位/职 务
                </td>
                <td className="border border-gray-300 px-2 py-2 text-center">
                  {employee.position}
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  入 厂 时 间
                </td>
                <td
                  colSpan={2}
                  className="border border-gray-300 px-2 py-2 text-center"
                >
                  {employee.factory_entry_date || employee.hire_date || ''}
                </td>
              </tr>
              {/* 第6-7行: 岗位变动记录 */}
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  岗 位 变 动
                </td>
                <td
                  colSpan={6}
                  rowSpan={2}
                  className="border border-gray-300 px-2 py-2 align-top"
                >
                  {employee.transfer_history || '无'}
                </td>
              </tr>
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  记　录
                </td>
              </tr>
              {/* 表头 */}
              <tr>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  年月日
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训课程
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训方式
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  课 时
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  培训单位/培训师
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center">
                  考核成绩
                </td>
                <td className="bg-gray-50 font-medium border border-gray-300 px-2 py-2 text-center no-print">
                  操作
                </td>
              </tr>
              {/* 数据行 */}
              {displayRows.map((record) => {
                const editing = isEditing(record)
                const isBlank = record.id.startsWith('blank-')
                return (
                  <tr key={record.id}>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <DatePicker
                          size="small"
                          style={{ width: '100%' }}
                          value={editForm.training_date ? dayjs(editForm.training_date) : null}
                          onChange={(d) =>
                            setEditForm((prev) => ({
                              ...prev,
                              training_date: d ? d.format('YYYY-MM-DD') : '',
                            }))
                          }
                        />
                      ) : (
                        <span className="px-1">{record.training_date || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.training_subject || ''}
                          onChange={(e) =>
                            setEditForm((prev) => ({
                              ...prev,
                              training_subject: e.target.value,
                            }))
                          }
                        />
                      ) : (
                        <span className="px-1">{record.training_subject || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Select
                          size="small"
                          style={{ width: '100%' }}
                          value={editForm.training_method || undefined}
                          onChange={(val) =>
                            setEditForm((prev) => ({
                              ...prev,
                              training_method: val,
                            }))
                          }
                          options={METHOD_OPTIONS.map((m) => ({
                            label: m,
                            value: m,
                          }))}
                          allowClear
                        />
                      ) : (
                        <span className="px-1">{record.training_method || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input
                          size="small"
                          type="number"
                          step={0.5}
                          value={editForm.duration_hours ?? ''}
                          onChange={(e) =>
                            setEditForm((prev) => ({
                              ...prev,
                              duration_hours: e.target.value
                                ? parseFloat(e.target.value)
                                : undefined,
                            }))
                          }
                        />
                      ) : (
                        <span className="px-1">{
                          record.duration_hours ?? ''
                        }</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.trainer || ''}
                          onChange={(e) =>
                            setEditForm((prev) => ({
                              ...prev,
                              trainer: e.target.value,
                            }))
                          }
                        />
                      ) : (
                        <span className="px-1">{record.trainer || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1">
                      {editing ? (
                        <Input
                          size="small"
                          value={editForm.assessment_result || ''}
                          onChange={(e) =>
                            setEditForm((prev) => ({
                              ...prev,
                              assessment_result: e.target.value,
                            }))
                          }
                        />
                      ) : (
                        <span className="px-1">{record.assessment_result || ''}</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-1 py-1 text-center no-print">
                      {isBlank ? null : editing ? (
                        <Space size="small">
                          <Button
                            type="primary"
                            size="small"
                            icon={<SaveOutlined />}
                            loading={saving}
                            onClick={() => handleSave(record)}
                          />
                          <Button
                            size="small"
                            onClick={handleCancel}
                          >
                            取消
                          </Button>
                        </Space>
                      ) : (
                        <Space size="small">
                          <Button
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() => handleEdit(record)}
                          />
                          <Popconfirm
                            title="确认删除？"
                            onConfirm={() => handleDelete(record)}
                          >
                            <Button
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                            />
                          </Popconfirm>
                        </Space>
                      )}
                    </td>
                  </tr>
                )
              })}
              {/* 备注 */}
              <tr>
                <td
                  colSpan={7}
                  className="border border-gray-300 px-2 py-2 text-xs text-gray-500"
                >
                  备注：笔试考核设置为满分100分，考试合格线为80分。
                </td>
              </tr>
            </tbody>
          </table>
        </Card>
      </div>

      <style jsx global>{`
        @media print {
          body * {
            visibility: hidden;
          }
          #print-area,
          #print-area * {
            visibility: visible;
          }
          #print-area {
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
          }
          .no-print {
            display: none !important;
          }
          .ant-card {
            border: none !important;
            box-shadow: none !important;
          }
          .ant-card-body {
            padding: 0 !important;
          }
        }
      `}</style>
    </div>
  )
}

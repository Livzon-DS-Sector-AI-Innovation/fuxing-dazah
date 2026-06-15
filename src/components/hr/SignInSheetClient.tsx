'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Select,
  Space,
  TimePicker,
  message,
} from 'antd'
import { FileTextOutlined, DownloadOutlined, PrinterOutlined, EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Employee } from '@/types/hr'
import { fetchDepartments, fetchEmployees, generateTrainingSignInSheet } from '@/lib/api/hr'

export default function SignInSheetClient() {
  const [form] = Form.useForm()
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedDepts, setSelectedDepts] = useState<string[]>([])
  const [showPreview, setShowPreview] = useState(false)

  useEffect(() => {
    fetchDepartments({ page_size: 100 }).then((res) => {
      const list = (res.data || []).map((d: any) => ({ value: d.name, label: d.name }))
      setDepartments(list)
    })
    setLoading(true)
    fetchEmployees({ page_size: 200 })
      .then((res) => {
        setEmployees(res.data || [])
      })
      .finally(() => setLoading(false))
  }, [])

  const filteredEmployees = useMemo(() => {
    if (selectedDepts.length === 0) return []
    return employees.filter((e) => selectedDepts.includes(e.department))
  }, [selectedDepts, employees])

  const handleDeptChange = (values: string[]) => {
    setSelectedDepts(values)
    const names = employees
      .filter((e) => values.includes(e.department))
      .map((e) => e.name)
    form.setFieldsValue({ employee_names: names })
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const employeeNames: string[] = values.employee_names || []
    if (employeeNames.length === 0) {
      message.warning('请至少选择一名受训人员')
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        training_date: values.training_date.format('YYYY-MM-DD'),
        training_time_start: values.training_time
          ? dayjs(values.training_time[0]).format('HH:mm')
          : undefined,
        training_time_end: values.training_time
          ? dayjs(values.training_time[1]).format('HH:mm')
          : undefined,
        department: selectedDepts.join('、'),
        topic: values.topic,
        instructor: values.instructor,
        location: values.location,
        training_method: values.training_method,
        employee_names: employeeNames,
        remarks: values.remarks,
      }
      await generateTrainingSignInSheet(payload)
      message.success('培训签到表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handlePreview = () => {
    const values = form.getFieldsValue()
    const names: string[] = values.employee_names || []
    if (names.length === 0) {
      message.warning('请至少选择一名受训人员')
      return
    }
    setShowPreview(true)
  }

  const handlePrint = () => {
    const values = form.getFieldsValue()
    const names: string[] = values.employee_names || []
    if (names.length === 0) {
      message.warning('请至少选择一名受训人员')
      return
    }
    if (!showPreview) {
      setShowPreview(true)
    }
    setTimeout(() => window.print(), 100)
  }

  const formValues = form.getFieldsValue()
  const employeeNames: string[] = formValues?.employee_names || []

  return (
    <div className="space-y-6">
      <Card title="填写培训信息">
        <Form form={form} layout="vertical" className="max-w-4xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item
              name="training_date"
              label="培训日期"
              rules={[{ required: true, message: '请选择培训日期' }]}
            >
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>

            <Form.Item name="training_time" label="培训时间">
              <TimePicker.RangePicker className="w-full" format="HH:mm" />
            </Form.Item>

            <Form.Item
              name="departments"
              label="受训部门"
              rules={[{ required: true, message: '请选择受训部门' }]}
            >
              <Select
                mode="multiple"
                placeholder="选择部门（可多选）"
                options={departments}
                onChange={handleDeptChange}
                className="w-full"
              />
            </Form.Item>

            <Form.Item
              name="topic"
              label="培训题目或内容摘要"
              rules={[{ required: true, message: '请填写培训题目' }]}
            >
              <Input.TextArea rows={2} placeholder="请输入培训题目或内容摘要" />
            </Form.Item>

            <Form.Item name="instructor" label="授课人">
              <Input placeholder="请输入授课人" />
            </Form.Item>

            <Form.Item name="location" label="培训地点">
              <Input placeholder="请输入培训地点" />
            </Form.Item>

            <Form.Item name="training_method" label="培训方式">
              <Select
                placeholder="选择培训方式"
                allowClear
                options={[
                  { value: '面授', label: '面授' },
                  { value: '函授', label: '函授' },
                  { value: '远程教育', label: '远程教育' },
                  { value: '自学', label: '自学' },
                  { value: '其他', label: '其他' },
                ]}
              />
            </Form.Item>

            <Form.Item name="remarks" label="备注" className="md:col-span-2">
              <Input.TextArea rows={2} placeholder="请输入备注内容" />
            </Form.Item>
          </div>

          <Form.Item label="应出席受训人员">
            <div className="flex items-center gap-4 mb-2">
              <span className="text-sm text-gray-500">
                已选择 {employeeNames.length} 人（按部门自动填充）
              </span>
            </div>
            <Form.Item name="employee_names" noStyle>
              <Select
                mode="multiple"
                placeholder="选择受训人员"
                options={filteredEmployees.map((e) => ({
                  value: e.name,
                  label: `${e.name} (${e.employee_number})`,
                }))}
                loading={loading}
                className="w-full"
              />
            </Form.Item>
          </Form.Item>

          <Form.Item>
            <Space>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={handleSubmit}
                loading={submitting}
              >
                生成并导出Excel
              </Button>
              <Button icon={<PrinterOutlined />} onClick={handlePrint}>
                打印预览
              </Button>
              <Button icon={<EyeOutlined />} onClick={handlePreview}>
                预览
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* Print preview area */}
      {showPreview && (
        <div id="print-area">
          <Card
            title={
              <div className="text-center">
                <div className="text-xs text-gray-500 mb-1">
                  QR.SOP.PM.003/18（格式） P3/12
                </div>
                <div className="text-lg font-bold">
                  丽珠集团新北江制药股份有限公司
                </div>
                <div className="text-base font-semibold mt-1">培训签到表</div>
              </div>
            }
          >
            <div className="mb-2 text-sm">
              <div className="flex gap-8 mb-1">
                <span className="min-w-[200px] border-b border-gray-800 pb-0.5">
                  <strong>培训日期：</strong>
                  {formValues.training_date
                    ? formValues.training_date.format('YYYY年MM月DD日')
                    : '<span className="text-gray-400">______年____月____日</span>'}
                </span>
              </div>
              <div className="flex gap-8 mb-1">
                <span className="min-w-[240px] border-b border-gray-800 pb-0.5">
                  <strong>受训部门：</strong>
                  {selectedDepts.join('、') || '<span className="text-gray-400">________________</span>'}
                </span>
                <span className="min-w-[240px] border-b border-gray-800 pb-0.5">
                  <strong>培训方式：</strong>
                  {formValues.training_method || '<span className="text-gray-400">□面授 □函授 □远程教育 □自学 □其他</span>'}
                </span>
              </div>
              <div className="flex gap-8 mb-1">
                <span className="min-w-[200px] border-b border-gray-800 pb-0.5">
                  <strong>应受训人数：</strong>
                  {employeeNames.length}<span className="text-gray-400">人</span>
                </span>
                <span className="min-w-[240px] border-b border-gray-800 pb-0.5">
                  <strong>实际受训人数合计：</strong>
                  <span className="text-gray-400">______人</span>
                </span>
              </div>
              <div className="flex gap-8 mb-1">
                <span className="min-w-[240px] border-b border-gray-800 pb-0.5">
                  <strong>培训时间：</strong>
                  {formValues.training_time
                    ? `${dayjs(formValues.training_time[0]).format('HH:mm')} ~ ${dayjs(formValues.training_time[1]).format('HH:mm')}`
                    : '<span className="text-gray-400">______ ~ ______</span>'}
                </span>
              </div>
              <div className="flex gap-8 mb-1">
                <span className="min-w-[300px] border-b border-gray-800 pb-0.5">
                  <strong>培训地点：</strong>
                  {formValues.location || '<span className="text-gray-400">________________</span>'}
                </span>
                <span className="min-w-[200px] border-b border-gray-800 pb-0.5">
                  <strong>授课人：</strong>
                  {formValues.instructor || '<span className="text-gray-400">________________</span>'}
                </span>
              </div>
              <div className="flex gap-8">
                <span className="flex-1 border-b border-gray-800 pb-0.5">
                  <strong>培训题目或内容概要：</strong>
                  {formValues.topic || '<span className="text-gray-400">________________</span>'}
                </span>
              </div>
              {formValues.remarks && (
                <div className="flex gap-8 mt-1">
                  <span className="flex-1 border-b border-gray-800 pb-0.5">
                    <strong>备注：</strong>
                    {formValues.remarks}
                  </span>
                </div>
              )}
            </div>

            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border border-gray-300 bg-gray-50">
                  <th className="border border-gray-300 px-2 py-1">应出席受训人员姓名</th>
                  <th className="border border-gray-300 px-2 py-1 w-24">受训人员签到</th>
                  <th className="border border-gray-300 px-2 py-1">应出席受训人员姓名</th>
                  <th className="border border-gray-300 px-2 py-1 w-24">受训人员签到</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 15 }, (_, i) => {
                  const leftIdx = i
                  const rightIdx = i + 15
                  return (
                    <tr key={i} className="border border-gray-300">
                      <td className="border border-gray-300 px-2 py-1">
                        {employeeNames[leftIdx] || ''}
                      </td>
                      <td className="border border-gray-300 px-2 py-1 h-8"></td>
                      <td className="border border-gray-300 px-2 py-1">
                        {employeeNames[rightIdx] || ''}
                      </td>
                      <td className="border border-gray-300 px-2 py-1 h-8"></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            <div className="mt-2 text-sm text-gray-500">
              备注：（未参加培训人员处理方式）
            </div>
          </Card>
        </div>
      )}

      {!showPreview && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>点击预览按钮查看培训签到表</p>
        </div>
      )}

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
        }
      `}</style>
    </div>
  )
}

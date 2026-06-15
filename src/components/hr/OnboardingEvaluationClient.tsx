'use client'

import { useState } from 'react'
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Radio,
  Select,
  Space,
  message,
} from 'antd'
import {
  DownloadOutlined,
  PrinterOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { generateOnboardingEvaluation } from '@/lib/api/hr'

export default function OnboardingEvaluationClient() {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const handleExport = async () => {
    const values = await form.validateFields()

    setSubmitting(true)
    try {
      const payload = {
        employee_name: values.employee_name,
        gender: values.gender,
        department_position: values.department_position,
        hire_date: values.hire_date
          ? values.hire_date.format('YYYY-MM-DD')
          : undefined,
        training_period: values.training_period,
        regularization_date: values.regularization_date
          ? values.regularization_date.format('YYYY-MM-DD')
          : undefined,
        assessment_contents: values.assessment_contents || [],
        comprehensive_comment: values.comprehensive_comment,
        is_qualified:
          values.is_qualified === true
            ? true
            : values.is_qualified === false
              ? false
              : undefined,
        assigned_position: values.assigned_position,
        assessment_method: values.assessment_method,
        dept_manager_signature: values.dept_manager_signature,
        signature_date: values.signature_date
          ? values.signature_date.format('YYYY-MM-DD')
          : undefined,
        remarks: values.remarks,
        dept_manager_agree:
          values.dept_manager_agree === true
            ? true
            : values.dept_manager_agree === false
              ? false
              : undefined,
        hr_manager_agree:
          values.hr_manager_agree === true
            ? true
            : values.hr_manager_agree === false
              ? false
              : undefined,
        qa_manager_agree:
          values.qa_manager_agree === true
            ? true
            : values.qa_manager_agree === false
              ? false
              : undefined,
        dept_manager: values.dept_manager,
        hr_manager: values.hr_manager,
        qa_manager: values.qa_manager,
        approval_date: values.approval_date
          ? values.approval_date.format('YYYY-MM-DD')
          : undefined,
      }
      await generateOnboardingEvaluation(payload)
      message.success('员工上岗评估表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handlePrint = () => {
    const values = form.getFieldsValue()
    if (!values.employee_name) {
      message.warning('请填写员工姓名')
      return
    }
    window.print()
  }

  const formValues = form.getFieldsValue()
  const nameValue = formValues?.employee_name || ''
  const genderValue = formValues?.gender || ''
  const deptPosValue = formValues?.department_position || ''
  const hireDateValue = formValues?.hire_date
  const trainingPeriodValue = formValues?.training_period || ''
  const regDateValue = formValues?.regularization_date
  const contents: string[] = formValues?.assessment_contents || []
  const commentValue = formValues?.comprehensive_comment || ''
  const isQualifiedValue = formValues?.is_qualified
  const assignedPosValue = formValues?.assigned_position || ''
  const methodValue = formValues?.assessment_method || ''
  const sigValue = formValues?.dept_manager_signature || ''
  const sigDateValue = formValues?.signature_date
  const remarksValue = formValues?.remarks || ''
  const deptMgrAgree = formValues?.dept_manager_agree
  const hrMgrAgree = formValues?.hr_manager_agree
  const qaMgrAgree = formValues?.qa_manager_agree
  const deptMgrValue = formValues?.dept_manager || ''
  const hrMgrValue = formValues?.hr_manager || ''
  const qaMgrValue = formValues?.qa_manager || ''
  const appDateValue = formValues?.approval_date

  const hireDateStr = hireDateValue
    ? hireDateValue.format('YYYY-MM-DD')
    : ''
  const regDateStr = regDateValue
    ? regDateValue.format('YYYY-MM-DD')
    : ''
  const sigDateStr = sigDateValue
    ? sigDateValue.format('YYYY年MM月DD日')
    : ''
  const appDateStr = appDateValue
    ? appDateValue.format('YYYY-MM-DD')
    : ''

  const hasBasicInfo = !!nameValue

  return (
    <div className="space-y-6" style={{ '--preview-border': '1px solid #1f2937' } as React.CSSProperties}>
      <Card title="填写员工上岗评估信息">
        <Form form={form} layout="vertical" className="max-w-4xl">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item
              name="employee_name"
              label="员工姓名"
              rules={[{ required: true, message: '请填写员工姓名' }]}
            >
              <Input placeholder="请输入员工姓名" />
            </Form.Item>

            <Form.Item name="gender" label="性别">
              <Select
                placeholder="选择性别"
                allowClear
                options={[
                  { value: '男', label: '男' },
                  { value: '女', label: '女' },
                ]}
              />
            </Form.Item>

            <Form.Item name="department_position" label="所在部门/岗位">
              <Input placeholder="如：人事行政部/人事行政专员" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="hire_date" label="入厂时间">
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>

            <Form.Item name="training_period" label="培训/考核期">
              <Input placeholder="如：2024.01.01-2024.03.01" />
            </Form.Item>

            <Form.Item name="regularization_date" label="转正时间">
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>
          </div>

          <div className="font-bold mb-2 border-b border-gray-300 pb-1">
            上岗培训期内考核内容、培训内容和结果
          </div>
          {Array.from({ length: 6 }, (_, i) => (
            <Form.Item key={i} name={['assessment_contents', i]} noStyle>
              <Input
                className="mb-2"
                placeholder={`考核内容 ${i + 1}`}
              />
            </Form.Item>
          ))}

          <Form.Item name="comprehensive_comment" label="培训/考核期综合评语">
            <Input.TextArea
              rows={3}
              placeholder="请输入综合评语"
            />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item name="is_qualified" label="是否同意上岗">
              <Radio.Group>
                <Radio value={true}>同意上岗</Radio>
                <Radio value={false}>不同意上岗</Radio>
              </Radio.Group>
            </Form.Item>

            <Form.Item name="assigned_position" label="担任岗位">
              <Input placeholder="如：人事行政专员" />
            </Form.Item>
          </div>

          <Form.Item name="assessment_method" label="考核方式">
            <Select
              placeholder="选择考核方式"
              allowClear
              options={[
                { value: '理论', label: '理论' },
                { value: '实操', label: '实操' },
                { value: '现场', label: '现场' },
              ]}
            />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item
              name="dept_manager_signature"
              label="部门负责人签名"
            >
              <Input placeholder="请输入签名" />
            </Form.Item>

            <Form.Item name="signature_date" label="签名日期">
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>
          </div>

          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>

          <div className="font-bold mb-2 border-b border-gray-300 pb-1">
            上岗考核审批
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="dept_manager_agree" label="部门负责人">
              <Radio.Group>
                <Radio value={true}>同意</Radio>
                <Radio value={false}>不同意</Radio>
              </Radio.Group>
            </Form.Item>

            <Form.Item name="hr_manager_agree" label="人事行政部负责人">
              <Radio.Group>
                <Radio value={true}>同意</Radio>
                <Radio value={false}>不同意</Radio>
              </Radio.Group>
            </Form.Item>

            <Form.Item name="qa_manager_agree" label="质量管理负责人">
              <Radio.Group>
                <Radio value={true}>同意</Radio>
                <Radio value={false}>不同意</Radio>
              </Radio.Group>
            </Form.Item>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="dept_manager" label="部门负责人姓名">
              <Input placeholder="姓名" />
            </Form.Item>

            <Form.Item name="hr_manager" label="人事行政部负责人姓名">
              <Input placeholder="姓名" />
            </Form.Item>

            <Form.Item name="qa_manager" label="质量管理负责人姓名">
              <Input placeholder="姓名" />
            </Form.Item>
          </div>

          <Form.Item name="approval_date" label="审批日期">
            <DatePicker className="w-full" placeholder="选择日期" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={handleExport}
                loading={submitting}
              >
                生成并导出Excel
              </Button>
              <Button icon={<PrinterOutlined />} onClick={handlePrint}>
                打印预览
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      {/* Print preview area */}
      {hasBasicInfo && (
        <div id="print-area">
          <Card>
            <div className="max-w-3xl mx-auto p-8 text-sm leading-relaxed">
              <div className="text-xs text-gray-500 mb-1">
                QR.SOP.PM.003/18（格式） P9/12
              </div>
              <h2 className="text-center text-lg font-bold mb-1">
                丽珠集团新北江制药股份有限公司
              </h2>
              <h2 className="text-center text-xl font-bold mb-6">
                员工上岗评估表
              </h2>

              {/* 统一的表格 */}
              <table
                className="w-full text-sm"
                style={{ borderCollapse: 'collapse' }}
              >
                <tbody>
                  {/* R4-R5 基本信息 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="w-16 bg-gray-50 font-bold text-center"
                    >
                      姓名
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="w-24 text-center"
                    >
                      {nameValue}
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="w-16 bg-gray-50 font-bold text-center"
                    >
                      性别
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="w-24 text-center"
                    >
                      {genderValue}
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="w-24 bg-gray-50 font-bold text-center"
                    >
                      所在部门/岗位
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center"
                    >
                      {deptPosValue}
                    </td>
                  </tr>
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="bg-gray-50 font-bold text-center"
                    >
                      入厂时间
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center"
                    >
                      {hireDateStr}
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="bg-gray-50 font-bold text-center"
                    >
                      培训/考核期
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center"
                    >
                      {trainingPeriodValue}
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="bg-gray-50 font-bold text-center"
                    >
                      转正时间
                    </td>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center"
                    >
                      {regDateStr}
                    </td>
                  </tr>

                  {/* R6 标题 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center font-bold bg-gray-50"
                      colSpan={6}
                    >
                      上岗培训期内考核内容、培训内容和结果
                    </td>
                  </tr>

                  {/* R7-R12 内容 */}
                  {Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <td
                        style={{
                          border: '1px solid #1f2937',
                          padding: '8px',
                          height: '28px',
                        }}
                        colSpan={6}
                      >
                        {contents[i] || ''}
                      </td>
                    </tr>
                  ))}

                  {/* R13 综合评语标题 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="font-bold bg-gray-50"
                      colSpan={6}
                    >
                      培训/考核期综合评语：
                    </td>
                  </tr>

                  {/* R14 评语内容 */}
                  <tr>
                    <td
                      style={{
                        border: '1px solid #1f2937',
                        padding: '8px',
                        height: '48px',
                      }}
                      colSpan={6}
                    >
                      {commentValue}
                    </td>
                  </tr>
n                  {/* R15 同意上岗 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      colSpan={6}
                    >
                      {isQualifiedValue === true ? '☑' : '□'}
                      经考核该员工培训期表现优秀/确认，同意该员工正式上岗，担任
                      <span
                        style={{
                          borderBottom: '1px solid #1f2937',
                          padding: '0 8px',
                          display: 'inline-block',
                          minWidth: '60px',
                        }}
                      >
                        {assignedPosValue}
                      </span>
                      岗位。
                    </td>
                  </tr>

                  {/* R16 不同意上岗 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      colSpan={6}
                    >
                      {isQualifiedValue === false ? '☑' : '□'}
                      经考核该员工培训期内表现不符合此岗位要求，不准上岗。
                    </td>
                  </tr>

                  {/* R17 考核方式 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      colSpan={6}
                    >
                      考核方式：
                      {methodValue === '理论'
                        ? '☑理论 □实操 □现场'
                        : methodValue === '实操'
                          ? '□理论 ☑实操 □现场'
                          : methodValue === '现场'
                            ? '□理论 □实操 ☑现场'
                            : '□理论 □实操 □现场'}
                    </td>
                  </tr>

                  {/* R18 签名 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      colSpan={6}
                    >
                      <div className="flex justify-between">
                        <span>
                          部门负责人签名：
                          <span
                            style={{
                              borderBottom: '1px solid #1f2937',
                              padding: '0 8px',
                              display: 'inline-block',
                              minWidth: '80px',
                            }}
                          >
                            {sigValue}
                          </span>
                        </span>
                        <span>
                          日期：
                          <span
                            style={{
                              borderBottom: '1px solid #1f2937',
                              padding: '0 8px',
                              display: 'inline-block',
                              minWidth: '100px',
                            }}
                          >
                            {sigDateStr}
                          </span>
                        </span>
                      </div>
                    </td>
                  </tr>

                  {/* R19 备注 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      colSpan={6}
                    >
                      备注：
                      {remarksValue || '培训期延长或转岗，由部门主管决定。'}
                    </td>
                  </tr>

                  {/* R20 上岗考核审批标题 */}
                  <tr>
                    <td
                      style={{ border: '1px solid #1f2937', padding: '8px' }}
                      className="text-center font-bold bg-gray-50"
                      colSpan={6}
                    >
                      上岗考核审批
                    </td>
                  </tr>

                  {/* R21-R23 审批 */}
                  {[
                    {
                      title: '部门负责人',
                      name: deptMgrValue,
                      agree: deptMgrAgree,
                    },
                    {
                      title: '人事行政部负责人',
                      name: hrMgrValue,
                      agree: hrMgrAgree,
                    },
                    {
                      title: '质量管理负责人',
                      name: qaMgrValue,
                      agree: qaMgrAgree,
                    },
                  ].map((item, i) => (
                    <tr key={i}>
                      <td
                        style={{
                          border: '1px solid #1f2937',
                          padding: '8px',
                          width: '128px',
                        }}
                        className="text-center"
                      >
                        {item.agree === true
                          ? '☑同意  □不同意'
                          : item.agree === false
                            ? '□同意  ☑不同意'
                            : '□同意  □不同意'}
                      </td>
                      <td
                        style={{
                          border: '1px solid #1f2937',
                          padding: '8px',
                          width: '128px',
                        }}
                        className="text-center font-bold bg-gray-50"
                        colSpan={2}
                      >
                        {item.title}
                      </td>
                      <td
                        style={{
                          border: '1px solid #1f2937',
                          padding: '8px',
                          width: '128px',
                        }}
                        className="text-center"
                      >
                        {item.name}
                      </td>
                      <td
                        style={{
                          border: '1px solid #1f2937',
                          padding: '8px',
                          width: '64px',
                        }}
                        className="text-center font-bold bg-gray-50"
                      >
                        日期
                      </td>
                      <td
                        style={{ border: '1px solid #1f2937', padding: '8px' }}
                        className="text-center"
                      >
                        {appDateStr}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {!hasBasicInfo && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>请填写员工基本信息后预览</p>
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

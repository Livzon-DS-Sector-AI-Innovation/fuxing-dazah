'use client'

import { useState } from 'react'
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Space,
  TimePicker,
  message,
} from 'antd'
import {
  DownloadOutlined,
  PrinterOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { generateTrainingEvaluation } from '@/lib/api/hr'

export default function TrainingEvaluationClient() {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const handleExport = async () => {
    const values = await form.validateFields()

    setSubmitting(true)
    try {
      const payload = {
        subject: values.subject,
        training_date: values.training_date
          ? values.training_date.format('YYYY-MM-DD')
          : undefined,
        training_time_start: values.training_time
          ? dayjs(values.training_time[0]).format('HH:mm')
          : undefined,
        training_time_end: values.training_time
          ? dayjs(values.training_time[1]).format('HH:mm')
          : undefined,
        duration_hours: values.duration_hours,
        training_method: values.training_method,
        is_exam: values.is_exam === true,
        trainer_type: values.trainer_type,
        expected_count: values.expected_count,
        actual_count: values.actual_count,
        absent_count: values.absent_count,
        textbook: values.textbook,
        makeup_training:
          values.makeup_training === true
            ? true
            : values.makeup_training === false
              ? false
              : undefined,
        assessment_method: values.assessment_method,
        pass_count: values.pass_count,
        fail_count: values.fail_count,
        absent_exam_count: values.absent_exam_count,
        absent_exam_handling: values.absent_exam_handling,
        excellent_count: values.excellent_count,
        qualified_count: values.qualified_count,
        unqualified_count: values.unqualified_count,
        evaluation_conclusion: values.evaluation_conclusion,
        organizer: values.organizer,
        organizer_date: values.organizer_date
          ? values.organizer_date.format('YYYY-MM-DD')
          : undefined,
        remarks: values.remarks,
      }
      await generateTrainingEvaluation(payload)
      message.success('培训效果评估表已生成')
    } catch (err: any) {
      message.error(err.message || '生成失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handlePrint = () => {
    const values = form.getFieldsValue()
    if (!values.subject) {
      message.warning('请填写培训主题')
      return
    }
    window.print()
  }

  const formValues = form.getFieldsValue()
  const subjectValue = formValues?.subject || ''
  const dateValue = formValues?.training_date
  const timeValue = formValues?.training_time
  const durationValue = formValues?.duration_hours
  const methodValue = formValues?.training_method || ''
  const isExamValue = formValues?.is_exam
  const trainerTypeValue = formValues?.trainer_type || ''
  const expectedValue = formValues?.expected_count
  const actualValue = formValues?.actual_count
  const absentValue = formValues?.absent_count
  const textbookValue = formValues?.textbook || ''
  const makeupValue = formValues?.makeup_training
  const assessmentValue = formValues?.assessment_method || ''
  const passValue = formValues?.pass_count
  const failValue = formValues?.fail_count
  const absentExamValue = formValues?.absent_exam_count
  const absentHandlingValue = formValues?.absent_exam_handling || ''
  const excellentValue = formValues?.excellent_count
  const qualifiedValue = formValues?.qualified_count
  const unqualifiedValue = formValues?.unqualified_count
  const conclusionValue = formValues?.evaluation_conclusion || ''
  const organizerValue = formValues?.organizer || ''
  const orgDateValue = formValues?.organizer_date
  const remarksValue = formValues?.remarks || ''

  const dateStr = dateValue ? dateValue.format('YYYY年MM月DD日') : '____年__月__日'
  const timeStr =
    timeValue
      ? `${dayjs(timeValue[0]).format('HH:mm')} ~ ${dayjs(timeValue[1]).format('HH:mm')}`
      : ''
  const orgDateStr = orgDateValue
    ? orgDateValue.format('YYYY年MM月DD日')
    : '____年__月__日'

  const methodMap: Record<string, string> = {
    面授: '☑面授  □函授  □远程教育  □自学  □其他方式',
    函授: '□面授  ☑函授  □远程教育  □自学  □其他方式',
    远程教育: '□面授  □函授  ☑远程教育  □自学  □其他方式',
    自学: '□面授  □函授  □远程教育  ☑自学  □其他方式',
    其他: '□面授  □函授  □远程教育  □自学  ☑其他方式',
  }
  const methodDisplay = methodMap[methodValue] || '□面授  □函授  □远程教育  □自学  □其他方式'

  const assessmentMap: Record<string, string> = {
    笔试: '☑ 笔试    □ 口试   □ 实操   □ 写总结',
    口试: '□ 笔试    ☑ 口试   □ 实操   □ 写总结',
    实操: '□ 笔试    □ 口试   ☑ 实操   □ 写总结',
    写总结: '□ 笔试    □ 口试   □ 实操   ☑ 写总结',
  }
  const assessmentDisplay = assessmentMap[assessmentValue] || '□ 笔试    □ 口试   □ 实操   □ 写总结'

  return (
    <div className="space-y-6">
      <Card title="填写培训效果评估表">
        <Form form={form} layout="vertical" className="max-w-4xl">
          <Form.Item
            name="subject"
            label="培训主题"
            rules={[{ required: true, message: '请填写培训主题' }]}
          >
            <Input placeholder="请输入培训主题" />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="training_date" label="培训日期">
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>

            <Form.Item name="training_time" label="培训时间">
              <TimePicker.RangePicker className="w-full" format="HH:mm" />
            </Form.Item>

            <Form.Item name="duration_hours" label="学时">
              <InputNumber className="w-full" placeholder="学时" min={0} step={0.5} />
            </Form.Item>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item name="training_method" label="培训方式">
              <Select
                placeholder="选择培训方式"
                allowClear
                options={[
                  { value: '面授', label: '面授' },
                  { value: '函授', label: '函授' },
                  { value: '远程教育', label: '远程教育' },
                  { value: '自学', label: '自学' },
                  { value: '其他', label: '其他方式' },
                ]}
              />
            </Form.Item>

            <Form.Item name="is_exam" label="是否考试">
              <Radio.Group>
                <Radio value={true}>是</Radio>
                <Radio value={false}>否</Radio>
              </Radio.Group>
            </Form.Item>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item name="trainer_type" label="培训人员类型">
              <Input placeholder="如：讲师/专家/官员等" />
            </Form.Item>

            <Form.Item name="textbook" label="培训教材">
              <Input placeholder="请输入培训教材" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="expected_count" label="应出席人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="actual_count" label="实际出席人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="absent_count" label="缺席人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>
          </div>

          <Form.Item name="makeup_training" label="是否补课">
            <Radio.Group>
              <Radio value={true}>是</Radio>
              <Radio value={false}>否</Radio>
            </Radio.Group>
          </Form.Item>

          <Form.Item name="assessment_method" label="考核方式">
            <Select
              placeholder="选择考核方式"
              allowClear
              options={[
                { value: '笔试', label: '笔试' },
                { value: '口试', label: '口试' },
                { value: '实操', label: '实操' },
                { value: '写总结', label: '写总结' },
              ]}
            />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="pass_count" label="合格人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="fail_count" label="不合格人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="absent_exam_count" label="缺考人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>
          </div>

          <Form.Item name="absent_exam_handling" label="缺考人员处理方式和原因">
            <Input.TextArea rows={2} placeholder="请输入处理方式" />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6">
            <Form.Item name="excellent_count" label="优秀人数">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="qualified_count" label="合格人数（综合评分）">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>

            <Form.Item name="unqualified_count" label="不合格人数（综合评分）">
              <InputNumber className="w-full" placeholder="人数" min={0} />
            </Form.Item>
          </div>

          <Form.Item name="evaluation_conclusion" label="培训效果评估及结论">
            <Input.TextArea rows={4} placeholder="请输入培训效果评估及结论" />
          </Form.Item>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
            <Form.Item name="organizer" label="培训组织人">
              <Input placeholder="请输入组织人姓名" />
            </Form.Item>

            <Form.Item name="organizer_date" label="组织日期">
              <DatePicker className="w-full" placeholder="选择日期" />
            </Form.Item>
          </div>

          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
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
      {subjectValue && (
        <div id="print-area">
          <Card>
            <div className="max-w-3xl mx-auto p-8 text-sm leading-relaxed">
              <div className="text-xs text-gray-500 mb-1">
                QR.SOP.PM.003/18（格式）  P8/12
              </div>
              <h2 className="text-center text-lg font-bold mb-1">
                丽珠集团新北江制药股份有限公司
              </h2>
              <h2 className="text-center text-xl font-bold mb-6">
                培训效果评估表
              </h2>

              <div className="border border-gray-800">
                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>培训主题：</strong>
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[300px]">
                    {subjectValue}
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2 flex gap-8">
                  <span>
                    <strong>培训时间：</strong>
                    <span className="border-b border-gray-800 px-2 inline-block min-w-[200px]">
                      {dateStr} {timeStr}
                    </span>
                  </span>
                  <span>
                    <strong>学时：</strong>
                    <span className="border-b border-gray-800 px-2 inline-block min-w-[60px]">
                      {durationValue !== undefined ? durationValue : ''}
                    </span>
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2 flex gap-8">
                  <span>
                    <strong>培训方式：</strong>
                    {methodDisplay}
                  </span>
                  <span>
                    {isExamValue === true ? '☑考试' : isExamValue === false ? '□考试' : '□考试'}
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>培训人员：</strong>
                  □讲师/专家/官员等
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[200px]">
                    {trainerTypeValue}
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  应出席
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {expectedValue !== undefined ? expectedValue : '___'}
                  </span>
                  人；实际出席
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {actualValue !== undefined ? actualValue : '___'}
                  </span>
                  人；缺席
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {absentValue !== undefined ? absentValue : '___'}
                  </span>
                  人。
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>培训教材：</strong>
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[300px]">
                    {textbookValue}
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>缺席人员处理方式：</strong>
                  <div className="mt-1">
                    是否进行补课培训，
                    {makeupValue === true ? '☑是 □否' : makeupValue === false ? '□是 ☑否' : '□是 □否'}
                    ，未参加培训人员必须补上培训内容，（包括培训时间、地点、方式等）。
                  </div>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>考核方式：</strong>
                  {assessmentDisplay}
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>考核结果：</strong>
                  □合格
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {passValue !== undefined ? passValue : '___'}
                  </span>
                  人；□不合格
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {failValue !== undefined ? failValue : '___'}
                  </span>
                  人；缺考
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {absentExamValue !== undefined ? absentExamValue : '___'}
                  </span>
                  人。
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>缺考人员处理方式和原因：</strong>
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[300px]">
                    {absentHandlingValue}
                  </span>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>综合评分：</strong>
                  □优秀
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {excellentValue !== undefined ? excellentValue : '___'}
                  </span>
                  人；□合格
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {qualifiedValue !== undefined ? qualifiedValue : '___'}
                  </span>
                  人；□不合格
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[40px] text-center">
                    {unqualifiedValue !== undefined ? unqualifiedValue : '___'}
                  </span>
                  人。
                </div>

                <div className="border-b border-gray-800 px-3 py-2 min-h-[80px]">
                  <strong>培训效果评估及结论：</strong>
                  <div className="mt-1 whitespace-pre-wrap">{conclusionValue}</div>
                </div>

                <div className="border-b border-gray-800 px-3 py-2">
                  <strong>培训组织人/日期：</strong>
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[200px]">
                    {organizerValue}
                  </span>
                  /
                  <span className="border-b border-gray-800 px-2 inline-block min-w-[120px]">
                    {orgDateStr}
                  </span>
                </div>

                <div className="px-3 py-2 min-h-[60px]">
                  <strong>备注：</strong>
                  <div className="mt-1 whitespace-pre-wrap">{remarksValue}</div>
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}

      {!subjectValue && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <CheckCircleOutlined className="text-5xl mb-4" />
          <p>请填写培训效果评估表信息后预览</p>
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

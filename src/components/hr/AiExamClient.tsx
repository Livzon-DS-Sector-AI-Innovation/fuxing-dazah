'use client'

import { useState } from 'react'
import {
  Button,
  Card,
  Input,
  Upload,
  message,
  Space,
  Divider,
  Typography,
  Spin,
} from 'antd'
import {
  UploadOutlined,
  DownloadOutlined,
  RobotOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import dayjs from 'dayjs'

import {
  ChoiceQuestion,
  ChoiceOption,
  ExamGenerateResponse,
  ExamExportData,
  TrueFalseQuestion,
} from '@/types/hr'
import { generateExamQuestions, exportExam } from '@/lib/api/ai'

const { Title, Text } = Typography

// 参考新员工入职培训预览边框样式
const BORDER_STYLE = { border: '1px solid #1f2937', padding: '8px' } as React.CSSProperties
const BORDER_STYLE_CENTER = { border: '1px solid #1f2937', padding: '8px', textAlign: 'center' } as React.CSSProperties

export default function AiExamClient() {
  // 手动输入字段
  const [title, setTitle] = useState('')
  const [examiner, setExaminer] = useState('')
  const [examDate, setExamDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [assessmentDate, setAssessmentDate] = useState(dayjs().format('YYYY-MM-DD'))

  // 上传和出题状态
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [generating, setGenerating] = useState(false)

  // 题目数据
  const [choiceQuestions, setChoiceQuestions] = useState<ChoiceQuestion[]>([])
  const [trueFalseQuestions, setTrueFalseQuestions] = useState<TrueFalseQuestion[]>([])

  // 导出状态
  const [exporting, setExporting] = useState(false)

  const handleUploadChange = (info: { fileList: UploadFile[] }) => {
    setFileList(info.fileList.slice(-1)) // 只保留最后一个文件
  }

  const handleGenerate = async () => {
    if (fileList.length === 0 || !fileList[0].originFileObj) {
      message.warning('请先上传文件')
      return
    }

    setGenerating(true)
    try {
      const res: ExamGenerateResponse = await generateExamQuestions(
        fileList[0].originFileObj
      )
      if (res.data?.choice_questions) {
        setChoiceQuestions(res.data.choice_questions)
      }
      if (res.data?.true_false_questions) {
        setTrueFalseQuestions(res.data.true_false_questions)
      }
      message.success('试卷题目生成成功')
    } catch (err: any) {
      message.error(err.message || '出题失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleExport = async () => {
    if (!title.trim()) {
      message.warning('请输入试卷标题')
      return
    }
    if (!examiner.trim()) {
      message.warning('请输入出卷人')
      return
    }
    if (choiceQuestions.length === 0 && trueFalseQuestions.length === 0) {
      message.warning('请先生成题目')
      return
    }

    setExporting(true)
    try {
      const data: ExamExportData = {
        title: title.trim(),
        examiner: examiner.trim(),
        exam_date: examDate,
        assessment_date: assessmentDate,
        choice_questions: choiceQuestions,
        true_false_questions: trueFalseQuestions,
      }
      const blob = await exportExam(data)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      const safeTitle = title.replace(/[\\/:*?"<>|]/g, '_')
      link.download = `${safeTitle}.docx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
      message.success('试卷导出成功')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const updateChoiceQuestion = (index: number, field: keyof ChoiceQuestion, value: any) => {
    setChoiceQuestions((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  const updateChoiceOption = (
    qIndex: number,
    oIndex: number,
    field: keyof ChoiceOption,
    value: string
  ) => {
    setChoiceQuestions((prev) => {
      const next = [...prev]
      const options = [...next[qIndex].options]
      options[oIndex] = { ...options[oIndex], [field]: value }
      next[qIndex] = { ...next[qIndex], options }
      return next
    })
  }

  const updateTrueFalseQuestion = (index: number, field: keyof TrueFalseQuestion, value: any) => {
    setTrueFalseQuestions((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  return (
    <div className="space-y-6">
      {/* ─── 手动输入区域 ─── */}
      <Card title="试卷基本信息" className="shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <Text className="block mb-1">试卷标题</Text>
            <Input
              placeholder="请输入试卷标题（对应文档页眉作为试卷题目）"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={100}
              showCount
            />
          </div>
          <div>
            <Text className="block mb-1">出卷人</Text>
            <Input
              placeholder="请输入出卷人"
              value={examiner}
              onChange={(e) => setExaminer(e.target.value)}
            />
          </div>
          <div>
            <Text className="block mb-1">出卷时间</Text>
            <Input
              type="date"
              value={examDate}
              onChange={(e) => setExamDate(e.target.value)}
            />
          </div>
          <div>
            <Text className="block mb-1">考核时间</Text>
            <Input
              type="date"
              value={assessmentDate}
              onChange={(e) => setAssessmentDate(e.target.value)}
            />
          </div>
        </div>
      </Card>

      {/* ─── 文件上传区域 ─── */}
      <Card title="上传培训文件" className="shadow-sm">
        <Space direction="vertical" size="middle" className="w-full">
          <Upload
            fileList={fileList}
            onChange={handleUploadChange}
            beforeUpload={() => false} // 阻止自动上传
            accept=".docx,.txt"
            maxCount={1}
          >
            <Button icon={<UploadOutlined />}>选择文件</Button>
          </Upload>
          <Text type="secondary">支持 .docx 和 .txt 格式，文件大小不超过 10MB</Text>

          <Button
            type="primary"
            icon={<RobotOutlined />}
            onClick={handleGenerate}
            loading={generating}
            disabled={fileList.length === 0}
            className="mt-2"
          >
            {generating ? 'AI 正在出题...' : 'AI 出题'}
          </Button>
        </Space>
      </Card>

      {/* ─── 题目展示与编辑区域 ─── */}
      {(choiceQuestions.length > 0 || trueFalseQuestions.length > 0) && (
        <Card
          title="试卷预览（可直接编辑）"
          className="shadow-sm"
          extra={
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={handleExport}
              loading={exporting}
            >
              导出试卷
            </Button>
          }
        >
          <Spin spinning={generating}>
            {/* 选择题 */}
            {choiceQuestions.length > 0 && (
              <>
                <Title level={5}>选择题（共50分，每题10分）</Title>
                <div className="space-y-4">
                  {choiceQuestions.map((item, index) => (
                    <div
                      key={item.number}
                      className="border border-[#1f2937]"
                    >
                      <div className="flex items-start gap-2 p-2">
                        <Text className="font-bold whitespace-nowrap mt-1">
                          {item.number}.
                        </Text>
                        <Input.TextArea
                          value={item.question}
                          onChange={(e) =>
                            updateChoiceQuestion(index, 'question', e.target.value)
                          }
                          autoSize={{ minRows: 1, maxRows: 4 }}
                          className="flex-1"
                        />
                      </div>
                      <div className="pl-6 space-y-1 pb-2">
                        {item.options.map((opt, oIndex) => (
                          <div key={opt.label} className="flex items-center gap-2">
                            <Text className="w-6 text-right">{opt.label}.</Text>
                            <Input
                              value={opt.text}
                              onChange={(e) =>
                                updateChoiceOption(
                                  index,
                                  oIndex,
                                  'text',
                                  e.target.value
                                )
                              }
                              className="flex-1"
                            />
                          </div>
                        ))}
                        <div className="flex items-center gap-2 pt-1">
                          <Text className="whitespace-nowrap">答案：</Text>
                          <Input
                            value={item.answer || ''}
                            onChange={(e) =>
                              updateChoiceQuestion(index, 'answer', e.target.value)
                            }
                            placeholder="如 A / B / C / D"
                            style={{ width: 120 }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <Divider />
              </>
            )}

            {/* 判断题 */}
            {trueFalseQuestions.length > 0 && (
              <>
                <Title level={5}>判断题（共50分，每题10分）</Title>
                <div className="space-y-4">
                  {trueFalseQuestions.map((item, index) => (
                    <div
                      key={item.number}
                      className="border border-[#1f2937]"
                    >
                      <div className="flex items-start gap-2 p-2">
                        <Text className="font-bold whitespace-nowrap mt-1">
                          {item.number}.
                        </Text>
                        <Input.TextArea
                          value={item.question}
                          onChange={(e) =>
                            updateTrueFalseQuestion(index, 'question', e.target.value)
                          }
                          autoSize={{ minRows: 1, maxRows: 4 }}
                          className="flex-1"
                        />
                      </div>
                      <div className="pl-6 pb-2">
                        <div className="flex items-center gap-2">
                          <Text className="whitespace-nowrap">答案：</Text>
                          <Input
                            value={item.answer || ''}
                            onChange={(e) =>
                              updateTrueFalseQuestion(index, 'answer', e.target.value)
                            }
                            placeholder="如 √ / ×"
                            style={{ width: 120 }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Spin>
        </Card>
      )}

      {/* ─── 空状态 ─── */}
      {choiceQuestions.length === 0 && trueFalseQuestions.length === 0 && !generating && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>上传培训文件并点击「AI 出题」生成试卷</p>
        </div>
      )}
    </div>
  )
}

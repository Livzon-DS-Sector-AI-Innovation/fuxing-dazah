'use client'

import { useState } from 'react'
import {
  Button,
  Card,
  Input,
  InputNumber,
  Upload,
  message,
  Space,
  Divider,
  Typography,
  Spin,
  Switch,
  Segmented,
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
import { generateExamQuestions, exportExam, saveExamPaper, generateQaQuestions, syncQaToBank } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'

const { Title, Text } = Typography

// 参考新员工入职培训预览边框样式
const BORDER_STYLE = { border: '1px solid #1f2937', padding: '8px' } as React.CSSProperties
const BORDER_STYLE_CENTER = { border: '1px solid #1f2937', padding: '8px', textAlign: 'center' } as React.CSSProperties

export default function AiExamClient() {
  // 出题模式：笔试组卷 / 问答考核
  const [mode, setMode] = useState<'exam' | 'qa'>('exam')

  // ── 问答考核出题状态 ──
  const [qaFileList, setQaFileList] = useState<UploadFile[]>([])
  const [qaSubject, setQaSubject] = useState('')
  const [qaCount, setQaCount] = useState(4)
  const [qaGenerating, setQaGenerating] = useState(false)
  const [qaQuestions, setQaQuestions] = useState<{ type?: string; question: string; answer: string; score?: number }[]>([])
  const [qaTitle, setQaTitle] = useState('')
  const [qaTotalScore, setQaTotalScore] = useState(0)
  const [qaSyncing, setQaSyncing] = useState(false)

  // 手动输入字段
  const [title, setTitle] = useState('')
  const [assessmentDate, setAssessmentDate] = useState('')

  // 上传和出题状态
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [generating, setGenerating] = useState(false)

  // 题目数据
  const [choiceQuestions, setChoiceQuestions] = useState<ChoiceQuestion[]>([])
  const [trueFalseQuestions, setTrueFalseQuestions] = useState<TrueFalseQuestion[]>([])
  const [multiQuestions, setMultiQuestions] = useState<ChoiceQuestion[]>([])
  const [fillQuestions, setFillQuestions] = useState<TrueFalseQuestion[]>([])

  // 导出状态
  const [exporting, setExporting] = useState(false)

  // 题目配置
  const [choiceEnabled, setChoiceEnabled] = useState(true)
  const [choiceCount, setChoiceCount] = useState(5)
  const [tfEnabled, setTfEnabled] = useState(true)
  const [tfCount, setTfCount] = useState(5)
  const [multiEnabled, setMultiEnabled] = useState(true)
  const [multiCount, setMultiCount] = useState(3)
  const [fillEnabled, setFillEnabled] = useState(true)
  const [fillCount, setFillCount] = useState(3)

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
      const config = {
        choice_count: choiceEnabled ? choiceCount : 0,
        true_false_count: tfEnabled ? tfCount : 0,
        multi_choice_count: multiEnabled ? multiCount : 0,
        fill_blank_count: fillEnabled ? fillCount : 0,
      }
      const fd = new FormData()
      fd.append('file', fileList[0].originFileObj)
      fd.append('choice_count', String(config.choice_count))
      fd.append('true_false_count', String(config.true_false_count))
      fd.append('multi_choice_count', String(config.multi_choice_count))
      fd.append('fill_blank_count', String(config.fill_blank_count))
      const res: ExamGenerateResponse = await generateExamQuestions(fd)
      if (res.data?.choice_questions) setChoiceQuestions(res.data.choice_questions)
      if (res.data?.true_false_questions) setTrueFalseQuestions(res.data.true_false_questions)
      if (res.data?.multi_choice_questions) setMultiQuestions(res.data.multi_choice_questions)
      if (res.data?.fill_blank_questions) setFillQuestions(res.data.fill_blank_questions)
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
    if (choiceQuestions.length === 0 && trueFalseQuestions.length === 0 && multiQuestions.length === 0 && fillQuestions.length === 0) {
      message.warning('请先生成题目')
      return
    }

    setExporting(true)
    try {
      const data: ExamExportData = {
        title: title.trim(),
        examiner: '',
        exam_date: '',
        assessment_date: '',
        choice_questions: choiceQuestions,
        true_false_questions: trueFalseQuestions,
        multi_choice_questions: multiQuestions,
        fill_blank_questions: fillQuestions,
      }
      const r = await exportExam(data)
      downloadBase64File(r.base64, r.filename)
      message.success('试卷导出成功')
    } catch (err: any) {
      message.error(err.message || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleSave = async () => {
    if (!title.trim()) {
      message.warning('请输入试卷标题')
      return
    }
    const total = choiceQuestions.length + trueFalseQuestions.length + multiQuestions.length + fillQuestions.length
    if (total === 0) {
      message.warning('请先生成题目')
      return
    }
    try {
      await saveExamPaper({
        subject: title,
        training_date: assessmentDate,
        questions: {
          choice_questions: choiceQuestions,
          true_false_questions: trueFalseQuestions,
          multi_choice_questions: multiQuestions,
          fill_blank_questions: fillQuestions,
        },
        full_score: 100,
        choice_count: choiceQuestions.length,
        true_false_count: trueFalseQuestions.length,
        multi_choice_count: multiQuestions.length,
        fill_blank_count: fillQuestions.length,
      })
      message.success('试卷已保存，可在「资料下载」中查看下载')
    } catch (err: any) {
      message.error(err.message || '保存失败')
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

  // ── 问答考核出题 ──
  const handleQaGenerate = async () => {
    if (qaFileList.length === 0 || !qaFileList[0].originFileObj) {
      message.warning('请先上传培训文件')
      return
    }
    setQaGenerating(true)
    try {
      const fd = new FormData()
      fd.append('file', qaFileList[0].originFileObj)
      fd.append('subject', qaSubject || qaFileList[0].name.replace(/\.[^.]+$/, ''))
      fd.append('question_count', String(qaCount))
      const res = await generateQaQuestions(fd)
      setQaQuestions(res.data?.questions || [])
      setQaTitle(res.data?.title || '')
      setQaTotalScore(res.data?.total_score || 0)
      message.success(`已生成 ${res.data?.questions?.length || 0} 道问答题`)
    } catch (err: any) {
      message.error(err.message || '问答出题失败')
    } finally {
      setQaGenerating(false)
    }
  }

  const handleQaSync = async () => {
    if (qaQuestions.length === 0) {
      message.warning('请先生成题目')
      return
    }
    setQaSyncing(true)
    try {
      const res = await syncQaToBank({
        subject: qaSubject || qaTitle || (qaFileList[0]?.name || '问答考核').replace(/\.[^.]+$/, ''),
        questions: qaQuestions,
      })
      message.success(res.message || `已同步 ${res.data?.inserted ?? 0} 题到题库大全`)
    } catch (err: any) {
      message.error(err.message || '同步失败')
    } finally {
      setQaSyncing(false)
    }
  }

  const updateQaQuestion = (index: number, field: 'question' | 'answer', value: string) => {
    setQaQuestions((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  return (
    <div className="space-y-6">
      <Segmented
        value={mode}
        onChange={(v) => setMode(v as 'exam' | 'qa')}
        options={[
          { label: '📝 笔试组卷', value: 'exam' },
          { label: '💬 问答出题', value: 'qa' },
        ]}
      />
      {mode === 'qa' ? (
        <div className="space-y-4">
          <Card title="问答考核出题（简短问答，可同步到题库大全）" className="shadow-sm">
            <Space direction="vertical" size="middle" className="w-full">
              <Space wrap>
                <Text>考核主题：</Text>
                <Input
                  placeholder="可留空，默认取文件名"
                  value={qaSubject}
                  onChange={(e) => setQaSubject(e.target.value)}
                  style={{ width: 320 }}
                />
                <Text>题数：</Text>
                <InputNumber min={1} max={10} value={qaCount} onChange={(v) => setQaCount(v ?? 4)} />
              </Space>
              <Upload
                fileList={qaFileList}
                onChange={(info) => setQaFileList(info.fileList.slice(-1))}
                beforeUpload={() => false}
                accept=".docx,.txt"
                maxCount={1}
              >
                <Button icon={<UploadOutlined />}>选择培训文件</Button>
              </Upload>
              <Text type="secondary">支持 .docx 和 .txt 格式；生成 10-20 字题目 + 15 字内答案的简短问答</Text>
              <Button type="primary" icon={<RobotOutlined />} loading={qaGenerating} onClick={handleQaGenerate}>
                AI 生成问答
              </Button>
            </Space>
          </Card>

          {qaQuestions.length > 0 && (
            <Card
              title={`${qaTitle}（共 ${qaQuestions.length} 题 / ${qaTotalScore} 分）`}
              className="shadow-sm"
              extra={
                <Button type="primary" loading={qaSyncing} onClick={handleQaSync}>
                  同步到题库大全
                </Button>
              }
            >
              <div className="space-y-3">
                {qaQuestions.map((q, i) => (
                  <div key={i} style={BORDER_STYLE}>
                    <div className="font-medium mb-1">
                      {i + 1}. {q.question}
                    </div>
                    <div className="text-gray-600 text-sm mb-1">答：{q.answer}</div>
                    <Input
                      size="small"
                      placeholder="可修改题目"
                      value={q.question}
                      onChange={(e) => updateQaQuestion(i, 'question', e.target.value)}
                    />
                    <Input
                      size="small"
                      className="mt-1"
                      placeholder="可修改答案"
                      value={q.answer}
                      onChange={(e) => updateQaQuestion(i, 'answer', e.target.value)}
                    />
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      ) : (
        <>
      {/* ─── 手动输入区域 ─── */}
      <Card title="试卷基本信息" className="shadow-sm">
        <div>
          <Text className="block mb-1">试卷标题</Text>
          <Input
            placeholder="请输入试卷标题"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={100}
            showCount
          />
        </div>
      </Card>

      {/* ─── 文件上传区域 ─── */}
      <Card title="上传培训文件" className="shadow-sm">
        <Space orientation="vertical" size="middle" className="w-full">
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

          <Divider style={{ margin: '8px 0' }} />
          <Text strong>题目配置</Text>
          <Space wrap>
            <Space>
              <Switch checked={choiceEnabled} onChange={setChoiceEnabled} size="small" />
              <span>单选题</span>
              {choiceEnabled && <InputNumber min={1} max={20} value={choiceCount} onChange={v => setChoiceCount(v || 1)} size="small" style={{ width: 60 }} />}
            </Space>
            <Space>
              <Switch checked={tfEnabled} onChange={setTfEnabled} size="small" />
              <span>判断题</span>
              {tfEnabled && <InputNumber min={1} max={20} value={tfCount} onChange={v => setTfCount(v || 1)} size="small" style={{ width: 60 }} />}
            </Space>
            <Space>
              <Switch checked={multiEnabled} onChange={setMultiEnabled} size="small" />
              <span>多选题</span>
              {multiEnabled && <InputNumber min={1} max={10} value={multiCount} onChange={v => setMultiCount(v || 1)} size="small" style={{ width: 60 }} />}
            </Space>
            <Space>
              <Switch checked={fillEnabled} onChange={setFillEnabled} size="small" />
              <span>填空题</span>
              {fillEnabled && <InputNumber min={1} max={10} value={fillCount} onChange={v => setFillCount(v || 1)} size="small" style={{ width: 60 }} />}
            </Space>
          </Space>

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
      {(choiceQuestions.length > 0 || trueFalseQuestions.length > 0 || multiQuestions.length > 0 || fillQuestions.length > 0) && (
        <Card
          title="试卷预览（可直接编辑）"
          className="shadow-sm"
          extra={
            <Space>
              <Button
                icon={<DownloadOutlined />}
                onClick={handleExport}
                loading={exporting}
              >
                导出试卷
              </Button>
              <Button
                type="primary"
                icon={<FileTextOutlined />}
                onClick={handleSave}
              >
                保存试卷
              </Button>
            </Space>
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

            {/* 多选题 */}
            {multiQuestions.length > 0 && (
              <>
                <Divider />
                <Title level={5}>三、多选题（共{multiQuestions.length * 10}分，每题10分）</Title>
                <div className="space-y-4">
                  {multiQuestions.map((item, index) => (
                    <div key={index} className="border border-gray-800 p-3 rounded">
                      <div className="flex items-start gap-2 mb-2">
                        <Text className="font-bold whitespace-nowrap mt-1">{index + 1}.</Text>
                        <Input.TextArea value={item.question} onChange={(e) => {
                          const next = [...multiQuestions]
                          next[index] = { ...next[index], question: e.target.value }
                          setMultiQuestions(next)
                        }} autoSize={{ minRows: 1, maxRows: 4 }} className="flex-1" />
                      </div>
                      {item.options?.map((opt, oi) => (
                        <div key={oi} className="pl-6 flex items-center gap-2 mb-1">
                          <Text className="whitespace-nowrap">{opt.label}.</Text>
                          <Input value={opt.text} onChange={(e) => {
                            const next = [...multiQuestions]
                            const opts = [...next[index].options!]
                            opts[oi] = { ...opts[oi], text: e.target.value }
                            next[index] = { ...next[index], options: opts }
                            setMultiQuestions(next)
                          }} className="flex-1" size="small" />
                        </div>
                      ))}
                      <div className="pl-6 pb-2">
                        <Text>答案：</Text>
                        <Input value={item.answer || ''} onChange={(e) => {
                          const next = [...multiQuestions]
                          next[index] = { ...next[index], answer: e.target.value }
                          setMultiQuestions(next)
                        }} placeholder="A,B" style={{ width: 120 }} />
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
            {/* 填空题 */}
            {fillQuestions.length > 0 && (
              <>
                <Divider />
                <Title level={5}>四、填空题（共{fillQuestions.length * 10}分，每题10分）</Title>
                <div className="space-y-4">
                  {fillQuestions.map((item, index) => (
                    <div key={index} className="border border-gray-800 p-3 rounded">
                      <div className="flex items-start gap-2 mb-2">
                        <Text className="font-bold whitespace-nowrap mt-1">{index + 1}.</Text>
                        <Input.TextArea value={item.question} onChange={(e) => {
                          const next = [...fillQuestions]
                          next[index] = { ...next[index], question: e.target.value }
                          setFillQuestions(next)
                        }} autoSize={{ minRows: 1, maxRows: 4 }} className="flex-1" />
                      </div>
                      <div className="pl-6">
                        <Text>答案：</Text>
                        <Input value={item.answer || ''} onChange={(e) => {
                          const next = [...fillQuestions]
                          next[index] = { ...next[index], answer: e.target.value }
                          setFillQuestions(next)
                        }} placeholder="参考答案" style={{ width: 200 }} />
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
        </Card>
      )}

      {/* ─── 空状态 ─── */}
      {choiceQuestions.length === 0 && trueFalseQuestions.length === 0 && multiQuestions.length === 0 && fillQuestions.length === 0 && !generating && (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <FileTextOutlined className="text-5xl mb-4" />
          <p>上传培训文件并点击「AI 出题」生成试卷</p>
        </div>
      )}
        </>
      )}
    </div>
  )
}

'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  DatePicker,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
} from 'antd'
import {
  DownloadOutlined,
  EditOutlined,
  DeleteOutlined,
  SearchOutlined,
  DatabaseOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchQuestionBank,
  fetchQaAssessmentDetail,
  fetchQaAssessments,
  downloadQaAssessmentRecord,
  downloadQaAssessmentEvaluation,
  API_BASE,
} from '@/lib/api/hr'
import {
  createQaAssessment,
  saveQaAssessmentScores,
  deleteQaAssessment,
} from '@/actions/hr'
import { QaAssessment, QaAssessmentScore, QuestionBankItem } from '@/types/hr'

interface AssessmentFlowProps {
  subject: string
  department: string
  trainingDate: string
  trainingMethod: string
  trainer?: string
  employeeNames: string[]
  employeeNumberMap: Record<string, string>
}

interface ScoreRow {
  employee_name: string
  employee_number?: string
  wrong: Set<number>
}

export default function AssessmentFlow({
  subject, department, trainingDate, trainingMethod, trainer,
  employeeNames, employeeNumberMap,
}: AssessmentFlowProps) {
  const { message } = App.useApp()

  // 题库
  const [bankItems, setBankItems] = useState<QuestionBankItem[]>([])
  const [bankTotal, setBankTotal] = useState(0)
  const [bankPage, setBankPage] = useState(1)
  const [bankLoading, setBankLoading] = useState(false)
  const [bankFileNo, setBankFileNo] = useState('')
  const [bankKeyword, setBankKeyword] = useState(subject)

  // 选题
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickedQuestions, setPickedQuestions] = useState<QuestionBankItem[]>([])
  const [pickedIds, setPickedIds] = useState<string[]>([])

  // 场次
  const [assessmentId, setAssessmentId] = useState<string | null>(null)
  const [assessment, setAssessment] = useState<QaAssessment | null>(null)
  const [creating, setCreating] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)

  // 成绩
  const [scoreRows, setScoreRows] = useState<ScoreRow[]>([])
  const [assessedDate, setAssessedDate] = useState<dayjs.Dayjs | null>(null)

  // 历史列表
  const [history, setHistory] = useState<QaAssessment[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyLoading, setHistoryLoading] = useState(false)

  const loadBank = useCallback(async (p = 1, fileNo?: string, keyword?: string) => {
    setBankLoading(true)
    try {
      const res = await fetchQuestionBank({
        file_no: fileNo ?? bankFileNo, keyword: keyword ?? bankKeyword, page: p, page_size: 50,
      })
      setBankItems(res.data || [])
      setBankTotal(res.meta?.total || 0)
      setBankPage(p)
    } catch (err: any) {
      message.error(err.message || '题库检索失败')
    } finally { setBankLoading(false) }
  }, [bankFileNo, bankKeyword, message])

  const loadHistory = useCallback(async (p = 1) => {
    setHistoryLoading(true)
    try {
      const res = await fetchQaAssessments({ department, page: p, page_size: 10 })
      setHistory(res.data || [])
      setHistoryTotal(res.meta?.total || 0)
      setHistoryPage(p)
    } catch { /* ignore */ }
    finally { setHistoryLoading(false) }
  }, [department])

  useEffect(() => { loadBank(1, '', subject); loadHistory(1) }, [])

  const handleCreate = async () => {
    if (pickedQuestions.length === 0) { message.warning('请先从题库选题'); return }
    setCreating(true)
    try {
      const res = await createQaAssessment({
        subject, department,
        training_date: trainingDate,
        training_method: trainingMethod, trainer,
        question_count: pickedQuestions.length,
        questions: pickedQuestions.map((q) => ({
          file_no: q.file_no, question: q.question, answer: q.answer, score: q.score,
        })),
        trainee_names: employeeNames,
      })
      const id = res.data?.id
      if (!id) throw new Error('创建失败：未返回ID')
      setAssessmentId(id)
      // 初始化成绩行
      setScoreRows(employeeNames.map((name) => ({
        employee_name: name,
        employee_number: employeeNumberMap[name],
        wrong: new Set<number>(),
      })))
      setAssessedDate(trainingDate ? dayjs(trainingDate) : null)
      message.success('考核场次已创建，默认全对，请录入错题')
      loadHistory(1)
    } catch (err: any) { message.error(err.message || '创建失败') }
    finally { setCreating(false) }
  }

  const openExisting = async (a: QaAssessment) => {
    try {
      const res = await fetchQaAssessmentDetail(a.id)
      const { assessment: aa, scores } = res.data
      setAssessmentId(a.id)
      setAssessment(aa)
      setScoreRows((scores || []).map((s: QaAssessmentScore) => ({
        employee_name: s.employee_name,
        employee_number: s.employee_number || undefined,
        wrong: new Set(s.wrong_questions || []),
      })))
      const d = (scores || []).find((s: any) => s.assessed_date)?.assessed_date || aa.training_date
      setAssessedDate(d ? dayjs(d) : null)
    } catch (err: any) { message.error(err.message || '加载考核详情失败') }
  }

  const questionScores = useMemo(() => {
    if (!assessment) return {}
    const map: Record<number, number> = {}
    if (assessment.questions?.length) {
      assessment.questions.forEach((q: any, i: number) => { map[i + 1] = q.score || 0 })
    } else {
      const per = Math.floor(assessment.full_score / (assessment.question_count || 10))
      for (let i = 1; i <= (assessment.question_count || 10); i++) map[i] = per
    }
    return map
  }, [assessment, pickedQuestions])

  const computeRow = (row: ScoreRow) => {
    if (!assessment) {
      const per = pickedQuestions.reduce((s, q) => s + (q.score || 0), 0) / Math.max(1, pickedQuestions.length)
      const deduction = [...row.wrong].reduce((s, n) => s + (pickedQuestions[n - 1]?.score || per || 0), 0)
      const total = Math.max(0, pickedQuestions.reduce((s, q) => s + (q.score || 0), 0) - deduction)
      return { total, grade: total >= 90 ? '优' : total >= 80 ? '合格' : '不合格' }
    }
    const deduction = [...row.wrong].reduce((s, n) => s + (questionScores[n] || 0), 0)
    const total = Math.max(0, assessment.full_score - deduction)
    const grade = total >= assessment.excellent_line ? '优' : total >= assessment.pass_line ? '合格' : '不合格'
    return { total, grade }
  }

  const toggleWrong = (name: string, q: number) => {
    setScoreRows((rows) => rows.map((r) => {
      if (r.employee_name !== name) return r
      const wrong = new Set(r.wrong)
      wrong.has(q) ? wrong.delete(q) : wrong.add(q)
      return { ...r, wrong }
    }))
  }

  const handleExport = async (kind: 'record' | 'evaluation') => {
    if (!assessmentId) return
    setExporting(`${kind}-${assessmentId}`)
    try {
      if (kind === 'record') await downloadQaAssessmentRecord(assessmentId)
      else await downloadQaAssessmentEvaluation(assessmentId)
      message.success('导出成功')
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setExporting(null) }
  }

  const handleExportScores = async () => {
    if (!assessmentId) { message.warning('请先创建考核场次'); return }
    setExporting(`scores-${assessmentId}`)
    try {
      // 1. 先保存成绩（含台账同步）
      const saveRes = await saveQaAssessmentScores(assessmentId, {
        assessed_date: assessedDate ? assessedDate.format('YYYY-MM-DD') : undefined,
        scores: scoreRows.map((r) => ({
          employee_name: r.employee_name,
          employee_number: r.employee_number,
          wrong_questions: [...r.wrong].sort((a, b) => a - b),
        })),
      })
      // 2. 再下载成绩单
      const dlRes = await fetch(`${API_BASE}/api/v1/hr/qa-assessments/${assessmentId}/export-scores`, { credentials: 'include' })
      if (dlRes.ok) {
        const blob = await dlRes.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = '成绩单.docx'
        document.body.appendChild(a); a.click(); document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
      }
      message.success((saveRes as any).message || '成绩单已导出，已同步到培训台账')
      loadHistory(1)
    } catch (err: any) { message.error(err.message || '导出失败') }
    finally { setExporting(null) }
  }

  const questionCount = assessment?.question_count || pickedQuestions.length || 0
  const scoreColumns = useMemo(() => {
    const cols: any[] = [
      { title: '姓名', dataIndex: 'employee_name', fixed: 'left' as const, width: 90 },
      ...Array.from({ length: questionCount }, (_, i) => {
        const q = i + 1
        return {
          title: `题${q}`, width: 52, align: 'center' as const,
          render: (_: any, row: ScoreRow) => (
            <Tag color={row.wrong.has(q) ? 'red' : 'green'}
              style={{ cursor: 'pointer', marginInlineEnd: 0, userSelect: 'none' }}
              onClick={() => toggleWrong(row.employee_name, q)}>
              {row.wrong.has(q) ? '✗' : '✓'}
            </Tag>
          ),
        }
      }),
      { title: '总分', width: 64, align: 'center' as const, fixed: 'right' as const,
        render: (_: any, row: ScoreRow) => <b>{computeRow(row).total}</b> },
      { title: '等级', width: 72, align: 'center' as const, fixed: 'right' as const,
        render: (_: any, row: ScoreRow) => {
          const g = computeRow(row).grade
          return <Tag color={g === '优' ? 'green' : g === '合格' ? 'blue' : 'red'}>{g}</Tag>
        }},
    ]
    return cols
  }, [questionCount, questionScores, assessment])

  const bankColumns = [
    { title: '文件编号', dataIndex: 'file_no', width: 140 },
    { title: '考题', dataIndex: 'question', ellipsis: true },
    { title: '答案', dataIndex: 'answer', ellipsis: true, width: 180 },
    { title: '分', dataIndex: 'score', width: 50, align: 'center' as const },
    { title: '来源', dataIndex: 'source', width: 72,
      render: (v: string) => <Tag color={v === 'AI生成' ? 'purple' : 'blue'}>{v}</Tag> },
    { title: '使用次数', dataIndex: 'usage_count', width: 70, align: 'center' as const },
  ]

  return (
    <div className="space-y-4">
      {/* 考核材料区 */}
      <div className="border rounded-lg p-4 bg-blue-50">
        <h3 className="font-semibold mb-2">考核材料</h3>
        {!assessmentId ? (
          <Space direction="vertical" className="w-full">
            <div className="text-sm text-gray-600">
              培训内容：<b>{subject}</b> · 部门：{department} · 方式：{trainingMethod}
              {trainer ? ` · 培训师：${trainer}` : ''} · 受训 {employeeNames.length} 人
            </div>
            <div className="flex items-center gap-3">
              <Button icon={<DatabaseOutlined />} type="primary" onClick={() => {
                setPickedIds(pickedQuestions.map(q => q.id))
                setPickerOpen(true)
                loadBank(1, '', subject)
              }}>
                从题库选题（已选 {pickedQuestions.length} 题）
              </Button>
              {employeeNames.length === 0 ? (
                <span className="text-orange-600 text-sm">请先在表单中选择受训部门及应出席人员</span>
              ) : (
                <Button
                  icon={<PlusOutlined />}
                  loading={creating}
                  disabled={pickedQuestions.length === 0}
                  onClick={handleCreate}
                >
                  确认选题，创建考核
                </Button>
              )}
            </div>
            {pickedQuestions.length > 0 && (
              <div className="max-h-24 overflow-auto text-xs text-gray-500 border rounded p-2 bg-white">
                {pickedQuestions.map((q, i) => (
                  <span key={q.id}>{i + 1}. [{q.file_no}] {q.question}（{q.score}分）{' | '}</span>
                ))}
              </div>
            )}
          </Space>
        ) : (
          <div className="space-y-3">
            {/* 成绩矩阵 */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="text-sm text-gray-600">
                已创建 {questionCount} 题 · 满分 {assessment?.full_score || pickedQuestions.reduce((s, q) => s + (q.score || 0), 0)} 分
              </div>
              <Space wrap>
                <DatePicker size="small" placeholder="考核日期" value={assessedDate} onChange={setAssessedDate} />
                <Button size="small" icon={<DownloadOutlined />}
                  loading={exporting === `record-${assessmentId}`}
                  onClick={() => handleExport('record')}>导出记录表</Button>
                <Button size="small" icon={<DownloadOutlined />}
                  loading={exporting === `evaluation-${assessmentId}`}
                  onClick={() => handleExport('evaluation')}>导出评估表</Button>
                <Button size="small" icon={<DownloadOutlined />} type="primary"
                  loading={exporting === `scores-${assessmentId}`}
                  onClick={handleExportScores}>导出成绩单</Button>
                <Button size="small" onClick={() => { setAssessmentId(null); setAssessment(null) }}>重新选题</Button>
              </Space>
            </div>
            <p className="text-xs text-gray-500">默认全对（绿✓），点击格子标记错题（红✗），导出成绩单自动保存并同步到培训台账</p>
            <Table
              rowKey="employee_name" size="small" dataSource={scoreRows} columns={scoreColumns}
              pagination={false} scroll={{ x: 'max-content' }}
            />
          </div>
        )}
      </div>

      {/* 历史考核 */}
        <Table
          rowKey="id" size="small" loading={historyLoading}
          dataSource={history}
          pagination={{ current: historyPage, pageSize: 10, total: historyTotal, onChange: (p) => loadHistory(p) }}
          columns={[
            { title: '培训内容', dataIndex: 'subject', ellipsis: true },
            { title: '日期', dataIndex: 'training_date', width: 100 },
            { title: '题数', dataIndex: 'question_count', width: 56, align: 'center' as const },
            { title: '操作', width: 150,
              render: (_: any, a: QaAssessment) => (
                <Space size="small">
                  <Button size="small" icon={<EditOutlined />} onClick={() => openExisting(a)}>录成绩</Button>
                  <Button size="small" icon={<DownloadOutlined />}
                    onClick={() => handleExport('record')}>表</Button>
                  <Popconfirm title="删除？" onConfirm={async () => {
                    try { await deleteQaAssessment(a.id); message.success('已删除'); loadHistory(1) }
                    catch (err: any) { message.error(err.message || '删除失败') }
                  }}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      <Modal title="从题库选题" open={pickerOpen} onCancel={() => setPickerOpen(false)} width={900}
        onOk={() => {
          const map = new Map(bankItems.map(i => [i.id, i]))
          const already = new Map(pickedQuestions.map(q => [q.id, q]))
          const selected = pickedIds.map(id => map.get(id) || already.get(id)).filter(Boolean) as QuestionBankItem[]
          setPickedQuestions(selected)
          setPickerOpen(false)
        }}
        okText={`确定（已选 ${pickedIds.length} 题）`}>
        <Space wrap className="mb-3">
          <Input placeholder="SOP编号" value={bankFileNo} onChange={e => setBankFileNo(e.target.value)} style={{ width: 160 }} allowClear />
          <Input placeholder="关键词" value={bankKeyword} onChange={e => setBankKeyword(e.target.value)} style={{ width: 200 }} allowClear />
          <Button icon={<SearchOutlined />} onClick={() => loadBank(1)}>搜索</Button>
        </Space>
        <Table rowKey="id" size="small" loading={bankLoading} dataSource={bankItems}
          rowSelection={{ selectedRowKeys: pickedIds, onChange: (keys) => setPickedIds(keys as string[]), preserveSelectedRowKeys: true }}
          pagination={{ current: bankPage, pageSize: 50, total: bankTotal, onChange: (p) => loadBank(p) }}
          columns={bankColumns} scroll={{ y: 380 }} />
      </Modal>
    </div>
  )
}


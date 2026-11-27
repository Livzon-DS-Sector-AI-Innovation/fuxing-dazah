'use client'

// SOP 登记的 AI 问答出题弹窗：上传该 SOP 的培训文档 → AI 生成简短问答 → 勾选后按 SOP 编号沉淀到共享题库。
// 题库按编号匹配：入库后下次「生成一套材料」，问答实操记录表自动带出这些题目（不再留空白行手写）。
// 由父组件换 key 重新挂载（与 SopRecordFormModal 同款约定），打开即初始状态，不用 effect 复位。

import { useEffect, useState, type Key } from 'react'
import { Alert, App, Button, Input, InputNumber, Modal, Radio, Space, Table, Typography, Upload } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadFile } from 'antd/es/upload/interface'
import { RobotOutlined, UploadOutlined } from '@ant-design/icons'
import { fetchQuestionBankCounts, generateQaQuestions, syncQaToBank } from '@/actions/hr'

interface SopQaFileOption {
  file_name: string
  file_no: string | null
}

interface SopQaGenerateModalProps {
  open: boolean
  /** 登记的文件列表（合并登记多份；单文件一条） */
  files: SopQaFileOption[]
  onClose: () => void
  /** 入库成功后通知父组件刷新题库题数 */
  onSynced: () => void
}

interface QaRow {
  key: number
  question: string
  answer: string
  score: number
}

const ACCEPT = '.docx,.txt'

const { Text } = Typography

export default function SopQaGenerateModal({ open, files, onClose, onSynced }: SopQaGenerateModalProps) {
  const { message } = App.useApp()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [subject, setSubject] = useState('')
  const [count, setCount] = useState(4)
  const [generating, setGenerating] = useState(false)
  const [questions, setQuestions] = useState<QaRow[]>([])
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([])
  const [syncing, setSyncing] = useState(false)

  // 题库按编号精确匹配：一份文件一份题。多份文件时先选这次上传的文档对应哪份
  const noMap = new Map<string, string>()
  for (const f of files) {
    const no = (f.file_no ?? '').trim()
    if (no && !noMap.has(no)) noMap.set(no, f.file_name)
  }
  const noOptions = [...noMap].map(([no, name]) => ({ no, name }))
  const [targetNo, setTargetNo] = useState(noOptions[0]?.no ?? '')

  const [bankCount, setBankCount] = useState<number | null>(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const r = open && targetNo ? await fetchQuestionBankCounts([targetNo]).catch(() => null) : null
      if (cancelled) return
      setBankCount(r?.data?.counts?.[targetNo] ?? null) // 拉不到计数不阻塞出题
    })()
    return () => { cancelled = true }
  }, [open, targetNo])

  const handleGenerate = async () => {
    const raw = fileList[0]?.originFileObj
    if (!raw) {
      message.warning('请先上传该 SOP 的培训文档')
      return
    }
    setGenerating(true)
    try {
      const fd = new FormData()
      fd.append('file', raw)
      fd.append('subject', subject || targetNo || raw.name.replace(/\.[^.]+$/, ''))
      fd.append('question_count', String(count))
      const res = await generateQaQuestions(fd)
      const rows: QaRow[] = (res.data?.questions || []).map((q, i) => ({
        key: i,
        question: q.question,
        answer: q.answer,
        score: q.score || 10,
      }))
      setQuestions(rows)
      setSelectedKeys(rows.map((q) => q.key)) // 默认全选，用户自行取消不要的
      message.success(`已生成 ${rows.length} 道问答题，勾选后入库`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '问答出题失败')
    } finally {
      setGenerating(false)
    }
  }

  const updateRow = (key: number, field: 'question' | 'answer', value: string) => {
    setQuestions((prev) => prev.map((q) => (q.key === key ? { ...q, [field]: value } : q)))
  }

  const handleSync = async () => {
    if (!targetNo) {
      message.warning('该登记没有 SOP 编号，题库按编号匹配，请先在登记里补编号')
      return
    }
    const chosen = questions.filter((q) => selectedKeys.includes(q.key) && q.question.trim())
    if (!chosen.length) {
      message.warning('请至少勾选一道题目')
      return
    }
    setSyncing(true)
    try {
      const res = await syncQaToBank({
        file_no: targetNo,
        subject: subject || files[0]?.file_name || targetNo,
        questions: chosen.map((q) => ({ question: q.question.trim(), answer: q.answer, score: q.score })),
      })
      const inserted = res.data?.inserted ?? 0
      const dup = chosen.length - inserted
      message.success(
        dup > 0 ? `已入库 ${inserted} 题（${dup} 题与题库重复，已跳过）` : `已入库 ${inserted} 题`,
      )
      onSynced()
      onClose()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '同步题库失败')
    } finally {
      setSyncing(false)
    }
  }

  const columns: ColumnsType<QaRow> = [
    {
      title: '题目',
      dataIndex: 'question',
      render: (_, q) => <Input variant="borderless" value={q.question} onChange={(e) => updateRow(q.key, 'question', e.target.value)} />,
    },
    {
      title: '参考答案',
      dataIndex: 'answer',
      width: 220,
      render: (_, q) => <Input variant="borderless" value={q.answer} onChange={(e) => updateRow(q.key, 'answer', e.target.value)} />,
    },
    { title: '分值', dataIndex: 'score', width: 56, render: (v: number) => <span className="tabular-nums">{v}</span> },
  ]

  return (
    <Modal
      title="AI 问答出题"
      open={open}
      onCancel={onClose}
      width={680}
      mask={{ closable: false }}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            disabled={!questions.length || !selectedKeys.length}
            loading={syncing}
            onClick={() => { void handleSync() }}
          >
            入库 {selectedKeys.length} 题{targetNo ? `（${targetNo}）` : ''}
          </Button>
        </Space>
      }
    >
      <div className="space-y-3">
        {noOptions.length > 1 ? (
          <div>
            <Typography.Text type="secondary" className="mr-2">本次出题对应：</Typography.Text>
            <Radio.Group value={targetNo} onChange={(e) => setTargetNo(e.target.value)} options={noOptions.map((o) => ({ value: o.no, label: `${o.no}（${o.name}）` }))} />
          </div>
        ) : noOptions.length === 1 ? (
          <div>
            <Typography.Text type="secondary" className="mr-2">SOP 编号：</Typography.Text>
            <Typography.Text strong>{targetNo}</Typography.Text>
            {bankCount !== null && (
              <Typography.Text type="secondary" className="ml-2">
                题库已有 {bankCount} 题，重复题干自动跳过
              </Typography.Text>
            )}
          </div>
        ) : (
          <Alert
            type="warning"
            showIcon
            title="该登记没有填 SOP 编号：题库按编号匹配考题，无编号的题生成材料时带不出来。请先在登记里补编号再出题。"
          />
        )}

        <Space wrap>
          <Upload
            fileList={fileList}
            onChange={(info) => setFileList(info.fileList.slice(-1))}
            beforeUpload={() => false}
            accept={ACCEPT}
            maxCount={1}
          >
            <Button icon={<UploadOutlined />}>上传该 SOP 的培训文档</Button>
          </Upload>
          <Input
            placeholder="考核主题（可留空，默认取文件名）"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            style={{ width: 240 }}
          />
          <Text type="secondary">题数：</Text>
          <InputNumber min={1} max={10} value={count} onChange={(v) => setCount(v ?? 4)} />
          <Button type="primary" icon={<RobotOutlined />} loading={generating} onClick={() => { void handleGenerate() }}>
            AI 生成问答
          </Button>
        </Space>
        <Typography.Text type="secondary">
          支持 .docx / .txt；生成 10-20 字题目 + 15 字内答案的简短问答，入库后「生成一套材料」的问答实操记录表自动带题
        </Typography.Text>

        {questions.length > 0 && (
          <Table<QaRow>
            rowKey="key"
            size="small"
            dataSource={questions}
            columns={columns}
            pagination={false}
            rowSelection={{ selectedRowKeys: selectedKeys, onChange: (keys) => setSelectedKeys(keys) }}
          />
        )}
      </div>
    </Modal>
  )
}

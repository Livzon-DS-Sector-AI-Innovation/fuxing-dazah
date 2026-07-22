'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Col, Row, Select } from 'antd'
import { DownloadOutlined, PrinterOutlined, SolutionOutlined, IdcardOutlined } from '@ant-design/icons'
import { downloadRoster, downloadTrainingRegistration } from '@/lib/api/hr'
import { Department } from '@/types/hr'

interface PrintingClientProps {
  initialDepartments: Department[]
}

interface PrintableDocument {
  key: string
  title: string
  desc: string
  icon: React.ReactNode
  download: (department?: string) => Promise<void>
}

const documents: PrintableDocument[] = [
  {
    key: 'roster',
    title: '员工花名册',
    desc: '按部门下载员工花名册（Word），不选部门时下载全部',
    icon: <SolutionOutlined className="text-2xl text-[var(--color-primary)]" />,
    download: downloadRoster,
  },
  {
    key: 'training-registration',
    title: '个人培训登记表',
    desc: '以员工档案自动填写，整个部门合并为一个文件（每人一页）',
    icon: <IdcardOutlined className="text-2xl text-[var(--color-primary)]" />,
    download: downloadTrainingRegistration,
  },
  {
    key: 'exam-paper',
    title: '笔试试卷',
    desc: '已保存的AI生成/手工组卷考卷，选择后下载Word打印',
    icon: <PrinterOutlined className="text-2xl text-[var(--color-primary)]" />,
    download: async (paperId?: string) => {
      if (!paperId) return
      const { downloadExamPaper } = await import('@/lib/api/hr')
      await downloadExamPaper(paperId)
    },
  },
]

export default function PrintingClient({ initialDepartments }: PrintingClientProps) {
  const { message } = App.useApp()
  const [selectedDepts, setSelectedDepts] = useState<Record<string, string | undefined>>({})
  const [downloading, setDownloading] = useState<string | null>(null)
  const [examPapers, setExamPapers] = useState<{ value: string; label: string }[]>([])
  const [papersLoading, setPapersLoading] = useState(false)

  const [departments, setDepartments] = useState(initialDepartments)
  useEffect(() => {
    if (initialDepartments.length === 0) {
      import('@/lib/api/hr').then(({ fetchDepartments }) => {
        fetchDepartments({ page_size: 200 }).then(res => setDepartments(res.data || [])).catch(() => {})
      })
    }
  }, [])

  const deptOptions = departments.map((d: any) => ({ value: d.name, label: d.name }))

  const loadExamPapers = async () => {
    if (examPapers.length > 0) return
    setPapersLoading(true)
    try {
      const { fetchExamPapers } = await import('@/lib/api/hr')
      const res = await fetchExamPapers({ page_size: 200 })
      setExamPapers((res.data || []).map((p: any) => ({
        value: p.id,
        label: `${p.subject}（${p.training_date || '无日期'} · ${p.choice_count + p.true_false_count + p.multi_choice_count + p.fill_blank_count}题）`,
      })))
    } finally { setPapersLoading(false) }
  }

  const handleDownload = async (doc: PrintableDocument) => {
    setDownloading(doc.key)
    try {
      await doc.download(selectedDepts[doc.key])
      message.success(`${doc.title}下载成功`)
    } catch (err: any) {
      message.error(err.message || `${doc.title}下载失败`)
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          <PrinterOutlined className="mr-2" />
          资料打印
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          按部门批量生成并下载人事资料文档
        </p>
      </div>

      <Row gutter={[16, 16]}>
        {documents.map((doc) => (
          <Col xs={24} sm={12} lg={8} key={doc.key}>
            <Card className="h-full">
              <div className="flex items-start gap-4">
                <div className="mt-1">{doc.icon}</div>
                <div className="flex-1">
                  <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1">
                    {doc.title}
                  </h3>
                  <p className="text-[14px] text-[var(--color-steel)] leading-relaxed mb-4">
                    {doc.desc}
                  </p>
                  <div className="flex items-center gap-2">
                    {doc.key === 'exam-paper' ? (
                      <>
                        <Select
                          placeholder="选择考卷"
                          allowClear
                          style={{ flex: 1, minWidth: 0 }}
                          options={examPapers}
                          loading={papersLoading}
                          value={selectedDepts[doc.key]}
                          onChange={(v) => setSelectedDepts((prev) => ({ ...prev, [doc.key]: v }))}
                          onDropdownVisibleChange={(open) => { if (open) loadExamPapers() }}
                        />
                        <Button
                          type="primary"
                          icon={<DownloadOutlined />}
                          loading={downloading === doc.key}
                          disabled={!selectedDepts[doc.key]}
                          onClick={() => handleDownload(doc)}
                        >
                          下载
                        </Button>
                      </>
                    ) : (
                      <>
                        <Select
                          placeholder="选择部门"
                          allowClear
                          style={{ flex: 1, minWidth: 0 }}
                          options={deptOptions}
                          value={selectedDepts[doc.key]}
                          onChange={(v) => setSelectedDepts((prev) => ({ ...prev, [doc.key]: v }))}
                        />
                        <Button
                          type="primary"
                          icon={<DownloadOutlined />}
                          loading={downloading === doc.key}
                          onClick={() => handleDownload(doc)}
                        >
                          下载
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

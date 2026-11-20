import PageHeader from '@/components/hr/PageHeader'
import AiExamClient from '@/components/hr/AiExamClient'

export default function AiExamPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="AI 出题" description="上传培训文件，AI 自动识别内容并生成试卷，支持导出 Word" />

      <AiExamClient />
    </div>
  )
}

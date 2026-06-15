import AiExamClient from '@/components/hr/AiExamClient'

export default function AiExamPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          AI 出题
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          上传培训文件，AI 自动识别内容并生成试卷，支持导出 Word
        </p>
      </div>

      <AiExamClient />
    </div>
  )
}

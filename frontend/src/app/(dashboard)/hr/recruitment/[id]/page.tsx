import { Suspense } from 'react'
import CandidateDetailLoader from '@/components/hr/CandidateDetailLoader'
import { fetchCandidateById } from '@/actions/hr'

// 页面本身保持为服务端组件：标签页标题带候选人姓名（浏览器多标签时能分清是哪位候选人）
export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  try {
    const d = await fetchCandidateById(id)
    const name = (d.data as { name?: string } | null | undefined)?.name
    if (name) return { title: `${name} - 候选人详情` }
  } catch {
    // 无权限 / 已删除：回落到通用标题
  }
  return { title: '候选人详情' }
}

export default function CandidateDetailPage() {
  return (
    <div className="space-y-4">
      <Suspense fallback={<div className="h-64" />}>
        <CandidateDetailLoader />
      </Suspense>
    </div>
  )
}

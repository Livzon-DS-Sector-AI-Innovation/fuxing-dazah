import PerformanceCategoryScoreClient from '@/components/hr/PerformanceCategoryScoreClient'

export default function ScorePage() {
  return <div className="space-y-6">
    <div><h1 className="text-[22px] font-semibold mb-2">考核项目评分</h1><p className="text-sm text-gray-500">各项目负责人给部门打分</p></div>
    <PerformanceCategoryScoreClient />
  </div>
}

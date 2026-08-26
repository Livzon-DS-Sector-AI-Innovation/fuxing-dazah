import PerformanceCategoryClient from '@/components/hr/PerformanceCategoryClient'

export default function CategoriesPage() {
  return <div className="space-y-6">
    <div><h1 className="text-[22px] font-semibold mb-2">考核项目配置</h1><p className="text-sm text-gray-500">配置考核项目名称、权重、负责人</p></div>
    <PerformanceCategoryClient />
  </div>
}

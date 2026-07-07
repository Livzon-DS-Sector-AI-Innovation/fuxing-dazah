import { getFullGraph } from '@/actions/safety/knowledge-graph'
import KnowledgeGraphPanel from '@/components/safety/KnowledgeGraphPanel'

export const dynamic = 'force-dynamic'
export const revalidate = 120

export default async function KnowledgeGraphPage() {
  // 初始数据获取 (Server Component)
  // 实际渲染由 Client Component 接管
  return (
    <div style={{ width: '100%', height: 'calc(100vh - 64px)', position: 'relative' }}>
      <KnowledgeGraphPanel />
    </div>
  )
}

import KnowledgeGraphTree from '@/components/safety/KnowledgeGraphTree'

export const dynamic = 'force-dynamic'
export const revalidate = 120

export default function KnowledgeGraphPage() {
  return (
    <div
      style={{
        display: 'flex',
        margin: -24,
        height: 'calc(100vh - 64px)',
      }}
    >
      {/* 目录树 (全宽，详情面板由树组件内部管理) */}
      <KnowledgeGraphTree />
    </div>
  )
}

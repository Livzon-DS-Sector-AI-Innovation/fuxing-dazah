import Link from 'next/link'
import { listWorkflowDefinitions } from '@/actions/workflow'
import { WorkflowList } from '@/components/safety/workflow/WorkflowList'

export const dynamic = 'force-dynamic'

export default async function WorkflowPage() {
  const { data, meta } = await listWorkflowDefinitions({ page_size: 100 })

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>工作流配置</h2>
        <Link
          href="/safety/workflow/new"
          style={{
            padding: '6px 16px',
            background: '#1890ff',
            color: '#fff',
            borderRadius: 6,
            textDecoration: 'none',
          }}
        >
          新建工作流
        </Link>
      </div>
      <WorkflowList items={data} total={meta.total} />
    </div>
  )
}

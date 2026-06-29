import { notFound } from 'next/navigation'
import { getWorkflowDefinition } from '@/actions/workflow'
import { WorkflowEditor } from '@/components/safety/workflow/WorkflowEditor'

export const dynamic = 'force-dynamic'

export default async function WorkflowEditorPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params

  // 'new' route — create a new workflow
  if (id === 'new') {
    return (
      <div style={{ padding: 24 }}>
        <h2 style={{ marginBottom: 16 }}>新建工作流</h2>
        <WorkflowEditor id="new" initialData={null} />
      </div>
    )
  }

  const result = await getWorkflowDefinition(id)
  if (result.code === 404 || !result.data) {
    notFound()
  }

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>
        编辑工作流: {result.data.name}
      </h2>
      <WorkflowEditor id={id} initialData={result.data} />
    </div>
  )
}

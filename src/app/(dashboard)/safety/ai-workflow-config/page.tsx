import { getAIWorkflowConfigs } from '@/actions/safety'
import AIWorkflowConfigClient from '@/components/safety/AIWorkflowConfigClient'

export const dynamic = 'force-dynamic'

export default async function AIWorkflowConfigPage() {
  let workflows: Awaited<ReturnType<typeof getAIWorkflowConfigs>>['data'] = []

  try {
    const wfRes = await getAIWorkflowConfigs({ page_size: 500 })
    workflows = wfRes.data || []
  } catch {
    // Use empty defaults
  }

  return (
    <AIWorkflowConfigClient
      initialWorkflows={workflows || []}
      apiConnected={true}
    />
  )
}

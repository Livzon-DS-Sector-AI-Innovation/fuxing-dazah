import { getScheduledTasks } from '@/actions/safety'
import { ScheduledTaskList } from '@/components/safety'

export const dynamic = 'force-dynamic'

export default async function ScheduledTasksPage() {
  const res = await getScheduledTasks({ page: 1, page_size: 20 })

  return (
    <div style={{ padding: '0 0 24px' }}>
      <h2 style={{ marginBottom: 16 }}>定时任务</h2>
      <ScheduledTaskList
        initialData={res.data || []}
        initialTotal={res.meta?.total || 0}
      />
    </div>
  )
}

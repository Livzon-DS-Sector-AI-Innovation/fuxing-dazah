import { ScheduledTaskForm } from '@/components/safety'

export default function NewScheduledTaskPage() {
  return (
    <div style={{ padding: '0 0 24px' }}>
      <h2 style={{ marginBottom: 16 }}>新建定时任务</h2>
      <ScheduledTaskForm />
    </div>
  )
}

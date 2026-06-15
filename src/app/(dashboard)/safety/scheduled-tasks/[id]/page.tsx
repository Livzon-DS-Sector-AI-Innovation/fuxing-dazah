import { notFound } from 'next/navigation'
import { getScheduledTask } from '@/actions/safety'
import { ScheduledTaskForm } from '@/components/safety'

interface EditTaskPageProps {
  params: Promise<{ id: string }>
}

export default async function EditScheduledTaskPage({ params }: EditTaskPageProps) {
  const { id } = await params
  const res = await getScheduledTask(id)

  if (res.code !== 200 || !res.data) {
    notFound()
  }

  return (
    <div style={{ padding: '0 0 24px' }}>
      <h2 style={{ marginBottom: 16 }}>编辑定时任务 — {res.data.name}</h2>
      <ScheduledTaskForm editData={res.data} />
    </div>
  )
}

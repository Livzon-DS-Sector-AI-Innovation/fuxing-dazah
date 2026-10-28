'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Empty, Modal, Progress, Segmented, Select, Space, Tag, Typography } from 'antd'
import { TeamOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { BoardTask, PersonnelItem, TaskAssignment } from '@/types/quality'
import { fetchTaskBoard, fetchPersonnel, saveTaskAssignments } from '@/actions/quality'

const { Text } = Typography

/** 任务看板：按人员分列展示任务 SOP 分工，支持手动排班（人员自选）。 */
export default function TaskBoard() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [tasks, setTasks] = useState<BoardTask[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('in_progress,pending_review')
  const [assignOpen, setAssignOpen] = useState<BoardTask | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string | undefined>>({})
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [boardRes, personRes] = await Promise.all([
        fetchTaskBoard(statusFilter),
        fetchPersonnel(),
      ])
      setTasks(boardRes.data)
      setPersonnel(personRes.data.items ?? [])
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取看板失败')
    } finally {
      setLoading(false)
    }
  }, [message, statusFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  // 人员列：有分工的人 + 未分配列
  const columns = useMemo(() => {
    const names: { id: string | null; name: string }[] = []
    const seen = new Set<string>()
    for (const t of tasks) {
      for (const a of t.assignments) {
        if (a.assignee_name && !seen.has(a.assignee_id)) {
          seen.add(a.assignee_id)
          names.push({ id: a.assignee_id, name: a.assignee_name })
        }
      }
    }
    names.push({ id: null, name: '未分配' })
    return names
  }, [tasks])

  const personOptions = personnel.map((p) => ({ value: p.id, label: `${p.name}${p.employee_no ? `（${p.employee_no}）` : ''}` }))

  const openAssign = (t: BoardTask) => {
    const init: Record<string, string | undefined> = {}
    for (const a of t.assignments) init[a.sop_no] = a.assignee_id
    for (const s of t.unassigned_sops) init[s] = undefined
    setDrafts(init)
    setAssignOpen(t)
  }

  const onSaveAssign = async () => {
    if (!assignOpen) return
    const assignments = Object.entries(drafts)
      .filter(([, v]) => v)
      .map(([sop_no, assignee_id]) => ({ sop_no, assignee_id: assignee_id as string }))
    setSaving(true)
    try {
      const res = await saveTaskAssignments(assignOpen.task_id, assignments)
      message.success(res.message)
      setAssignOpen(null)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存分工失败')
    } finally {
      setSaving(false)
    }
  }

  const statusMeta: Record<string, { label: string; color: string }> = {
    in_progress: { label: '填报中', color: 'blue' },
    pending_review: { label: '待复核', color: 'orange' },
    completed: { label: '已完成', color: 'green' },
  }

  const renderCard = (t: BoardTask, personId: string | null) => {
    const mine = t.assignments.filter((a) => (personId === null ? false : a.assignee_id === personId))
    const unassigned = personId === null ? t.unassigned_sops : []
    return (
      <Card
        key={t.task_id}
        size="small"
        style={{ marginBottom: 8, cursor: 'pointer' }}
        onClick={() => router.push(`/quality/task/${t.task_id}`)}
        title={<Space size={4}>
          <Text strong>{t.product_name}</Text>
          <Text type="secondary">批号 {t.batch_number}</Text>
        </Space>}
        extra={<Tag color={statusMeta[t.status]?.color}>{statusMeta[t.status]?.label ?? t.status}</Tag>}
      >
        <Progress percent={t.total ? Math.round((t.filled / t.total) * 100) : 0} size="small" format={() => `${t.filled}/${t.total}`} />
        {personId === null ? (
          unassigned.length > 0 ? (
            <div style={{ marginTop: 6 }}>
              <Text type="warning" style={{ fontSize: 12 }}>未分配 SOP：{unassigned.join('、')}</Text>
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>全部 SOP 已分配</Text>
          )
        ) : (
          <div style={{ marginTop: 6 }}>
            {mine.map((a) => (
              <div key={a.sop_no} style={{ fontSize: 12.5, paddingBlock: 1 }}>
                <Text code style={{ fontSize: 11.5 }}>{a.sop_no}</Text>
                <Text style={{ marginLeft: 4 }}>{a.items.join('、')}</Text>
                <Tag style={{ marginLeft: 4 }} color={a.filled === a.total ? 'green' : 'orange'}>{a.filled}/{a.total}</Tag>
              </div>
            ))}
          </div>
        )}
        {canAssign && (
          <Button size="small" type="link" style={{ marginTop: 4, padding: 0 }}
            onClick={(e) => { e.stopPropagation(); openAssign(t) }}>
            分配
          </Button>
        )}
      </Card>
    )
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Segmented
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as string)}
          options={[
            { value: 'in_progress,pending_review', label: '进行中' },
            { value: 'in_progress', label: '填报中' },
            { value: 'pending_review', label: '待复核' },
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12.5 }}>
          <TeamOutlined /> 看板按人员分列；点「分配」给任务内各 SOP 指派负责人（人员手动选择）
        </Text>
      </Space>

      <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 8 }}>
        {columns.map((col) => (
          <div key={col.id ?? '__unassigned'} style={{ flex: '0 0 300px' }}>
            <div style={{
              padding: '6px 10px', borderRadius: 6, marginBottom: 8,
              background: col.id === null ? '#fff7e6' : '#e6f4ff', fontWeight: 500,
            }}>
              {col.name}
              <Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>
                {col.id === null
                  ? tasks.filter((t) => t.unassigned_sops.length > 0).length
                  : tasks.filter((t) => t.assignments.some((a) => a.assignee_id === col.id)).length} 个任务
              </Text>
            </div>
            {tasks
              .filter((t) => (col.id === null ? t.unassigned_sops.length > 0 : t.assignments.some((a) => a.assignee_id === col.id)))
              .map((t) => renderCard(t, col.id))}
            {tasks.filter((t) => (col.id === null ? t.unassigned_sops.length > 0 : t.assignments.some((a) => a.assignee_id === col.id))).length === 0 && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无任务" />
            )}
          </div>
        ))}
      </div>

      <Modal
        title={`任务分工 ${assignOpen ? `（${assignOpen.product_name} 批号 ${assignOpen.batch_number}）` : ''}`}
        open={!!assignOpen}
        onCancel={() => setAssignOpen(null)}
        onOk={onSaveAssign}
        confirmLoading={saving}
        okText="保存分工"
        width={520}
      >
        {assignOpen && (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {Object.keys(drafts).map((sop) => (
              <div key={sop} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Text code style={{ flex: '0 0 150px', fontSize: 12 }}>{sop}</Text>
                <Select
                  showSearch allowClear optionFilterProp="label"
                  style={{ flex: 1 }}
                  placeholder="选择负责人"
                  value={drafts[sop]}
                  onChange={(v) => setDrafts((m) => ({ ...m, [sop]: v }))}
                  options={personOptions}
                />
              </div>
            ))}
            {Object.keys(drafts).length === 0 && (
              <Text type="secondary">该任务没有可分配的 SOP。</Text>
            )}
          </Space>
        )}
      </Modal>
    </>
  )
}

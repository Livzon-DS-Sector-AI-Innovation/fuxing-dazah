'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Empty, Modal, Progress, Segmented, Select, Space, Tag, Typography } from 'antd'
import { DragOutlined, TeamOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { BoardTask, PersonnelItem, TaskAssignment } from '@/types/quality'
import { fetchTaskBoard, fetchPersonnel, saveTaskAssignments } from '@/actions/quality'

const { Text } = Typography

/** 任务看板：筛选特定成员分列展示，拖拽任务卡到成员列即排班（分配未分配 SOP）。 */
export default function TaskBoard() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [tasks, setTasks] = useState<BoardTask[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState('in_progress,pending_review')
  const [memberFilter, setMemberFilter] = useState<string[]>([])
  const [assignOpen, setAssignOpen] = useState<BoardTask | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string | undefined>>({})
  const [saving, setSaving] = useState(false)
  const [dragOver, setDragOver] = useState<string | null>(null)

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

  const personOptions = personnel.map((p) => ({
    value: p.id,
    label: `${p.name}${p.employee_no ? `（${p.employee_no}）` : ''}${p.department ? ` ${p.department}` : ''}`,
  }))

  // 列：筛选的成员（默认=有分工的成员）+ 未分配列
  const columns = useMemo(() => {
    const assigned = new Map<string, string>()
    for (const t of tasks) {
      for (const a of t.assignments) {
        if (a.assignee_name && !assigned.has(a.assignee_id)) assigned.set(a.assignee_id, a.assignee_name)
      }
    }
    const chosen = memberFilter.length > 0 ? memberFilter : [...assigned.keys()]
    const list: { id: string | null; name: string }[] = []
    for (const id of chosen) {
      const p = personnel.find((x) => x.id === id)
      list.push({ id, name: p?.name ?? assigned.get(id) ?? id })
    }
    if (memberFilter.length > 0) {
      // 筛选时仍显示未分配列
      list.push({ id: null, name: '未分配' })
      return list
    }
    list.push({ id: null, name: '未分配' })
    return list
  }, [tasks, memberFilter, personnel])

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

  /** 拖拽落列：任务所有未分配 SOP 分配给该成员（若全部已分配则整体改派给该成员）。 */
  const onDropTask = async (taskId: string, personId: string | null, personName: string) => {
    if (!canAssign || personId === null) return
    const t = tasks.find((x) => x.task_id === taskId)
    if (!t) return
    const existing = t.assignments.map((a) => ({ sop_no: a.sop_no, assignee_id: a.assignee_id }))
    const targets = t.unassigned_sops.length > 0 ? t.unassigned_sops : t.assignments.map((a) => a.sop_no)
    for (const sop of targets) {
      const i = existing.findIndex((a) => a.sop_no === sop)
      if (i >= 0) existing[i] = { sop_no: sop, assignee_id: personId }
      else existing.push({ sop_no: sop, assignee_id: personId })
    }
    try {
      const res = await saveTaskAssignments(taskId, existing)
      message.success(`${res.message}${t.unassigned_sops.length > 0 ? '' : '（全部 SOP 已改派）'}`)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '拖拽分配失败')
    }
    setDragOver(null)
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
        draggable={canAssign}
        onDragStart={(e) => { e.dataTransfer.setData('text/plain', t.task_id); e.dataTransfer.effectAllowed = 'move' }}
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
        <Select
          mode="multiple" allowClear showSearch optionFilterProp="label"
          placeholder="筛选成员（空=有分工的人）" style={{ minWidth: 280 }}
          value={memberFilter}
          onChange={setMemberFilter}
          options={personOptions}
          maxTagCount={3}
        />
        <Text type="secondary" style={{ fontSize: 12.5 }}>
          <TeamOutlined /> <DragOutlined /> 拖任务卡到成员列即排班；点「分配」可逐 SOP 选人
        </Text>
      </Space>

      <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 8 }}>
        {columns.map((col) => {
          const colTasks = tasks.filter((t) => (
            col.id === null
              ? t.unassigned_sops.length > 0
              : t.assignments.some((a) => a.assignee_id === col.id)
          ))
          return (
            <div
              key={col.id ?? '__unassigned'}
              style={{
                flex: '0 0 300px',
                minHeight: 200,
                borderRadius: 8,
                padding: 4,
                outline: dragOver === (col.id ?? '__unassigned') ? '2px dashed #1677ff' : 'none',
                background: dragOver === (col.id ?? '__unassigned') ? '#f0f7ff' : 'transparent',
              }}
              onDragOver={(e) => { if (canAssign && col.id !== null) { e.preventDefault(); setDragOver(col.id) } }}
              onDragLeave={() => setDragOver(null)}
              onDrop={(e) => {
                e.preventDefault()
                const taskId = e.dataTransfer.getData('text/plain')
                if (taskId) void onDropTask(taskId, col.id, col.name)
              }}
            >
              <div style={{
                padding: '6px 10px', borderRadius: 6, marginBottom: 8,
                background: col.id === null ? '#fff7e6' : '#e6f4ff', fontWeight: 500,
              }}>
                {col.name}
                <Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>{colTasks.length} 个任务</Text>
              </div>
              {colTasks.map((t) => renderCard(t, col.id))}
              {colTasks.length === 0 && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={col.id === null ? '无待分配任务' : '拖任务卡到这里排班'} />
              )}
            </div>
          )
        })}
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

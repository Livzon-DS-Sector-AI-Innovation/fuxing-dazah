'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Empty, Progress, Select, Space, Tag, Typography } from 'antd'
import { ReloadOutlined, TeamOutlined } from '@ant-design/icons'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { PersonnelItem, PlanBoardItem } from '@/types/quality'
import { fetchPlanBoard, fetchPersonnel, savePlanAssignments } from '@/actions/quality'

const { Text } = Typography

/** 请检任务排班看板：今天及以后的请检计划，按计划展示待检 SOP，逐 SOP 选人排班，人员名字显示在计划下。 */
export default function TaskBoard() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [plans, setPlans] = useState<PlanBoardItem[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [boardRes, personRes] = await Promise.all([
        fetchPlanBoard(),
        fetchPersonnel(),
      ])
      setPlans(boardRes.data)
      setPersonnel(personRes.data.items ?? [])
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取排班看板失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => { (async () => { await load() })() }, [load])

  const personOptions = personnel.map((p) => ({
    value: p.id,
    label: `${p.name}${p.employee_no ? `（${p.employee_no}）` : ''}${p.department ? ` ${p.department}` : ''}`,
  }))

  // 按请检日期分组（今天 / 之后按日期）
  const groups = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const map = new Map<string, PlanBoardItem[]>()
    for (const p of plans) {
      const key = p.plan_time.slice(0, 10)
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(p)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([date, items]) => ({
      date,
      label: date === today ? '今天' : date,
      items: items.sort((a, b) => a.plan_time.localeCompare(b.plan_time)),
    }))
  }, [plans])

  const onAssign = async (plan: PlanBoardItem, sopNo: string, assigneeId: string | undefined) => {
    if (!canAssign) return
    const existing = plan.assignments
      .filter((a) => a.sop_no !== sopNo)
      .map((a) => ({ sop_no: a.sop_no, assignee_id: a.assignee_id }))
    if (assigneeId) existing.push({ sop_no: sopNo, assignee_id: assigneeId })
    try {
      const res = await savePlanAssignments(plan.plan_id, existing)
      message.success(res.message)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '排班保存失败')
    }
  }

  const statusMeta: Record<string, { label: string; color: string }> = {
    pending: { label: '待请检', color: 'gold' },
    inspected: { label: '已请检', color: 'blue' },
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        <Text type="secondary" style={{ fontSize: 12.5 }}>
          <TeamOutlined /> 今天及以后的请检任务排班：每个 SOP 选人，分配后人员名字显示在计划下方；建任务后分工自动带到检验任务
        </Text>
      </Space>

      {groups.length === 0 && !loading && (
        <Empty description="今天及以后没有请检计划（可在「检验填报 → 请检计划」页新增）" />
      )}

      {groups.map((g) => (
        <div key={g.date} style={{ marginBottom: 18 }}>
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 8 }}>
            {g.label}
            <Text type="secondary" style={{ marginLeft: 6, fontSize: 12 }}>{g.items.length} 个请检任务</Text>
          </div>
          <Space direction="vertical" style={{ width: '100%' }} size={10}>
            {g.items.map((plan) => {
              const bySop = new Map(plan.assignments.map((a) => [a.sop_no, a]))
              return (
                <Card
                  key={plan.plan_id}
                  size="small"
                  style={{ cursor: plan.task_id ? 'pointer' : undefined }}
                  onClick={() => plan.task_id && router.push(`/quality/task/${plan.task_id}`)}
                  title={
                    <Space size={6} wrap>
                      <Text strong>{plan.product_name}</Text>
                      {plan.batch_no && <Text type="secondary">批号 {plan.batch_no}</Text>}
                      <Tag color={statusMeta[plan.status]?.color}>{statusMeta[plan.status]?.label ?? plan.status}</Tag>
                      {plan.task_id && <Tag color={plan.task_status === 'in_progress' ? 'cyan' : 'default'}>任务已建</Tag>}
                    </Space>
                  }
                  extra={
                    <Text type="secondary" style={{ fontSize: 12.5 }}>
                      {plan.department}｜请检 {plan.plan_time.slice(11)}
                    </Text>
                  }
                >
                  {/* 待检 SOP 行：逐 SOP 选人 */}
                  <Space direction="vertical" style={{ width: '100%' }} size={4}>
                    {plan.sops.map((sop) => {
                      const a = bySop.get(sop.sop_no)
                      return (
                        <div
                          key={sop.sop_no}
                          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Text code style={{ flex: '0 0 170px', fontSize: 11.5 }}>{sop.sop_no}</Text>
                          <Text style={{ flex: 1, fontSize: 12.5, minWidth: 0 }} ellipsis>
                            {sop.items.join('、')}
                          </Text>
                          {plan.task_id && (
                            <Tag color={sop.filled === sop.total && sop.total > 0 ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                              {sop.filled}/{sop.total}
                            </Tag>
                          )}
                          <Select
                            allowClear showSearch optionFilterProp="label"
                            size="small"
                            style={{ flex: '0 0 240px' }}
                            placeholder={canAssign ? '选择负责人员' : '未分配'}
                            disabled={!canAssign}
                            value={a?.assignee_id}
                            onChange={(v) => onAssign(plan, sop.sop_no, v)}
                            options={personOptions}
                          />
                        </div>
                      )
                    })}
                    {plan.sops.length === 0 && <Text type="secondary">暂无 SOP（建任务后显示项目，或检查产品标准）</Text>}
                  </Space>

                  {/* 任务下显示人员名字 */}
                  {plan.assignments.length > 0 && (
                    <div style={{ marginTop: 8, borderTop: '1px dashed #eee', paddingTop: 6, fontSize: 12.5 }}>
                      <Text type="secondary">已排班：</Text>
                      {plan.assignments.map((a, i) => (
                        <span key={a.sop_no}>
                          {i > 0 && <Text type="secondary">、</Text>}
                          <Text strong>{a.assignee_name ?? '未知'}</Text>
                          <Text type="secondary">→{a.sop_no}</Text>
                        </span>
                      ))}
                    </div>
                  )}
                </Card>
              )
            })}
          </Space>
        </div>
      ))}
    </>
  )
}

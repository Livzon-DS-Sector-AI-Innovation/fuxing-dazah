'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Progress, Select, Space, Tag, Typography } from 'antd'
import { ReloadOutlined, SettingOutlined, TeamOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { PersonnelItem, PlanBoardItem } from '@/types/quality'
import {
  fetchPlanBoard, fetchPersonnel, savePlanAssignments,
  fetchShiftTeams, createShiftTeam, updateShiftTeam, deleteShiftTeam,
  fetchShiftConfig, saveShiftConfig, fetchShiftDuty,
} from '@/actions/quality'

const { Text } = Typography

/** 请检任务排班看板：今天及以后的请检计划，按计划展示待检 SOP，逐 SOP 选人排班，人员名字显示在计划下。 */
export default function TaskBoard() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [plans, setPlans] = useState<PlanBoardItem[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [shiftTeams, setShiftTeams] = useState<{ id: string; name: string; member_ids: string[]; member_names: string[]; seq: number }[]>([])
  const [shiftConfig, setShiftConfig] = useState<{ start_date: string | null; period_days: number; duty_teams: number } | null>(null)
  const [duty, setDuty] = useState<{ teams: { id: string; name: string }[]; members: { id: string; name: string }[] } | null>(null)
  const [shiftOpen, setShiftOpen] = useState(false)
  const [shiftSaving, setShiftSaving] = useState(false)
  const [shiftForm] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [boardRes, personRes, teamsRes, dutyRes] = await Promise.all([
        fetchPlanBoard(),
        fetchPersonnel(),
        fetchShiftTeams().catch(() => null),
        fetchShiftDuty().catch(() => null),
      ])
      setPlans(boardRes.data)
      setPersonnel(personRes.data.items ?? [])
      setShiftTeams(teamsRes?.data ?? [])
      setDuty(dutyRes?.data ?? null)
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
  const dutyIds = new Set(duty?.members.map((m) => m.id) ?? [])
  const dutyOptions = personOptions.filter((o) => dutyIds.has(o.value))
  const otherOptions = personOptions.filter((o) => !dutyIds.has(o.value))
  const groupedPersonOptions = [
    ...(dutyOptions.length
      ? [{ label: `今日当班（${duty?.teams.map((t) => t.name).join('+') ?? ''}）`, options: dutyOptions }]
      : []),
    ...(otherOptions.length ? [{ label: '其他人员', options: otherOptions }] : []),
  ]

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

  const openShiftConfig = () => {
    void Promise.all([fetchShiftTeams(), fetchShiftConfig()]).then(([t, c]) => {
      setShiftTeams(t.data)
      setShiftConfig(c.data)
      setShiftOpen(true)
    }).catch(() => message.error('获取班组配置失败'))
  }

  const onSaveShift = async () => {
    const values = await shiftForm.validateFields()
    setShiftSaving(true)
    try {
      await saveShiftConfig({
        start_date: (values.start_date as Dayjs).format('YYYY-MM-DD'),
        period_days: values.period_days ?? 3,
        duty_teams: values.duty_teams ?? 2,
      })
      message.success('轮换配置已保存')
      setShiftOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setShiftSaving(false)
    }
  }

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
        {canAssign && (
          <Button icon={<SettingOutlined />} onClick={openShiftConfig}>班组配置</Button>
        )}
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
                            options={groupedPersonOptions}
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

      <Modal
        title="班组排班配置"
        open={shiftOpen}
        onCancel={() => setShiftOpen(false)}
        onOk={onSaveShift}
        confirmLoading={shiftSaving}
        okText="保存轮换配置"
        width={680}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          班组固定成员、每 {shiftConfig?.period_days ?? 3} 天交替、同时 {shiftConfig?.duty_teams ?? 2} 个班组当班；排班选人时「今日当班」人员排在最前。
        </Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%' }} size={10}>
          {shiftTeams.map((team) => (
            <div key={team.id} style={{ border: '1px solid #eee', borderRadius: 8, padding: 8 }}>
              <Space wrap size={6} align="center">
                <Text strong style={{ width: 110 }}>{team.name}</Text>
                <Select
                  mode="multiple" showSearch optionFilterProp="label"
                  style={{ minWidth: 380 }}
                  placeholder="选择班组成员"
                  value={team.member_ids}
                  onChange={(v) => {
                    void updateShiftTeam(team.id, {
                      name: team.name, seq: team.seq, member_ids: v,
                    }).then(() => {
                      setShiftTeams((ts) => ts.map((x) => x.id === team.id ? { ...x, member_ids: v } : x))
                      message.success(`${team.name} 成员已更新`)
                    }).catch((e: unknown) => message.error((e instanceof Error ? e.message : String(e)) || '更新失败'))
                  }}
                  options={personOptions}
                  maxTagCount={5}
                />
                <Button size="small" danger onClick={() => {
                  void deleteShiftTeam(team.id).then(() => {
                    setShiftTeams((ts) => ts.filter((x) => x.id !== team.id))
                    message.success('已删除')
                  })
                }}>删除</Button>
              </Space>
            </div>
          ))}
          <Space size={6}>
            <Input placeholder="新班组名" style={{ width: 130 }} id="shift-team-name" />
            <Button onClick={() => {
              const name = (document.getElementById('shift-team-name') as HTMLInputElement).value.trim()
              if (!name) { message.warning('请输入班组名'); return }
              void createShiftTeam({ name, member_ids: [], seq: shiftTeams.length }).then(() => {
                message.success('班组已创建，请在下方选择成员')
                void fetchShiftTeams().then((t) => setShiftTeams(t.data))
                ;(document.getElementById('shift-team-name') as HTMLInputElement).value = ''
              })
            }}>新增班组</Button>
          </Space>
          <Form form={shiftForm} layout="inline" initialValues={{
            start_date: shiftConfig?.start_date ? dayjs(shiftConfig.start_date) : undefined,
            period_days: shiftConfig?.period_days ?? 3,
            duty_teams: shiftConfig?.duty_teams ?? 2,
          }}>
            <Form.Item name="start_date" label="轮换基准日" rules={[{ required: true, message: '必填' }]}>
              <DatePicker />
            </Form.Item>
            <Form.Item name="period_days" label="周期(天)">
              <InputNumber min={1} max={30} />
            </Form.Item>
            <Form.Item name="duty_teams" label="当班班组数">
              <InputNumber min={1} max={5} />
            </Form.Item>
          </Form>
          {duty && duty.teams.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12.5 }}>
              今日当班：{duty.teams.map((t) => t.name).join('、')}（{duty.members.length} 人）
            </Text>
          )}
        </Space>
      </Modal>
    </>
  )
}

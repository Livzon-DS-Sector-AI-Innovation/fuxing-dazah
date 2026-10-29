'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Progress, Select, Space, Tabs, Tag, Typography } from 'antd'
import { ReloadOutlined, SettingOutlined, TeamOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { PersonnelItem, PlanBoardItem } from '@/types/quality'
import {
  fetchPlanBoard, fetchPersonnel, savePlanAssignments,
  fetchShiftTeams, createShiftTeam, updateShiftTeam, deleteShiftTeam,
  fetchShiftConfig, saveShiftConfig, fetchShiftGroups, saveShiftItemGroups,
} from '@/actions/quality'

const { Text } = Typography

const GROUP_COLORS: Record<string, string> = {
  仪器组: 'geekblue',
  生物组: 'green',
  理化组: 'orange',
}

function itemGroupOf(name: string, mapping: Record<string, string[]>): string {
  for (const [group, keywords] of Object.entries(mapping)) {
    for (const kw of keywords) {
      if (kw && name.includes(kw)) return group
    }
  }
  return '理化组'
}

/** 请检任务排班看板：今天及以后的请检计划，按 SOP 组别从对应组当班人员中选人排班。 */
export default function TaskBoard() {
  const router = useRouter()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [plans, setPlans] = useState<PlanBoardItem[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [shiftTeams, setShiftTeams] = useState<{ id: string; name: string; group_key: string; member_ids: string[]; member_names: string[]; seq: number }[]>([])
  const [groups, setGroups] = useState<{ group: string; configured: boolean; teams: { id: string; name: string }[]; members: { id: string; name: string }[] }[]>([])
  const [mapping, setMapping] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false)
  const [shiftOpen, setShiftOpen] = useState(false)
  const [shiftSaving, setShiftSaving] = useState(false)
  const [activeGroup, setActiveGroup] = useState('仪器组')
  const [shiftForm] = Form.useForm()
  const [mappingDrafts, setMappingDrafts] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [boardRes, personRes, teamsRes, groupsRes] = await Promise.all([
        fetchPlanBoard(),
        fetchPersonnel(),
        fetchShiftTeams().catch(() => null),
        fetchShiftGroups().catch(() => null),
      ])
      setPlans(boardRes.data)
      setPersonnel(personRes.data.items ?? [])
      setShiftTeams(teamsRes?.data ?? [])
      setGroups(groupsRes?.data.groups ?? [])
      setMapping(groupsRes?.data.mapping ?? {})
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

  // 组别 → 当班成员
  const groupMembers = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const g of groups) m.set(g.group, g.members.map((x) => x.id))
    return m
  }, [groups])

  const optionsForGroup = (group: string) => {
    const ids = groupMembers.get(group)
    if (ids && ids.length > 0) return personOptions.filter((o) => ids.includes(o.value))
    return personOptions
  }

  const openShiftConfig = () => {
    void Promise.all([fetchShiftTeams(), fetchShiftGroups()]).then(([t, g]) => {
      setShiftTeams(t.data)
      setGroups(g.data.groups)
      setMapping(g.data.mapping)
      setMappingDrafts(Object.fromEntries(Object.entries(g.data.mapping).map(([k, v]) => [k, v.join('、')])))
      setActiveGroup(g.data.groups[0]?.group ?? '仪器组')
      setShiftOpen(true)
    }).catch(() => message.error('获取班组配置失败'))
  }

  const onSaveShift = async () => {
    const values = await shiftForm.validateFields()
    setShiftSaving(true)
    try {
      await saveShiftConfig({
        group: activeGroup,
        start_date: (values.start_date as Dayjs).format('YYYY-MM-DD'),
        period_days: values.period_days ?? 3,
        duty_teams: values.duty_teams ?? 2,
      })
      message.success(`${activeGroup}轮换配置已保存`)
      setShiftOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存失败')
    } finally {
      setShiftSaving(false)
    }
  }

  const onSaveMapping = async () => {
    const mappingOut: Record<string, string[]> = {}
    for (const [k, v] of Object.entries(mappingDrafts)) {
      mappingOut[k] = v.split(/[、,，\s]+/).filter(Boolean)
    }
    try {
      await saveShiftItemGroups(mappingOut)
      message.success('项目组别映射已保存')
      setMapping(mappingOut)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '保存映射失败')
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

  const groupTabs = useMemo(() => {
    const seen = [...new Set([
      ...groups.map((g) => g.group),
      ...Object.keys(mapping),
    ])]
    return seen.length ? seen : ['仪器组', '生物组', '理化组']
  }, [groups, mapping])

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        {canAssign && (
          <Button icon={<SettingOutlined />} onClick={openShiftConfig}>班组配置</Button>
        )}
        <Text type="secondary" style={{ fontSize: 12.5 }}>
          <TeamOutlined /> 今天及以后的请检任务排班：SOP 按组别（仪器组/生物组/理化组）从对应组当班人员中选人；建任务后分工自动带到检验任务
        </Text>
      </Space>

      {plans.length === 0 && !loading && (
        <Empty description="今天及以后没有请检计划（可在「检验填报 → 请检计划」页新增）" />
      )}

      {plans.map((plan) => {
        const bySop = new Map(plan.assignments.map((a) => [a.sop_no, a]))
        return (
          <Card
            key={plan.plan_id}
            size="small"
            style={{ marginBottom: 10, cursor: plan.task_id ? 'pointer' : undefined }}
            onClick={() => plan.task_id && router.push(`/quality/task/${plan.task_id}`)}
            title={
              <Space size={6} wrap>
                <Text strong>{plan.product_name}</Text>
                {plan.batch_no && <Text type="secondary">批号 {plan.batch_no}</Text>}
                <Tag color={statusMeta[plan.status]?.color}>{statusMeta[plan.status]?.label ?? plan.status}</Tag>
                {plan.task_id && <Tag color="cyan">任务已建</Tag>}
              </Space>
            }
            extra={
              <Text type="secondary" style={{ fontSize: 12.5 }}>
                {plan.department}｜请检 {plan.plan_time.slice(5, 16).replace('T', ' ')}
              </Text>
            }
          >
            <Space direction="vertical" style={{ width: '100%' }} size={4}>
              {plan.sops.map((sop) => {
                const a = bySop.get(sop.sop_no)
                const group = itemGroupOf(sop.items.join(' '), mapping)
                const options = optionsForGroup(group)
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
                    <Tag color={GROUP_COLORS[group] ?? 'default'} style={{ marginInlineEnd: 0 }}>{group}</Tag>
                    {plan.task_id && (
                      <Tag color={sop.filled === sop.total && sop.total > 0 ? 'green' : 'orange'} style={{ marginInlineEnd: 0 }}>
                        {sop.filled}/{sop.total}
                      </Tag>
                    )}
                    <Select
                      allowClear showSearch optionFilterProp="label"
                      size="small"
                      style={{ flex: '0 0 220px' }}
                      placeholder={canAssign ? `从${group}当班人员中选择` : '未分配'}
                      disabled={!canAssign}
                      value={a?.assignee_id}
                      onChange={(v) => onAssign(plan, sop.sop_no, v)}
                      options={options}
                    />
                  </div>
                )
              })}
              {plan.sops.length === 0 && <Text type="secondary">暂无 SOP（建任务后显示项目，或检查产品标准）</Text>}
            </Space>
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

      <Modal
        title="班组与组别配置"
        open={shiftOpen}
        onCancel={() => setShiftOpen(false)}
        onOk={onSaveShift}
        confirmLoading={shiftSaving}
        okText="保存轮换配置"
        width={760}
      >
        <Tabs
          activeKey={activeGroup}
          onChange={(k) => setActiveGroup(k)}
          items={groupTabs.map((g) => ({
            key: g,
            label: g,
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
                <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, margin: 0 }}>
                  {g}班组固定成员、每 3 天交替、同时 2 个班组当班（各组独立轮换）。
                </Typography.Paragraph>
                {shiftTeams.filter((t) => t.group_key === g).map((team) => (
                  <div key={team.id} style={{ border: '1px solid #eee', borderRadius: 8, padding: 8 }}>
                    <Space wrap size={6} align="center">
                      <Text strong style={{ width: 90 }}>{team.name}</Text>
                      <Select
                        mode="multiple" showSearch optionFilterProp="label"
                        style={{ minWidth: 360 }}
                        placeholder="选择班组成员"
                        value={team.member_ids}
                        onChange={(v) => {
                          void updateShiftTeam(team.id, {
                            name: team.name, group_key: g, seq: team.seq, member_ids: v,
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
                  <Input placeholder={`新班组名（${g}）`} style={{ width: 150 }} id={`shift-team-name-${g}`} />
                  <Button onClick={() => {
                    const name = (document.getElementById(`shift-team-name-${g}`) as HTMLInputElement).value.trim()
                    if (!name) { message.warning('请输入班组名'); return }
                    void createShiftTeam({ name, group_key: g, member_ids: [], seq: shiftTeams.filter((t) => t.group_key === g).length }).then(() => {
                      message.success('班组已创建')
                      void fetchShiftTeams().then((t) => setShiftTeams(t.data))
                      ;(document.getElementById(`shift-team-name-${g}`) as HTMLInputElement).value = ''
                    })
                  }}>新增班组</Button>
                </Space>
                <Form form={shiftForm} layout="inline">
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
                {groups.find((x) => x.group === g) && (
                  <Text type="secondary" style={{ fontSize: 12.5 }}>
                    今日当班：{groups.find((x) => x.group === g)!.teams.map((t) => t.name).join('、') || '未配置'}（{groups.find((x) => x.group === g)!.members.length} 人）
                  </Text>
                )}
              </Space>
            ),
          }))}
        />
        <Typography.Paragraph strong style={{ marginTop: 12, marginBottom: 4 }}>项目组别映射（项目名关键词 → 组别）</Typography.Paragraph>
        <Space direction="vertical" style={{ width: '100%' }} size={6}>
          {Object.keys(mappingDrafts).map((g) => (
            <div key={g} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text strong style={{ width: 64 }}>{g}</Text>
              <Input
                style={{ flex: 1 }}
                value={mappingDrafts[g]}
                onChange={(e) => setMappingDrafts((m) => ({ ...m, [g]: e.target.value }))}
                placeholder="关键词，顿号分隔（如 杂质、含量、有关物质）"
              />
            </div>
          ))}
          <Button size="small" onClick={onSaveMapping}>保存组别映射</Button>
        </Space>
      </Modal>
    </>
  )
}

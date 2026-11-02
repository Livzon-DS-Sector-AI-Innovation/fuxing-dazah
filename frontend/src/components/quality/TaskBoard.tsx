'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Card, DatePicker, Empty, Form, Input, InputNumber, Modal, Select, Space, Tabs, Tag, Typography } from 'antd'
import { ReloadOutlined, SettingOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { useRouter } from 'next/navigation'
import { usePermission } from '@/hooks/usePermission'
import type { PersonnelItem, PlanBoardItem } from '@/types/quality'
import {
  fetchPlanBoard, fetchPersonnel, savePlanAssignments, notifyPlanAssignments,
  fetchShiftTeams, createShiftTeam, updateShiftTeam, deleteShiftTeam,
  fetchShiftConfig, saveShiftConfig, fetchShiftGroups, saveShiftItemGroups,
} from '@/actions/quality'

const { Text } = Typography

const GROUP_COLORS: Record<string, string> = {
  仪器组: 'geekblue',
  生物组: 'green',
  理化组: 'orange',
}

/** 弹窗内与组别页签平级的「全局配置」页签 key（不与组名冲突） */
const CONFIG_TAB_KEY = '__global-config'

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
  const { message, modal } = App.useApp()
  const { hasPermission } = usePermission()
  const canAssign = hasPermission('quality:task:create')
  const [plans, setPlans] = useState<PlanBoardItem[]>([])
  const [personnel, setPersonnel] = useState<PersonnelItem[]>([])
  const [shiftTeams, setShiftTeams] = useState<{ id: string; name: string; group_key: string; member_ids: string[]; member_names: string[]; seq: number }[]>([])
  const [groups, setGroups] = useState<{ group: string; configured: boolean; teams: { id: string; name: string }[]; members: { id: string; name: string }[]; all_members: { id: string; name: string }[] }[]>([])
  const [mapping, setMapping] = useState<Record<string, string[]>>({})
  const [scopeGroups, setScopeGroups] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [shiftOpen, setShiftOpen] = useState(false)
  const [shiftSaving, setShiftSaving] = useState(false)
  const [activeGroup, setActiveGroup] = useState('仪器组')
  const [shiftForm] = Form.useForm()
  const [mappingDrafts, setMappingDrafts] = useState<Record<string, string>>({})
  // 自定义轮换顺序：勾选先后即轮换先后（空=按班组创建顺序滑窗）
  const [teamOrder, setTeamOrder] = useState<string[]>([])
  // 班组配置弹窗的组别范围：编入班组的用户只能看/管本组（空=不限）
  const [configScopeGroups, setConfigScopeGroups] = useState<string[]>([])

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
      setScopeGroups(boardRes.meta?.scope_groups ?? [])
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

  // 组别 → 全部成员（选人范围）；今日当班成员（置顶标注）
  const groupAllMembers = useMemo(() => {
    const m = new Map<string, string[]>()
    for (const g of groups) m.set(g.group, g.all_members.map((x) => x.id))
    return m
  }, [groups])

  const groupDutyIds = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const g of groups) m.set(g.group, new Set(g.members.map((x) => x.id)))
    return m
  }, [groups])

  const optionsForGroup = (group: string) => {
    const ids = groupAllMembers.get(group)
    if (!ids || ids.length === 0) return []
    const duty = groupDutyIds.get(group)
    return personOptions
      .filter((o) => ids.includes(o.value))
      .map((o) => duty?.has(o.value) ? { ...o, label: `${o.label}（今日当班）` } : o)
      .sort((a, b) => Number(duty?.has(b.value)) - Number(duty?.has(a.value)))
  }

  const openShiftConfig = () => {
    void Promise.all([fetchShiftTeams(), fetchShiftGroups(), fetchShiftConfig()]).then(([t, g, c]) => {
      setShiftTeams(t.data)
      setGroups(g.data.groups)
      setMapping(g.data.mapping)
      setMappingDrafts(Object.fromEntries(Object.entries(g.data.mapping).map(([k, v]) => [k, v.join('、')])))
      shiftForm.setFieldsValue({
        start_date: c.data.start_date ? dayjs(c.data.start_date) : undefined,
        period_days: c.data.period_days ?? 3,
        duty_teams: c.data.duty_teams ?? 2,
      })
      setTeamOrder((c.data.team_order ?? []).filter((n): n is string => typeof n === 'string'))
      const scope = g.meta?.scope_groups ?? []
      setConfigScopeGroups(scope)
      const groupNames = g.data.groups.map((x) => x.group)
      const firstVisible = scope.length
        ? scope.find((x) => groupNames.includes(x)) ?? groupNames[0] ?? scope[0]
        : groupNames[0] ?? '仪器组'
      setActiveGroup(firstVisible)
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
        team_order: teamOrder,
      })
      message.success('轮换配置已保存')
      // 只刷新今日当班预览，保留未保存的映射草稿
      setGroups((await fetchShiftGroups()).data.groups)
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

  // 管理员确认后才向被排班人发飞书通知
  const onNotify = (plan: PlanBoardItem) => {
    modal.confirm({
      title: '下发排班通知',
      content: `确定向「${plan.product_name}」的已排班人员（${plan.assignments.length} 个 SOP）发送飞书通知吗？`,
      okText: '确认下发',
      onOk: async () => {
        try {
          const res = await notifyPlanAssignments(plan.plan_id)
          message.success(res.message)
          load()
        } catch (err: unknown) {
          message.error((err instanceof Error ? err.message : String(err)) || '通知下发失败')
        }
      },
    })
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

  // 轮换顺序候选：班组名去重，标签标注该班组存在于哪些组别（全局按名称对各组生效）
  const teamOrderOptions = useMemo(() => {
    const byName = new Map<string, string[]>()
    for (const t of shiftTeams) {
      const groups = byName.get(t.name) ?? []
      if (!groups.includes(t.group_key)) groups.push(t.group_key)
      byName.set(t.name, groups)
    }
    return [...byName.entries()].map(([name, groups]) => ({
      value: name,
      label: `${name}（${groups.join('、')}）`,
    }))
  }, [shiftTeams])

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        {canAssign && (
          <Button icon={<SettingOutlined />} onClick={openShiftConfig}>班组配置</Button>
        )}
        {scopeGroups.length > 0 && (
          <Tag color="geekblue">
            仅显示本组（{scopeGroups.join('、')}）排班内容
          </Tag>
        )}
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
                {plan.status === 'pending' && dayjs(plan.plan_time).isBefore(dayjs().startOf('day')) && (
                  <Tag color="red">已过期</Tag>
                )}
                {plan.task_id && <Tag color="cyan">任务已建</Tag>}
              </Space>
            }
            extra={
              <Space size={6}>
                <Text type="secondary" style={{ fontSize: 12.5 }}>
                  {plan.department}｜请检 {plan.plan_time.slice(5, 16).replace('T', ' ')}
                </Text>
                {canAssign && plan.assignments.length > 0 && (
                  <Button
                    size="small"
                    type={plan.notified_at ? 'link' : 'primary'}
                    onClick={(e) => { e.stopPropagation(); onNotify(plan) }}
                  >
                    {plan.notified_at ? `已下发 ${plan.notified_at.slice(5, 16)}` : '下发排班通知'}
                  </Button>
                )}
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: '100%' }} size={4}>
              {plan.sops.map((sop) => {
                const a = bySop.get(sop.sop_no)
                const group = itemGroupOf(sop.items.join(' '), mapping)
                const baseOptions = optionsForGroup(group)
                // 历史排班的人已不在本组名单/未配班组时兜底显示姓名（仅可清除）
                const options = a?.assignee_id && !baseOptions.some((o) => o.value === a.assignee_id)
                  ? [{ value: a.assignee_id, label: personOptions.find((p) => p.value === a.assignee_id)?.label ?? a.assignee_id }, ...baseOptions]
                  : baseOptions
                const unconfigured = baseOptions.length === 0
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
                      placeholder={!canAssign ? '未分配' : unconfigured ? `${group}未配置班组` : `从${group}班组人员中选择`}
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
        onCancel={() => { setShiftOpen(false); load() }}
        footer={null}
        width={760}
      >
        <Tabs
          activeKey={activeGroup}
          onChange={(k) => setActiveGroup(k)}
          items={[...groupTabs
            .filter((g) => configScopeGroups.length === 0 || configScopeGroups.includes(g))
            .map((g) => ({
            key: g,
            label: g,
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
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
              </Space>
            ),
          })),
            ...(configScopeGroups.length === 0 ? [{
              key: CONFIG_TAB_KEY,
              label: '全局配置',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={12}>
                  <Card size="small" title="轮换配置（全局，所有组共用）">
                    <Form form={shiftForm} layout="inline" style={{ marginBottom: 8 }}>
                      <Form.Item name="start_date" label="轮换基准日" rules={[{ required: true, message: '必填' }]}>
                        <DatePicker />
                      </Form.Item>
                      <Form.Item name="period_days" label="周期(天)">
                        <InputNumber min={1} max={30} />
                      </Form.Item>
                      <Form.Item name="duty_teams" label="当班班组数">
                        <InputNumber min={1} max={5} />
                      </Form.Item>
                      <Form.Item>
                        <Button type="primary" loading={shiftSaving} onClick={onSaveShift}>保存</Button>
                      </Form.Item>
                    </Form>
                    <Text strong style={{ fontSize: 12.5, display: 'block', marginBottom: 4 }}>
                      轮换顺序（勾选先后即轮换先后，勾一次长期生效）
                    </Text>
                    <Select
                      mode="multiple" allowClear showSearch optionFilterProp="label"
                      style={{ width: '100%' }}
                      placeholder="勾选班组并排先后顺序；留空则按班组创建顺序轮换"
                      value={teamOrder}
                      onChange={(v: string[]) => setTeamOrder(v)}
                      options={teamOrderOptions}
                    />
                    <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, marginTop: 6, marginBottom: 8 }}>
                      从基准日起每「周期(天)」天向后滑一位，取「当班班组数」个班组当班，按此顺序循环；
                      该顺序按班组名对所有组别生效（各组轮换自己的班组），未勾选的班组不参与轮换。
                    </Typography.Paragraph>
                    {groups.length > 0 && (
                      <div style={{ fontSize: 13 }}>
                        <Text type="secondary">今日当班：</Text>
                        {groups.map((g) => (
                          <span key={g.group} style={{ marginRight: 14 }}>
                            <Tag color={GROUP_COLORS[g.group] ?? 'default'}>{g.group}</Tag>
                            {g.teams.map((t) => t.name).join('+') || '未配置'}（{g.members.length} 人）
                          </span>
                        ))}
                      </div>
                    )}
                  </Card>
                  <Card size="small" title="项目组别映射（项目名关键词 → 组别）">
                    <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, marginBottom: 8 }}>
                      SOP 的项目名称命中关键词即归属对应组别，排班选人限定在该组班组成员内；未命中默认归理化组。
                    </Typography.Paragraph>
                    <Space direction="vertical" style={{ width: '100%' }} size={8}>
                      {Object.keys(mappingDrafts).map((g) => (
                        <div key={g} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Tag color={GROUP_COLORS[g] ?? 'default'} style={{ width: 64, textAlign: 'center', marginInlineEnd: 0 }}>{g}</Tag>
                          <Input
                            style={{ flex: 1 }}
                            value={mappingDrafts[g]}
                            onChange={(e) => setMappingDrafts((m) => ({ ...m, [g]: e.target.value }))}
                            placeholder="关键词，顿号分隔（如 杂质、含量、有关物质）"
                          />
                        </div>
                      ))}
                      {canAssign && (
                        <Button type="primary" size="small" style={{ width: 120 }} onClick={onSaveMapping}>保存组别映射</Button>
                      )}
                    </Space>
                  </Card>
                </Space>
              ),
            }] : []),
          ]}
        />
      </Modal>
    </>
  )
}

'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Alert, App, Button, DatePicker, Drawer, Form, Input, Radio, Select, Space, Spin, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { EditOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { patchCapaAction, transitionCapa, updateCapa } from '@/actions/qa-deviation'
import { usePermission } from '@/hooks/usePermission'
import { fetchCapa } from '@/lib/api/qa-deviation'
import {
  CAPA_ACTION_STATUS_LABEL,
  CAPA_ACTION_TYPE_LABEL,
  CAPA_STATUS_LABEL,
  DEVIATION_ACTION_LABEL,
  EFFECT_CONCLUSION_LABEL,
  EFFECT_METHOD_LABEL,
  type CapaActionItem,
  type CapaActionStatus,
  type CapaDetail,
  type CapaStatus,
  type CapaTransitionAction,
  type EffectConclusion,
  type EffectMethod,
} from '@/types/qa-deviation'
import { SectionCard } from '../deviation/DeviationSections'
import { TimelineCard } from '../deviation/DeviationSideBlocks'
import { CapaStatusPill, Field, PILL, SeverityPill, actionError, fieldGrid, fmtDate, fmtDateTime, toOptions } from '../deviation/shared'
import { CapaFormModal } from './CapaFormModal'

const NEXT_ACTION: Partial<Record<CapaStatus, CapaTransitionAction>> = {
  planned: 'start',
  in_progress: 'complete',
  completed: 'start_evaluation',
  effect_evaluating: 'close',
}

const NEXT_HINT: Record<CapaTransitionAction, string> = {
  start: '开始实施前至少要有一条措施。',
  complete: '所有措施标记为已完成后才能进入这一步；完成日期将作为有效性跟踪周期的起点。',
  start_evaluation: '跟踪周期到期后开始回顾评估，需先填写评估方式。',
  close: '仅当有效性结论为「有效」且填写了回顾评估结果时可关闭；结论为无效应发起追加 CAPA。',
}

interface EffectFormValues {
  effect_method?: EffectMethod | null
  effect_plan?: string
  effect_due_date?: Dayjs | null
  effect_result?: string
  effect_conclusion?: EffectConclusion | null
}

function EffectForm({ capa, onSaved, onCancel }: { capa: CapaDetail; onSaved: () => void; onCancel: () => void }) {
  const { message } = App.useApp()
  const [form] = Form.useForm<EffectFormValues>()
  const [saving, setSaving] = useState(false)

  const handleFinish = async (values: EffectFormValues) => {
    setSaving(true)
    try {
      const result = await updateCapa(capa.id, {
        effect_method: values.effect_method ?? null,
        effect_plan: values.effect_plan?.trim() || null,
        effect_due_date: values.effect_due_date ? values.effect_due_date.format('YYYY-MM-DD') : null,
        effect_result: values.effect_result?.trim() || null,
        effect_conclusion: values.effect_conclusion ?? null,
      })
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success('有效性评估已保存')
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={handleFinish}
      initialValues={{
        effect_method: capa.effect_method,
        effect_plan: capa.effect_plan ?? undefined,
        effect_due_date: capa.effect_due_date ? dayjs(capa.effect_due_date) : null,
        effect_result: capa.effect_result ?? undefined,
        effect_conclusion: capa.effect_conclusion,
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr 160px', gap: '0 12px' }}>
        <Form.Item name="effect_method" label="评估方式">
          <Select options={toOptions(EFFECT_METHOD_LABEL)} allowClear />
        </Form.Item>
        <Form.Item name="effect_plan" label="方案说明">
          <Input maxLength={4000} />
        </Form.Item>
        <Form.Item name="effect_due_date" label="评估到期日">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
      </div>
      <Form.Item name="effect_result" label="回顾评估结果" extra="评估周期内是否再次发生类似事件、数据汇总分析">
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} maxLength={8000} />
      </Form.Item>
      <Form.Item name="effect_conclusion" label="有效性结论">
        <Radio.Group options={toOptions(EFFECT_CONCLUSION_LABEL)} />
      </Form.Item>
      <Space>
        <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
        <Button onClick={onCancel} disabled={saving}>取消</Button>
      </Space>
    </Form>
  )
}

/** CAPA 详情：措施进度、有效性评估、流转历史与状态推进。 */
export function CapaDetailDrawer({
  capaId,
  onClose,
  onChanged,
}: {
  capaId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  const { message, modal } = App.useApp()
  const { hasPermission } = usePermission()
  const canUpdate = hasPermission('qa:capa:update')
  const canCreate = hasPermission('qa:capa:create')

  const [editingEffect, setEditingEffect] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [followUpOpen, setFollowUpOpen] = useState(false)
  const [transitioning, setTransitioning] = useState(false)
  const queryClient = useQueryClient()

  const capaQuery = useQuery({
    queryKey: ['qa', 'capa', capaId],
    queryFn: () => fetchCapa(capaId as string),
    enabled: capaId !== null,
  })
  const capa = capaQuery.data ?? null
  const error = capaQuery.error ? (capaQuery.error instanceof Error ? capaQuery.error.message : '加载 CAPA 失败') : null

  const refresh = () => {
    void capaQuery.refetch()
    void queryClient.invalidateQueries({ queryKey: ['qa', 'deviation'] })
    onChanged()
  }

  const closed = capa?.status === 'closed'
  const editable = Boolean(capa) && canUpdate && !closed

  const changeActionStatus = async (action: CapaActionItem, status: CapaActionStatus) => {
    if (!capa || !action.id) return
    const result = await patchCapaAction(capa.id, action.id, { status })
    if (!result.success) {
      message.error(actionError(result))
      return
    }
    refresh()
  }

  const runTransition = (action: CapaTransitionAction) => {
    if (!capa) return
    const run = async () => {
      setTransitioning(true)
      try {
        const result = await transitionCapa(capa.id, action)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success(`${DEVIATION_ACTION_LABEL[action]}成功`)
        refresh()
      } finally {
        setTransitioning(false)
      }
    }
    if (action === 'close') {
      modal.confirm({
        title: '关闭 CAPA',
        content: '关闭后 CAPA 内容将锁定不可编辑。确认有效性评估已完成并结论为有效？',
        okText: '关闭 CAPA',
        cancelText: '取消',
        onOk: run,
      })
      return
    }
    void run()
  }

  const actionColumns: ColumnsType<CapaActionItem> = [
    { title: '措施', dataIndex: 'content', render: (value: string, row) => (
      <div>
        <div style={{ whiteSpace: 'pre-wrap' }}>{value}</div>
        <span style={{ color: '#787671', fontSize: 12 }}>{CAPA_ACTION_TYPE_LABEL[row.action_type]}</span>
      </div>
    ) },
    { title: '责任', width: 140, render: (_, row) => [row.department_name, row.owner_name].filter(Boolean).join(' · ') || '—' },
    { title: '计划 / 实际完成', width: 150, render: (_, row) => (
      <div style={{ fontSize: 12 }}>
        <div>计划 {fmtDate(row.planned_date)}</div>
        <div style={{ color: row.actual_date ? '#1aae39' : '#787671' }}>实际 {fmtDate(row.actual_date)}</div>
      </div>
    ) },
    { title: '状态', width: 120, render: (_, row) => editable ? (
      <Select
        size="small"
        value={row.status}
        style={{ width: 110 }}
        options={toOptions(CAPA_ACTION_STATUS_LABEL)}
        onChange={(value) => void changeActionStatus(row, value)}
      />
    ) : (
      <span style={row.status === 'done' ? PILL.success : row.status === 'in_progress' ? PILL.info : PILL.neutral}>
        {CAPA_ACTION_STATUS_LABEL[row.status]}
      </span>
    ) },
  ]

  const nextAction = capa ? NEXT_ACTION[capa.status] : undefined
  const doneCount = capa?.actions.filter((action) => action.status === 'done').length ?? 0

  // 抽屉组件不会随关闭卸载；关闭时重置编辑态，避免泄漏到下一条 CAPA。
  const closeDrawer = () => {
    setEditingEffect(false)
    setEditOpen(false)
    setFollowUpOpen(false)
    onClose()
  }

  return (
    <Drawer
      open={capaId !== null}
      onClose={closeDrawer}
      size={880}
      destroyOnHidden
      title={
        capa ? (
          <Space size={10} wrap>
            <span>{capa.capa_no}</span>
            <CapaStatusPill status={capa.status} />
            <SeverityPill value={capa.severity} />
            {capa.is_overdue && <span style={PILL.error}>计划逾期</span>}
            {capa.effect_conclusion === 'ineffective' && <span style={PILL.error}>评估无效</span>}
          </Space>
        ) : 'CAPA 详情'
      }
      extra={
        capa && (
          <Space>
            {editable && <Button size="small" icon={<EditOutlined />} onClick={() => setEditOpen(true)}>编辑</Button>}
            {canCreate && capa.effect_conclusion === 'ineffective' && !closed && (
              <Button size="small" icon={<PlusOutlined />} onClick={() => setFollowUpOpen(true)}>追加 CAPA</Button>
            )}
            {editable && nextAction && (
              <Button size="small" type="primary" icon={<RightOutlined />} loading={transitioning} onClick={() => runTransition(nextAction)}>
                {DEVIATION_ACTION_LABEL[nextAction]}
              </Button>
            )}
          </Space>
        )
      }
    >
      {error && <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />}
      {!capa && !error && <div style={{ padding: 60, textAlign: 'center' }}><Spin /></div>}
      {capa && (
        <>
          {nextAction && !closed && (
            <Alert type="info" showIcon title={NEXT_HINT[nextAction]} style={{ marginBottom: 16 }} />
          )}
          <SectionCard title="基本信息">
            <div style={fieldGrid(2)}>
              <Field label="来源偏差" span={2}>
                {capa.deviation ? (
                  <Space size={8} wrap>
                    <Link href={`/qa/deviation/${capa.deviation.id}`} style={{ color: '#0075de', fontWeight: 600 }}>{capa.deviation.deviation_no}</Link>
                    <span style={{ color: '#5d5b54' }}>{capa.deviation.description}</span>
                  </Space>
                ) : null}
              </Field>
              {capa.parent_capa_no && <Field label="上游 CAPA" span={2}>{capa.parent_capa_no}</Field>}
              <Field label="问题及 CAPA 要求概述" span={2}>{capa.summary}</Field>
              <Field label="责任部门">{capa.responsible_department_name}</Field>
              <Field label="计划完成日期">{fmtDate(capa.planned_completion_date)}</Field>
              <Field label="发起日期">{fmtDateTime(capa.created_at)}</Field>
              <Field label="措施完成日期">{capa.completed_at ? fmtDateTime(capa.completed_at) : null}</Field>
              {capa.remark && <Field label="备注" span={2}>{capa.remark}</Field>}
              {capa.follow_up_capas.length > 0 && (
                <Field label="追加 CAPA" span={2}>
                  <Space size={8} wrap>
                    {capa.follow_up_capas.map((item) => (
                      <span key={item.id}>{item.capa_no}（{CAPA_STATUS_LABEL[item.status]}）</span>
                    ))}
                  </Space>
                </Field>
              )}
            </div>
          </SectionCard>

          <SectionCard title="措施明细" hint={`${doneCount}/${capa.actions.length} 已完成`}>
            <Table<CapaActionItem>
              rowKey={(row) => row.id ?? row.content}
              size="small"
              pagination={false}
              columns={actionColumns}
              dataSource={capa.actions}
              locale={{ emptyText: '尚未填写措施，点击右上角「编辑」添加' }}
            />
          </SectionCard>

          <SectionCard
            title="有效性评估"
            hint="措施完成后按方案跟踪，确认类似事件未再发生"
            extra={editable && !editingEffect && <Button size="small" icon={<EditOutlined />} onClick={() => setEditingEffect(true)}>填写评估</Button>}
          >
            {editingEffect ? (
              <EffectForm capa={capa} onSaved={() => { setEditingEffect(false); refresh() }} onCancel={() => setEditingEffect(false)} />
            ) : (
              <div style={fieldGrid(3)}>
                <Field label="评估方式">{capa.effect_method ? EFFECT_METHOD_LABEL[capa.effect_method] : null}</Field>
                <Field label="评估到期日">{fmtDate(capa.effect_due_date)}</Field>
                <Field label="有效性结论">
                  {capa.effect_conclusion ? (
                    <span style={capa.effect_conclusion === 'effective' ? PILL.success : PILL.error}>{EFFECT_CONCLUSION_LABEL[capa.effect_conclusion]}</span>
                  ) : null}
                </Field>
                <Field label="方案说明" span={3}>{capa.effect_plan}</Field>
                <Field label="回顾评估结果" span={3}>{capa.effect_result}</Field>
                {capa.evaluated_at && <Field label="评估时间">{fmtDateTime(capa.evaluated_at)}</Field>}
              </div>
            )}
          </SectionCard>

          <TimelineCard logs={capa.logs} statusLabels={CAPA_STATUS_LABEL} />

          {capa.deviation && (
            <>
              <CapaFormModal
                open={editOpen}
                onClose={() => setEditOpen(false)}
                onSaved={() => { setEditOpen(false); refresh() }}
                deviation={{ id: capa.deviation.id, deviation_no: capa.deviation.deviation_no }}
                editing={capa}
              />
              <CapaFormModal
                open={followUpOpen}
                onClose={() => setFollowUpOpen(false)}
                onSaved={() => { setFollowUpOpen(false); refresh() }}
                deviation={{
                  id: capa.deviation.id,
                  deviation_no: capa.deviation.deviation_no,
                  description: capa.deviation.description,
                  department_name: capa.deviation.department_name,
                }}
                parent={{ id: capa.id, capa_no: capa.capa_no }}
              />
            </>
          )}
        </>
      )}
    </Drawer>
  )
}

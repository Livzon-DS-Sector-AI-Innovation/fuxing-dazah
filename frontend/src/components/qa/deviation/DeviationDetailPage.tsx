'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Alert, App, Button, Card, Col, Row, Space, Spin, Steps, Tooltip } from 'antd'
import { ArrowLeftOutlined, ClockCircleOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { deleteDeviation } from '@/actions/qa-deviation'
import { usePermission } from '@/hooks/usePermission'
import { fetchDeviation } from '@/lib/api/qa-deviation'
import {
  DEVIATION_ACTION_LABEL,
  type DeviationStatus,
  type DeviationTransitionAction,
} from '@/types/qa-deviation'
import { CapaFormModal } from '../capa/CapaFormModal'
import { ExtendModal, TransitionModal } from './DeviationDialogs'
import { AssessmentSection, InvestigationSection, ReportSection } from './DeviationSections'
import { AttachmentsCard, TimelineCard } from './DeviationSideBlocks'
import {
  CapaStatusPill,
  ClassificationPill,
  DeviationStatusPill,
  Field,
  PILL,
  SeverityPill,
  actionError,
  cardStyle,
  cardStyles,
  fieldGrid,
  fmtDate,
  fmtDateTime,
} from './shared'

const STAGE_ORDER: DeviationStatus[] = ['draft', 'investigating', 'assessing', 'closed']
const NEXT_ACTION: Partial<Record<DeviationStatus, DeviationTransitionAction>> = {
  draft: 'start_investigation',
  investigating: 'submit_assessment',
  assessing: 'close',
}

export function DeviationDetailPage({ id }: { id: string }) {
  const { message, modal } = App.useApp()
  const router = useRouter()
  const { hasPermission } = usePermission()
  const canUpdate = hasPermission('qa:deviation:update')
  const canCreateCapa = hasPermission('qa:capa:create')

  const [action, setAction] = useState<DeviationTransitionAction | null>(null)
  const [extendOpen, setExtendOpen] = useState(false)
  const [capaOpen, setCapaOpen] = useState(false)
  const queryClient = useQueryClient()

  const detailQuery = useQuery({
    queryKey: ['qa', 'deviation', id],
    queryFn: () => fetchDeviation(id),
  })
  const detail = detailQuery.data
  const error = detailQuery.error ? (detailQuery.error instanceof Error ? detailQuery.error.message : '加载偏差失败') : null
  // 任何写操作后刷新详情，并让台账与 CAPA 列表失效。
  const load = () => {
    void detailQuery.refetch()
    void queryClient.invalidateQueries({ queryKey: ['qa', 'deviations'] })
    void queryClient.invalidateQueries({ queryKey: ['qa', 'capas'] })
  }

  if (error) {
    return (
      <div style={{ maxWidth: 1480, margin: '0 auto' }}>
        <Alert type="error" showIcon title={error} style={{ marginBottom: 16 }} />
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/qa/deviation')}>返回台账</Button>
      </div>
    )
  }
  if (!detail) {
    return <div style={{ padding: 80, textAlign: 'center' }}><Spin /></div>
  }

  const closed = detail.status === 'closed'
  const editable = canUpdate && !closed
  const nextAction = NEXT_ACTION[detail.status]
  const missing = detail.missing_for_next
  const currentIndex = STAGE_ORDER.indexOf(detail.status)

  // 30 天关闭期限是偏差处理的主轴：用剩余天数 + 进度条把紧迫度放在处理进度卡里。
  const daysRemaining = detail.days_remaining ?? 0
  const windowDays = Math.max(1, dayjs(detail.due_date).diff(dayjs(detail.discovery_date), 'day'))
  const remainingPct = closed ? 100 : Math.min(100, Math.max(0, (daysRemaining / windowDays) * 100))
  const dueTone = closed ? '#1aae39' : detail.is_overdue || daysRemaining < 0 ? '#e03131' : daysRemaining <= 7 ? '#dd5b00' : '#5645d4'
  const dueLabel = closed ? '已关闭' : detail.is_overdue || daysRemaining < 0 ? `超期 ${Math.abs(daysRemaining)} 天` : `剩 ${daysRemaining} 天`

  const stepItems = [
    { title: '登记', content: fmtDateTime(detail.created_at) },
    { title: '调查', content: detail.investigating_at ? fmtDateTime(detail.investigating_at) : '—' },
    { title: '评估', content: detail.assessing_at ? fmtDateTime(detail.assessing_at) : '—' },
    { title: '关闭', content: detail.closed_at ? fmtDateTime(detail.closed_at) : '待关闭' },
  ]

  const handleDelete = () => {
    modal.confirm({
      title: '删除偏差',
      content: `仅登记中的偏差可删除。确认删除 ${detail.deviation_no}？`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteDeviation(detail.id)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('偏差已删除')
        // 台账缓存里还有这一行，返回前显式失效，避免点到已删除记录。
        await queryClient.invalidateQueries({ queryKey: ['qa', 'deviations'] })
        router.push('/qa/deviation')
      },
    })
  }

  const capaSlot = (
    <div>
      <div style={{ fontSize: 12, color: '#787671', marginBottom: 6 }}>已发起的 CAPA</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {detail.capas.length === 0 && <span style={{ color: '#a4a097' }}>尚未发起</span>}
        {detail.capas.map((capa) => (
          <div key={capa.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Link href={`/qa/capa?id=${capa.id}`} style={{ color: '#0075de', fontWeight: 600 }}>{capa.capa_no}</Link>
            <CapaStatusPill status={capa.status} />
            <SeverityPill value={capa.severity} />
            {capa.effect_due_date && <span style={{ color: '#787671', fontSize: 12 }}>有效性评估到期 {fmtDate(capa.effect_due_date)}</span>}
          </div>
        ))}
        {canCreateCapa && (
          <Button size="small" icon={<PlusOutlined />} onClick={() => setCapaOpen(true)} style={{ alignSelf: 'flex-start', marginTop: 4 }}>
            发起 CAPA
          </Button>
        )}
      </div>
    </div>
  )

  return (
    <div style={{ maxWidth: 1480, margin: '0 auto', paddingBottom: 36 }}>
      {/* ── 顶部：返回 + 编号 + 状态 + 操作 ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <Space size={12} wrap>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => router.push('/qa/deviation')}>偏差台账</Button>
          <span style={{ fontSize: 22, fontWeight: 600, color: '#1a1a1a' }}>{detail.deviation_no}</span>
          <DeviationStatusPill status={detail.status} />
          <ClassificationPill value={detail.classification} />
          {detail.is_overdue && <span style={PILL.error}>已超期</span>}
          {detail.reported_late && (
            <Tooltip title="登记日晚于发现日次日，超过 24 小时书面报告时限"><span style={PILL.error}>迟报</span></Tooltip>
          )}
          {detail.is_repeat && <span style={PILL.purple}>重复偏差</span>}
          {detail.extension_count > 0 && <span style={PILL.warning}>已延期 {detail.extension_count} 次</span>}
        </Space>
        <Space>
          {detail.status === 'draft' && canUpdate && (
            <Button danger onClick={handleDelete}>删除</Button>
          )}
          {editable && (
            <Button icon={<ClockCircleOutlined />} onClick={() => setExtendOpen(true)}>延期</Button>
          )}
          {editable && nextAction && (
            <Tooltip title={missing.length ? `需先补齐：${missing.join('、')}` : undefined}>
              <Button type="primary" icon={<RightOutlined />} disabled={missing.length > 0} onClick={() => setAction(nextAction)}>
                {DEVIATION_ACTION_LABEL[nextAction]}
              </Button>
            </Tooltip>
          )}
        </Space>
      </div>

      {/* ── 进度 + 关键信息 ── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={15}>
          <Card size="small" title="处理进度" style={{ ...cardStyle, height: '100%' }} styles={cardStyles}>
            <Steps
              size="small"
              current={currentIndex}
              status={closed ? 'finish' : 'process'}
              items={stepItems}
            />
            <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #ede9e4' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 26, fontWeight: 600, lineHeight: 1.15, color: dueTone, fontVariantNumeric: 'tabular-nums' }}>
                    {dueLabel}
                  </span>
                  <span style={{ fontSize: 12, color: '#787671' }}>
                    {closed ? `关闭于 ${fmtDate(detail.closed_at)}` : `关闭期限 ${fmtDate(detail.due_date)}`}
                    {detail.extension_count > 0 && ` · 已延期 ${detail.extension_count} 次`}
                  </span>
                </div>
                {!closed && <span style={{ fontSize: 12, color: '#787671' }}>发现于 {fmtDate(detail.discovery_date)}</span>}
              </div>
              <div
                role="progressbar"
                aria-label="剩余关闭期限占比"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(remainingPct)}
                style={{ marginTop: 10, height: 6, borderRadius: 999, background: !closed && (detail.is_overdue || daysRemaining < 0) ? '#fde0ec' : '#f0eeec', overflow: 'hidden' }}
              >
                <div style={{ width: `${remainingPct}%`, height: '100%', background: dueTone, transition: 'width 200ms ease' }} />
              </div>
            </div>
            {missing.length > 0 && !closed && (
              <Alert
                type="warning"
                showIcon
                title={`进入下一阶段前需补齐：${missing.join('、')}`}
                style={{ marginTop: 16 }}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card size="small" title="关键信息" style={{ ...cardStyle, height: '100%' }} styles={cardStyles}>
            <div style={fieldGrid(2)}>
              <Field label="发现日期">{fmtDate(detail.discovery_date)}</Field>
              <Field label="发生日期">{detail.occurrence_date ? fmtDate(detail.occurrence_date) : null}</Field>
              <Field label="发生部门">{detail.department_name}</Field>
              <Field label="组别">{detail.group_name}</Field>
              <Field label="发现人">{detail.reporter_name}</Field>
              <Field label="质量员">{detail.qa_person_name}</Field>
            </div>
          </Card>
        </Col>
      </Row>

      <ReportSection detail={detail} canEdit={editable} onSaved={load} />
      <InvestigationSection detail={detail} canEdit={editable} locked={detail.status === 'draft'} onSaved={load} />
      <AssessmentSection
        detail={detail}
        canEdit={editable}
        locked={detail.status === 'draft' || detail.status === 'investigating'}
        onSaved={load}
        capaSlot={capaSlot}
      />

      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <AttachmentsCard detail={detail} canEdit={editable} onChanged={load} />
        </Col>
        <Col xs={24} lg={12}>
          <TimelineCard logs={detail.logs} />
        </Col>
      </Row>

      <TransitionModal deviation={detail} action={action} onClose={() => setAction(null)} onDone={() => { setAction(null); void load() }} />
      <ExtendModal deviation={detail} open={extendOpen} onClose={() => setExtendOpen(false)} onDone={() => { setExtendOpen(false); void load() }} />
      <CapaFormModal
        open={capaOpen}
        onClose={() => setCapaOpen(false)}
        onSaved={() => { setCapaOpen(false); void load() }}
        deviation={{ id: detail.id, deviation_no: detail.deviation_no, description: detail.description, department_name: detail.department_name }}
      />
    </div>
  )
}

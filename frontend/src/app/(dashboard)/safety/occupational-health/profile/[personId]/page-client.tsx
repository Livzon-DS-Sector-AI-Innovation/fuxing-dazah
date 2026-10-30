'use client'

// 职业健康个人完整档案（profile/[personId]）— 六源聚合展示。
//
// 数据：fetchOhPersonProfile（人员+体检+随访+转岗申请+培训参训+违章+平台身份一次拉全）。
// 区块：PageHeader → 人员信息卡（Descriptions+接害Tag）→ 平台身份卡（3.x，
// OH/平台值并排+差异标签）→ StatCard 行 → Tabs（综合时间线 / 体检 / 培训 /
// 违章 / 转岗申请 / 随访）。
// 匹配口径标注：培训=签到表AI转录按姓名；违章=open_id 强匹配（姓名兜底时
// 明确提示同名误差）；违章源失败降级（violations=null + errors 提示）；
// 平台身份卡三态信封独立降级（platform.status）。

import { useMemo } from 'react'
import type { CSSProperties } from 'react'
import { useRouter } from 'next/navigation'
import {
  Button,
  Descriptions,
  Empty,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
} from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useQuery } from '@tanstack/react-query'
import { fetchOhPersonProfile } from '@/lib/api/safety/occupational-health'
import type {
  OhFollowup,
  OhHealthExam,
  OhPerson,
  OhPersonProfile,
  OhPlatformIdentity,
  OhProfileApplication,
  OhProfileViolation,
  OhTrainingAttendee,
} from '@/types/safety'
import { EmptyGuide, PageHeader, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'
import {
  OH_AI_CONCLUSION_UI,
  OH_EXAM_TYPE_UI,
  OH_FOLLOWUP_STATUS_UI,
  OH_PARSE_STATUS_UI,
  OH_WORK_STATUS_UI,
  T,
  UI,
  CARD_STYLE,
} from '@/components/safety/ohConstants'
import { monoFont } from '@/components/safety/shared-styles'

const AI_CONCLUSION_TONE: Record<string, Tone> = {
  normal: 'ok',
  abnormal_other: 'warn',
  contraindicated: 'danger',
  suspected_od: 'danger',
  od_diagnosed: 'danger',
  re_examination: 'info',
}

const VIOLATION_LEVEL_TONE: Record<string, Tone> = {
  重大: 'danger',
  严重: 'danger',
  一般: 'warn',
}
const VIOLATION_STATUS_TONE: Record<string, Tone> = {
  已纠正: 'ok',
  纠正中: 'warn',
}

function Pill({ status, map, toneMap }: {
  status?: string
  map: Record<string, { label: string; color: string; bg: string }>
  toneMap?: Record<string, Tone>
}) {
  if (!status) return <span style={{ color: UI.muted }}>-</span>
  const ui = map[status]
  if (!ui) return <span>{status}</span>
  if (toneMap) return <StatusTag tone={toneMap[status] ?? 'default'} label={ui.label} />
  return <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, color: ui.color, background: ui.bg, fontWeight: 600 }}>{ui.label}</span>
}

function fmtDate(v?: string): string {
  return v ? dayjs(v).format('YYYY-MM-DD') : '-'
}

function fmtYears(v?: number): string {
  if (v === undefined || v === null) return '-'
  const y = Math.floor(v)
  const m = Math.round((v - y) * 12)
  if (y === 0 && m === 0) return '0 年'
  if (y === 0) return `${m} 个月`
  if (m === 0) return `${y} 年`
  return `${y} 年 ${m} 个月`
}

const TRANSFER_TYPE_LABEL: Record<string, string> = {
  transfer: '转岗',
  post_employment: '离岗',
}

// ── 综合时间线 ──

interface TimelineEntry {
  key: string
  at: string
  color: string
  typeLabel: string
  title: string
  detail?: string
}

function buildTimeline(profile: OhPersonProfile): TimelineEntry[] {
  const entries: TimelineEntry[] = []
  for (const e of profile.exams) {
    entries.push({
      key: `exam-${e.id}`,
      at: e.exam_date || e.created_at,
      color: 'blue',
      typeLabel: '体检',
      title: `${e.exam_no || '体检记录'}（${OH_EXAM_TYPE_UI[e.exam_type]?.label ?? e.exam_type}）`,
      detail: OH_AI_CONCLUSION_UI[(e.override_conclusion ?? e.ai_conclusion) || '']?.label,
    })
  }
  for (const t of profile.trainings) {
    entries.push({
      key: `training-${t.training_record_id}-${t.person_name}`,
      at: t.held_at || '',
      color: 'green',
      typeLabel: '培训',
      title: t.training_name || '培训记录',
      detail: [
        t.hours ? `${t.hours} 学时` : '',
        t.score != null ? `成绩 ${t.score}` : '',
        t.unrecognized ? '签到表辨认不清（待人工确认）' : '',
      ].filter(Boolean).join(' · '),
    })
  }
  for (const v of profile.violations ?? []) {
    entries.push({
      key: `violation-${v.record_id}`,
      at: v.occurred_at || '',
      color: 'red',
      typeLabel: '违章',
      title: `${v.category || '违章'}（${v.level || '-'}）`,
      detail: v.description,
    })
  }
  for (const a of profile.applications) {
    entries.push({
      key: `application-${a.id}`,
      at: a.submitted_at || '',
      color: 'orange',
      typeLabel: TRANSFER_TYPE_LABEL[a.transfer_type || ''] || '申请',
      title: `${a.department || '-'}${a.position ? `（${a.position}）` : ''} → ${a.new_department || '-'}`,
      detail: a.diff_summary || a.apply_status,
    })
  }
  for (const f of profile.followups) {
    entries.push({
      key: `followup-${f.id}`,
      at: f.followup_date || f.created_at,
      color: 'purple',
      typeLabel: '随访',
      title: `异常指标：${f.indicator_name || '-'}`,
      detail: f.action_taken,
    })
  }
  return entries
    .filter((e) => e.at)
    .sort((a, b) => dayjs(b.at).valueOf() - dayjs(a.at).valueOf())
}

// ── 平台身份卡（3.x，第 6 源）──

const PLATFORM_STATUS_UI: Record<string, { label: string; tone: Tone }> = {
  live: { label: '已关联', tone: 'ok' },
  degraded: { label: '缓存降级', tone: 'warn' },
  empty: { label: '平台不可用', tone: 'default' },
  unmatched: { label: '平台未匹配', tone: 'default' },
}

const MATCH_BASIS_LABEL: Record<string, string> = {
  job_no: '按工号精确匹配',
  name_dept: '按姓名 + 部门匹配',
}

function normText(v?: string | null): string {
  return (v ?? '').trim()
}

/** 一行三列对比：字段 | OH 台账 | 3.x 平台；两侧有值且不一致打「两侧不一致」 */
const COMPARE_GRID_STYLE: CSSProperties = {
  display: 'grid', gridTemplateColumns: '90px 1fr 1fr', gap: 8,
}

function CompareField({ label, oh, pf, ohMissingHint }: {
  label: string
  oh: string
  pf: string
  ohMissingHint?: boolean
}) {
  const differs = oh !== pf && (oh !== '' || pf !== '')
  // 工号行专属：台账缺、平台有 → 「台账未登记」提示（替代差异标签，语义更准）
  const ohMissing = Boolean(ohMissingHint) && oh === '' && pf !== ''
  return (
    <div style={{ ...COMPARE_GRID_STYLE, padding: '7px 0', borderTop: '1px solid #f0f0f0' }}>
      <span style={{ color: UI.muted, fontSize: 12 }}>{label}</span>
      <span style={{ fontSize: 13, color: oh ? UI.ink : UI.muted }}>{oh || '-'}</span>
      <span style={{ fontSize: 13, color: pf ? UI.ink : UI.muted, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        {pf || '-'}
        {ohMissing && <Tag color="default" style={{ marginInlineEnd: 0 }}>台账未登记</Tag>}
        {differs && !ohMissing && <Tag color="warning" style={{ marginInlineEnd: 0 }}>两侧不一致</Tag>}
      </span>
    </div>
  )
}

function PlatformIdentityCard({ person, platform }: {
  person: OhPerson
  platform?: OhPlatformIdentity | null
}) {
  if (!platform) {
    return (
      <SectionCard title="平台身份（3.x）" description="3.x 平台主数据关联（第 6 源，独立降级）">
        <EmptyGuide compact title="平台身份源不可用" description="平台身份卡采集失败，不影响其余档案区块" />
      </SectionCard>
    )
  }
  const ui = PLATFORM_STATUS_UI[platform.status] ?? PLATFORM_STATUS_UI.empty
  const basis = platform.match_basis ? MATCH_BASIS_LABEL[platform.match_basis] ?? platform.match_basis : null
  const p = platform.person
  return (
    <SectionCard
      title="平台身份（3.x）"
      description="3.x 平台主数据关联（工号优先匹配；差异仅展示，不回写台账）"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <StatusTag tone={ui.tone} label={ui.label} />
        {basis && <span style={{ fontSize: 12, color: UI.steel }}>{basis}</span>}
        {platform.fetched_at && (
          <span style={{ fontSize: 12, color: UI.muted }}>数据时点 {dayjs(platform.fetched_at).format('YYYY-MM-DD HH:mm')}</span>
        )}
      </div>

      {platform.status === 'empty' && (
        <EmptyGuide compact title="平台暂不可用" description={platform.message ?? '3.x 平台接口暂不可用，请稍后重试'} />
      )}
      {platform.status === 'unmatched' && (
        <EmptyGuide compact title="平台未匹配" description={platform.message ?? '同名多人或零命中，未自动匹配'} />
      )}
      {(platform.status === 'live' || platform.status === 'degraded') && (
        <>
          {/* degraded 且缓存结论为未匹配（person=null）时同样要有提示正文 */}
          {platform.status === 'degraded' && (
            <div style={{ fontSize: 12, color: UI.steel, marginBottom: 8 }}>
              {platform.message}
              {!p && '（上次缓存结论为平台未匹配）'}
            </div>
          )}
          {p && (
            <>
              <div style={{ ...COMPARE_GRID_STYLE, padding: '6px 0', fontWeight: 600, fontSize: 12, color: UI.muted, borderBottom: '1px solid #f0f0f0' }}>
                <span>字段</span><span>OH 台账</span><span>3.x 平台</span>
              </div>
              <CompareField label="工号" oh={normText(person.employee_no)} pf={normText(p.job_no)} ohMissingHint />
              <CompareField label="部门" oh={normText(person.department)} pf={normText(p.dept_name)} />
              <CompareField label="岗位" oh={normText(person.position)} pf={normText(p.post_name)} />
              <Descriptions column={3} size="small" style={{ marginTop: 12 }}>
                <Descriptions.Item label="部门全路径">{p.dept_whole_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="直属上级">{p.direct_leader || '-'}</Descriptions.Item>
                <Descriptions.Item label="在职状态">{p.status || '-'}</Descriptions.Item>
                <Descriptions.Item label="电话">{p.telephone || '-'}</Descriptions.Item>
                <Descriptions.Item label="邮箱">{p.email || '-'}</Descriptions.Item>
                <Descriptions.Item label="入职日期">{p.entry_date ? fmtDate(p.entry_date) : '-'}</Descriptions.Item>
              </Descriptions>
              <div style={{ marginTop: 8, fontSize: 12, color: UI.muted }}>
                平台字段未填时以 - 容空；工号/部门/岗位与台账的差异仅并排展示，不回写任何一侧。
              </div>
            </>
          )}
        </>
      )}
    </SectionCard>
  )
}

// ── 页面 ──

export default function OccupationalHealthProfileClient({ personId }: { personId: string }) {
  const router = useRouter()
  const { data: profile, isLoading, isError } = useQuery({
    queryKey: ['oh-person-profile', personId],
    queryFn: () => fetchOhPersonProfile(personId),
    retry: false,
  })

  const person = profile?.person

  const timeline = useMemo(() => (profile ? buildTimeline(profile) : []), [profile])

  const totalHours = useMemo(
    () => (profile?.trainings ?? []).reduce((s, t) => s + (t.hours ?? 0), 0),
    [profile],
  )

  const examColumns: ColumnsType<OhHealthExam> = [
    { title: '体检号', dataIndex: 'exam_no', key: 'exam_no', width: 150, render: (v: string) => <span style={monoFont}>{v || '-'}</span> },
    { title: '类型', dataIndex: 'exam_type', key: 'exam_type', width: 100, render: (v: string) => <Pill status={v} map={OH_EXAM_TYPE_UI} /> },
    { title: '体检日期', dataIndex: 'exam_date', key: 'exam_date', width: 110, render: (v: string) => fmtDate(v) },
    { title: '体检机构', dataIndex: 'exam_agency', key: 'exam_agency', width: 150, ellipsis: true, render: (v: string) => v || '-' },
    { title: '报告日期', dataIndex: 'report_date', key: 'report_date', width: 110, render: (v: string) => fmtDate(v) },
    {
      title: 'AI 结论', key: 'conclusion', width: 110,
      render: (_: unknown, r: OhHealthExam) => <Pill status={r.override_conclusion ?? r.ai_conclusion} map={OH_AI_CONCLUSION_UI} toneMap={AI_CONCLUSION_TONE} />,
    },
    { title: '解析状态', dataIndex: 'ai_parse_status', key: 'parse', width: 100, render: (v: string) => <Pill status={v} map={OH_PARSE_STATUS_UI} /> },
  ]

  const trainingColumns: ColumnsType<OhTrainingAttendee> = [
    {
      title: '培训名称', dataIndex: 'training_name', key: 'training_name', ellipsis: true,
      render: (v: string, r) => (
        <span style={r.unrecognized ? { color: UI.muted } : undefined}>
          {v || '-'}
          {r.unrecognized && <Tag style={{ marginInlineStart: 6 }} color="warning">辨认不清</Tag>}
        </span>
      ),
    },
    { title: '类别', dataIndex: 'category', key: 'category', width: 110, render: (v: string) => v || '-' },
    { title: '实施日期', dataIndex: 'held_at', key: 'held_at', width: 110, render: (v: string) => fmtDate(v) },
    { title: '学时', dataIndex: 'hours', key: 'hours', width: 70, render: (v: number) => (v != null ? v : '-') },
    { title: '考核方式', dataIndex: 'assessment', key: 'assessment', width: 100, render: (v: string) => v || '-' },
    { title: '成绩', dataIndex: 'score', key: 'score', width: 80, render: (v: number) => (v != null ? v : '-') },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 90,
      render: (v: string) => {
        if (!v) return '-'
        const tone: Tone = v === 'high' ? 'ok' : v === 'medium' ? 'warn' : 'danger'
        const label = v === 'high' ? '高' : v === 'medium' ? '中' : '低'
        return <StatusTag tone={tone} label={label} />
      },
    },
  ]

  const violationColumns: ColumnsType<OhProfileViolation> = [
    { title: '违章日期', dataIndex: 'occurred_at', key: 'occurred_at', width: 110, render: (v: string) => fmtDate(v) },
    { title: '类别', dataIndex: 'category', key: 'category', width: 100, render: (v: string) => v || '-' },
    { title: '等级', dataIndex: 'level', key: 'level', width: 90, render: (v: string) => <StatusTag tone={VIOLATION_LEVEL_TONE[v] ?? 'default'} label={v || '-'} /> },
    { title: '违章描述', dataIndex: 'description', key: 'description', ellipsis: true, render: (v: string) => v || '-' },
    { title: '处理方式', dataIndex: 'handling', key: 'handling', width: 100, render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => <StatusTag tone={VIOLATION_STATUS_TONE[v] ?? 'default'} label={v || '-'} /> },
    {
      title: '匹配', dataIndex: 'match_basis', key: 'match_basis', width: 80,
      render: (v: string) => (
        <Tooltip title={v === 'open_id' ? '按飞书身份精确匹配' : '按姓名匹配，可能存在同名误差'}>
          <span>{v === 'open_id' ? '精确' : '姓名'}</span>
        </Tooltip>
      ),
    },
  ]

  const applicationColumns: ColumnsType<OhProfileApplication> = [
    { title: '类型', dataIndex: 'transfer_type', key: 'transfer_type', width: 80, render: (v: string) => TRANSFER_TYPE_LABEL[v] || v || '-' },
    { title: '申请编号', dataIndex: 'application_no', key: 'application_no', width: 150, ellipsis: true, render: (v: string) => <span style={monoFont}>{v || '-'}</span> },
    {
      title: '岗位变动', key: 'move', width: 220, ellipsis: true,
      render: (_: unknown, r: OhProfileApplication) =>
        `${r.department || '-'}${r.position ? `（${r.position}）` : ''} → ${r.new_department || '-'}${r.new_position ? `（${r.new_position}）` : ''}`,
    },
    { title: '发起时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 110, render: (v: string) => fmtDate(v) },
    { title: '状态', dataIndex: 'apply_status', key: 'apply_status', width: 90, render: (v: string) => v || '-' },
    { title: '差异分析摘要', dataIndex: 'diff_summary', key: 'diff_summary', ellipsis: true, render: (v: string) => v || '-' },
  ]

  const followupColumns: ColumnsType<OhFollowup> = [
    { title: '异常指标', dataIndex: 'indicator_name', key: 'indicator_name', render: (v: string) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 110, render: (v: string) => <Pill status={v} map={OH_FOLLOWUP_STATUS_UI} /> },
    { title: '建议复查日期', dataIndex: 'followup_date', key: 'followup_date', width: 130, render: (v: string) => fmtDate(v) },
    { title: '处置记录', dataIndex: 'action_taken', key: 'action_taken', ellipsis: true, render: (v: string) => v || '-' },
  ]

  if (isLoading) {
    return (
      <div>
        <PageHeader breadcrumb={['安全管理', '职业健康管理', '个人档案']} title="个人档案" description="加载中…" />
        <EmptyGuide compact title="加载中" description="正在拉取档案数据" />
      </div>
    )
  }

  if (isError || !profile || !person) {
    return (
      <div>
        <PageHeader breadcrumb={['安全管理', '职业健康管理', '个人档案']} title="个人档案" description="人员记录不存在或加载失败" />
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push('/safety/occupational-health')}
          style={{ marginBottom: 16 }}
        >
          返回职业健康管理
        </Button>
        <EmptyGuide compact title="未找到该人员" description="请从人员台账重新进入档案页" />
      </div>
    )
  }

  const hazards = person.hazard_factors ?? []
  const openFollowups = profile.followups.filter((f) => f.status !== 'closed').length
  const violations = profile.violations
  const violationBasis = profile.match_notes?.violations

  return (
    <div className="flex flex-col gap-4 pb-8">
      <PageHeader
        breadcrumb={['安全管理', '职业健康管理', '个人档案']}
        title={`${person.name} · 个人档案`}
        description="职业健康、培训、违章等多域记录单人聚合视图"
        actions={(
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push('/safety/occupational-health')}>
            返回台账
          </Button>
        )}
      />

      {/* ── 人员信息卡 ── */}
      <div style={{ ...CARD_STYLE, padding: '16px 20px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 12 }}>基本信息</div>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label="姓名"><b>{person.name}</b></Descriptions.Item>
          <Descriptions.Item label="工号">{person.employee_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="身份证号">{person.id_card_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="部门">{person.department || '-'}</Descriptions.Item>
          <Descriptions.Item label="岗位">{person.position || '-'}</Descriptions.Item>
          <Descriptions.Item label="在岗状态"><Pill status={person.work_status} map={OH_WORK_STATUS_UI} /></Descriptions.Item>
          <Descriptions.Item label="性别">{person.gender || '-'}</Descriptions.Item>
          <Descriptions.Item label="年龄">{person.age ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="电话">{person.phone || '-'}</Descriptions.Item>
          <Descriptions.Item label="总工龄">{fmtYears(person.total_work_years)}</Descriptions.Item>
          <Descriptions.Item label="接害工龄">{fmtYears(person.hazard_exposure_years)}</Descriptions.Item>
          <Descriptions.Item label="部门安全员">{person.safety_officer || '-'}</Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: UI.muted }}>接触危害因素：</span>
          {hazards.length === 0 ? (
            <span style={{ color: UI.muted, fontSize: 13 }}>未登记</span>
          ) : (
            <Space size={[6, 6]} wrap>
              {hazards.map((h) => (
                <Tag key={h} style={{ marginInlineEnd: 0, background: T.lavender, color: '#391c57', borderColor: 'transparent', borderRadius: 6 }}>{h}</Tag>
              ))}
            </Space>
          )}
        </div>
      </div>

      {/* ── 平台身份卡（3.x，第 6 源）── */}
      <PlatformIdentityCard person={person} platform={profile.platform} />

      {/* ── 统计行 ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard
          label="体检次数"
          value={profile.exams.length}
          sub={`最近 ${
            person.last_exam_at
              ? dayjs(person.last_exam_at).format('YYYY-MM-DD')
              : profile.exams[0]?.exam_date
                ? dayjs(profile.exams[0].exam_date).format('YYYY-MM-DD')
                : '无'
          }`}
        />
        <StatCard
          label="最近体检结论"
          value={OH_AI_CONCLUSION_UI[person.last_exam_conclusion || '']?.label ?? '-'}
          sub={person.last_exam_summary ? person.last_exam_summary.slice(0, 18) : '按最后体检归一'}
        />
        <StatCard label="培训场次" value={profile.trainings.length} sub={`累计 ${totalHours} 学时 · 签到表AI转录`} />
        <StatCard label="违章记录" value={violations ? violations.length : '—'} sub={violations === null ? '违章源不可用' : violationBasis === 'open_id' ? '按飞书身份精确匹配' : '含姓名匹配'} />
        <StatCard label="待随访" value={openFollowups} sub={`随访共 ${profile.followups.length} 条`} />
      </div>

      {/* ── 分区 Tabs ── */}
      <SectionCard title="档案记录" description="综合时间线 + 各域明细（体检 / 培训 / 违章 / 转岗离岗申请 / 随访）">
        <Tabs
          defaultActiveKey="timeline"
          items={[
            {
              key: 'timeline',
              label: `综合时间线 (${timeline.length})`,
              children: timeline.length === 0 ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可时间线化的记录" />
              ) : (
                <Timeline
                  mode="start"
                  style={{ marginTop: 8, paddingTop: 4 }}
                  items={timeline.map((e) => ({
                    key: e.key,
                    title: <span style={{ color: UI.muted, fontSize: 12 }}>{fmtDate(e.at)}</span>,
                    color: e.color,
                    content: (
                      <span style={{ fontSize: 13 }}>
                        <span style={{ fontWeight: 600, color: UI.ink, marginRight: 8 }}>
                          <Tag style={{ marginInlineEnd: 8 }} color={e.color}>{e.typeLabel}</Tag>
                          {e.title}
                        </span>
                        {e.detail && <span style={{ color: UI.steel }}>{e.detail}</span>}
                      </span>
                    ),
                  }))}
                />
              ),
            },
            {
              key: 'exams',
              label: `体检记录 (${profile.exams.length})`,
              children: (
                <Table<OhHealthExam> rowKey="id" size="small" columns={examColumns}
                  dataSource={profile.exams} pagination={profile.exams.length > 10 ? { pageSize: 10 } : false}
                  locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无体检记录" /> }} />
              ),
            },
            {
              key: 'trainings',
              label: `培训记录 (${profile.trainings.length})`,
              children: (
                <>
                  <div style={{ fontSize: 12, color: UI.muted, marginBottom: 8 }}>
                    培训明细来自签到表/成绩单 AI 逐名转录，按姓名关联到本人；「辨认不清」为原样转录，待人工确认。
                  </div>
                  <Table<OhTrainingAttendee> rowKey={(r) => `${r.training_record_id}-${r.person_name}`}
                    size="small" columns={trainingColumns} dataSource={profile.trainings}
                    pagination={profile.trainings.length > 10 ? { pageSize: 10 } : false}
                    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无培训明细（需在 S6 培训域解析签到表后逐步积累）" /> }} />
                </>
              ),
            },
            {
              key: 'violations',
              label: `违章记录 (${violations ? violations.length : '—'})`,
              children: violations === null ? (
                <EmptyGuide compact title="违章源不可用" description="违章档案表直读失败或未接入，其余档案区块不受影响" />
              ) : (
                <>
                  {violationBasis && violationBasis !== 'open_id' && (
                    <div style={{ fontSize: 12, color: UI.steel, marginBottom: 8 }}>
                      部分违章记录按姓名匹配（无飞书身份可用），同名人员可能存在误差，请以「匹配」列口径核对。
                    </div>
                  )}
                  <Table<OhProfileViolation> rowKey="record_id" size="small" columns={violationColumns}
                    dataSource={violations} pagination={violations.length > 10 ? { pageSize: 10 } : false}
                    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无违章记录" /> }} />
                </>
              ),
            },
            {
              key: 'applications',
              label: `转岗离岗申请 (${profile.applications.length})`,
              children: (
                <Table<OhProfileApplication> rowKey="id" size="small" columns={applicationColumns}
                  dataSource={profile.applications} pagination={profile.applications.length > 10 ? { pageSize: 10 } : false}
                  locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无转岗/离岗申请" /> }} />
              ),
            },
            {
              key: 'followups',
              label: `异常随访 (${profile.followups.length})`,
              children: (
                <Table<OhFollowup> rowKey="id" size="small" columns={followupColumns}
                  dataSource={profile.followups} pagination={profile.followups.length > 10 ? { pageSize: 10 } : false}
                  locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无异常随访" /> }} />
              ),
            },
          ]}
        />
      </SectionCard>
    </div>
  )
}

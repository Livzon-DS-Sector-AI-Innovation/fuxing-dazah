'use client'

/**
 * S6 培训生产链 T1-T5 前端接入（#7，后端零改动）。
 *
 * 三区块（DESIGN-S6培训生产链-前端接入-20261026 §2）：
 * 1. 年度培训需求（AI 草案）：生成（同年重跑替换未处理草案，confirm 门）→
 *    草案表评审 → 采纳（写台账计划行）/驳回；已处理行灰显。
 * 2. 课件与试卷生成：培训行选择（默认未开始/进行中）+ 类型 → 生成
 *    （60s 超时口径：转提示「稍后在本清单查看」，产物清单兜底）。
 * 3. 签到成绩解析：行选择 → 解析（后端自动取该行「签到表」附件首图，
 *    端点不收图片——设计文档 {record_id,image} 与实测后端不符，按后端贴齐）
 *    → confidence 分级展示（high 回填数字列 / medium·low 仅备注待人工）。
 *
 * 操作按钮定性=AI 确认流（人对 AI 产物的审核门），与「推送到群」同级例外。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { App, Alert, Button, Select, Switch, Table, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'
import { SectionCard } from '@/components/ui-kit'
import { fetchDomainPage, type DomainLedgerRow } from '@/lib/api/safety/domain-pages'
import {
  adoptTrainingDemandDraft,
  fetchTrainingDemandDrafts,
  fetchTrainingMaterials,
  generateTrainingDemand,
  generateTrainingMaterial,
  parseTrainingRecord,
  rejectTrainingDemandDraft,
  type MaterialType,
  type ParseRecordResult,
  type TrainingDemandDraft,
} from '@/lib/api/safety/training-production'

const DRAFT_ROWS_QUERY = ['safety', 'training-production', 'drafts']
const MATERIALS_QUERY = ['safety', 'training-production', 'materials']

/** 默认可选行=未开始/进行中（未实施完的培训才需要课件/解析） */
const ACTIVE_STATUSES = new Set(['未开始', '进行中'])

// ═══════════════════ 培训行选择器（链2/链3 共用） ═══════════════════

function TrainingRowSelect({
  value,
  onChange,
  testId,
}: {
  value: string | null
  onChange: (recordId: string | null) => void
  testId?: string
}) {
  const [showAll, setShowAll] = useState(false)
  const [keyword, setKeyword] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['safety', 'training-production', 'ledger-rows'],
    // 后端域页端点 page_size 上限 100（零新增端点边界；台账超百行时选择器
    // 覆盖最近创建的 100 行，超出走表格侧操作）
    queryFn: () => fetchDomainPage('training-behavior', { page: 1, page_size: 100 }),
    staleTime: 5 * 60_000,
  })

  const rows = useMemo(() => {
    const all = (data?.ledger.data ?? []) as DomainLedgerRow[]
    const filtered = showAll ? all : all.filter(r => ACTIVE_STATUSES.has(String(r.status ?? '')))
    const kw = keyword.trim()
    const matched = kw ? filtered.filter(r => String(r.name ?? '').includes(kw)) : filtered
    return matched.slice(0, 100)
  }, [data, showAll, keyword])

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      <Select
        showSearch
        placeholder="选择培训行（标题检索）"
        style={{ minWidth: 320 }}
        loading={isLoading}
        value={value}
        onSearch={setKeyword}
        onChange={(v: string | null) => onChange(v)}
        filterOption={false}
        allowClear
        options={rows.map(r => ({
          value: r.record_id,
          label: `${String(r.name ?? '（未命名）')}（${String(r.status ?? '—')}）`,
        }))}
      />
      <span className="flex items-center gap-1 text-[12px] text-[var(--color-steel)]">
        <Switch size="small" checked={showAll} onChange={setShowAll} />
        显示全部行（默认未开始/进行中）
      </span>
      {data?.status === 'live' && (
        <span className="text-[11px] text-[var(--color-steel)]">
          共 {data.ledger.meta.total} 行
        </span>
      )}
    </div>
  )
}

// ═══════════════════ 区块1：年度培训需求（AI 草案） ═══════════════════

const DRAFT_STATUS_TAG: Record<string, { label: string; color: string }> = {
  draft: { label: '待处理', color: 'blue' },
  adopted: { label: '已采纳', color: 'green' },
  rejected: { label: '已驳回', color: 'default' },
}

function DemandSection() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const nextYear = dayjs().year() + 1
  const [year, setYear] = useState(nextYear)

  const draftsQuery = useQuery({
    queryKey: [...DRAFT_ROWS_QUERY, year],
    queryFn: () => fetchTrainingDemandDrafts({ year }),
  })

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: DRAFT_ROWS_QUERY })

  const generateMutation = useMutation({
    mutationFn: () => generateTrainingDemand(year),
    onSuccess: r => {
      message.success(
        `生成完成：${r.count} 条草案（替换旧草案 ${r.replaced} 条）` +
          (r.sources?.disconnected ? `；${r.sources.disconnected} 个数据源未接入已降级` : ''),
      )
      invalidate()
    },
    onError: e => message.error(e instanceof Error ? e.message : '生成失败'),
  })

  const adoptMutation = useMutation({
    mutationFn: (id: string) => adoptTrainingDemandDraft(id),
    onSuccess: r => {
      message.success(`已采纳并写入培训台账（行 ${r.adopted_record_id}）`)
      invalidate()
    },
    onError: e => message.error(e instanceof Error ? e.message : '采纳失败'),
  })

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectTrainingDemandDraft(id),
    onSuccess: () => {
      message.success('已驳回')
      invalidate()
    },
    onError: e => message.error(e instanceof Error ? e.message : '驳回失败'),
  })

  const [actingId, setActingId] = useState<string | null>(null)

  function confirmAdopt(row: TrainingDemandDraft) {
    modal.confirm({
      title: '采纳该草案？',
      content: '将写入培训台账计划行（状态=未开始），生成记录回填到草案行。',
      okText: '采纳',
      onOk: async () => {
        setActingId(row.id)
        try {
          await adoptMutation.mutateAsync(row.id)
        } finally {
          setActingId(null)
        }
      },
    })
  }

  function confirmReject(row: TrainingDemandDraft) {
    modal.confirm({
      title: '驳回该草案？',
      content: `${row.topic}（${row.position || '全体'}）`,
      okText: '驳回',
      okButtonProps: { danger: true },
      onOk: () => rejectMutation.mutateAsync(row.id),
    })
  }

  const columns: TableColumnsType<TrainingDemandDraft> = [
    { title: '岗位', dataIndex: 'position', width: 110, ellipsis: true },
    { title: '培训主题', dataIndex: 'topic', width: 220, ellipsis: true },
    { title: '对象', dataIndex: 'audience', width: 130, ellipsis: true },
    { title: '课时', dataIndex: 'suggested_hours', width: 64, render: v => v ?? '—' },
    { title: '依据', dataIndex: 'basis', ellipsis: true },
    {
      title: '法定缺口',
      dataIndex: 'is_statutory_gap',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="red">缺口</Tag> : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 86,
      render: (v: string) => {
        const tag = DRAFT_STATUS_TAG[v] ?? { label: v, color: 'default' }
        return <Tag color={tag.color}>{tag.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 132,
      render: (_, row) => {
        const done = row.status !== 'draft'
        return (
          <span className="flex gap-1">
            <Button
              size="small"
              type="primary"
              disabled={done || actingId !== null}
              loading={actingId === row.id}
              onClick={() => confirmAdopt(row)}
            >
              采纳
            </Button>
            <Button size="small" disabled={done || actingId !== null} onClick={() => confirmReject(row)}>
              驳回
            </Button>
          </span>
        )
      },
    },
  ]

  return (
    <SectionCard
      title="年度培训需求（AI 草案）"
      description="五源数据（危险源/隐患/违章/新法规/上学年完成）→ AI 生成需求清单草案；采纳后写入培训台账计划行，驳回留痕。同年重跑将替换未处理草案。"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          value={year}
          onChange={setYear}
          style={{ width: 120 }}
          options={[nextYear, nextYear + 1, nextYear - 1].map(y => ({ value: y, label: `${y} 年` }))}
        />
        <Button
          type="primary"
          loading={generateMutation.isPending}
          disabled={generateMutation.isPending}
          onClick={() =>
            modal.confirm({
              title: `生成 ${year} 年度培训需求草案？`,
              content: 'AI+五源取数约 10-30 秒；同年重跑将替换未处理草案（已采纳/驳回保留）。',
              okText: '生成',
              onOk: () => generateMutation.mutateAsync(),
            })
          }
        >
          生成草案
        </Button>
        {generateMutation.isPending && (
          <span className="text-[12px] text-[var(--color-steel)]">五源取数+AI 生成中，约 10-30 秒…</span>
        )}
        <span className="ml-auto text-[12px] text-[var(--color-steel)]">
          {draftsQuery.data ? `${draftsQuery.data.length} 条草案` : ''}
        </span>
      </div>
      <Table<TrainingDemandDraft>
        rowKey="id"
        size="small"
        loading={draftsQuery.isLoading}
        columns={columns}
        dataSource={draftsQuery.data ?? []}
        pagination={{ pageSize: 8, showTotal: t => `共 ${t} 条` }}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: `${year} 年暂无草案——点击「生成草案」由 AI 基于五源数据生成` }}
      />
    </SectionCard>
  )
}

// ═══════════════════ 区块2：课件与试卷生成 ═══════════════════

const MATERIAL_TYPE_LABEL: Record<string, string> = {
  lecture: '讲义要点卡',
  exam: '试卷',
  both: '全套',
}

function MaterialSection() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [recordId, setRecordId] = useState<string | null>(null)
  const [materialType, setMaterialType] = useState<MaterialType>('both')
  const [slowHint, setSlowHint] = useState(false)
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (slowTimer.current) clearTimeout(slowTimer.current)
  }, [])

  const materialsQuery = useQuery({
    queryKey: [...MATERIALS_QUERY, recordId],
    queryFn: () => fetchTrainingMaterials(recordId!),
    enabled: !!recordId,
  })

  const generateMutation = useMutation({
    mutationFn: () => generateTrainingMaterial(recordId!, materialType),
    onMutate: () => {
      setSlowHint(false)
      slowTimer.current = setTimeout(() => setSlowHint(true), 60_000)
    },
    onSuccess: r => {
      message.success(`已生成并挂附件：${r.materials.map(m => m.file_name).join('、')}`)
      void queryClient.invalidateQueries({ queryKey: MATERIALS_QUERY })
    },
    onSettled: () => {
      if (slowTimer.current) clearTimeout(slowTimer.current)
      setSlowHint(false)
    },
    onError: e => message.error(e instanceof Error ? e.message : '生成失败'),
  })

  const columns: TableColumnsType<{ name: string; material_type: string | null; generated_at?: string }> = [
    { title: '文件名', dataIndex: 'name', ellipsis: true },
    {
      title: '类型',
      dataIndex: 'material_type',
      width: 110,
      render: (v: string | null) =>
        v ? <Tag color={v === 'exam' ? 'geekblue' : 'cyan'}>{MATERIAL_TYPE_LABEL[v] ?? v}</Tag> : '—',
    },
    { title: '生成日期', dataIndex: 'generated_at', width: 110, render: v => v ?? '—' },
  ]

  const rows = useMemo(() => {
    const list = materialsQuery.data
    if (!list) return []
    const genByType = new Map(
      list.generations.map(g => [g.material_type, g.generated_at]),
    )
    return list.attachments.map(a => ({
      name: a.name,
      material_type: a.material_type,
      generated_at: a.material_type ? genByType.get(a.material_type) : undefined,
    }))
  }, [materialsQuery.data])

  return (
    <SectionCard
      title="课件与试卷生成"
      description="选中培训行生成讲义要点卡/试卷 docx，产物自动挂该行「课件与试卷」附件列（不覆盖既有附件）。生成中请勿重复触发；耗时较长时可稍后在下方产物清单查看。"
    >
      <div className="mb-3 flex flex-col gap-2">
        <TrainingRowSelect value={recordId} onChange={setRecordId} testId="material-row-select" />
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={materialType}
            onChange={setMaterialType}
            style={{ width: 140 }}
            options={(Object.keys(MATERIAL_TYPE_LABEL) as MaterialType[]).map(t => ({
              value: t,
              label: MATERIAL_TYPE_LABEL[t],
            }))}
          />
          <Button
            type="primary"
            disabled={!recordId}
            loading={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            生成
          </Button>
          {slowHint && generateMutation.isPending && (
            <span className="text-[12px] text-[var(--wh-warn, #d48806)]">
              生成耗时较长，可稍后在下方产物清单查看（无需重复点击）
            </span>
          )}
          {recordId && (
            <Button
              size="small"
              onClick={() =>
                void queryClient.invalidateQueries({ queryKey: MATERIALS_QUERY })
              }
            >
              刷新产物清单
            </Button>
          )}
        </div>
      </div>
      {recordId ? (
        <Table
          rowKey="name"
          size="small"
          loading={materialsQuery.isLoading}
          columns={columns}
          dataSource={rows}
          pagination={false}
          locale={{ emptyText: '该行暂无生成产物（备注无生成标记）' }}
        />
      ) : (
        <div className="py-6 text-center text-[12px] text-[var(--color-steel)]">
          先选择培训行，再查看/生成产物
        </div>
      )}
      {materialsQuery.data && materialsQuery.data.attachments.length > 0 && (
        <div className="pt-2 text-[11px] text-[var(--color-steel)]">
          附件已挂培训台账「课件与试卷」列，请在飞书多维表格中打开查看。
        </div>
      )}
    </SectionCard>
  )
}

// ═══════════════════ 区块3：签到成绩解析 ═══════════════════

/** vision 链置信度口径：high 回填数字列 / medium·low 仅备注（与 CONFIDENCE_TAG 的 mid 不同名） */
const PARSE_CONFIDENCE: Record<string, { label: string; color: string }> = {
  high: { label: 'high·已回填', color: 'green' },
  medium: { label: 'medium·仅备注', color: 'gold' },
  low: { label: 'low·待人工', color: 'red' },
}

function ParseSection() {
  const { message } = App.useApp()
  const [recordId, setRecordId] = useState<string | null>(null)
  const [result, setResult] = useState<ParseRecordResult | null>(null)

  const parseMutation = useMutation({
    mutationFn: () => parseTrainingRecord(recordId!),
    onSuccess: r => {
      setResult(r)
      const keys = r.writeback_keys.filter(k => k !== '备注')
      message.success(
        `解析完成：${r.parse.doc_type}（confidence=${r.parse.confidence}），${keys.length ? `回填 ${keys.join('、')}` : '仅备注'}`,
      )
    },
    onError: e => message.error(e instanceof Error ? e.message : '解析失败'),
  })

  const parse = result?.parse
  const needsManual = parse && parse.confidence !== 'high'
  const scoreRows = (parse?.scores ?? []).map(s => ({
    name: String(s.name ?? ''),
    score: String(s.score ?? s.value ?? ''),
  }))

  return (
    <SectionCard
      title="签到成绩解析"
      description="解析将读取所选培训行「签到表」附件列的首张图片（vision 识别），按置信度分级回填：high 回填实到/合格数字列，medium/low 仅写备注待人工核对。重复解析按需手动触发，人工改表=覆盖终值。"
    >
      <div className="mb-3 flex flex-col gap-2">
        <TrainingRowSelect value={recordId} onChange={setRecordId} testId="parse-row-select" />
        <div className="flex items-center gap-2">
          <Button
            type="primary"
            disabled={!recordId}
            loading={parseMutation.isPending}
            onClick={() => parseMutation.mutate()}
          >
            解析
          </Button>
          <span className="text-[12px] text-[var(--color-steel)]">
            {recordId
              ? '将读取该行「签到表」附件首图（需已在表格上传照片）'
              : '先选择培训行'}
          </span>
        </div>
      </div>

      {parse && (
        <div className="flex flex-col gap-3" data-testid="parse-result">
          <div className="flex flex-wrap items-center gap-3 text-[13px]">
            <Tag color={PARSE_CONFIDENCE[parse.confidence]?.color ?? 'default'}>
              {PARSE_CONFIDENCE[parse.confidence]?.label ?? parse.confidence}
            </Tag>
            <span>单据类型：{parse.doc_type}</span>
            <span>实到 {parse.attendance_count ?? '—'} 人</span>
            <span>考核合格 {parse.passed_count ?? '—'} 人</span>
            <span>
              回填列：
              {result!.writeback_keys.filter(k => k !== '备注').join('、') || '仅备注（未回填数字列）'}
            </span>
          </div>
          {needsManual && (
            <Alert
              type="warning"
              showIcon
              message="medium/low 置信度未回填数字列，请在飞书培训台账人工核对签到与成绩。"
            />
          )}
          {parse.names.length > 0 && (
            <div>
              <div className="mb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
                名单转录（{parse.names.length} 名）
              </div>
              <div className="text-[13px] text-[var(--color-charcoal)]">
                {parse.names.join('、')}
              </div>
            </div>
          )}
          {scoreRows.length > 0 && (
            <div>
              <div className="mb-1.5 text-[12px] font-medium text-[var(--color-stone)]">
                分数明细（只抄录不推算）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {scoreRows.map((r, i) => (
                  <Tag key={i}>
                    {r.name}：{r.score || '—'}
                  </Tag>
                ))}
              </div>
            </div>
          )}
          {parse.notes && (
            <div className="text-[12px] text-[var(--color-steel)]">备注：{parse.notes}</div>
          )}
        </div>
      )}
    </SectionCard>
  )
}

// ═══════════════════ 面板出口（S6 域页挂载） ═══════════════════

export function TrainingProductionPanel() {
  return (
    <div className="mt-4 flex flex-col gap-4">
      <DemandSection />
      <MaterialSection />
      <ParseSection />
    </div>
  )
}

'use client'

/**
 * 承包商在册人员副台账区块（3.x 平台关联 F1，S14 相关方管理域页第二表）。
 *
 * 数据源：3.x 平台承包商人员实名台账（后端只读直读+三组交叉核验，
 * 文案统一「在册」不称「在场」——平台 bind/定位字段全空无法验在场）。
 * 展示形态参照 S6 违章副台账先例（SectionCard + StatCard 行 + 全量行
 * 客户端分页 + detailFields 配置驱动 Drawer），但独立实现于本组件，
 * 不并入 DomainLedgerPage（S14 主台账走专属 REST，非 domain_pages 信封）。
 * 三态：live（标注台账时点）/ degraded（缓存时点+降级提示）/ empty（EmptyGuide）。
 */
import { useMemo, useState } from 'react'
import { Drawer, Select, Space, Switch, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { TriangleAlert } from 'lucide-react'
import {
  fetchContractorWorkers,
  type ContractorWorkerRow,
  type InsuranceStatus,
  type CertStatus,
} from '@/lib/api/safety/contractor-workers'
import { EmptyGuide, SectionCard, StatCard, StatusTag } from '@/components/ui-kit'
import type { Tone } from '@/components/ui-kit'

const INSURANCE_UI: Record<InsuranceStatus, { label: string; tone: Tone }> = {
  covered: { label: '已覆盖', tone: 'ok' },
  expiring: { label: '临期', tone: 'warn' },
  expired: { label: '已过期', tone: 'danger' },
  unfiled: { label: '未填报', tone: 'warn' },
  uncovered: { label: '未覆盖', tone: 'danger' },
}

const CERT_UI: Record<CertStatus, { label: string; tone: Tone }> = {
  hit: { label: '持证', tone: 'ok' },
  // cert 台账主体是内部员工证书，不能断言无证——降格文案（拍板口径）
  missing: { label: '未见持证记录', tone: 'warn' },
  nonspecial: { label: '—', tone: 'default' },
}

/** 异常标签 → tone（后端中文文案映射；缺省 warn，超龄红档例外） */
const TAG_TONE: Record<string, Tone> = { 超龄: 'danger' }

/** 行详情 Drawer 字段（配置驱动；*为后端已打码字段） */
const DETAIL_FIELDS: { title: string; dataIndex: keyof ContractorWorkerRow; kind?: 'insurance' | 'cert' | 'sex' | 'anomalies' }[] = [
  { title: '姓名', dataIndex: 'name' },
  { title: '身份证（打码）', dataIndex: 'card_no_masked' },
  { title: '手机（打码）', dataIndex: 'phone_masked' },
  { title: '性别', dataIndex: 'sex', kind: 'sex' },
  { title: '出生日期', dataIndex: 'birth_date' },
  { title: '健康状况', dataIndex: 'health' },
  { title: '学历', dataIndex: 'education' },
  { title: '专业', dataIndex: 'major' },
  { title: '入场日期', dataIndex: 'join_job_date' },
  { title: '保险状态', dataIndex: 'insurance_status', kind: 'insurance' },
  { title: '保险有效期至', dataIndex: 'insurance_expire_date' },
  { title: '保险剩余天数', dataIndex: 'insurance_days_left' },
  { title: '保险来源单位', dataIndex: 'insurance_source_company' },
  { title: '特种持证', dataIndex: 'cert_status', kind: 'cert' },
  { title: '证书项目', dataIndex: 'cert_project' },
  { title: '再复审时间', dataIndex: 'cert_next_review_date' },
  { title: '异常标签', dataIndex: 'anomalies', kind: 'anomalies' },
]

function fmtTime(v?: string | null): string {
  if (!v) return '—'
  const d = dayjs(v)
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : v
}

function detailValue(row: ContractorWorkerRow, field: (typeof DETAIL_FIELDS)[number]): string {
  const v = row[field.dataIndex]
  if (field.kind === 'insurance') return INSURANCE_UI[v as InsuranceStatus]?.label ?? '—'
  if (field.kind === 'cert') return CERT_UI[v as CertStatus]?.label ?? '—'
  if (field.kind === 'sex') return v === 1 ? '男' : v === 2 ? '女' : '—'
  if (field.kind === 'anomalies') return (v as string[]).length > 0 ? (v as string[]).join('、') : '无'
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

export function ContractorWorkersLedger() {
  const [contractor, setContractor] = useState<string | undefined>()
  const [workType, setWorkType] = useState<string | undefined>()
  const [anomalyOnly, setAnomalyOnly] = useState(false)
  const [detailRow, setDetailRow] = useState<ContractorWorkerRow | null>(null)

  const query = useQuery({
    queryKey: ['contractor-workers'],
    queryFn: fetchContractorWorkers,
  })
  const data = query.data
  const workers = data?.workers ?? []
  const stats = data?.stats
  const hasData = !!data && data.status !== 'empty' && workers.length > 0

  const contractorOptions = useMemo(
    () =>
      Array.from(new Set(workers.map((w) => w.contractor_name).filter(Boolean)))
        .sort()
        .map((c) => ({ value: c, label: c })),
    [workers],
  )
  const workTypeOptions = useMemo(
    () =>
      Array.from(new Set(workers.map((w) => w.work_type).filter(Boolean)))
        .sort()
        .map((t) => ({ value: t, label: t })),
    [workers],
  )

  const filtered = useMemo(
    () =>
      workers.filter((w) => {
        if (contractor && w.contractor_name !== contractor) return false
        if (workType && w.work_type !== workType) return false
        if (anomalyOnly && w.anomalies.length === 0) return false
        return true
      }),
    [workers, contractor, workType, anomalyOnly],
  )

  const timeNote = data?.fetched_at
    ? data.status === 'degraded'
      ? `缓存时点 ${fmtTime(data.fetched_at)}`
      : `台账时点 ${fmtTime(data.fetched_at)}`
    : ''

  const columns: ColumnsType<ContractorWorkerRow> = [
    { title: '姓名', dataIndex: 'name', width: 90 },
    {
      title: '承包商',
      dataIndex: 'contractor_name',
      width: 200,
      ellipsis: true,
    },
    { title: '工种', dataIndex: 'work_type', width: 90 },
    {
      title: '年龄',
      dataIndex: 'age',
      width: 70,
      render: (v: number | null, row) =>
        v === null || v === undefined ? (
          <span style={{ fontSize: 12, color: '#a4a097' }}>—</span>
        ) : (
          <span style={{ fontSize: 12, color: row.age_flag === 'red' ? '#c53211' : row.age_flag === 'yellow' ? '#9a6b15' : undefined, fontWeight: row.age_flag !== 'none' ? 600 : undefined }}>{v}</span>
        ),
    },
    { title: '入场日期', dataIndex: 'join_job_date', width: 100 },
    {
      title: '保险状态',
      dataIndex: 'insurance_status',
      width: 110,
      render: (v: InsuranceStatus, row) => {
        const ui = INSURANCE_UI[v]
        const label = v === 'expiring' && row.insurance_days_left != null ? `临期${row.insurance_days_left}天` : ui.label
        return <StatusTag tone={ui.tone} label={label} />
      },
    },
    {
      title: '特种持证',
      dataIndex: 'cert_status',
      width: 120,
      render: (v: CertStatus) => {
        if (v === 'nonspecial') return <span style={{ fontSize: 12, color: '#a4a097' }}>—</span>
        const ui = CERT_UI[v]
        return <StatusTag tone={ui.tone} label={ui.label} />
      },
    },
    {
      title: '异常',
      dataIndex: 'anomalies',
      width: 160,
      render: (v: string[]) =>
        v.length === 0 ? (
          <span style={{ fontSize: 12, color: '#a4a097' }}>—</span>
        ) : (
          <Space size={4} wrap>
            {v.map((tag) => (
              <StatusTag key={tag} tone={TAG_TONE[tag] ?? 'warn'} label={tag} />
            ))}
          </Space>
        ),
    },
  ]

  if (query.isError || data?.status === 'empty') {
    return (
      <SectionCard title="承包商在册人员" description="3.x 平台实名台账（在册口径）" className="mt-4">
        <EmptyGuide
          compact
          icon={<TriangleAlert size={28} />}
          title="平台数据暂不可用"
          description={data?.message ?? '3.x 平台接口加载失败，请稍后重试'}
        />
      </SectionCard>
    )
  }

  return (
    <SectionCard
      title="承包商在册人员"
      description={`3.x 平台实名台账 · ${timeNote}${stats ? ` · 特种工种 ${stats.special_total} 人` : ''}`}
      className="mt-4"
    >
      {data?.status === 'degraded' && (
        <div
          style={{
            marginBottom: 12,
            padding: '8px 12px',
            background: '#fdf6e9',
            border: '1px solid #eedfb8',
            borderRadius: 8,
            fontSize: 12,
            color: '#9a6b15',
          }}
        >
          {data.message}
        </div>
      )}

      {hasData && stats && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <StatCard label="在册人数" value={stats.total} tone="primary" loading={query.isLoading} sub="平台实名台账（在册口径）" />
            <StatCard label="承包商数" value={stats.contractors} tone="default" loading={query.isLoading} sub="在册人员覆盖单位" />
            <StatCard
              label="保险覆盖"
              value={`${stats.insurance_covered_pct}%`}
              tone={stats.insurance_covered_pct >= 80 ? 'ok' : stats.insurance_covered_pct >= 50 ? 'warn' : 'danger'}
              loading={query.isLoading}
              sub="有效保险（含临期）占比"
            />
            <StatCard
              label="特种工持证率"
              value={stats.cert_covered_pct == null ? '—' : `${stats.cert_covered_pct}%`}
              tone={stats.cert_covered_pct == null ? 'default' : stats.cert_covered_pct >= 80 ? 'ok' : 'warn'}
              loading={query.isLoading}
              sub={`特种 ${stats.special_total} 人（姓名匹配证书台账）`}
            />
            <StatCard
              label="超龄（≥60）"
              value={stats.overage_count}
              tone={stats.overage_count > 0 ? 'danger' : 'ok'}
              loading={query.isLoading}
              sub={`另有 55-59 岁 ${stats.overage_warn_count} 人预警`}
            />
          </div>

          <div style={{ marginBottom: 12 }}>
            <Space wrap>
              <Select
                placeholder="全部承包商"
                allowClear
                showSearch
                size="small"
                style={{ width: 220 }}
                options={contractorOptions}
                value={contractor}
                onChange={(v) => setContractor(v)}
              />
              <Select
                placeholder="全部工种"
                allowClear
                size="small"
                style={{ width: 120 }}
                options={workTypeOptions}
                value={workType}
                onChange={(v) => setWorkType(v)}
              />
              <span style={{ fontSize: 12, color: '#6b675e' }}>
                仅看异常
                <Switch size="small" style={{ marginLeft: 8 }} checked={anomalyOnly} onChange={setAnomalyOnly} />
              </span>
            </Space>
          </div>

          <Table
            columns={columns}
            dataSource={filtered}
            rowKey="id"
            size="small"
            loading={query.isLoading}
            scroll={{ x: 'max-content' }}
            locale={{
              emptyText: (
                <EmptyGuide compact title="无符合条件的在册人员" description="调整筛选条件后重试" />
              ),
            }}
            onRow={(record) => ({ onClick: () => setDetailRow(record), style: { cursor: 'pointer' } })}
            pagination={{ showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          />
        </>
      )}

      <Drawer
        open={detailRow !== null}
        onClose={() => setDetailRow(null)}
        title={detailRow ? `在册人员详情 - ${detailRow.name}` : '在册人员详情'}
        width={520}
        // 关闭动画结束后再清数据（同 ContractorAdmissionPage 的遮罩卡死教训）
        afterOpenChange={(open) => { if (!open) setDetailRow(null) }}
      >
        {detailRow && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {DETAIL_FIELDS.map((field) => (
              <div key={String(field.dataIndex)}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#a4a097', marginBottom: 2 }}>{field.title}</div>
                <div style={{ fontSize: 13, color: '#43403a', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
                  {detailValue(detailRow, field)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </SectionCard>
  )
}

'use client'

/* 页面数据加载请求会在 effect 中更新本地状态。 */
/* eslint-disable react-hooks/set-state-in-effect */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  EditOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  SettingOutlined,
  TeamOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { PageHeading } from '@/components/shared/PageHeading'
import { usePermission } from '@/hooks/usePermission'
import {
  fetchQaAuditLogs,
  fetchQaAiAnalysis,
  fetchQaMasterObjectProposals,
  fetchQaDepartments,
  fetchQaDocument,
  fetchQaDocumentProcessingResults,
  fetchQaDocumentTypes,
  fetchQaDocuments,
  fetchQaMasterObjects,
  fetchQaSearch,
  fetchQaSources,
  qaFileContentUrl,
  qaMasterKindLabel,
} from '@/lib/api/qa'
import {
  copyQaVersionRelations,
  confirmQaAiRelations,
  createQaDocument,
  createQaDocumentType,
  createQaMasterObject,
  makeQaVersionCurrent,
  retryQaExtraction,
  triggerQaAiAnalysis,
  approveQaMasterObjectProposal,
  rejectQaMasterObjectProposal,
  setQaDocumentActive,
  setQaDocumentTypeActive,
  setQaMasterObjectActive,
  setQaVersionActive,
  updateQaDocument,
  updateQaDocumentType,
  updateQaMasterObject,
  updateQaVersionRelations,
  uploadQaVersion,
} from '@/actions/qa'
import type {
  QaAuditLog,
  QaAiAnalysisRun,
  QaAiObservation,
  QaAiRelationSuggestion,
  QaDepartmentReference,
  QaDocument,
  QaDocumentChunkRunSummary,
  QaDocumentExtractionRunSummary,
  QaDocumentFile,
  QaDocumentProcessingResult,
  QaDocumentProcessingView,
  QaDocumentRawBlock,
  QaDocumentSort,
  QaDocumentTextChunk,
  QaDocumentType,
  QaDocumentVersion,
  QaMasterKind,
  QaMasterObject,
  QaMasterObjectProposal,
  QaSearchResult,
  QaSourceReference,
} from '@/types/qa'
import { QA_MASTER_KIND_LABELS } from '@/types/qa'
import styles from './QaWorkspace.module.css'

const { Text } = Typography
const { Dragger } = Upload

export type QaView = 'home' | 'master-data' | 'documents' | 'audit'

const MASTER_KIND_ORDER: QaMasterKind[] = ['PRODUCT', 'MATERIAL', 'EQUIPMENT', 'SUPPLIER', 'REGION']

/** 台账每页条数。请求、分页器、是否显示分页器三处必须一致，抽成常量避免写飘。 */
const DOCUMENT_PAGE_SIZE = 20

const STATUS_LABEL: Record<string, string> = {
  // 主数据用 active/inactive 两态；缺了 active 会回退成英文原值。
  active: '启用',
  registered: '已登记',
  current: '当前版本',
  history: '历史版本',
  inactive: '已停用',
  queued: '排队中',
  processing: '解析中',
  ready: '可检索',
  partial: '部分完成',
  stale: '需重新分析',
  text_not_available: '无正文',
  unsupported: '不支持解析',
  failed: '解析失败',
}

function displayMasterCode(item: QaMasterObject): string {
  return item.code || item.business_code || '—'
}

function displayDepartmentId(item: QaDepartmentReference): string {
  return item.feishu_department_id || item.id
}

function isMasterActive(item: QaMasterObject): boolean {
  return item.is_active ?? item.status !== 'inactive'
}

function isDocumentActive(item: QaDocument): boolean {
  return item.is_active ?? item.status !== 'inactive'
}

function isVersionActive(item: QaDocumentVersion): boolean {
  return item.is_active ?? displayVersionState(item) !== 'inactive'
}

function isDocumentTypeActive(item: QaDocumentType): boolean {
  return item.is_active ?? item.status !== 'inactive'
}

function displayVersionState(version: QaDocumentVersion): string {
  if (version.state) return version.state
  if (version.status) return version.status
  return version.locked_at || version.first_locked_at ? 'history' : 'registered'
}

function displayFile(version: QaDocumentVersion): QaDocumentFile | null {
  return version.file || version.files?.[0] || null
}

/** 将后端保留的稳定定位字段转换为审核人员可读的位置。索引约定来自
 *  raw block：页码、段落和表格从 1 开始，行/列字段从 0 开始。 */
function formatAiEvidenceLocation(observation: QaAiObservation): string {
  const locator = observation.locator || ''
  const locatorValue = (name: string) => {
    const match = locator.match(new RegExp(`(?:^|/)${name}:(\\d+)`))
    return match ? Number(match[1]) : null
  }
  const parts: string[] = []
  const page = observation.page_number ?? locatorValue('page')
  const paragraph = observation.paragraph_index ?? locatorValue('paragraph')
  const table = observation.table_index ?? locatorValue('table')
  const row = observation.row_index == null ? locatorValue('row') : observation.row_index + 1
  const column = observation.column_index == null ? locatorValue('column') : observation.column_index + 1
  const block = locatorValue('block')
  const chunk = locatorValue('chunk')

  if (page != null) parts.push(`第 ${page} 页`)
  if (paragraph != null) parts.push(`第 ${paragraph} 段`)
  if (table != null) parts.push(`第 ${table} 个表格`)
  if (row != null) parts.push(`第 ${row} 行`)
  if (column != null) parts.push(`第 ${column} 列`)
  if (block != null) parts.push(`第 ${block} 个版面块`)
  if (chunk != null) parts.push(`第 ${chunk + 1} 个上下文块`)
  if (!parts.length && observation.source_order != null) parts.push(`原始块 ${observation.source_order}`)
  return parts.join(' · ') || locator || '定位不可用'
}

function formatRawEvidenceLocator(locator?: unknown): string {
  return formatAiEvidenceLocation({
    id: '',
    mention_text: '',
    normalized_text: '',
    entity_type: '',
    quote: '',
    locator: typeof locator === 'string' ? locator : '',
  })
}

/** 同一实体跨 chunk 去重后，observation_metadata.evidence_locations 汇总了
 *  各处出现位置（首条与主定位字段一致）；旧 run 未重跑时列表缺失，退回单条展示。 */
function evidenceLocationLocators(observation: QaAiObservation): string[] {
  const raw = observation.observation_metadata?.evidence_locations
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => (typeof item.locator === 'string' ? item.locator : ''))
    .filter(Boolean)
}

/** 同一主数据可能被不同写法分别命中（编码原文 exact_code、变体写法
 *  model_fuzzy），各成一条候选行。审核列表按主数据合并成一张卡片：
 *  保留置信度最高的一条（exact 恒高于 model_fuzzy），被合并行的证据
 *  折叠进卡片的「另有 N 处提及」，状态由确认接口统一结算。 */
function dedupeSuggestionsByMaster(suggestions: QaAiRelationSuggestion[]): QaAiRelationSuggestion[] {
  const best = new Map<string, QaAiRelationSuggestion>()
  for (const suggestion of suggestions) {
    const current = best.get(suggestion.master_object_id)
    if (!current || suggestion.confidence > current.confidence) best.set(suggestion.master_object_id, suggestion)
  }
  return suggestions.filter((suggestion) => best.get(suggestion.master_object_id) === suggestion)
}

function AiObservationEvidence({ observation }: { observation: QaAiObservation }) {
  const location = formatAiEvidenceLocation(observation)
  const metadata = observation.observation_metadata?.evidence_location
  const pdf = metadata && typeof metadata === 'object' && 'pdf' in metadata
    ? (metadata as { pdf?: unknown }).pdf
    : null
  const bbox = pdf && typeof pdf === 'object' && Array.isArray((pdf as { bbox?: unknown }).bbox)
    ? (pdf as { bbox: unknown[] }).bbox
    : null
  const coordinate = bbox && bbox.length >= 4
    ? ` · 坐标 ${bbox.slice(0, 4).map((value) => typeof value === 'number' ? value.toFixed(1) : String(value)).join(', ')}`
    : ''
  const locators = evidenceLocationLocators(observation)
  return (
    <div style={{ color: 'var(--color-slate)', fontSize: 12 }}>
      <div>“{observation.quote}”</div>
      <Tooltip title={observation.locator ? `原始定位：${observation.locator}` : undefined}>
        <span>证据位置：{location}{coordinate}</span>
      </Tooltip>
      {locators.length > 1 && (
        <Tooltip title={locators.map((locator, index) => (
          <div key={index}>{index + 1}. {formatRawEvidenceLocator(locator)}</div>
        ))}
        >
          <span style={{ marginLeft: 8 }}>共出现 {locators.length} 处</span>
        </Tooltip>
      )}
    </div>
  )
}

/** 类型在文件台账里一律按名称显示：编码是「文件类型管理」里的书脊、也是跨系统引用的键，
 *  登记与检索时认名字就够了（"验证报告"比"验证报告 (VALIDATION_REPORT)"好读）。
 *  名称缺失时退回编码。 */
function documentTypeLabel(name?: string | null, code?: string | null): string {
  return name || code || '—'
}

/** 列表接口给扁平的 document_type_name/code，详情接口给嵌套的 document_type，两种都要认。 */
function documentTypeLabelOf(document: QaDocument): string {
  return documentTypeLabel(
    document.document_type_name || document.document_type?.name,
    document.document_type_code || document.document_type?.code,
  )
}

/** 下拉里显示名称，但编码仍要能搜到——QA 常常是先拿到别的系统给的编码再来找类型。 */
function documentTypeOption(item: QaDocumentType): { value: string; label: string; search: string } {
  return { value: item.id, label: documentTypeLabel(item.name, item.code), search: `${item.name} ${item.code}` }
}

function formatBytes(value?: number | null): string {
  if (!value || value < 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

const pad2 = (value: number) => String(value).padStart(2, '0')

/** 表格列用的日期：主数据扫读只需要到天。 */
function formatDay(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}

/** 详情用的时间：到分钟，秒对登记类数据没有意义。 */
function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${formatDay(value)} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`
}

function statusTag(value: string | undefined | null, active = true) {
  if (!active || value === 'inactive') return <Tag color="default">已停用</Tag>
  const color = value === 'current' || value === 'ready' || value === 'active' ? 'green' : value === 'failed' ? 'red' : value === 'processing' ? 'blue' : 'gold'
  return <Tag color={color}>{STATUS_LABEL[value || ''] || value || '启用'}</Tag>
}

function actionError(result: { success: boolean; error?: string }): string {
  return result.success ? '' : result.error || '操作失败'
}

function qaSourceOptionLabel(source: QaSourceReference): string {
  const baseLabel = source.code && source.code !== source.name ? `${source.code} · ${source.name}` : source.name
  if (source.source_module !== 'equipment') return baseLabel
  const sourceLabel = source.source === 'shared'
    ? ' · 已共享'
    : source.source === 'own_scope'
      ? ' · 我的设备'
      : ''
  return `${baseLabel}${sourceLabel}`
}

function PageIntro({ view }: { view: QaView }) {
  const title = view === 'home' ? 'QA' : view === 'master-data' ? '质量主数据' : view === 'documents' ? '批准文件台账' : 'QA 审计日志'
  const subtitle = view === 'home'
    ? '集中管理已批准质量文件、质量主数据及其可追溯关系。'
    : view === 'master-data'
      ? 'QA 自有的稳定业务身份；可在登记时关联生产、设备及飞书组织数据。'
      : view === 'documents'
        ? '仅登记外部正式流程已经批准的文件；本模块不替代审批或电子签名。'
        : '记录 QA 写操作、版本切换、文件访问及正文解析结果。'
  return <PageHeading title={title} subtitle={subtitle} />
}

/** QA 模块入口；各路由只传一个 view，便于保持页面边界清晰。 */
export default function QaWorkspace({ view = 'home', documentId }: { view?: QaView; documentId?: string }) {
  return (
    <div style={{ maxWidth: 1480, margin: '0 auto', paddingBottom: 36 }}>
      <PageIntro view={view} />
      {view === 'home' && <QaHome />}
      {view === 'master-data' && <QaMasterData />}
      {view === 'documents' && <QaDocuments initialDocumentId={documentId} />}
      {view === 'audit' && <QaAudit />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 首页：全局搜索 + 概览
// ─────────────────────────────────────────────────────────────

function QaHome() {
  const { message } = App.useApp()
  const router = useRouter()
  const [keyword, setKeyword] = useState('')
  const [submittedKeyword, setSubmittedKeyword] = useState('')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [includeInactive, setIncludeInactive] = useState(false)
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState<QaSearchResult[]>([])
  const [stats, setStats] = useState({ documents: 0, masters: 0, currentVersions: 0, departments: 0 })
  const [statsLoading, setStatsLoading] = useState(true)

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const masterPages = await Promise.all(MASTER_KIND_ORDER.map((kind) => fetchQaMasterObjects({ kind, page: 1, page_size: 1 })))
      // 两个统计都只取接口的 total，各要一行就够，不再逐页拉整本台账。
      const [allDocuments, currentDocuments] = await Promise.all([
        fetchQaDocuments({ page: 1, page_size: 1 }),
        fetchQaDocuments({ page: 1, page_size: 1, has_current_version: true }),
      ])
      const departments = await fetchQaDepartments()
      const masters = masterPages.reduce((sum, page) => sum + page.total, 0)
      setStats({ documents: allDocuments.total, masters, currentVersions: currentDocuments.total, departments: departments.length })
    } catch {
      // 首页概览失败不应阻断搜索；显示 0 并允许用户刷新。
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => { void loadStats() }, [loadStats])

  const runSearch = async () => {
    const q = keyword.trim()
    if (!q) {
      setSubmittedKeyword('')
      setResults([])
      return
    }
    setSearching(true)
    try {
      const page = await fetchQaSearch({ q, include_history: includeHistory, include_inactive: includeInactive, page_size: 50 })
      setResults(page.items)
      setSubmittedKeyword(q)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '搜索失败')
    } finally {
      setSearching(false)
    }
  }

  const resultColumns: ColumnsType<QaSearchResult> = [
    {
      title: '类型', key: 'kind', width: 100,
      render: (_, row) => <Tag color={row.kind === 'document' ? 'purple' : row.kind === 'department' ? 'cyan' : 'blue'}>{qaMasterKindLabel(row.object_type || row.kind)}</Tag>,
    },
    {
      title: '编码 / 文件编号', key: 'code', width: 180,
      render: (_, row) => row.code || row.document_no || row.master_object?.code || '—',
    },
    {
      title: '名称', key: 'name',
      render: (_, row) => row.title || row.name || row.document?.title || row.master_object?.name || row.department?.name || '—',
    },
    {
      title: '命中内容', key: 'snippet', ellipsis: true,
      render: (_, row) => <Tooltip title={row.snippet || undefined}><span>{row.snippet || '—'}</span></Tooltip>,
    },
    {
      title: '定位', key: 'locator', width: 130,
      render: (_, row) => row.locator || (row.page_number ? `第 ${row.page_number} 页` : '—'),
    },
  ]

  return (
    <>
      <Card variant="borderless" style={{ marginBottom: 18, boxShadow: '0 1px 4px rgba(15,15,15,.06)' }}>
        <Input.Search
          size="large"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={() => { void runSearch() }}
          loading={searching}
          enterButton={<><SearchOutlined /> 搜索</>}
          placeholder="搜索文件编号、标题、设备编号、别名或文件正文"
          allowClear
        />
        <Space wrap style={{ marginTop: 14 }}>
          <span style={{ color: '#5d5b54', fontSize: 13 }}>搜索范围：</span>
          <Switch checked={includeHistory} onChange={setIncludeHistory} size="small" />
          <span style={{ fontSize: 13 }}>包含历史版本</span>
          <Switch checked={includeInactive} onChange={setIncludeInactive} size="small" />
          <span style={{ fontSize: 13 }}>包含停用主数据</span>
          {submittedKeyword && <Text type="secondary">“{submittedKeyword}”返回 {results.length} 条</Text>}
        </Space>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 18 }}>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="文件台账" value={stats.documents} loading={statsLoading} prefix={<FileTextOutlined />} /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="质量主数据" value={stats.masters} loading={statsLoading} prefix={<DatabaseOutlined />} /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="已设当前版本" value={stats.currentVersions} loading={statsLoading} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col xs={24} sm={12} lg={6}><Card><Statistic title="飞书部门" value={stats.departments} loading={statsLoading} prefix={<TeamOutlined />} /></Card></Col>
      </Row>

      {results.length > 0 ? (
        <Card title={<span><SearchOutlined /> 搜索结果</span>} extra={<Button icon={<ReloadOutlined />} onClick={() => { void runSearch() }}>刷新</Button>}>
          <Table<QaSearchResult> rowKey={(row) => `${row.kind}-${row.id}-${row.version_id || ''}`} columns={resultColumns} dataSource={results} pagination={false} scroll={{ x: 820 }} onRow={(row) => ({ onClick: () => { const id = row.document_id || (row.kind === 'document' ? row.id : null); if (id) router.push(`/qa/documents/${id}`) }, style: row.document_id || row.kind === 'document' ? { cursor: 'pointer' } : undefined })} />
        </Card>
      ) : (
        <Card>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={submittedKeyword ? '没有匹配的 QA 记录' : '输入关键词检索已批准文件和质量主数据'} />
        </Card>
      )}
    </>
  )
}

// ─────────────────────────────────────────────────────────────
// 质量主数据
// ─────────────────────────────────────────────────────────────

function QaMasterData() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('qa:master:create')
  const canUpdate = hasPermission('qa:master:update')
  const canDeactivate = hasPermission('qa:master:deactivate')
  const [kind, setKind] = useState<QaMasterKind>('PRODUCT')
  const [activeTab, setActiveTab] = useState<string>('PRODUCT')
  const [keyword, setKeyword] = useState('')
  const [queryKeyword, setQueryKeyword] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<QaMasterObject[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Partial<Record<QaMasterKind, number>>>({})
  const [departments, setDepartments] = useState<QaDepartmentReference[]>([])
  const [regionRows, setRegionRows] = useState<QaMasterObject[]>([])
  const [loading, setLoading] = useState(false)
  const [departmentLoading, setDepartmentLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<QaMasterObject | null>(null)
  const [detail, setDetail] = useState<QaMasterObject | null>(null)
  const [proposalInboxOpen, setProposalInboxOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestIdRef = useRef(0)

  const loadRows = useCallback(async () => {
    // 快速切 tab/翻页时旧请求可能后到，用请求序号丢弃过期响应，避免表格显示与当前筛选不符的数据。
    const requestId = ++requestIdRef.current
    setLoading(true)
    try {
      const result = await fetchQaMasterObjects({ kind, keyword: queryKeyword.trim() || undefined, include_inactive: includeInactive, page, page_size: 20 })
      if (requestId === requestIdRef.current) {
        setRows(result.items)
        setTotal(result.total)
      }
    } catch (error) {
      if (requestId === requestIdRef.current) {
        message.error(error instanceof Error ? error.message : '加载主数据失败')
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }, [includeInactive, kind, message, page, queryKeyword])

  const loadReferences = useCallback(async () => {
    setDepartmentLoading(true)
    try {
      const [deptResult, regionResult] = await Promise.all([
        fetchQaDepartments(),
        fetchQaMasterObjects({ kind: 'REGION', include_inactive: false, page: 1, page_size: 200 }),
      ])
      setDepartments(deptResult)
      setRegionRows(regionResult.items)
    } catch {
      // 选择器失败不影响表格查看。
    } finally {
      setDepartmentLoading(false)
    }
  }, [])

  // 类型索引的计数：只取各类型的 total，每类拉一行就够。
  // 它反映词表规模，不跟随关键词筛选——搜"淀粉"时看到各类型还剩多少条，
  // 比看到"当前命中几条"更有用。
  const loadCounts = useCallback(async () => {
    try {
      const pages = await Promise.all(
        MASTER_KIND_ORDER.map((item) => fetchQaMasterObjects({ kind: item, include_inactive: includeInactive, page: 1, page_size: 1 })),
      )
      setCounts(Object.fromEntries(MASTER_KIND_ORDER.map((item, index) => [item, pages[index].total])))
    } catch {
      // 计数失败不影响列表本身，索引退化为不显示数字。
    }
  }, [includeInactive])

  useEffect(() => { void loadRows() }, [loadRows, refreshKey])
  useEffect(() => { void loadReferences() }, [loadReferences])
  useEffect(() => { void loadCounts() }, [loadCounts, refreshKey])

  const openCreate = () => { setEditing(null); setModalOpen(true) }
  const openEdit = (record: QaMasterObject) => { setEditing(record); setModalOpen(true) }

  const toggleActive = async (record: QaMasterObject) => {
    const active = isMasterActive(record)
    const result = await setQaMasterObjectActive(record.id, !active)
    if (!result.success) { message.error(actionError(result)); return }
    message.success(active ? '主数据已停用' : '主数据已启用')
    setRefreshKey((value) => value + 1)
  }

  // 列宽合计必须 ≤ scroll.x，否则末尾列会被 fixed 的操作列盖住（更新时间曾被截断）。
  const MASTER_TABLE_WIDTH = 1130
  const columns: ColumnsType<QaMasterObject> = [
    { title: '业务编码', key: 'code', width: 150, render: (_, row) => <Text strong copyable={{ text: displayMasterCode(row) }}>{displayMasterCode(row)}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    // 别名可能很长，交给列 ellipsis 裁切并把全文放进 title。
    { title: '别名', key: 'aliases', width: 170, ellipsis: true, render: (_, row) => row.aliases?.map((alias) => alias.alias).filter(Boolean).join('、') || '—' },
    {
      title: '责任部门', key: 'department', width: 150, ellipsis: true,
      render: (_, row) => row.responsible_department_name || row.responsible_department_name_snapshot || row.department_name || '—',
    },
    {
      title: '来源', key: 'sources', width: 80, align: 'center',
      render: (_, row) => {
        const list = row.sources || []
        const count = row.source_count ?? list.length
        if (!count) return <span className={styles.muted}>—</span>
        const names = list.map((source) => source.source_name || source.source_name_snapshot || source.name_snapshot || source.source_entity).filter(Boolean)
        return (
          <Tooltip title={names.length ? names.join('、') : `${count} 个外部来源`}>
            <span className={styles.sourceCount}><LinkOutlined />{count}</span>
          </Tooltip>
        )
      },
    },
    { title: '状态', key: 'status', width: 90, render: (_, row) => statusTag(row.status, isMasterActive(row)) },
    {
      title: '更新时间', key: 'updated_at', width: 110,
      render: (_, row) => formatDay(row.updated_at),
    },
    {
      title: '操作', key: 'actions', fixed: 'right', width: 160,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setDetail(row)}>详情</Button>
          {canUpdate && <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>}
          {canDeactivate && <Button type="link" size="small" danger={isMasterActive(row)} onClick={() => { void toggleActive(row) }}>{isMasterActive(row) ? '停用' : '启用'}</Button>}
        </Space>
      ),
    },
  ]

  const departmentColumns: ColumnsType<QaDepartmentReference> = [
    // 飞书部门 ID 是 36 字符，240px 下会折成三行把行高从 56 拉到 82，必须裁切。
    { title: '飞书部门 ID', key: 'id', width: 220, render: (_, row) => <Text copyable={{ text: displayDepartmentId(row) }} ellipsis={{ tooltip: displayDepartmentId(row) }} style={{ maxWidth: '100%' }}>{displayDepartmentId(row)}</Text> },
    { title: '部门名称', dataIndex: 'name', key: 'name', width: 220, ellipsis: true },
    {
      title: '上级部门', dataIndex: 'parent_feishu_department_id', key: 'parent', width: 200, ellipsis: true,
      // 同步下来的是父部门 UUID，直接显示对用户没有意义，换成本地已有的部门名。
      render: (value: string | null | undefined) => {
        if (!value) return '—'
        return departments.find((item) => displayDepartmentId(item) === value)?.name || value
      },
    },
    // 组织路径排最后：本地库这一列还是空的，但 identity.departments.path 是
    // 真实字段（public_api 还用它做搜索），生产可能有值，不删；放末尾是为了
    // 不让空列把 ID / 名称 / 上级部门这三个有用的列隔开。
    { title: '组织路径', dataIndex: 'path', key: 'path', width: 260, ellipsis: true, render: (value: string | null | undefined) => value || '—' },
  ]

  const tabItems = [
    ...MASTER_KIND_ORDER.map((item) => ({
      key: item,
      label: (
        <span className={styles.tabLabel}>
          {QA_MASTER_KIND_LABELS[item]}
          {counts[item] !== undefined && <span className={styles.tabCount}>{counts[item]}</span>}
        </span>
      ),
    })),
    {
      key: 'DEPARTMENTS',
      label: (
        <span className={styles.tabLabel}>
          <span className={styles.tabSep} aria-hidden="true" />
          飞书部门
          <span className={styles.tabCount}>{departments.length || ''}</span>
        </span>
      ),
    },
  ]

  return (
    <>
      <Card variant="borderless">
        <Tabs
          activeKey={activeTab}
          items={tabItems}
          onChange={(key) => {
            setActiveTab(key)
            if (key === 'DEPARTMENTS') return
            setKind(key as QaMasterKind)
            setPage(1)
          }}
        />
        {activeTab !== 'DEPARTMENTS' ? (
          <>
            {/* 工具行独立于 Tabs：放进 tabBarExtraContent 会和 6 个标签抢同一行宽度，
                1200px 下标签已被挤成 "..."。 */}
            <div className={styles.toolbar}>
              <Input.Search
                className={styles.search}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                onSearch={(value) => { setQueryKeyword(value); setPage(1) }}
                allowClear
                placeholder="搜索编码、名称或别名"
              />
              <label className={styles.inactiveToggle}>
                <Switch size="small" checked={includeInactive} onChange={(value) => { setIncludeInactive(value); setPage(1) }} />
                包含停用
              </label>
              <Space>
                {(canCreate || canUpdate) && <Button icon={<CheckCircleOutlined />} onClick={() => setProposalInboxOpen(true)}>AI 提案箱</Button>}
                {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增{QA_MASTER_KIND_LABELS[kind]}</Button>}
              </Space>
            </div>
            <Table<QaMasterObject>
              rowKey="id"
              loading={loading}
              columns={columns}
              dataSource={rows}
              scroll={{ x: MASTER_TABLE_WIDTH }}
              pagination={false}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={queryKeyword ? `没有匹配「${queryKeyword}」的${QA_MASTER_KIND_LABELS[kind]}` : `还没有登记${QA_MASTER_KIND_LABELS[kind]}`}
                  >
                    {queryKeyword
                      ? <Button onClick={() => { setKeyword(''); setQueryKeyword(''); setPage(1) }}>清除搜索</Button>
                      : canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增{QA_MASTER_KIND_LABELS[kind]}</Button>}
                  </Empty>
                ),
              }}
            />
            {total > 20 && (
              <div className={styles.pagination}>
                <Pagination current={page} pageSize={20} total={total} showSizeChanger={false} onChange={(next) => setPage(next)} showTotal={(value) => `共 ${value} 条`} />
              </div>
            )}
          </>
        ) : (
          <>
            <p className={styles.readonlyNote}>飞书部门来自通讯录同步，只读；登记主数据时的「责任部门」从这里选取。</p>
            <Table<QaDepartmentReference> rowKey="id" loading={departmentLoading} columns={departmentColumns} dataSource={departments} pagination={{ pageSize: 20, showSizeChanger: false }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无飞书部门" /> }} />
          </>
        )}
      </Card>

      <QaMasterObjectModal
        open={modalOpen}
        record={editing}
        kind={kind}
        departments={departments}
        regions={regionRows}
        onClose={() => setModalOpen(false)}
        onSaved={() => { setModalOpen(false); setRefreshKey((value) => value + 1); void loadReferences() }}
      />
      <Drawer title="主数据详情" open={!!detail} size={520} onClose={() => setDetail(null)}>
        {detail && <QaMasterDetail item={detail} />}
      </Drawer>
      <QaMasterProposalInbox
        open={proposalInboxOpen}
        onClose={() => setProposalInboxOpen(false)}
        canCreate={canCreate}
        canUpdate={canUpdate}
      />
    </>
  )
}

/** 单条主数据的身份卡：先立编码/名称/状态，再列属性与外部来源。
 *
 * 空字段不逐行铺开成 "—"，只保留有值的；但「责任部门」缺失是 QA 需要看到的
 * 管理信号（无人负责的受控身份），所以始终占位并标为未指定。
 */
function QaMasterDetail({ item }: { item: QaMasterObject }) {
  const aliases = item.aliases?.map((entry) => entry.alias).filter(Boolean) || []
  const sources = item.sources || []
  const department = item.responsible_department_name || item.responsible_department_name_snapshot || item.department_name || ''

  const fields: Array<{ label: string; value: React.ReactNode }> = [
    { label: '责任部门', value: department || <span className={styles.fieldMissing}>未指定</span> },
    ...(item.kind === 'REGION' ? [{ label: '父级区域', value: item.parent_id || item.region_parent_id || '' }] : []),
    ...(item.kind === 'SUPPLIER' ? [
      { label: '联系人', value: item.contact_name || '' },
      { label: '电话', value: item.contact_phone || '' },
      { label: '邮箱', value: item.contact_email || '' },
    ] : []),
    { label: '描述', value: item.description || item.remark || '' },
    { label: '更新时间', value: formatDate(item.updated_at) },
  ].filter((field) => field.value !== '' && field.value != null)

  return (
    <>
      <div className={styles.identity}>
        <Text className={styles.identityCode} copyable={{ text: displayMasterCode(item) }}>{displayMasterCode(item)}</Text>
        <div className={styles.identityName}>{item.name}</div>
        <div className={styles.identityMeta}>
          {statusTag(item.status, isMasterActive(item))}
          <span className={styles.identityKind}>{qaMasterKindLabel(item.kind || item.object_type)}</span>
        </div>
        {/* 别名是"同一实体在别的系统/车间里的叫法"，主数据存在的理由；没有就不占位。 */}
        {aliases.length > 0 && (
          <div className={styles.aliasRow}>
            <span className={styles.aliasLabel}>又名</span>
            <span className={styles.aliasValue}>{aliases.map((alias) => <Tag key={alias}>{alias}</Tag>)}</span>
          </div>
        )}
      </div>

      <dl className={styles.fields}>
        {fields.map((field) => (
          <Fragment key={field.label}>
            <dt className={styles.fieldLabel}>{field.label}</dt>
            <dd className={styles.fieldValue}>{field.value}</dd>
          </Fragment>
        ))}
      </dl>

      <div className={styles.sectionTitle}>外部来源</div>
      {sources.length > 0 ? (
        <ul className={styles.sourceList}>
          {sources.map((source, index) => {
            const available = source.source_available !== false
            return (
              <li className={styles.sourceRow} key={source.id || `${source.source_module}-${source.source_id}-${index}`}>
                <div className={styles.sourceMain}>
                  <span className={styles.sourceName}>{source.source_name || source.source_name_snapshot || source.name_snapshot || '未命名来源'}</span>
                  <span className={styles.sourceMeta}>{source.source_module} / {source.source_entity} · {source.source_id}</span>
                </div>
                <span className={available ? styles.sourceOk : styles.sourceWarn}>{available ? '可用' : '已失效'}</span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className={styles.fieldMissing}>未关联外部来源</p>
      )}
    </>
  )
}

function QaMasterObjectModal({
  open,
  record,
  kind,
  departments,
  regions,
  onClose,
  onSaved,
}: {
  open: boolean
  record: QaMasterObject | null
  kind: QaMasterKind
  departments: QaDepartmentReference[]
  regions: QaMasterObject[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = record ? hasPermission('qa:master:update') : hasPermission('qa:master:create')
  const [sourceOptions, setSourceOptions] = useState<QaSourceReference[]>([])
  const [sourceLoading, setSourceLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    const sourceValues = record?.sources?.map((source) => `${source.source_module}|${source.source_entity}|${source.source_id}`) || []
    form.setFieldsValue({
      kind: record?.kind || kind,
      code: record ? displayMasterCode(record) : '',
      name: record?.name || '',
      description: record?.description || record?.remark || '',
      department_id: record?.responsible_department_id || record?.department_id || undefined,
      parent_id: record?.parent_id || record?.region_parent_id || undefined,
      contact_name: record?.contact_name || '',
      contact_phone: record?.contact_phone || '',
      contact_email: record?.contact_email || '',
      remark: record?.remark || '',
      aliases: record?.aliases?.map((alias) => alias.alias).join(', ') || '',
      sources: sourceValues,
    })
    setSourceOptions([])
  }, [form, kind, open, record])

  const loadSources = async (search: string) => {
    if (!open || kind === 'SUPPLIER' || kind === 'REGION') return
    setSourceLoading(true)
    try {
      const result = await fetchQaSources(kind, { keyword: search || undefined, page_size: 50 })
      setSourceOptions(result.items)
    } catch {
      setSourceOptions([])
    } finally {
      setSourceLoading(false)
    }
  }

  const handleSubmit = async () => {
    if (!canManage) { message.error('没有该操作权限'); return }
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values) return
    const department = departments.find((item) => item.id === values.department_id || item.feishu_department_id === values.department_id)
    const rawAliases = typeof values.aliases === 'string' ? values.aliases : ''
    const aliases = rawAliases.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean)
    const sourceValues = Array.isArray(values.sources) ? values.sources as string[] : []
    const sources = sourceValues.map((value) => {
      const [source_module, source_entity, source_id] = value.split('|')
      return { source_module, source_entity, source_id }
    }).filter((value) => value.source_id)
    const payload: Record<string, unknown> = {
      kind: (record?.kind || kind),
      code: String(values.code || '').trim().toUpperCase(),
      name: String(values.name || '').trim(),
      description: values.description || null,
      responsible_department_id: values.department_id || null,
      responsible_department_name: department?.name || null,
      responsible_department_name_snapshot: department?.name || null,
      parent_id: values.parent_id || null,
      region_parent_id: values.parent_id || null,
      contact_name: values.contact_name || null,
      contact_phone: values.contact_phone || null,
      contact_email: values.contact_email || null,
      remark: values.remark || null,
      aliases,
      sources,
    }
    if (submitting) return
    setSubmitting(true)
    try {
      const result = record ? await updateQaMasterObject(record.id, payload) : await createQaMasterObject(payload)
      if (!result.success) { message.error(actionError(result)); return }
      message.success(record ? '主数据已更新' : '主数据已创建')
      onSaved()
    } finally { setSubmitting(false) }
  }

  // 已关联的来源可能不在搜索结果里（打开弹窗时还没搜索），先并入选项，
  // 否则 Select 找不到匹配项会直接显示 `模块|实体|id` 原始值。
  const sourceSelectOptions = useMemo(() => {
    const linked = (record?.sources || []).map((source) => ({
      id: source.id || `${source.source_module}|${source.source_id}`,
      code: source.source_code || source.source_code_snapshot || source.code_snapshot || null,
      name: source.source_name || source.source_name_snapshot || source.name_snapshot || '未命名来源',
      source_module: source.source_module,
      source_entity: source.source_entity,
      source_id: source.source_id,
    }))
    return [...sourceOptions, ...linked]
      .map((source) => ({
        value: `${source.source_module}|${source.source_entity}|${source.source_id}`,
        label: qaSourceOptionLabel(source),
      }))
      .filter((option, index, list) => list.findIndex((item) => item.value === option.value) === index)
  }, [record, sourceOptions])

  return (
    <Modal title={record ? `编辑${QA_MASTER_KIND_LABELS[record.kind]}` : `新增${QA_MASTER_KIND_LABELS[kind]}`} open={open} onCancel={onClose} onOk={() => { void handleSubmit() }} okText="保存" cancelText="取消" confirmLoading={submitting} destroyOnHidden width={620}>
      <Form form={form} layout="vertical">
        <Form.Item name="kind" label="主数据类型"><Select disabled options={MASTER_KIND_ORDER.map((value) => ({ value, label: QA_MASTER_KIND_LABELS[value] }))} /></Form.Item>
        <Row gutter={12}>
          <Col span={10}><Form.Item name="code" label="业务编码" rules={[{ required: true, message: '请输入业务编码' }]}><Input disabled={!!record} maxLength={80} placeholder="保存时自动转为大写" /></Form.Item></Col>
          <Col span={14}><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input maxLength={200} /></Form.Item></Col>
        </Row>
        <Form.Item name="aliases" label="别名" extra="多个别名用逗号或换行分隔，用于全局检索"><Input.TextArea rows={2} maxLength={1000} /></Form.Item>
        <Form.Item name="department_id" label="责任部门"><Select allowClear showSearch={{ optionFilterProp: 'label' }} options={departments.map((item) => ({ value: displayDepartmentId(item), label: `${item.name} (${displayDepartmentId(item)})` }))} placeholder="选择飞书组织部门" /></Form.Item>
        {kind === 'REGION' && <Form.Item name="parent_id" label="父级区域"><Select allowClear showSearch={{ optionFilterProp: 'label' }} options={regions.filter((item) => item.id !== record?.id).map((item) => ({ value: item.id, label: `${displayMasterCode(item)} · ${item.name}` }))} placeholder="可选，系统会校验不能形成循环" /></Form.Item>}
        {kind === 'SUPPLIER' && <Row gutter={12}>
          <Col span={8}><Form.Item name="contact_name" label="联系人"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="contact_phone" label="电话"><Input /></Form.Item></Col>
          <Col span={8}><Form.Item name="contact_email" label="邮箱"><Input /></Form.Item></Col>
        </Row>}
        {(kind === 'PRODUCT' || kind === 'MATERIAL' || kind === 'EQUIPMENT') && <Form.Item name="sources" label="关联外部来源" extra="来源仅保存引用与快照，QA 记录仍由本模块负责">
          <Select mode="multiple" showSearch={{ filterOption: false, onSearch: (value) => { void loadSources(value) } }} onFocus={() => { void loadSources('') }} loading={sourceLoading} options={sourceSelectOptions} placeholder="搜索生产产品、产出物或设备台账" />
        </Form.Item>}
        <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
      </Form>
    </Modal>
  )
}

function QaMasterProposalInbox({ open, onClose, canCreate, canUpdate }: {
  open: boolean
  onClose: () => void
  canCreate: boolean
  canUpdate: boolean
}) {
  const { message, modal } = App.useApp()
  const [rows, setRows] = useState<QaMasterObjectProposal[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [editing, setEditing] = useState<QaMasterObjectProposal | null>(null)
  const [statusFilter, setStatusFilter] = useState<'pending' | 'conflict' | 'all'>('pending')

  const load = useCallback(async () => {
    if (!open) return
    setLoading(true)
    try {
      const result = await fetchQaMasterObjectProposals({
        status: statusFilter === 'all' ? undefined : statusFilter,
        page: 1,
        page_size: 100,
      })
      setRows(result.items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载 AI 提案失败')
    } finally { setLoading(false) }
  }, [message, open, statusFilter])

  useEffect(() => { void load() }, [load, refreshKey])

  const approve = (row: QaMasterObjectProposal) => {
    setEditing(row)
  }

  const reject = (row: QaMasterObjectProposal) => {
    modal.confirm({
      title: '拒绝 AI 提案',
      content: '拒绝后该提案将从提案箱移除。',
      okText: '拒绝', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        const result = await rejectQaMasterObjectProposal(row.id)
        if (!result.success) { message.error(actionError(result)); return }
        message.success('提案已拒绝')
        setRefreshKey((value) => value + 1)
      },
    })
  }

  return (
    <Drawer title="AI 主数据提案箱" open={open} onClose={() => { setEditing(null); onClose() }} size={720} extra={<Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((value) => value + 1)}>刷新</Button>}>
      <Alert type="info" showIcon title="AI 只提出建议" description="审批前可在此核对字段和证据；AI 不会自动写入正式主数据或跨模块来源。" style={{ marginBottom: 16 }} />
      <Segmented
        value={statusFilter}
        options={[
          { value: 'pending', label: '待审核' },
          { value: 'conflict', label: '冲突' },
          { value: 'all', label: '全部' },
        ]}
        onChange={(value) => setStatusFilter(value as 'pending' | 'conflict' | 'all')}
        style={{ marginBottom: 16 }}
      />
      <Table<QaMasterObjectProposal>
        rowKey="id" loading={loading} dataSource={rows} pagination={false} scroll={{ x: 760 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={statusFilter === 'pending' ? '暂无待审核提案' : statusFilter === 'conflict' ? '暂无冲突提案' : '暂无 AI 提案'} /> }}
        columns={[
          { title: '类型', dataIndex: 'proposal_type', width: 80, render: (value: string) => value === 'create' ? '新增' : '变更' },
          { title: '主数据类型', dataIndex: 'object_type', width: 100, render: (value: string) => qaMasterKindLabel(value) },
          { title: '建议名称', key: 'name', render: (_, row) => String(row.proposed_payload.name || row.proposed_payload.code || '—') },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (value: string, row) => {
              const conflictText = row.conflicts?.map((item) => String(item.reason || '')).filter(Boolean).join('；')
              const tag = value === 'pending'
                ? <Tag color="gold">待审核</Tag>
                : value === 'conflict'
                  ? <Tag color="red">冲突</Tag>
                  : value === 'approved'
                    ? <Tag color="green">已审批</Tag>
                    : value === 'rejected'
                      ? <Tag>已拒绝</Tag>
                      : <Tag>{STATUS_LABEL[value] || value}</Tag>
              return conflictText ? <Tooltip title={conflictText}>{tag}</Tooltip> : tag
            },
          },
          {
            title: '证据',
            key: 'evidence',
            width: 200,
            render: (_, row) => {
              const evidence = row.evidence?.[0]
              const quote = typeof evidence?.quote === 'string' ? evidence.quote : ''
              const locator = typeof evidence?.locator === 'string' ? evidence.locator : ''
              const documentName = typeof evidence?.document_name === 'string' ? evidence.document_name : ''
              if (!quote && !locator) return '—'
              // 审核人先认「哪个文件」再看段落位置；来源文件经后端按提案回填。
              const source = [documentName, locator ? formatRawEvidenceLocator(locator) : ''].filter(Boolean).join(' · ')
              return (
                <Tooltip title={[documentName ? `文件：${documentName}` : '', quote, locator ? `原始定位：${locator}` : ''].filter(Boolean).join('\n')}>
                  <div style={{ maxWidth: 180 }}>
                    <Text ellipsis style={{ display: 'block' }}>{quote || '无引用片段'}</Text>
                    {source && <Text type="secondary" ellipsis style={{ display: 'block', fontSize: 12 }}>{source}</Text>}
                  </div>
                </Tooltip>
              )
            },
          },
          {
            title: '操作', key: 'actions', width: 140,
            render: (_, row) => {
              if (row.status !== 'pending') {
                const reason = row.status === 'conflict'
                  ? row.conflicts?.map((item) => String(item.reason || '')).filter(Boolean).join('；')
                  : undefined
                return <Tooltip title={reason || undefined}><Text type="secondary">已处理</Text></Tooltip>
              }
              const canHandle = row.proposal_type === 'create' ? canCreate : canUpdate
              return canHandle
                ? <Space size={0}><Button type="link" size="small" onClick={() => approve(row)}>审批</Button><Button type="link" size="small" danger onClick={() => reject(row)}>拒绝</Button></Space>
                : <Text type="secondary">无对应权限</Text>
            },
          },
        ]}
      />
      <QaProposalApproveModal
        proposal={editing}
        onClose={() => setEditing(null)}
        onApproved={() => { setEditing(null); setRefreshKey((value) => value + 1) }}
        onServerStateChanged={(status) => {
          setEditing(null)
          setStatusFilter(status)
          setRefreshKey((value) => value + 1)
        }}
      />
    </Drawer>
  )
}

/** 提案最终展示/编辑用的字段快照：基线叠加提案自身建议的修正。 */
function proposalPayload(proposal: QaMasterObjectProposal): Record<string, unknown> {
  return { ...(proposal.base_snapshot || {}), ...(proposal.proposed_payload || {}) }
}

/** 快照里的别名列表 → 表单多行文本，供提交时比对审核人是否真的改过。 */
function proposalAliasText(proposal: QaMasterObjectProposal): string {
  const payload = proposalPayload(proposal)
  return Array.isArray(payload.aliases)
    ? payload.aliases
      .map((item) => typeof item === 'string' ? item : (item && typeof item === 'object' ? String((item as { alias?: unknown }).alias || '') : ''))
      .filter(Boolean)
      .join('\n')
    : ''
}

/**
 * 提案审批前的最小人工修正表单。
 *
 * 提案服务会将这里提交的字段合并回原始提案，因此没有出现在表单中的
 * 联系人、责任部门等字段仍会被保留；来源对象刻意不暴露，避免 AI 路径
 * 越过人工来源选择约束。主数据编码在更新场景保持只读（后端更新契约
 * 也不允许改编码），新增场景可以在发布前修正。
 */
function QaProposalApproveModal({ proposal, onClose, onApproved, onServerStateChanged }: {
  proposal: QaMasterObjectProposal | null
  onClose: () => void
  onApproved: () => void
  onServerStateChanged: (status: 'conflict' | 'all') => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!proposal) return
    const payload = proposalPayload(proposal)
    form.setFieldsValue({
      code: String(payload.code || payload.business_code || ''),
      name: String(payload.name || ''),
      description: payload.description == null ? '' : String(payload.description),
      aliases: proposalAliasText(proposal),
    })
  }, [form, proposal])

  const submit = async () => {
    if (!proposal || submitting) return
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values) return
    const aliases = String(values.aliases || '')
      .split(/[\n,，]/)
      .map((item) => item.trim())
      .filter(Boolean)
    const payload: Record<string, unknown> = {
      name: String(values.name || '').trim(),
      description: String(values.description || '').trim() || null,
    }
    // 用「值是否变化」而不是 isFieldTouched 判断审核人是否改过别名：
    // setFieldsValue 是外部赋值，字段是否被标记为 touched 取决于表单库实现，
    // 一旦误判就会把只改了名称的提案里的别名一并提交，而别名在提交时会被
    // 按逗号/换行拆分，含逗号的真实别名会被拆成多个错误别名。
    const aliasesWereExplicitlyChanged = String(values.aliases || '') !== proposalAliasText(proposal)
    if (proposal.proposal_type === 'create' || aliasesWereExplicitlyChanged || Object.prototype.hasOwnProperty.call(proposal.proposed_payload || {}, 'aliases')) {
      payload.aliases = aliases
    }
    if (proposal.proposal_type === 'create') {
      payload.object_type = String(proposal.object_type).toUpperCase()
      payload.code = String(values.code || '').trim()
    }
    setSubmitting(true)
    try {
      const result = await approveQaMasterObjectProposal(proposal.id, payload)
      if (!result.success) {
        const error = actionError(result)
        message.error(error)
        // 冲突/过期路径会先持久化提案状态再返回 409；立即切换并刷新，
        // 避免用户仍在编辑一条已经不能再次审批的旧快照。
        if (error.includes('已标记冲突')) onServerStateChanged('conflict')
        else if (/已标记过期|来源已过期|来源已失效|来源分析运行不存在/.test(error)) onServerStateChanged('all')
        return
      }
      // 审批通过时后端已在同一事务内自动建立文件 ↔ 主数据关联；仅当来源
      // 版本已是历史/停用快照时无法追加，需走新版本链路。
      if (result.data?.auto_linked === false) {
        message.warning(`提案已审批，但文件关联未自动建立（${result.data.auto_link_skipped_reason || '原因未知'}）；如需关联请上传新版本后维护`)
      } else {
        message.success('提案已审批，正式主数据与文件关联已更新')
      }
      onApproved()
    } finally {
      setSubmitting(false)
    }
  }

  const payload = proposal?.proposed_payload || {}
  return (
    <Modal
      title={`审批${proposal?.proposal_type === 'create' ? '新增' : '变更'}提案`}
      open={Boolean(proposal)}
      onCancel={onClose}
      onOk={() => { void submit() }}
      okText="审批并发布"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
    >
      {proposal && <>
        <Alert
          type="info"
          showIcon
          title={`主数据类型：${qaMasterKindLabel(proposal.object_type)}`}
          description={proposal.proposal_type === 'create' ? '请核对并修正发布字段；来源对象需在主数据页面另行人工维护。' : '更新提案以当前主数据为基础，编码不可修改；如基础版本已变化，审批会被标记为冲突。'}
          style={{ marginBottom: 16 }}
        />
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="业务编码" rules={proposal.proposal_type === 'create' ? [{ required: true, message: '请输入业务编码' }] : undefined}>
            <Input disabled={proposal.proposal_type !== 'create'} maxLength={100} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
          <Form.Item name="aliases" label="别名" extra="多个别名用换行或逗号分隔">
            <Input.TextArea rows={3} maxLength={4000} />
          </Form.Item>
        </Form>
        <Divider plain>原始提案字段（未编辑项会按原提案保留）</Divider>
        <pre style={{ maxHeight: 140, overflow: 'auto', whiteSpace: 'pre-wrap', marginBottom: 0 }}>{JSON.stringify(payload, null, 2)}</pre>
      </>}
    </Modal>
  )
}

// ─────────────────────────────────────────────────────────────
// 文件台账、版本与关联
// ─────────────────────────────────────────────────────────────

function QaDocuments({ initialDocumentId }: { initialDocumentId?: string }) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canCreate = hasPermission('qa:document:create')
  const canUpdate = hasPermission('qa:document:update')
  const canDeactivate = hasPermission('qa:document:deactivate')
  const canVersion = hasPermission('qa:version:create')
  const canCurrent = hasPermission('qa:version:make_current')
  const canDisableVersion = hasPermission('qa:version:disable')
  const canRelation = hasPermission('qa:relation:manage')
  const canConfig = hasPermission('qa:config:manage')
  const [keyword, setKeyword] = useState('')
  const [queryKeyword, setQueryKeyword] = useState('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [includeHistory, setIncludeHistory] = useState(false)
  const [sortBy, setSortBy] = useState<QaDocumentSort>('document_no')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<QaDocument[]>([])
  const [total, setTotal] = useState(0)
  const [types, setTypes] = useState<QaDocumentType[]>([])
  const [departments, setDepartments] = useState<QaDepartmentReference[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<QaDocument | null>(null)
  const [typeManagerOpen, setTypeManagerOpen] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(initialDocumentId || null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => { setDetailId(initialDocumentId || null) }, [initialDocumentId])

  const loadDocuments = useCallback(async () => {
    setLoading(true)
    try {
      const result = await fetchQaDocuments({ keyword: queryKeyword.trim() || undefined, include_inactive: includeInactive, include_history: includeHistory, sort_by: sortBy, page, page_size: DOCUMENT_PAGE_SIZE })
      setRows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载文件台账失败')
    } finally {
      setLoading(false)
    }
  }, [includeHistory, includeInactive, message, page, queryKeyword, sortBy])

  useEffect(() => { void loadDocuments() }, [loadDocuments, refreshKey])
  useEffect(() => {
    void Promise.all([fetchQaDocumentTypes(), fetchQaDepartments()]).then(([documentTypes, depts]) => {
      setTypes(documentTypes)
      setDepartments(depts)
    }).catch(() => { /* 表格仍可使用 */ })
  }, [])

  const toggleActive = async (record: QaDocument) => {
    const active = isDocumentActive(record)
    const result = await setQaDocumentActive(record.id, !active)
    if (!result.success) { message.error(actionError(result)); return }
    message.success(active ? '文件已停用' : '文件已启用')
    setRefreshKey((value) => value + 1)
  }

  const openDetail = (id: string) => setDetailId(id)
  const trimmedKeyword = queryKeyword.trim()

  return (
    <>
      <div className={`${styles.toolbar} ${styles.toolbarSpaced}`}>
        <Input.Search
          className={styles.search}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={(value) => { setQueryKeyword(value); setPage(1) }}
          allowClear
          placeholder="搜索文件编号、标题或正文"
        />
        <Segmented
          value={sortBy}
          onChange={(value) => { setSortBy(value as QaDocumentSort); setPage(1) }}
          options={[{ value: 'document_no', label: '按编号' }, { value: 'title', label: '按标题' }]}
        />
        <label className={styles.toggle}>
          <Switch size="small" checked={includeHistory} onChange={(value) => { setIncludeHistory(value); setPage(1) }} />
          包含历史版本
        </label>
        <label className={styles.toggle}>
          <Switch size="small" checked={includeInactive} onChange={(value) => { setIncludeInactive(value); setPage(1) }} />
          包含停用
        </label>
        <div className={styles.toolbarActions}>
          <Button icon={<ReloadOutlined />} onClick={() => { setRefreshKey((value) => value + 1) }}>刷新</Button>
          {canConfig && <Button icon={<SettingOutlined />} onClick={() => setTypeManagerOpen(true)}>文件类型</Button>}
          {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalOpen(true) }}>登记文件</Button>}
        </div>
      </div>

      {loading && rows.length === 0 ? (
        <div className={`${styles.ledgerPanel} ${styles.ledgerEmpty}`}><Spin /></div>
      ) : rows.length === 0 ? (
        <div className={`${styles.ledgerPanel} ${styles.ledgerEmpty}`}>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={trimmedKeyword ? `没有匹配「${trimmedKeyword}」的文件` : '还没有登记文件'}
          >
            {trimmedKeyword
              ? <Button onClick={() => { setKeyword(''); setQueryKeyword(''); setPage(1) }}>清除搜索</Button>
              : canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalOpen(true) }}>登记文件</Button>}
          </Empty>
        </div>
      ) : (
        <div className={styles.ledgerPanel}>
          <ul className={styles.ledger}>
            {rows.map((row) => {
              const active = isDocumentActive(row)
              const currentLabel = row.current_version_label || ''
              const versionCount = row.version_count ?? 0
              const department = row.responsible_department_name_snapshot || row.responsible_department_name || row.department_name || ''
              return (
                <li key={row.id} className={styles.ledgerRow}>
                  {/* 书脊：编号对齐成一条竖线，台账的"一本"感来自这里 */}
                  <div className={styles.ledgerSpine}>
                    <span className={`${styles.ledgerCode} ${active ? '' : styles.ledgerCodeOff}`}>{row.document_no}</span>
                  </div>

                  <div className={styles.ledgerMain}>
                    {/* 一行装完：标题 · 现行版本 · 出处 · 例外。台账要的是行数，不是行高。 */}
                    <div className={styles.ledgerHead}>
                      <button type="button" className={styles.ledgerTitle} onClick={() => openDetail(row.id)}>{row.title}</button>
                      {currentLabel
                        ? <span className={`${styles.chainMark} ${styles.chainMarkCurrent}`}>{currentLabel} 现行</span>
                        : active && <span className={styles.chainWarn}>未设现行版本</span>}
                      <span className={styles.ledgerMetaItem}>{documentTypeLabelOf(row)}</span>
                      {department && <span className={styles.ledgerMetaItem}>{department}</span>}
                      <span className={styles.ledgerMetaItem}>{versionCount > 0 ? `共 ${versionCount} 个版本` : '尚无版本'}</span>
                      <span className={styles.ledgerMetaItem}>更新于 {formatDay(row.updated_at)}</span>
                      {row.current_extraction_status === 'failed' && <span className={styles.chainWarn}>正文解析失败</span>}
                    </div>
                  </div>

                  {/* 状态与动作同处一组：例外标签和它要做的处理读成一句话，也不跟按钮隔一道行间距 */}
                  <div className={styles.ledgerActions}>
                    {!active && <span className={styles.ledgerStatus}>{statusTag(row.status, false)}</span>}
                    <button type="button" className={styles.rowAction} onClick={() => openDetail(row.id)}>详情</button>
                    {canUpdate && <button type="button" className={styles.rowAction} onClick={() => { setEditing(row); setModalOpen(true) }}>编辑</button>}
                    {canDeactivate && (
                      <button
                        type="button"
                        className={`${styles.rowAction} ${active ? styles.rowActionDanger : styles.rowActionPositive}`}
                        onClick={() => { void toggleActive(row) }}
                      >
                        {active ? '停用' : '启用'}
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* 只有一页时不渲染分页器：单页的「1」和总数是纯噪音，台账本身已经把条数说清楚了。 */}
      {total > DOCUMENT_PAGE_SIZE && (
        <div className={styles.pagination}>
          <Pagination current={page} pageSize={DOCUMENT_PAGE_SIZE} total={total} showSizeChanger={false} onChange={setPage} showTotal={(value) => `共 ${value} 条`} />
        </div>
      )}

      <QaDocumentModal open={modalOpen} record={editing} types={types} departments={departments} onClose={() => setModalOpen(false)} onSaved={() => { setModalOpen(false); setRefreshKey((value) => value + 1) }} />
      <QaDocumentTypeManager open={typeManagerOpen} onClose={() => setTypeManagerOpen(false)} onChanged={() => { void fetchQaDocumentTypes({ include_inactive: true }).then(setTypes).catch(() => undefined) }} />
      <QaDocumentDetailDrawer
        documentId={detailId}
        canVersion={canVersion}
        canCurrent={canCurrent}
        canDisableVersion={canDisableVersion}
        canRelation={canRelation}
        onClose={() => setDetailId(null)}
        onChanged={() => setRefreshKey((value) => value + 1)}
      />
    </>
  )
}

function QaDocumentModal({
  open,
  record,
  types,
  departments,
  onClose,
  onSaved,
}: {
  open: boolean
  record: QaDocument | null
  types: QaDocumentType[]
  departments: QaDepartmentReference[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      document_no: record?.document_no || '',
      title: record?.title || '',
      document_type_id: record?.document_type_id || undefined,
      department_id: record?.responsible_department_id || record?.department_id || undefined,
    })
  }, [form, open, record])

  const handleSubmit = async () => {
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values) return
    const department = departments.find((item) => item.id === values.department_id || item.feishu_department_id === values.department_id)
    const payload = {
      // 编号在编辑态是只读身份、不再作为表单控件，值直接取记录本身
      document_no: record ? record.document_no : String(values.document_no || '').trim(),
      title: String(values.title || '').trim(),
      document_type_id: values.document_type_id,
      responsible_department_id: values.department_id || null,
      responsible_department_name: department?.name || null,
    }
    const allowed = record ? hasPermission('qa:document:update') : hasPermission('qa:document:create')
    if (!allowed) { message.error('没有该操作权限'); return }
    if (submitting) return
    setSubmitting(true)
    try {
      const result = record ? await updateQaDocument(record.id, payload) : await createQaDocument(payload)
      if (!result.success) { message.error(actionError(result)); return }
      message.success(record ? '文件台账已更新' : '文件台账已创建')
      onSaved()
    } finally { setSubmitting(false) }
  }

  return (
    <Modal title={record ? '编辑文件台账' : '登记文件台账'} open={open} onCancel={onClose} onOk={() => { void handleSubmit() }} okText={record ? '保存' : '登记'} cancelText="取消" confirmLoading={submitting} destroyOnHidden width={560}>
      <Form form={form} layout="vertical">
        <p className={styles.formNote}>
          {record
            ? '这里只改这份文件在台账里的登记项；版本与原件在文件详情里维护。'
            : '登记的是外部已批准的文件，编号与标题按批准件填写。登记后还要上传批准原件作为版本，正文才能被检索到。'}
        </p>

        <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
          <Form.Item label="文件编号" required={!record}>
            {record
              ? <span className={styles.lockedCode}>{record.document_no}</span>
              : <Form.Item name="document_no" noStyle rules={[{ required: true, message: '请输入文件编号' }]}><Input maxLength={100} /></Form.Item>}
          </Form.Item>
          <Form.Item name="document_type_id" label="文件类型" rules={[{ required: true, message: '请选择文件类型' }]}><Select showSearch={{ optionFilterProp: 'search' }} options={types.filter(isDocumentTypeActive).map(documentTypeOption)} placeholder="选择文件类型" /></Form.Item>
        </div>

        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入文件标题' }]}><Input maxLength={300} placeholder="与批准件上的标题一致" /></Form.Item>
        <Form.Item name="department_id" label="责任部门" extra="文件的归口部门，可留空"><Select allowClear showSearch={{ optionFilterProp: 'label' }} options={departments.map((item) => ({ value: displayDepartmentId(item), label: item.name }))} placeholder="选择飞书组织部门" /></Form.Item>
      </Form>
    </Modal>
  )
}

/** 行内小标签：静默灰底，只承载文字含义，不与主色 CTA 抢眼（只标例外，正常项不加）。 */
function MetaChip({ children }: { children: string }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-[4px] bg-[var(--color-surface)] px-2 py-[1px] text-[11px] font-medium leading-[18px] text-[var(--color-slate)]">
      {children}
    </span>
  )
}

/** 文件类型是受控词表：条目少、变动慢，编码是跨系统引用的稳定键。
 *  故按「词条」而非数据表排布——编码作定宽书脊对齐成一条竖线，名称与描述是词条本体，
 *  状态只标例外（停用项加标签，正常项不加）；编辑在原行就地展开，不在列表上方另起表单区。 */
function QaDocumentTypeManager({ open, onClose, onChanged }: { open: boolean; onClose: () => void; onChanged: () => void }) {
  const { message } = App.useApp()
  const [types, setTypes] = useState<QaDocumentType[]>([])
  const [loading, setLoading] = useState(false)
  // null = 未编辑；{ row: null } = 新增；{ row } = 编辑该词条
  const [editor, setEditor] = useState<{ row: QaDocumentType | null } | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try { setTypes(await fetchQaDocumentTypes({ include_inactive: true })) }
    catch (error) { message.error(error instanceof Error ? error.message : '加载文件类型失败') }
    finally { setLoading(false) }
  }, [message])

  useEffect(() => { if (open) void load() }, [load, open])

  // 在打开事件里一次性写好初值，不用 effect 同步（避免 props → state 的级联渲染）
  const openEditor = (row: QaDocumentType | null) => {
    setEditor({ row })
    form.resetFields()
    form.setFieldsValue({ code: row?.code ?? '', name: row?.name ?? '', description: row?.description ?? '', ai_source_policy: row?.ai_source_policy ?? 'authoritative' })
  }

  // 关闭即卸载编辑表单，初值统一由 openEditor 写入；这里不要 reset：
  // 表单尚未渲染过时调用 resetFields 会触发 antd「useForm 未连接」告警。
  const closeEditor = () => setEditor(null)

  const save = async () => {
    const row = editor?.row ?? null
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values) return
    setSaving(true)
    try {
      const result = row
        ? await updateQaDocumentType(row.id, { name: values.name, description: values.description, ai_source_policy: values.ai_source_policy })
        : await createQaDocumentType({ code: String(values.code || '').trim().toUpperCase(), name: values.name, description: values.description, ai_source_policy: values.ai_source_policy })
      if (!result.success) { message.error(actionError(result)); return }
      message.success(row ? `「${values.name}」已更新` : `「${values.name}」已创建`)
      closeEditor()
      await load()
      onChanged()
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (row: QaDocumentType) => {
    const wasActive = isDocumentTypeActive(row)
    const result = await setQaDocumentTypeActive(row.id, !wasActive)
    if (!result.success) { message.error(actionError(result)); return }
    message.success(wasActive ? `「${row.name}」已停用` : `「${row.name}」已启用`)
    closeEditor()
    await load()
    onChanged()
  }

  const activeTypes = types.filter(isDocumentTypeActive)
  const inactiveTypes = types.filter((item) => !isDocumentTypeActive(item))

  /** 编码书脊：定宽 + 居中，所有词条的编码对齐成一条竖线。
   *  不截断——编码是给人读的标识，宁可折行也不能看不全。
   *  min-h 与名称行高同为 22px，两者的首行文字才能水平对齐（否则 padding 会把编码压低）。 */
  const codeCell = (code: string, muted: boolean) => (
    <span
      className={`inline-flex min-h-[22px] w-[132px] shrink-0 items-center justify-center break-all rounded-[6px] bg-[var(--color-surface)] px-2 text-center text-[12px] font-semibold leading-[18px] tracking-[0.06em] ${muted ? 'text-[var(--color-steel)]' : 'text-[var(--color-charcoal)]'}`}
    >
      {code}
    </span>
  )

  /** 就地编辑表单：新增与编辑共用，编码格在位但编辑时锁定。 */
  const editorForm = (row: QaDocumentType | null) => (
    <Form form={form} layout="vertical" onFinish={() => { void save() }}>
      <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-[140px_minmax(0,1fr)]">
        <Form.Item
          name="code"
          label="编码"
          style={{ marginBottom: 12 }}
          normalize={(value: string) => String(value ?? '').toUpperCase()}
          rules={row ? undefined : [{ required: true, message: '请输入编码' }]}
        >
          <Input disabled={Boolean(row)} placeholder="如 SOP" />
        </Form.Item>
        <Form.Item name="name" label="名称" style={{ marginBottom: 12 }} rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="如 标准操作规程" />
        </Form.Item>
      </div>
      <Form.Item name="description" label="描述" style={{ marginBottom: 12 }}>
        <Input placeholder="这类文件涵盖什么（可选）" />
      </Form.Item>
      <Form.Item name="ai_source_policy" label="AI 来源策略" style={{ marginBottom: 12 }} rules={[{ required: true }]}>
        <Select options={[
          { value: 'authoritative', label: '权威来源：可产生关联候选与主数据提案' },
          { value: 'reference', label: '参考来源：只产生已有主数据关联候选' },
          { value: 'disabled', label: '禁用：不允许 AI 分析' },
        ]} />
      </Form.Item>
      <div className="flex justify-end gap-2">
        <Button onClick={closeEditor} disabled={saving}>取消</Button>
        <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
      </div>
    </Form>
  )

  const typeRow = (row: QaDocumentType) => {
    const active = isDocumentTypeActive(row)
    return (
      <li key={row.id} className="flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3.5">
        {codeCell(row.code, !active)}
        <div className="min-w-[150px] flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={`text-[14px] font-medium leading-[22px] ${active ? 'text-[var(--color-charcoal)]' : 'text-[var(--color-slate)]'}`}>{row.name}</span>
            {row.is_system && <MetaChip>系统</MetaChip>}
            {!active && <MetaChip>已停用</MetaChip>}
            <MetaChip>{row.ai_source_policy === 'disabled' ? 'AI 禁用' : row.ai_source_policy === 'reference' ? 'AI 参考' : 'AI 权威'}</MetaChip>
          </div>
          {row.description && (
            <p
              className={`m-0 mt-1 text-[13px] leading-relaxed ${active ? 'text-[var(--color-slate)]' : 'text-[var(--color-steel)]'}`}
              style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
            >
              {row.description}
            </p>
          )}
        </div>
        <Space size={2} className="ml-auto shrink-0">
          {row.is_system ? (
            <Tooltip title="系统内置类型的名称与描述不可修改">
              <span><Button type="text" size="small" disabled>编辑</Button></span>
            </Tooltip>
          ) : (
            <Button type="text" size="small" onClick={() => openEditor(row)}>编辑</Button>
          )}
          <Button type="text" size="small" onClick={() => { void toggleActive(row) }}>{active ? '停用' : '启用'}</Button>
        </Space>
      </li>
    )
  }

  // editor 打开时空列表要落到列表分支，否则新增表单被空状态挡掉
  const empty = !loading && types.length === 0 && !editor

  return (
    <Modal
      title="文件类型"
      open={open}
      onCancel={() => { closeEditor(); onClose() }}
      footer={null}
      width={760}
      destroyOnHidden
    >
      <p className="m-0 mb-4 text-[13px] leading-relaxed text-[var(--color-slate)]">
        批准文件台账用它给文件归类。编码是其他系统引用该类型的键，创建后不可修改。
      </p>

      <div className="overflow-hidden rounded-[12px] border border-[var(--color-hairline)]">
        {/* 列表头：左边是计数，右边是唯一的动作——动作与它作用的列表同处一块面板 */}
        <div className="flex items-center justify-between gap-3 border-b border-[var(--color-hairline)] bg-[var(--color-surface-soft)] px-4 py-2.5">
          <span className="text-[12px] font-medium text-[var(--color-steel)]">
            {loading ? '加载中…' : `共 ${types.length} 个类型`}
          </span>
          <Button type="primary" size="small" icon={<PlusOutlined />} disabled={Boolean(editor)} onClick={() => openEditor(null)}>
            新增类型
          </Button>
        </div>

        <div className="max-h-[52vh] overflow-y-auto">
          {loading && types.length === 0 ? (
            <div className="flex justify-center py-16"><Spin /></div>
          ) : empty ? (
            <div className="px-6 py-12 text-center">
              <FileTextOutlined className="text-[24px] text-[var(--color-steel)]" />
              <p className="m-0 mt-3 text-[14px] font-medium text-[var(--color-charcoal)]">还没有文件类型</p>
              <p className="m-0 mt-1 text-[13px] text-[var(--color-slate)]">先建一个，登记文件时就能选到。</p>
            </div>
          ) : (
            <ul className="m-0 list-none p-0 [&>li+li]:border-t [&>li+li]:border-[var(--color-hairline-soft)]">
              {editor && !editor.row && (
                <li className="bg-[var(--color-surface-soft)] px-4 py-3.5">{editorForm(null)}</li>
              )}
              {activeTypes.map((row) => (
                editor?.row?.id === row.id
                  ? <li key={row.id} className="bg-[var(--color-surface-soft)] px-4 py-3.5">{editorForm(row)}</li>
                  : typeRow(row)
              ))}
              {inactiveTypes.length > 0 && (
                <li className="bg-[var(--color-surface-soft)] px-4 py-2">
                  <span className="text-[12px] font-medium text-[var(--color-steel)]">已停用 {inactiveTypes.length} 个</span>
                </li>
              )}
              {inactiveTypes.map((row) => (
                editor?.row?.id === row.id
                  ? <li key={row.id} className="bg-[var(--color-surface-soft)] px-4 py-3.5">{editorForm(row)}</li>
                  : typeRow(row)
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}

function QaDocumentDetailDrawer({
  documentId,
  canVersion,
  canCurrent,
  canDisableVersion,
  canRelation,
  onClose,
  onChanged,
}: {
  documentId: string | null
  canVersion: boolean
  canCurrent: boolean
  canDisableVersion: boolean
  canRelation: boolean
  onClose: () => void
  onChanged: () => void
}) {
  const { message, modal } = App.useApp()
  const [document, setDocument] = useState<QaDocument | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [relationVersion, setRelationVersion] = useState<QaDocumentVersion | null>(null)
  const [aiVersion, setAiVersion] = useState<QaDocumentVersion | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const requestIdRef = useRef(0)

  const loadDetail = useCallback(async (clearExisting = false) => {
    if (!documentId) return
    const requestId = ++requestIdRef.current
    if (clearExisting) setDocument(null)
    setLoading(true)
    try {
      const result = await fetchQaDocument(documentId)
      if (requestId === requestIdRef.current) setDocument(result)
    } catch (error) {
      if (requestId === requestIdRef.current) {
        setDocument(null)
        message.error(error instanceof Error ? error.message : '加载文件详情失败')
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }, [documentId, message])

  useEffect(() => { if (documentId) void loadDetail(true); else { requestIdRef.current += 1; setDocument(null) } }, [documentId, loadDetail, refreshKey])

  const versions = useMemo(() => document?.versions || (document?.current_version ? [document.current_version] : []), [document])
  const currentVersion = useMemo(() => versions.find((version) => version.id === document?.current_version_id) || null, [document?.current_version_id, versions])
  // 链上选中的版本。记下它属于哪份文件，换文件时自然回落，不用 effect 同步 state。
  const [picked, setPicked] = useState<{ documentId: string; versionId: string } | null>(null)
  const selected = (picked?.documentId === documentId ? versions.find((version) => version.id === picked.versionId) : undefined)
    || currentVersion || versions[0] || null
  // 新上传文件由后台持久化调度器解析；仅在存在待处理版本时轮询，避免无意义请求。
  useEffect(() => {
    if (!documentId || !document) return
    const pending = versions.some((version) => {
      const status = displayFile(version)?.extraction_status
      return status === 'queued' || status === 'processing'
    })
    if (!pending) return
    const timer = window.setInterval(() => { void loadDetail() }, 5000)
    return () => window.clearInterval(timer)
  }, [document, documentId, loadDetail, versions])
  const doMakeCurrent = (version: QaDocumentVersion) => {
    if (!document) return
    modal.confirm({
      title: '设为当前版本',
      content: `确认将版本 ${version.version_label} 设为当前版本吗？旧当前版本将自动成为历史版本。`,
      okText: '确认', cancelText: '取消',
      onOk: async () => {
        const result = await makeQaVersionCurrent(document.id, version.id)
        if (!result.success) { message.error(actionError(result)); return }
        message.success('已设为当前版本')
        setRefreshKey((value) => value + 1)
        onChanged()
      },
    })
  }

  const doCopyRelations = async (version: QaDocumentVersion) => {
    if (!document) return
    const result = await copyQaVersionRelations(document.id, version.id)
    if (!result.success) { message.error(actionError(result)); return }
    message.success('已复制当前版本关联，可继续调整后再设为当前')
    setRefreshKey((value) => value + 1)
    onChanged()
  }

  const doSetVersionActive = async (version: QaDocumentVersion, active: boolean) => {
    const result = await setQaVersionActive(version.id, active)
    if (!result.success) { message.error(actionError(result)); return }
    message.success(active ? '版本已启用' : '版本已停用')
    setRefreshKey((value) => value + 1)
    onChanged()
  }

  return (
    <Drawer title="文件详情" open={!!documentId} size={720} onClose={onClose}>
      {loading && !document ? <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div> : document ? <>
        {/* 先立身份：编号是这份文件在台账里的名字，标题是它是什么 */}
        <div className={styles.identity}>
          <Text className={styles.identityCode} copyable={{ text: document.document_no }}>{document.document_no}</Text>
          <div className={styles.identityName}>{document.title}</div>
          <div className={styles.identityMeta}>
            {statusTag(document.status, isDocumentActive(document))}
            <span className={styles.identityKind}>
              {[documentTypeLabelOf(document), document.responsible_department_name || document.responsible_department_name_snapshot || document.department_name].filter(Boolean).join(' · ')}
            </span>
          </div>
        </div>

        {/* 版本链既是这份文件的形态，也是选择器：点哪个版本，下面就是哪个版本的档案。 */}
        <div className={styles.versionBar}>
          {versions.map((version) => {
            const versionActive = isVersionActive(version)
            const isCurrent = version.id === document.current_version_id
            return (
              <button
                key={version.id}
                type="button"
                className={`${styles.versionTab} ${selected?.id === version.id ? styles.versionTabActive : ''} ${versionActive ? '' : styles.versionTabInactive}`}
                aria-pressed={selected?.id === version.id}
                onClick={() => setPicked({ documentId: document.id, versionId: version.id })}
              >
                {version.version_label}
                {isCurrent && <span>现行</span>}
                {!versionActive && <span>已停用</span>}
              </button>
            )
          })}
          {canVersion && (
            <button type="button" className={`${styles.versionTab} ${styles.versionTabAdd}`} onClick={() => setUploadOpen(true)}>
              <PlusOutlined />上传新版本
            </button>
          )}
          {!versions.length && <span className={styles.fieldMissing}>尚未上传版本</span>}
        </div>

        {selected && (
          <VersionPanel
            version={selected}
            isCurrent={selected.id === document.current_version_id}
            hasCurrent={Boolean(document.current_version_id)}
            canCurrent={canCurrent}
            canDisableVersion={canDisableVersion}
            canRetry={canVersion}
            canRelation={canRelation}
            canAi={canRelation}
            documentActive={isDocumentActive(document)}
            aiSourcePolicy={document.document_type?.ai_source_policy}
            onMakeCurrent={() => doMakeCurrent(selected)}
            onCopyRelations={() => { void doCopyRelations(selected) }}
            onSetActive={(active) => { void doSetVersionActive(selected, active) }}
            onRelations={() => setRelationVersion(selected)}
            onAiAnalysis={() => setAiVersion(selected)}
            onRefresh={() => { setRefreshKey((value) => value + 1); onChanged() }}
          />
        )}

        {/* 台账自身的登记时间保留在末尾，不跟版本信息抢位置 */}
        <p className={styles.drawerFoot}>本台账登记于 {formatDate(document.created_at)}</p>

        <QaUploadVersionModal
          open={uploadOpen}
          documentId={document.id}
          documentNo={document.document_no}
          documentTitle={document.title}
          currentVersionLabel={currentVersion?.version_label || document.current_version_label || ''}
          onClose={() => setUploadOpen(false)}
          onSaved={() => { setUploadOpen(false); setRefreshKey((value) => value + 1); onChanged() }}
        />
        <QaRelationsModal open={!!relationVersion} version={relationVersion} onClose={() => setRelationVersion(null)} onSaved={() => { setRelationVersion(null); setRefreshKey((value) => value + 1); onChanged() }} />
        <QaAiAnalysisModal open={!!aiVersion} version={aiVersion} onClose={() => setAiVersion(null)} onConfirmed={() => { setAiVersion(null); setRefreshKey((value) => value + 1); onChanged() }} />
      </> : <Empty description="无法加载文件详情" />}
    </Drawer>
  )
}

/** 选中版本的档案区。一次只展示一个版本，版本多少都不改变抽屉的长度。
 *  对应地，"这个版本能不能设为现行 / 停用 / 维护关联"也集中在这一处。 */
function VersionPanel({
  version,
  isCurrent,
  hasCurrent,
  canCurrent,
  canDisableVersion,
  canRetry,
  canRelation,
  canAi,
  documentActive,
  aiSourcePolicy,
  onMakeCurrent,
  onCopyRelations,
  onSetActive,
  onRelations,
  onAiAnalysis,
  onRefresh,
}: {
  version: QaDocumentVersion
  isCurrent: boolean
  hasCurrent: boolean
  canCurrent: boolean
  canDisableVersion: boolean
  canRetry: boolean
  canRelation: boolean
  canAi: boolean
  documentActive: boolean
  aiSourcePolicy?: string | null
  onMakeCurrent: () => void
  onCopyRelations: () => void
  onSetActive: (active: boolean) => void
  onRelations: () => void
  onAiAnalysis: () => void
  onRefresh: () => void
}) {
  const { message, modal } = App.useApp()
  const [retrying, setRetrying] = useState(false)
  const [processingOpen, setProcessingOpen] = useState(false)
  const [processingSummary, setProcessingSummary] = useState<QaDocumentProcessingResult | null>(null)
  const [processingSummaryLoading, setProcessingSummaryLoading] = useState(false)
  const file = displayFile(version)
  const state = displayVersionState(version)
  const versionActive = isVersionActive(version)
  // 登记版本和现行版本都可维护关联（后端同一道闸门），历史/停用版本冻结。
  const relationsEditable = state === 'registered' || state === 'current'
  const relations = version.relations || []
  const currentExtractionRunId = file?.current_extraction_run_id || ''
  const currentChunkRunId = file?.current_chunk_run_id || ''

  // 只为当前选中的版本读取一次轻量摘要；raw/chunk 明细在用户打开查看器后再分页读取。
  // queued/processing 也要读取 latest run，用户可以在正文处理期间打开查看器看进度。
  useEffect(() => {
    if (!file?.id) {
      setProcessingSummary(null)
      return
    }
    let cancelled = false
    setProcessingSummaryLoading(true)
    void fetchQaDocumentProcessingResults(file.id, {
      view: 'raw_blocks',
      page: 1,
      page_size: 1,
      // 与后端预览契约的最小值一致；摘要只取一条、最多 100 字符，
      // 不加载完整正文。
      content_limit: 100,
    }).then((result) => {
      if (!cancelled) setProcessingSummary(result)
    }).catch(() => {
      if (!cancelled) setProcessingSummary(null)
    }).finally(() => {
      if (!cancelled) setProcessingSummaryLoading(false)
    })
    return () => { cancelled = true }
  }, [currentChunkRunId, currentExtractionRunId, file?.extraction_status, file?.id])
  const aiUnavailableReason = !documentActive
    ? '文件台账已停用，不能发起新的 AI 分析。'
    : !version.approved_declared
      ? '未确认外部批准的版本不能发起 AI 分析。'
    : aiSourcePolicy === 'disabled'
      ? '该文件类型已禁用 AI 分析。'
    : file?.legacy
      ? '旧解析数据尚未生成可追溯的 raw block 和 chunk，请先重建解析与分块。'
    : file?.extraction_status !== 'ready'
      ? '正文解析完成后才能运行 AI 分析。'
      : !file.current_chunk_run_id
        ? '当前正文没有可用分块，请先重新解析。'
        : ''

  const retry = async () => {
    if (!file?.id || retrying) return
    setRetrying(true)
    try {
      const result = await retryQaExtraction(file.id)
      if (!result.success) { message.error(actionError(result)); return }
      message.success(file.legacy ? '已加入解析与分块重建队列' : '已重新加入解析队列')
      onRefresh()
    } finally { setRetrying(false) }
  }

  const fields: Array<{ label: string; value: React.ReactNode }> = [
    { label: '版本标签', value: <>{version.version_label}{isCurrent && <span className={styles.fieldMissing}> · 现行版本</span>}</> },
    { label: '登记时间', value: formatDate(version.created_at) },
    { label: '锁定时间', value: formatDate(version.locked_at || version.first_locked_at) },
    { label: '批准声明', value: version.approved_declared ? '已确认外部批准' : <span className={styles.fieldMissing}>未确认</span> },
    {
      label: '正文',
      value: file ? (
        <>
          <div className={styles.versionFile}>
            <div className={styles.versionFileHead}>
              {statusTag(file.extraction_status, true)}
              {file.legacy && <Tag color="gold">旧解析</Tag>}
              <span className={styles.versionFileName}>{file.original_filename || file.filename || '文件'}</span>
              <span className={styles.fieldMissing}>{formatBytes(file.size_bytes ?? file.file_size)}</span>
            </div>
            <div className={styles.versionFileMeta}>
              {file.sha256 && <Text className={styles.versionHash} copyable={{ text: file.sha256 }}>SHA-256 {file.sha256.slice(0, 16)}…</Text>}
              <Button type="link" size="small" icon={<FilePdfOutlined />} href={qaFileContentUrl(file.id)} target="_blank">预览 / 下载</Button>
              <Button
                type="link"
                size="small"
                icon={<FileSearchOutlined />}
                onClick={() => setProcessingOpen(true)}
              >
                查看解析/分块
              </Button>
              {canRetry && file.extraction_status === 'failed' && <Button type="link" size="small" loading={retrying} onClick={() => { void retry() }}>重试解析</Button>}
            </div>
            <ProcessingSummaryLine
              file={file}
              result={processingSummary}
              loading={processingSummaryLoading}
            />
          </div>
          {file.legacy && (
            <Alert
              type="warning"
              showIcon
              title="旧解析数据需要重建解析与分块"
              description={canRetry
                ? '该版本仍可预览并人工维护关联；运行 AI 分析前，请先生成可追溯的 raw block 和 chunk，也可以上传新版本走新解析链路。重建不会修改原文件或现有正式关联。'
                : '该版本仍可预览并人工维护关联；AI 分析前需由具备版本维护权限的用户重建解析与分块，或上传新版本走新解析链路。'}
              action={canRetry ? <Button size="small" loading={retrying} onClick={() => { void retry() }}>重建解析/分块</Button> : undefined}
              style={{ marginTop: 10 }}
            />
          )}
        </>
      ) : <span className={styles.fieldMissing}>该版本没有上传原件</span>,
    },
    {
      label: '适用/关联',
      value: relations.length
        ? <span className={styles.relationRow}>{relations.map((link) => <Tag key={link.id || link.master_object_id}>{link.master_object_code || link.code_snapshot || ''}{link.master_object_name || link.name_snapshot ? ` · ${link.master_object_name || link.name_snapshot}` : ''}</Tag>)}</span>
        : <span className={styles.fieldMissing}>未关联主数据</span>,
    },
  ]

  return (
    <div className={styles.versionPanel}>
      <dl className={styles.fields}>
        {fields.map((field) => (
          <Fragment key={field.label}>
            <dt className={styles.fieldLabel}>{field.label}</dt>
            <dd className={styles.fieldValue}>{field.value}</dd>
          </Fragment>
        ))}
      </dl>

      <div className={styles.versionActions}>
        {canAi && file && versionActive && (
          <Tooltip title={aiUnavailableReason || undefined}>
            <span><Button icon={<DatabaseOutlined />} disabled={Boolean(aiUnavailableReason)} onClick={onAiAnalysis}>AI 分析文档</Button></span>
          </Tooltip>
        )}
        {canRelation && relationsEditable && <Button onClick={onRelations}>维护关联</Button>}
        {canRelation && relationsEditable && hasCurrent && !isCurrent && <Button onClick={onCopyRelations}>复制当前关联</Button>}
        {canDisableVersion && !versionActive && <Button onClick={() => onSetActive(true)}>启用版本</Button>}
        {canCurrent && !isCurrent && versionActive && <Button type="primary" onClick={onMakeCurrent}>设为当前</Button>}
        {canDisableVersion && !isCurrent && versionActive && <Button danger onClick={() => { modal.confirm({ title: '停用版本', content: '停用后该版本不再参与默认检索，历史记录仍会保留。确认继续吗？', okText: '停用', cancelText: '取消', onOk: () => onSetActive(false) }) }}>停用版本</Button>}
      </div>
      {file && (
        <QaDocumentProcessingModal
          open={processingOpen}
          file={file}
          versionLabel={version.version_label}
          initialResult={processingSummary}
          onClose={() => setProcessingOpen(false)}
        />
      )}
    </div>
  )
}

/** 索引基准与 raw block 一致：页码、段落、表格从 1 开始，行/列从 0 开始。 */
function processingBlockLocation(item: QaDocumentRawBlock): string {
  const parts: string[] = []
  if (item.page_number != null) parts.push(`第 ${item.page_number} 页`)
  if (item.paragraph_index != null) parts.push(`第 ${item.paragraph_index} 段`)
  if (item.table_index != null) parts.push(`第 ${item.table_index} 个表格`)
  if (item.row_index != null) parts.push(`第 ${item.row_index + 1} 行`)
  if (item.column_index != null) parts.push(`第 ${item.column_index + 1} 列`)
  return parts.join(' · ') || item.locator || '定位不可用'
}

function processingBlockTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    paragraph: '段落',
    heading: '标题',
    list_item: '列表项',
    table_header: '表头',
    table_row: '表格行',
    pdf_block: 'PDF 块',
  }
  return labels[value] || value || '正文块'
}

function processingCount(value?: number | null): string {
  return value == null ? '—' : new Intl.NumberFormat('zh-CN').format(value)
}

function ProcessingSummaryLine({
  file,
  result,
  loading,
}: {
  file: QaDocumentFile
  result: QaDocumentProcessingResult | null
  loading: boolean
}) {
  const extractionRun = result?.current_extraction_run
  const chunkRun = result?.current_chunk_run
  const latestExtraction = result?.latest_extraction_run
  const latestChunk = result?.latest_chunk_run
  const countExtractionRun = extractionRun || latestExtraction
  const countChunkRun = chunkRun || latestChunk
  const latestIsDifferent = Boolean(latestExtraction && extractionRun && latestExtraction.id !== extractionRun.id)
  return (
    <div className={styles.processingSummaryLine}>
      <span className={styles.processingSummaryLabel}>解析/分块</span>
      {statusTag(result?.extraction_status || file.extraction_status, true)}
      <span>解析器 {result?.parser_version || countExtractionRun?.parser_version || file.parser_version || '—'}</span>
      {loading ? <Spin size="small" /> : result ? <>
        <span>raw block {processingCount(result.total ?? countExtractionRun?.block_count)}</span>
        <span>chunk {processingCount(countChunkRun?.chunk_count)}</span>
      </> : <span className={styles.fieldMissing}>运行摘要尚未建立</span>}
      {latestExtraction && (!extractionRun || latestIsDifferent) && <span className={styles.processingLatest}>最近任务：{STATUS_LABEL[latestExtraction.status] || latestExtraction.status}</span>}
    </div>
  )
}

function ProcessingRunDescription({
  extractionRun,
  chunkRun,
  result,
}: {
  extractionRun?: QaDocumentExtractionRunSummary | null
  chunkRun?: QaDocumentChunkRunSummary | null
  result: QaDocumentProcessingResult
}) {
  return (
    <Descriptions size="small" column={2} className={styles.processingDescriptions}>
      <Descriptions.Item label="文件解析状态">{statusTag(result.extraction_status, true)}</Descriptions.Item>
      <Descriptions.Item label="解析模式">{result.parser_mode || '—'}</Descriptions.Item>
      <Descriptions.Item label="解析器版本">{result.parser_version || extractionRun?.parser_version || '—'}</Descriptions.Item>
      <Descriptions.Item label="raw block 数">{processingCount(extractionRun?.block_count ?? result.total)}</Descriptions.Item>
      <Descriptions.Item label="正文字符数">{processingCount(extractionRun?.char_count)}</Descriptions.Item>
      <Descriptions.Item label="分块版本">{chunkRun?.chunk_version || '—'}</Descriptions.Item>
      <Descriptions.Item label="chunk 数">{processingCount(chunkRun?.chunk_count)}</Descriptions.Item>
      <Descriptions.Item label="chunk 字符数">{processingCount(chunkRun?.char_count)}</Descriptions.Item>
      <Descriptions.Item label="解析完成时间">{formatDate(extractionRun?.finished_at || extractionRun?.created_at)}</Descriptions.Item>
      <Descriptions.Item label="分块完成时间">{formatDate(chunkRun?.finished_at || chunkRun?.created_at)}</Descriptions.Item>
    </Descriptions>
  )
}

function QaDocumentProcessingModal({
  open,
  file,
  versionLabel,
  initialResult,
  onClose,
}: {
  open: boolean
  file: QaDocumentFile
  versionLabel: string
  initialResult?: QaDocumentProcessingResult | null
  onClose: () => void
}) {
  const [view, setView] = useState<QaDocumentProcessingView>('raw_blocks')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<QaDocumentProcessingResult | null>(initialResult || null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pollTick, setPollTick] = useState(0)
  const requestIdRef = useRef(0)

  useEffect(() => {
    if (!open) return
    setView('raw_blocks')
    setPage(1)
    setResult((previous) => previous?.file_id === file.id ? previous : null)
    setError(null)
  }, [file.id, open])

  // 摘要请求和查看器明细请求可能同时完成；只在当前没有结果时注入摘要，
  // 避免摘要更新把用户已经打开的 chunk 页签重置回第一页。
  useEffect(() => {
    if (open && !result && initialResult?.file_id === file.id) setResult(initialResult)
  }, [file.id, initialResult, open, result])

  // 重新解析可能在查看器打开后完成；仅在后台仍处于 queued/processing 时轮询，
  // ready/failed 等终态不会制造额外请求。
  useEffect(() => {
    if (!open) return
    const status = result?.latest_extraction_run?.status || result?.extraction_status
    if (status !== 'queued' && status !== 'processing') return
    const timer = window.setInterval(() => setPollTick((value) => value + 1), 5000)
    return () => window.clearInterval(timer)
  }, [open, result?.extraction_status, result?.latest_extraction_run?.status])

  useEffect(() => {
    if (!open || !file.id) return
    const requestId = ++requestIdRef.current
    setLoading(true)
    setError(null)
    void fetchQaDocumentProcessingResults(file.id, {
      view,
      page,
      page_size: 20,
      content_limit: 800,
    }).then((next) => {
      if (requestId === requestIdRef.current) setResult(next)
    }).catch((cause) => {
      if (requestId === requestIdRef.current) setError(cause instanceof Error ? cause.message : '加载解析结果失败')
    }).finally(() => {
      if (requestId === requestIdRef.current) setLoading(false)
    })
    return () => { requestIdRef.current += 1 }
  }, [file.id, open, page, pollTick, view])

  const currentExtractionRun = result?.current_extraction_run
  const currentChunkRun = result?.current_chunk_run
  const extractionCount = currentExtractionRun?.block_count ?? result?.latest_extraction_run?.block_count
  const chunkCount = currentChunkRun?.chunk_count ?? result?.latest_chunk_run?.chunk_count
  const hasChunks = Boolean(file.current_chunk_run_id || currentChunkRun)
  const items = view === 'raw_blocks' ? result?.raw_blocks || [] : result?.chunks || []
  const total = result?.total || 0

  const changeView = (next: string) => {
    if (next !== 'raw_blocks' && next !== 'chunks') return
    setView(next)
    setPage(1)
  }

  return (
    <Modal
      title={`解析与分块 · 版本 ${versionLabel}`}
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={920}
      destroyOnHidden
    >
      {error && <Alert type="error" showIcon message="解析结果加载失败" description={error} style={{ marginBottom: 14 }} />}
      {result ? (
        <>
          <ProcessingRunDescription extractionRun={currentExtractionRun} chunkRun={currentChunkRun} result={result} />
          {result.latest_extraction_run && (!currentExtractionRun || result.latest_extraction_run.id !== currentExtractionRun.id) && (
            <Alert
              type="info"
              showIcon
              message={`最近解析任务：${STATUS_LABEL[result.latest_extraction_run.status] || result.latest_extraction_run.status}`}
              description="下面的 raw block/chunk 明细仍然只来自当前有效运行；最近任务完成后会自动刷新。"
              style={{ marginBottom: 14 }}
            />
          )}
          {result.extraction_error && <Alert type="warning" showIcon message="最近一次解析任务有提示" description={result.extraction_error} style={{ marginBottom: 14 }} />}
          {!currentExtractionRun && result.legacy ? (
            <Alert
              type="warning"
              showIcon
              message="这是历史 legacy 解析数据"
              description="当前可兼容查看已保存的 raw block；该历史数据没有新的分块运行。重建解析后，才会生成带版本和映射关系的 chunk。"
              style={{ marginBottom: 14 }}
            />
          ) : !currentExtractionRun ? (
            <Alert type="info" showIcon message="当前没有可用的解析运行" description="文件仍在排队或解析失败；解析完成后会自动刷新当前有效的 raw block 和 chunk。" style={{ marginBottom: 14 }} />
          ) : null}
        </>
      ) : (
        <div className={styles.processingLoadingSummary}><Spin /> 正在读取解析运行摘要…</div>
      )}

      <Tabs
        activeKey={view}
        onChange={changeView}
        items={[
          { key: 'raw_blocks', label: `Raw block（原始块）${result ? ` · ${processingCount(view === 'raw_blocks' ? total : extractionCount)} 条` : ''}` },
          { key: 'chunks', disabled: !hasChunks, label: `Chunk（上下文块）${result ? ` · ${processingCount(view === 'chunks' ? total : chunkCount)} 条` : ''}` },
        ]}
      />

      <Spin spinning={loading}>
        {items.length ? (
          <div className={styles.processingItemList}>
            {view === 'raw_blocks'
              ? (items as QaDocumentRawBlock[]).map((item, index) => (
                <details className={styles.processingItem} key={item.id} open>
                  <summary className={styles.processingItemSummary}>
                    <span className={styles.processingItemOrder}>#{item.source_order ?? index + 1}</span>
                    <Tag>{processingBlockTypeLabel(item.block_type)}</Tag>
                    <span className={styles.processingItemLocation}>{processingBlockLocation(item)}</span>
                    {item.heading_path?.length ? <span className={styles.processingItemHeading}>{item.heading_path.join(' / ')}</span> : null}
                  </summary>
                  <div className={styles.processingItemBody}>
                    <div className={styles.processingItemMeta}>
                      {processingCount(item.content_length)} 字符
                      {item.content_truncated && <Tag color="gold">预览已截断</Tag>}
                      <Text type="secondary" copyable={{ text: item.text_hash }}>hash {item.text_hash.slice(0, 12)}…</Text>
                    </div>
                    <div className={styles.processingContent}>{item.content_preview || '（空正文块）'}</div>
                    <div className={styles.processingLocator}>定位：{item.locator}</div>
                  </div>
                </details>
              ))
              : (items as QaDocumentTextChunk[]).map((item) => (
                <details className={styles.processingItem} key={item.id} open>
                  <summary className={styles.processingItemSummary}>
                    <span className={styles.processingItemOrder}>#{item.chunk_order + 1}</span>
                    <Tag color="blue">上下文块</Tag>
                    <span className={styles.processingItemLocation}>{item.page_start != null ? `第 ${item.page_start}${item.page_end && item.page_end !== item.page_start ? `–${item.page_end}` : ''} 页` : '页码不可用'}</span>
                    {item.heading_path?.length ? <span className={styles.processingItemHeading}>{item.heading_path.join(' / ')}</span> : null}
                  </summary>
                  <div className={styles.processingItemBody}>
                    <div className={styles.processingItemMeta}>
                      {processingCount(item.char_count)} 字符
                      {item.content_truncated && <Tag color="gold">预览已截断</Tag>}
                      <Text type="secondary" copyable={{ text: item.content_hash }}>hash {item.content_hash.slice(0, 12)}…</Text>
                    </div>
                    <div className={styles.processingContent}>{item.content_preview || '（空上下文块）'}</div>
                  </div>
                </details>
              ))}
          </div>
        ) : (
          <Empty description={loading ? '正在加载…' : view === 'chunks' && !hasChunks ? '当前没有可用 chunk' : '当前运行没有正文块'} />
        )}
      </Spin>
      {result && total > result.page_size && (
        <div className={styles.processingPagination}>
          <Pagination current={result.page} pageSize={result.page_size} total={total} showSizeChanger={false} onChange={setPage} showTotal={(value) => `共 ${value} 条`} />
        </div>
      )}
    </Modal>
  )
}

function QaUploadVersionModal({ open, documentId, documentNo, documentTitle, currentVersionLabel, onClose, onSaved }: {
  open: boolean
  documentId: string
  documentNo: string
  documentTitle: string
  currentVersionLabel: string
  onClose: () => void
  onSaved: () => void
}) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)

  // 清空上次残留改在打开时做（表单卸载不清 store）；关闭时 reset 会在表单从未渲染时报 useForm 告警
  useEffect(() => { if (open) { form.resetFields(); setFileList([]); setSelectedFile(null) } }, [form, open])

  const submit = async () => {
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values || !selectedFile) return
    if (!values.approved_declared) { message.error('请先确认文件已在现行正式流程中批准'); return }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('version_label', String(values.version_label))
      formData.append('approved_declared', 'true')
      formData.append('file', selectedFile)
      const result = await uploadQaVersion(documentId, formData)
      if (!result.success) { message.error(actionError(result)); return }
      message.success('版本已登记，正文将在后台解析')
      onSaved()
    } finally { setUploading(false) }
  }

  return (
    <Modal
      title="上传批准文件版本"
      open={open}
      onCancel={onClose}
      onOk={() => { void submit() }}
      okText="上传并登记"
      cancelText="取消"
      confirmLoading={uploading}
      okButtonProps={{ disabled: !selectedFile }}
      destroyOnHidden
    >
      {/* 批准声明默认勾选（resetFields 会回到这个初值）：上传的都是外部已批准件，
          这一步是"确认"而不是"补填"；取消勾选仍会被 validator 拦下。 */}
      <Form form={form} layout="vertical" initialValues={{ approved_declared: true }}>
        {/* 这个弹窗是从文件详情里打开的，先确认传对了文件 */}
        <div className={styles.uploadTarget}>
          <span className={styles.uploadTargetCode}>{documentNo}</span>
          <span className={styles.uploadTargetTitle}>{documentTitle}</span>
        </div>
        <p className={styles.formNote}>
          {currentVersionLabel ? `当前现行版本 ${currentVersionLabel}。` : '这份文件还没有现行版本。'}
          上传后版本进入台账、正文在后台解析；要让它成为现行版本，还需在文件详情里「设为当前」。
        </p>

        <Form.Item name="version_label" label="版本标签" rules={[{ required: true, message: '请输入版本标签' }]} extra="手工维护，例如 1.0、2026.09"><Input maxLength={50} placeholder="1.0" /></Form.Item>
        <Form.Item name="approved_declared" valuePropName="checked" label="批准声明" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('必须确认外部批准')) }]}><Checkbox>我确认该文件已在现行正式流程中批准</Checkbox></Form.Item>
        <Form.Item label="主文件" required>
          <Dragger className={styles.uploader} accept=".pdf,.docx,.doc" maxCount={1} fileList={fileList} beforeUpload={(file) => {
            if (file.size > 50 * 1024 * 1024) { message.error('文件大小不能超过 50 MB'); return Upload.LIST_IGNORE }
            const ext = file.name.split('.').pop()?.toLowerCase()
            if (!ext || !['pdf', 'docx', 'doc'].includes(ext)) { message.error('仅支持 PDF、DOCX 或 DOC'); return Upload.LIST_IGNORE }
            setSelectedFile(file)
            setFileList([{ uid: file.uid, name: file.name, status: 'done', size: file.size, type: file.type }])
            return false
          }} onRemove={() => { setFileList([]); setSelectedFile(null); return true }}>
            <p className="ant-upload-drag-icon"><UploadOutlined /></p><p className="ant-upload-text">点击或拖拽文件到此处</p><p className="ant-upload-hint">PDF / DOCX 可提取正文，DOC 仅归档 · 单个文件最大 50 MB</p>
          </Dragger>
        </Form.Item>
      </Form>
    </Modal>
  )
}

function QaRelationsModal({ open, version, onClose, onSaved }: { open: boolean; version: QaDocumentVersion | null; onClose: () => void; onSaved: () => void }) {
  const [selected, setSelected] = useState<string[]>([])
  const [options, setOptions] = useState<QaMasterObject[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const { message } = App.useApp()

  const loadOptions = useCallback(async (keyword = '') => {
    setLoading(true)
    try {
      const result = await fetchQaMasterObjects({
        keyword: keyword.trim() || undefined,
        include_inactive: false,
        page: 1,
        page_size: 200,
      })
      setOptions(result.items)
    } catch {
      setOptions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open || !version) return
    setSelected(version.relations?.map((relation) => relation.master_object_id) || [])
    void loadOptions()
  }, [loadOptions, open, version])

  const submit = async () => {
    if (!version) return
    if (submitting) return
    setSubmitting(true)
    try {
      const result = await updateQaVersionRelations(version.id, selected)
      if (!result.success) { message.error(actionError(result)); return }
      message.success('版本关联已保存')
      onSaved()
    } finally { setSubmitting(false) }
  }

  return (
    <Modal title={`维护版本 ${version?.version_label || ''} 的适用/关联`} open={open} onCancel={onClose} onOk={() => { void submit() }} okText="保存关联" cancelText="取消" confirmLoading={submitting} destroyOnHidden>
      <Alert type="info" showIcon title="关联挂在版本层级" description="登记版本和现行版本都可以直接维护关联；历史或停用版本作为过审快照冻结，如需调整请上传新版本。" style={{ marginBottom: 14 }} />
      <Select mode="multiple" value={selected} onChange={setSelected} loading={loading} showSearch={{ filterOption: false, optionFilterProp: 'label', onSearch: (value) => { void loadOptions(value) } }} onFocus={() => { if (!options.length) void loadOptions() }} style={{ width: '100%' }} placeholder="搜索并选择产品、物料、设备、供应商或区域" options={options.map((item) => ({ value: item.id, label: `${qaMasterKindLabel(item.kind)} · ${displayMasterCode(item)} · ${item.name}` }))} />
    </Modal>
  )
}

function QaAiAnalysisModal({ open, version, onClose, onConfirmed }: { open: boolean; version: QaDocumentVersion | null; onClose: () => void; onConfirmed: () => void }) {
  const { message } = App.useApp()
  const [run, setRun] = useState<QaAiAnalysisRun | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedSuggestions, setSelectedSuggestions] = useState<string[]>([])
  const [manualMasterIds, setManualMasterIds] = useState<string[]>([])
  const [removeIds, setRemoveIds] = useState<string[]>([])
  const [masterNames, setMasterNames] = useState<Record<string, string>>({})
  const [masterOptions, setMasterOptions] = useState<QaMasterObject[]>([])

  const load = useCallback(async () => {
    if (!open || !version) return
    setLoading(true)
    try {
      const result = await fetchQaAiAnalysis(version.id)
      setRun(result)
      setLoadError(null)
      // 已关联的主数据不再进候选列表，也不参与默认勾选——确认时重复
      // 追加是空操作，展示层直接去掉更省审核。
      const linkedIds = new Set((version.relations || []).map((item) => item.master_object_id))
      setSelectedSuggestions(dedupeSuggestionsByMaster(result.suggestions).filter((item) => !linkedIds.has(item.master_object_id) && item.selected_by_default && item.status === 'pending').map((item) => item.id))
      setManualMasterIds([])
      setRemoveIds([])
    } catch (error) {
      // 读取失败不能降级成「尚未运行分析」：那会让用户对着一个必然失败
      // 的「开始分析」按钮反复点击，真正的原因只剩浏览器控制台。
      setRun(null)
      setLoadError(error instanceof Error ? error.message : '加载 AI 分析结果失败')
    } finally { setLoading(false) }
  }, [open, version])

  useEffect(() => { void load() }, [load])

  const loadMasterOptions = useCallback(async (keyword = '') => {
    try {
      const result = await fetchQaMasterObjects({ keyword: keyword.trim() || undefined, include_inactive: false, page: 1, page_size: 200 })
      setMasterOptions(result.items)
      setMasterNames((current) => ({
        ...current,
        ...Object.fromEntries(result.items.map((item) => [item.id, `${displayMasterCode(item)} · ${item.name}`])),
      }))
    } catch {
      if (!keyword) setMasterOptions([])
    }
  }, [])

  useEffect(() => {
    if (!open || !version) return
    void loadMasterOptions()
  }, [loadMasterOptions, open, version])

  useEffect(() => {
    if (!open || !run || !['queued', 'processing'].includes(run.status)) return
    const timer = window.setInterval(() => { void load() }, 3000)
    return () => window.clearInterval(timer)
  }, [load, open, run])

  const start = async (force = false) => {
    if (!version || starting) return
    setStarting(true)
    try {
      const result = await triggerQaAiAnalysis(version.id, force)
      if (!result.success) { message.error(actionError(result)); return }
      message.success(force ? '已重新提交 AI 分析，后台处理中' : '已提交 AI 分析，后台处理中')
      await load()
    } finally { setStarting(false) }
  }

  const confirm = async () => {
    if (!run || !version || submitting) return
    setSubmitting(true)
    try {
      const result = await confirmQaAiRelations(run.id, {
        accepted_suggestion_ids: selectedSuggestions,
        manual_master_object_ids: manualMasterIds,
        remove_master_object_ids: removeIds,
      })
      if (!result.success) { message.error(actionError(result)); return }
      message.success('AI 候选已确认，正式关联已更新')
      onConfirmed()
    } finally { setSubmitting(false) }
  }

  const relationIds = new Set((version?.relations || []).map((item) => item.master_object_id))
  // 候选审核列表：按主数据合并后，再剔除已建立正式关联的主数据。
  const reviewSuggestions = run
    ? dedupeSuggestionsByMaster(run.suggestions).filter((item) => !relationIds.has(item.master_object_id))
    : []
  // 与后端 confirm-relations 校验同步：登记/现行版本可确认 AI 候选。
  const canConfirm = Boolean(run && ['ready', 'partial'].includes(run.status) && (version?.status === 'registered' || version?.status === 'current'))
  const manualSelectOptions = (() => {
    const options = new Map<string, { value: string; label: string }>()
    masterOptions.forEach((item) => options.set(item.id, { value: item.id, label: `${qaMasterKindLabel(item.kind)} · ${displayMasterCode(item)} · ${item.name}` }))
    manualMasterIds.forEach((id) => {
      if (!options.has(id)) options.set(id, { value: id, label: masterNames[id] || id })
    })
    return Array.from(options.values())
  })()

  const canRerun = Boolean(run && ['ready', 'partial'].includes(run.status))
  const modalFooter = run && canConfirm
    ? <Space><Button onClick={onClose}>取消</Button>{canRerun && <Button disabled={submitting} loading={starting} onClick={() => { void start(true) }}>重新分析</Button>}<Button type="primary" disabled={starting} loading={submitting} onClick={() => { void confirm() }}>确认关联</Button></Space>
    : <Space><Button onClick={onClose}>关闭</Button>{canRerun && <Button disabled={submitting} loading={starting} onClick={() => { void start(true) }}>重新分析</Button>}</Space>

  return (
    <Modal title={`AI 分析文档${version ? ` · ${version.version_label}` : ''}`} open={open} onCancel={onClose} width={780} footer={modalFooter} destroyOnHidden>
      <Alert type="info" showIcon title="AI 只生成候选和提案，正式写入仍需人工确认" description="编码/别名精确命中默认勾选；模糊命中和模型判断需要逐项核对。跨生产、设备来源不会由 AI 自动选择。" style={{ marginBottom: 16 }} />
      {loadError && <Alert type="error" showIcon title="加载 AI 分析结果失败" description={loadError} action={<Button size="small" onClick={() => { void load() }}>重试</Button>} style={{ marginBottom: 16 }} />}
      {!run && !loadError && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未运行 AI 分析"><Button type="primary" loading={starting} onClick={() => { void start() }}>开始分析文档</Button></Empty>}
      {loading && !run && <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>}
      {run && <>
        <Descriptions size="small" column={3} bordered style={{ marginBottom: 16 }}>
          <Descriptions.Item label="状态">{statusTag(run.status, !['failed', 'stale'].includes(run.status))}</Descriptions.Item>
          <Descriptions.Item label="进度">{run.processed_chunks}/{run.total_chunks} 块</Descriptions.Item>
          <Descriptions.Item label="实体/候选/提案">{run.entity_count}/{run.suggestion_count}/{run.proposal_count}</Descriptions.Item>
        </Descriptions>
        {run.error && <Alert type="warning" showIcon title={run.error} style={{ marginBottom: 12 }} />}
        {['queued', 'processing'].includes(run.status) && <div style={{ textAlign: 'center', padding: 18 }}><Spin description="后台分析中，页面会自动刷新" /></div>}
        {['failed', 'stale'].includes(run.status) && <Button type="primary" loading={starting} onClick={() => { void start() }}>重新分析</Button>}
        {reviewSuggestions.length > 0 && <>
          <Divider orientation="horizontal">已有主数据关联候选</Divider>
          <Space orientation="vertical" style={{ width: '100%' }}>
            {reviewSuggestions.map((suggestion) => {
              const observation = run.observations.find((item) => item.id === suggestion.observation_id)
              const extraObservations = run.suggestions
                .filter((item) => item.master_object_id === suggestion.master_object_id && item.id !== suggestion.id)
                .map((item) => run.observations.find((obs) => obs.id === item.observation_id))
                .filter((obs): obs is QaAiObservation => Boolean(obs))
              return <Card key={suggestion.id} size="small" styles={{ body: { padding: '8px 12px' } }}>
                <Checkbox checked={selectedSuggestions.includes(suggestion.id)} disabled={suggestion.status !== 'pending'} onChange={(event) => setSelectedSuggestions((current) => event.target.checked ? [...current, suggestion.id] : current.filter((id) => id !== suggestion.id))}>
                  <Text strong>{masterNames[suggestion.master_object_id] || suggestion.master_object_id}</Text>
                  <Tag color={suggestion.match_method.startsWith('exact') ? 'green' : 'gold'} style={{ marginLeft: 8 }}>{suggestion.match_method} · {Math.round(suggestion.confidence * 100)}%</Tag>
                </Checkbox>
                {observation && <div style={{ marginLeft: 24, marginTop: 4 }}><AiObservationEvidence observation={observation} /></div>}
                {extraObservations.length > 0 && (
                  <Tooltip title={extraObservations.map((obs, index) => (
                    <div key={obs.id}>{index + 1}. {obs.mention_text} · {formatAiEvidenceLocation(obs)}</div>
                  ))}
                  >
                    <span style={{ marginLeft: 24, fontSize: 12, color: 'var(--color-slate)' }}>另有 {extraObservations.length} 处其他写法提及</span>
                  </Tooltip>
                )}
              </Card>
            })}
          </Space>
        </>}
        {canConfirm && <>
          <Divider orientation="horizontal">人工新增关联（可选）</Divider>
          <Select
            mode="multiple"
            value={manualMasterIds}
            options={manualSelectOptions}
            style={{ width: '100%' }}
            maxTagCount="responsive"
            showSearch={{ filterOption: false, onSearch: (value) => { void loadMasterOptions(value) } }}
            onFocus={() => { if (!masterOptions.length) void loadMasterOptions() }}
            onChange={(values) => setManualMasterIds(values as string[])}
            placeholder="搜索并选择需要人工补充的质量主数据"
          />
          <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>人工新增项会与勾选的 AI 候选一起写入本版本；AI 不会自动选择跨模块来源。</Text>
        </>}
        {run.observations.filter((observation) => !run.suggestions.some((suggestion) => suggestion.observation_id === observation.id)).length > 0 && <>
          <Divider orientation="horizontal">未匹配实体（仅事实，不自动创建）</Divider>
          {run.observations.filter((observation) => !run.suggestions.some((suggestion) => suggestion.observation_id === observation.id)).map((observation) => (
            <Card key={observation.id} size="small" styles={{ body: { padding: '8px 12px' } }} style={{ marginBottom: 8 }}>
              <Text strong>{observation.mention_text}</Text>
              <div style={{ marginTop: 4 }}><AiObservationEvidence observation={observation} /></div>
            </Card>
          ))}
        </>}
        {relationIds.size > 0 && <>
          <Divider orientation="horizontal">明确移除现有关联（可选）</Divider>
          <Checkbox.Group value={removeIds} onChange={(values) => setRemoveIds(values as string[])} options={[...(version?.relations || [])].map((relation) => ({ value: relation.master_object_id, label: masterNames[relation.master_object_id] || relation.name_snapshot || relation.master_object_id }))} />
        </>}
        {run.proposals.length > 0 && <Alert type="warning" showIcon title={`发现 ${run.proposals.length} 条主数据提案`} description="请到质量主数据页的 AI 提案箱审核；本窗口不会自动创建主数据。" style={{ marginTop: 16 }} />}
      </>}
    </Modal>
  )
}

// ─────────────────────────────────────────────────────────────
// 审计日志
// ─────────────────────────────────────────────────────────────

function QaAudit() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canRead = hasPermission('qa:audit:read')
  const [action, setAction] = useState<string | undefined>()
  const [objectType, setObjectType] = useState<string | undefined>()
  const [actor, setActor] = useState('')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<QaAuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<QaAuditLog | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  // actor 只是输入框的值，不进 load 的依赖——否则每敲一个字都会打一次接口。
  // 真正发请求时（筛选/回车）从 ref 取最新值。
  const actorRef = useRef(actor)
  useEffect(() => { actorRef.current = actor }, [actor])

  const load = useCallback(async () => {
    if (!canRead) return
    setLoading(true)
    try {
      const result = await fetchQaAuditLogs({ action, object_type: objectType, actor_id: actorRef.current.trim() || undefined, page, page_size: 50 })
      setRows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载审计日志失败')
    } finally { setLoading(false) }
  }, [action, canRead, message, objectType, page])

  // page 与 reloadKey 一起作为触发源：setPage(1) 与 setReloadKey 在同一次批更新里生效，
  // effect 只跑一次且读到新 page，不会再出现「点了筛选却请求旧页码」的并发覆盖。
  useEffect(() => { void load() }, [load, reloadKey])

  if (!canRead) {
    return <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="需要 qa:audit:read 权限才能查看审计日志" /></Card>
  }

  const columns: ColumnsType<QaAuditLog> = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 180, render: (value: string) => formatDate(value) },
    { title: '操作者', key: 'actor', width: 150, render: (_, row) => row.actor_name || row.actor_id || '—' },
    { title: '动作', dataIndex: 'action', key: 'action', width: 180, render: (value: string) => <Tag color="blue">{value}</Tag> },
    { title: '对象', key: 'object', width: 220, render: (_, row) => `${row.object_type || '—'} / ${row.object_id || '—'}` },
    { title: '文件哈希', dataIndex: 'file_sha256', key: 'hash', width: 180, render: (value: string | null | undefined) => value ? `${value.slice(0, 16)}…` : '—' },
    { title: '详情', key: 'detail', width: 80, render: (_, row) => <Button type="link" size="small" onClick={() => setDetail(row)}>查看</Button> },
  ]

  return (
    <>
      <Card variant="borderless">
        <Space wrap style={{ marginBottom: 16 }}>
          <Select allowClear value={action} onChange={(value) => { setAction(value); setPage(1) }} placeholder="动作" style={{ width: 220 }} options={[{ value: 'create', label: '创建' }, { value: 'update', label: '更新' }, { value: 'deactivate', label: '停用' }, { value: 'make_current', label: '设为当前' }, { value: 'version_create', label: '版本上传' }, { value: 'preview', label: '文件预览' }, { value: 'download', label: '文件下载' }, { value: 'extraction_complete', label: '正文解析完成' }, { value: 'extraction_failed', label: '正文解析失败' }, { value: 'extraction_retry', label: '正文解析重试' }, { value: 'ai_analysis_requested', label: 'AI 分析请求' }, { value: 'ai_analysis_retry_requested', label: 'AI 分析重试' }, { value: 'ai_analysis_completed', label: 'AI 分析完成' }, { value: 'ai_analysis_partial', label: 'AI 分析部分完成' }, { value: 'ai_analysis_failed', label: 'AI 分析失败' }, { value: 'ai_analysis_stale', label: 'AI 分析过期' }, { value: 'ai_relations_confirmed', label: 'AI 关联确认' }, { value: 'ai_proposal_approved', label: 'AI 提案审批' }, { value: 'ai_proposal_conflict', label: 'AI 提案冲突' }, { value: 'ai_proposal_stale', label: 'AI 提案过期' }]} />
          <Select allowClear value={objectType} onChange={(value) => { setObjectType(value); setPage(1) }} placeholder="对象类型" style={{ width: 220 }} options={[{ value: 'qa.master_object', label: '主数据' }, { value: 'qa.document', label: '文件台账' }, { value: 'qa.document_version', label: '文件版本' }, { value: 'qa.document_file', label: '文件' }, { value: 'qa.document_ai_analysis_run', label: 'AI 分析运行' }, { value: 'qa.master_object_proposal', label: '主数据提案' }]} />
          <Input value={actor} onChange={(event) => setActor(event.target.value)} onPressEnter={() => { setPage(1); setReloadKey((value) => value + 1) }} placeholder="操作者 ID" style={{ width: 190 }} allowClear />
          <Button type="primary" icon={<SearchOutlined />} onClick={() => { setPage(1); setReloadKey((value) => value + 1) }}>筛选</Button>
          <Button icon={<ReloadOutlined />} onClick={() => { void load() }}>刷新</Button>
        </Space>
        <Table<QaAuditLog> rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 980 }} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计记录" /> }} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}><Pagination current={page} pageSize={50} total={total} showSizeChanger={false} onChange={setPage} showTotal={(value) => `共 ${value} 条`} /></div>
      </Card>
      <Drawer title="审计详情" open={!!detail} onClose={() => setDetail(null)} size={560}>
        {detail && <>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="时间">{formatDate(detail.created_at)}</Descriptions.Item>
            <Descriptions.Item label="操作者">{detail.actor_name || detail.actor_id || '—'}</Descriptions.Item>
            <Descriptions.Item label="动作">{detail.action}</Descriptions.Item>
            <Descriptions.Item label="对象">{detail.object_type || '—'} / {detail.object_id || '—'}</Descriptions.Item>
            <Descriptions.Item label="文件 SHA-256">{detail.file_sha256 || '—'}</Descriptions.Item>
            <Descriptions.Item label="来源 IP">{detail.ip_address || '—'}</Descriptions.Item>
          </Descriptions>
          <Divider plain>变更前</Divider>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#f6f5f4', padding: 12, borderRadius: 8, fontSize: 12 }}>{JSON.stringify(detail.before_value || {}, null, 2)}</pre>
          <Divider plain>变更后 / 附加信息</Divider>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#f6f5f4', padding: 12, borderRadius: 8, fontSize: 12 }}>{JSON.stringify(detail.after_value || detail.metadata || {}, null, 2)}</pre>
        </>}
      </Drawer>
    </>
  )
}

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
  CloudUploadOutlined,
  DatabaseOutlined,
  EditOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  HistoryOutlined,
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
  fetchQaDepartments,
  fetchQaDocument,
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
  createQaDocument,
  createQaDocumentType,
  createQaMasterObject,
  makeQaVersionCurrent,
  retryQaExtraction,
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
  QaDepartmentReference,
  QaDocument,
  QaDocumentFile,
  QaDocumentType,
  QaDocumentVersion,
  QaMasterKind,
  QaMasterObject,
  QaSearchResult,
  QaSourceReference,
} from '@/types/qa'
import { QA_MASTER_KIND_LABELS } from '@/types/qa'
import styles from './QaWorkspace.module.css'

const { Text } = Typography
const { Dragger } = Upload

export type QaView = 'home' | 'master-data' | 'documents' | 'audit'

const MASTER_KIND_ORDER: QaMasterKind[] = ['PRODUCT', 'MATERIAL', 'EQUIPMENT', 'SUPPLIER', 'REGION']

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
  const baseLabel = `${source.code ? `${source.code} · ` : ''}${source.name}`
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
              {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增{QA_MASTER_KIND_LABELS[kind]}</Button>}
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

  const sourceSelectOptions = sourceOptions.map((source) => ({
    value: `${source.source_module}|${source.source_entity}|${source.source_id}`,
    label: qaSourceOptionLabel(source),
  }))

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
      const result = await fetchQaDocuments({ keyword: queryKeyword.trim() || undefined, include_inactive: includeInactive, include_history: includeHistory, page, page_size: 20 })
      setRows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载文件台账失败')
    } finally {
      setLoading(false)
    }
  }, [includeHistory, includeInactive, message, page, queryKeyword])

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

  const columns: ColumnsType<QaDocument> = [
    { title: '文件编号', dataIndex: 'document_no', key: 'document_no', width: 170, render: (value: string) => <Text strong copyable>{value}</Text> },
    { title: '标题', dataIndex: 'title', key: 'title', width: 280, ellipsis: true },
    { title: '文件类型', key: 'type', width: 150, render: (_, row) => row.document_type_name || row.document_type_code || '—' },
    { title: '责任部门', key: 'department', width: 150, render: (_, row) => row.responsible_department_name || row.responsible_department_name_snapshot || row.department_name || '—' },
    {
      title: '当前版本', key: 'current', width: 130,
      render: (_, row) => row.current_version?.version_label || row.current_version_label || (row.current_version_id ? '已设置' : <Tag>未设置</Tag>),
    },
    { title: '版本数', key: 'versions', width: 85, render: (_, row) => row.version_count ?? row.versions?.length ?? 0 },
    { title: '状态', key: 'status', width: 90, render: (_, row) => statusTag(row.status, isDocumentActive(row)) },
    {
      title: '操作', key: 'actions', fixed: 'right', width: 220,
      render: (_, row) => <Space size={2}>
        <Button type="link" size="small" onClick={() => setDetailId(row.id)}>详情</Button>
        {canUpdate && <Button type="link" size="small" icon={<EditOutlined />} onClick={() => { setEditing(row); setModalOpen(true) }}>编辑</Button>}
        {canDeactivate && <Button type="link" size="small" danger={isDocumentActive(row)} onClick={() => { void toggleActive(row) }}>{isDocumentActive(row) ? '停用' : '启用'}</Button>}
      </Space>,
    },
  ]

  return (
    <>
      <Card variant="borderless">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'space-between', marginBottom: 16 }}>
          <Space wrap>
            <Input.Search value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={(value) => { setQueryKeyword(value); setPage(1) }} allowClear placeholder="搜索文件编号、标题或正文" style={{ width: 280 }} />
            <Space size={6}><Switch size="small" checked={includeHistory} onChange={(value) => { setIncludeHistory(value); setPage(1) }} /><span style={{ fontSize: 12 }}>包含历史版本</span></Space>
            <Space size={6}><Switch size="small" checked={includeInactive} onChange={(value) => { setIncludeInactive(value); setPage(1) }} /><span style={{ fontSize: 12 }}>包含停用</span></Space>
          </Space>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => { setRefreshKey((value) => value + 1) }}>刷新</Button>
            {canConfig && <Button icon={<SettingOutlined />} onClick={() => setTypeManagerOpen(true)}>文件类型</Button>}
            {canCreate && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setModalOpen(true) }}>登记文件</Button>}
          </Space>
        </div>
        <Table<QaDocument> rowKey="id" loading={loading} columns={columns} dataSource={rows} scroll={{ x: 1250 }} pagination={false} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件台账" /> }} />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}><Pagination current={page} pageSize={20} total={total} showSizeChanger={false} onChange={setPage} showTotal={(value) => `共 ${value} 条`} /></div>
      </Card>

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
      document_no: String(values.document_no || '').trim(),
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
    <Modal title={record ? '编辑文件台账' : '登记文件台账'} open={open} onCancel={onClose} onOk={() => { void handleSubmit() }} okText="保存" cancelText="取消" confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical">
        <Form.Item name="document_no" label="文件编号" rules={[{ required: true, message: '请输入文件编号' }]}><Input disabled={!!record} maxLength={100} /></Form.Item>
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入文件标题' }]}><Input maxLength={300} /></Form.Item>
        <Form.Item name="document_type_id" label="文件类型" rules={[{ required: true, message: '请选择文件类型' }]}><Select showSearch={{ optionFilterProp: 'label' }} options={types.filter(isDocumentTypeActive).map((item) => ({ value: item.id, label: `${item.name} (${item.code})` }))} placeholder="选择文件类型" /></Form.Item>
        <Form.Item name="department_id" label="责任部门"><Select allowClear showSearch={{ optionFilterProp: 'label' }} options={departments.map((item) => ({ value: displayDepartmentId(item), label: item.name }))} placeholder="选择飞书组织部门" /></Form.Item>
        {!record && <Alert type="info" showIcon title="先登记文件台账，再上传一个或多个不可覆盖的版本。" />}
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
    form.setFieldsValue({ code: row?.code ?? '', name: row?.name ?? '', description: row?.description ?? '' })
  }

  const closeEditor = () => {
    setEditor(null)
    form.resetFields()
  }

  const save = async () => {
    const row = editor?.row ?? null
    const values = await form.validateFields().catch(() => null) as Record<string, unknown> | null
    if (!values) return
    setSaving(true)
    try {
      const result = row
        ? await updateQaDocumentType(row.id, { name: values.name, description: values.description })
        : await createQaDocumentType({ code: String(values.code || '').trim().toUpperCase(), name: values.name, description: values.description })
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
  const { message } = App.useApp()
  const [document, setDocument] = useState<QaDocument | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [relationVersion, setRelationVersion] = useState<QaDocumentVersion | null>(null)
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
    Modal.confirm({
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
    <Drawer title={document ? `${document.document_no} · ${document.title}` : '文件详情'} open={!!documentId} size={720} onClose={onClose}>
      {loading && !document ? <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div> : document ? <>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="文件编号">{document.document_no}</Descriptions.Item>
          <Descriptions.Item label="文件类型">{document.document_type_name || document.document_type?.name || document.document_type_code || document.document_type?.code || '—'}</Descriptions.Item>
          <Descriptions.Item label="责任部门">{document.responsible_department_name || document.responsible_department_name_snapshot || document.department_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="状态">{statusTag(document.status, isDocumentActive(document))}</Descriptions.Item>
          <Descriptions.Item label="当前版本">{document.current_version?.version_label || document.versions?.find((item) => item.id === document.current_version_id)?.version_label || document.current_version_label || (document.current_version_id ? '已设置' : '未设置')}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDate(document.created_at)}</Descriptions.Item>
        </Descriptions>
        <Divider plain>版本时间线</Divider>
        <Space orientation="vertical" style={{ width: '100%' }} size={10}>
          {versions.length ? versions.map((version) => <VersionCard key={version.id} version={version} isCurrent={version.id === document.current_version_id} hasCurrent={Boolean(document.current_version_id)} canCurrent={canCurrent} canDisableVersion={canDisableVersion} canRetry={canVersion} canRelation={canRelation} onMakeCurrent={() => doMakeCurrent(version)} onCopyRelations={() => { void doCopyRelations(version) }} onSetActive={(active) => { void doSetVersionActive(version, active) }} onRelations={() => setRelationVersion(version)} onRefresh={() => { setRefreshKey((value) => value + 1); onChanged() }} />) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未上传版本" />}
        </Space>
        {canVersion && <Button type="primary" icon={<CloudUploadOutlined />} style={{ marginTop: 18 }} onClick={() => setUploadOpen(true)}>上传新版本</Button>}
        <QaUploadVersionModal open={uploadOpen} documentId={document.id} onClose={() => setUploadOpen(false)} onSaved={() => { setUploadOpen(false); setRefreshKey((value) => value + 1); onChanged() }} />
        <QaRelationsModal open={!!relationVersion} version={relationVersion} onClose={() => setRelationVersion(null)} onSaved={() => { setRelationVersion(null); setRefreshKey((value) => value + 1); onChanged() }} />
      </> : <Empty description="无法加载文件详情" />}
    </Drawer>
  )
}

function VersionCard({
  version,
  isCurrent,
  hasCurrent,
  canCurrent,
  canDisableVersion,
  canRetry,
  canRelation,
  onMakeCurrent,
  onCopyRelations,
  onSetActive,
  onRelations,
  onRefresh,
}: {
  version: QaDocumentVersion
  isCurrent: boolean
  hasCurrent: boolean
  canCurrent: boolean
  canDisableVersion: boolean
  canRetry: boolean
  canRelation: boolean
  onMakeCurrent: () => void
  onCopyRelations: () => void
  onSetActive: (active: boolean) => void
  onRelations: () => void
  onRefresh: () => void
}) {
  const { message } = App.useApp()
  const file = displayFile(version)
  const state = displayVersionState(version)
  const locked = Boolean(version.locked_at || version.first_locked_at || isCurrent || state === 'history')
  const relations = version.relations || []

  const retry = async () => {
    if (!file?.id) return
    const result = await retryQaExtraction(file.id)
    if (!result.success) { message.error(actionError(result)); return }
    message.success('已重新加入解析队列')
    onRefresh()
  }

  return (
    <Card size="small" title={<Space><HistoryOutlined />版本 {version.version_label}</Space>} extra={statusTag(isCurrent ? 'current' : state, isVersionActive(version))}>
      <Descriptions column={2} size="small">
        <Descriptions.Item label="登记时间">{formatDate(version.created_at)}</Descriptions.Item>
        <Descriptions.Item label="锁定时间">{formatDate(version.locked_at || version.first_locked_at)}</Descriptions.Item>
        <Descriptions.Item label="批准声明">{version.approved_declared ? <Tag color="green">已确认外部批准</Tag> : <Tag color="red">未确认</Tag>}</Descriptions.Item>
        <Descriptions.Item label="正文状态">{file ? statusTag(file.extraction_status, true) : '—'}</Descriptions.Item>
        <Descriptions.Item label="文件" span={2}>
          {file ? <Space wrap><Text>{file.original_filename || file.filename || '文件'}</Text><Text type="secondary">{formatBytes(file.size_bytes ?? file.file_size)}</Text><Text type="secondary">SHA-256: {file.sha256 ? `${file.sha256.slice(0, 16)}…` : '—'}</Text>{canRetry && file.extraction_status === 'failed' && <Button type="link" size="small" onClick={() => { void retry() }}>重试解析</Button>}<Button type="link" icon={<FilePdfOutlined />} href={qaFileContentUrl(file.id)} target="_blank">预览 / 下载</Button></Space> : <Text type="secondary">无文件</Text>}
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <Space wrap><LinkOutlined /><Text type="secondary">适用/关联：</Text>{relations.length ? relations.map((link) => <Tag key={link.id || link.master_object_id}>{link.master_object_code || link.code_snapshot || ''}{link.master_object_name || link.name_snapshot ? ` · ${link.master_object_name || link.name_snapshot}` : ''}</Tag>) : <Text type="secondary">暂无</Text>}</Space>
        <Space>
          {canRelation && state === 'registered' && !locked && <Button size="small" onClick={onRelations}>维护关联</Button>}
          {canRelation && state === 'registered' && hasCurrent && !isCurrent && !locked && <Button size="small" onClick={onCopyRelations}>复制当前关联</Button>}
          {canCurrent && !isCurrent && isVersionActive(version) && <Button size="small" type="primary" onClick={onMakeCurrent}>设为当前</Button>}
          {canDisableVersion && state === 'inactive' && <Button size="small" onClick={() => onSetActive(true)}>启用版本</Button>}
          {canDisableVersion && !isCurrent && isVersionActive(version) && <Button size="small" danger onClick={() => { Modal.confirm({ title: '停用版本', content: '停用后该版本不再参与默认检索，历史记录仍会保留。确认继续吗？', okText: '停用', cancelText: '取消', onOk: () => onSetActive(false) }) }}>停用版本</Button>}
        </Space>
      </div>
    </Card>
  )
}

function QaUploadVersionModal({ open, documentId, onClose, onSaved }: { open: boolean; documentId: string; onClose: () => void; onSaved: () => void }) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)

  useEffect(() => { if (!open) { form.resetFields(); setFileList([]); setSelectedFile(null) } }, [form, open])

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
    <Modal title="上传批准文件版本" open={open} onCancel={onClose} onOk={() => { void submit() }} okText="上传并登记" cancelText="取消" confirmLoading={uploading} destroyOnHidden>
      <Form form={form} layout="vertical">
        <Form.Item name="version_label" label="版本标签" rules={[{ required: true, message: '请输入版本标签' }]} extra="手工维护，例如 1.0、2026.09"><Input maxLength={50} placeholder="1.0" /></Form.Item>
        <Form.Item name="approved_declared" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('必须确认外部批准')) }]}><Checkbox>我确认该文件已在现行正式流程中批准</Checkbox></Form.Item>
        <Form.Item label="主文件" required>
          <Dragger accept=".pdf,.docx,.doc" maxCount={1} fileList={fileList} beforeUpload={(file) => {
            if (file.size > 50 * 1024 * 1024) { message.error('文件大小不能超过 50 MB'); return Upload.LIST_IGNORE }
            const ext = file.name.split('.').pop()?.toLowerCase()
            if (!ext || !['pdf', 'docx', 'doc'].includes(ext)) { message.error('仅支持 PDF、DOCX 或 DOC'); return Upload.LIST_IGNORE }
            setSelectedFile(file)
            setFileList([{ uid: file.uid, name: file.name, status: 'done', size: file.size, type: file.type }])
            return false
          }} onRemove={() => { setFileList([]); setSelectedFile(null); return true }}>
            <p className="ant-upload-drag-icon"><UploadOutlined /></p><p className="ant-upload-text">点击或拖拽文件到此处</p><p className="ant-upload-hint">PDF / DOCX 进入正文提取；DOC 仅归档不保证正文解析，最大 50 MB</p>
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
      <Alert type="info" showIcon title="关联挂在版本层级" description="版本锁定后不能修改关系；如需调整，请上传新版本。" style={{ marginBottom: 14 }} />
      <Select mode="multiple" value={selected} onChange={setSelected} loading={loading} showSearch={{ filterOption: false, optionFilterProp: 'label', onSearch: (value) => { void loadOptions(value) } }} onFocus={() => { if (!options.length) void loadOptions() }} style={{ width: '100%' }} placeholder="搜索并选择产品、物料、设备、供应商或区域" options={options.map((item) => ({ value: item.id, label: `${qaMasterKindLabel(item.kind)} · ${displayMasterCode(item)} · ${item.name}` }))} />
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
          <Select allowClear value={action} onChange={(value) => { setAction(value); setPage(1) }} placeholder="动作" style={{ width: 180 }} options={[{ value: 'create', label: '创建' }, { value: 'update', label: '更新' }, { value: 'deactivate', label: '停用' }, { value: 'make_current', label: '设为当前' }, { value: 'version_create', label: '版本上传' }, { value: 'preview', label: '文件预览' }, { value: 'download', label: '文件下载' }, { value: 'extraction_complete', label: '正文解析完成' }, { value: 'extraction_failed', label: '正文解析失败' }]} />
          <Select allowClear value={objectType} onChange={(value) => { setObjectType(value); setPage(1) }} placeholder="对象类型" style={{ width: 160 }} options={[{ value: 'qa.master_object', label: '主数据' }, { value: 'qa.document', label: '文件台账' }, { value: 'qa.document_version', label: '文件版本' }, { value: 'qa.document_file', label: '文件' }]} />
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

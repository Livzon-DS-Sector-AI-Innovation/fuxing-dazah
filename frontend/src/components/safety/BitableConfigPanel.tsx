'use client'

// 多维表格配置中心主面板（design.md §1-§6）
// 组装：左域列表（260px）+ 右域详情（连接配置卡 + 字段映射卡）+ 抽屉/弹窗
// 取数链路：挂载 → fetchBitableDomains（URL ?domain= 恢复选中，缺省首个）→
//           选中域变化 → Promise.all([fetchBitableConnection, fetchBitableMappings(domain, kind)])
// 保存成功后 onSaved → loadDomains() 重拉（客户端 state 为准，同 ScheduledTasksPanel 模式）

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { App, Button, Empty, Skeleton, Space } from 'antd'
import { ReloadOutlined, SyncOutlined } from '@ant-design/icons'

import {
  fetchBitableConnection,
  fetchBitableDomains,
  fetchBitableMappings,
  resubscribeBitable,
} from '@/actions/safety'
import type {
  BitableConnection,
  BitableDomainOverview,
  BitableFieldMapping,
  BitableMappingStatus,
} from '@/types/safety'
import BitableDomainList from './BitableDomainList'
import BitableConnectionCard from './BitableConnectionCard'
import BitableConnectionEditDrawer from './BitableConnectionEditDrawer'
import BitableMappingEditor from './BitableMappingEditor'
import BitableTestConnectionModal from './BitableTestConnectionModal'
import BitableAuditDrawer from './BitableAuditDrawer'
import { CARD_STYLE, MONO_FONT, UI } from './bitableConfigConstants'

interface DrawerState {
  open: boolean
  mode: 'new' | 'edit'
  kind: string | null
  record: BitableConnection | null
}

const CLOSED_DRAWER: DrawerState = { open: false, mode: 'new', kind: null, record: null }

export default function BitableConfigPanel() {
  const { message } = App.useApp()
  const router = useRouter()
  const searchParams = useSearchParams()

  // ── 域清单 ──
  const [domains, setDomains] = useState<BitableDomainOverview[]>([])
  const [domainsLoading, setDomainsLoading] = useState(true)
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null)
  // ── 映射 kind（后端映射按 domain+kind 存储）──
  const [mappingKind, setMappingKind] = useState<string | null>(null)
  // ── 域详情 ──
  const [connections, setConnections] = useState<BitableConnection[]>([])
  const [connLoading, setConnLoading] = useState(false)
  const [mappings, setMappings] = useState<BitableFieldMapping[]>([])
  const [mappingStatus, setMappingStatus] = useState<BitableMappingStatus | null>(null)
  const [mappingLoading, setMappingLoading] = useState(false)
  // ── 抽屉/弹窗 ──
  const [drawer, setDrawer] = useState<DrawerState>(CLOSED_DRAWER)
  const [testModal, setTestModal] = useState<{ open: boolean; appToken: string; tableId: string }>({
    open: false,
    appToken: '',
    tableId: '',
  })
  const [auditOpen, setAuditOpen] = useState(false)
  const [resubscribing, setResubscribing] = useState(false)
  const emptyWarned = useRef(false)
  /** 挂载时读取一次 URL ?domain=（后续选中由 handleSelectDomain 维护，避免 searchParams 变化触发重拉） */
  const initialUrlDomain = useRef<string | null>(null)

  useEffect(() => {
    initialUrlDomain.current = searchParams.get('domain')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadDomains = useCallback(async () => {
    setDomainsLoading(true)
    try {
      const res = await fetchBitableDomains()
      if (res.code === 200 && res.data) {
        const list = res.data
        setDomains(list)
        // URL ?domain= 恢复选中；无效或缺失回退首个域
        const urlKey = initialUrlDomain.current
        const target = urlKey && list.some((d) => d.key === urlKey) ? urlKey : (list[0]?.key ?? null)
        setSelectedDomain(target)
        setMappingKind(list.find((d) => d.key === target)?.kinds[0]?.kind ?? null)
      } else {
        message.error(res.message || '加载域清单失败')
      }
    } finally {
      setDomainsLoading(false)
    }
  }, [message])

  useEffect(() => {
    void loadDomains()
  }, [loadDomains])

  // 域清单 15 秒仍为空 → 警告（后端不可用场景，design.md §6）
  useEffect(() => {
    if (domainsLoading || domains.length > 0 || emptyWarned.current) return
    emptyWarned.current = true
    const timer = setTimeout(() => {
      if (domains.length === 0) message.warning('域清单加载失败，请刷新重试')
    }, 15000)
    return () => clearTimeout(timer)
  }, [domainsLoading, domains.length, message])

  // 选中域（含映射 kind）变化 → 并行重拉连接 + 映射（design.md §4.3）
  useEffect(() => {
    if (!selectedDomain) {
      setConnections([])
      setMappings([])
      setMappingStatus(null)
      return
    }
    const kind = mappingKind ?? domains.find((d) => d.key === selectedDomain)?.kinds[0]?.kind ?? null
    let cancelled = false
    setConnLoading(true)
    setMappingLoading(true)
    Promise.all([
      fetchBitableConnection(selectedDomain),
      kind ? fetchBitableMappings(selectedDomain, kind) : Promise.resolve(null),
    ])
      .then(([connRes, mappingRes]) => {
        if (cancelled) return
        if (connRes.code === 200 && connRes.data) {
          setConnections(connRes.data)
        } else {
          message.error(connRes.message || '加载连接配置失败')
        }
        if (mappingRes) {
          if (mappingRes.code === 200 && mappingRes.data) {
            setMappings(mappingRes.data.mappings ?? [])
            setMappingStatus(mappingRes.data.status ?? null)
          } else {
            message.error(mappingRes.message || '加载字段映射失败')
          }
        } else {
          setMappings([])
          setMappingStatus(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setConnLoading(false)
          setMappingLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [selectedDomain, mappingKind, domains, message])

  const selectedDomainInfo = domains.find((d) => d.key === selectedDomain) ?? null

  const handleSelectDomain = (key: string) => {
    setSelectedDomain(key)
    const d = domains.find((x) => x.key === key)
    setMappingKind(d?.kinds[0]?.kind ?? null)
    router.push(`?domain=${encodeURIComponent(key)}`)
  }

  const handleRefresh = () => {
    void loadDomains()
  }

  const handleResubscribe = async () => {
    if (!selectedDomain) return
    setResubscribing(true)
    try {
      const res = await resubscribeBitable(selectedDomain)
      if (res.code === 200 && res.data) {
        const results = res.data.results ?? {}
        const values = Object.values(results)
        if (values.length > 0 && values.every((v) => v === 'ok')) {
          message.success('手动重订阅完成，该域事件订阅已生效')
        } else if (values.some((v) => v === 'failed')) {
          message.warning('重订阅部分失败，请稍后重试或检查连接配置')
        } else {
          message.success('手动重订阅已触发')
        }
      } else {
        message.error(res.message || '重订阅失败')
      }
    } finally {
      setResubscribing(false)
    }
  }

  const openEditDrawer = (record: BitableConnection) => {
    setDrawer({ open: true, mode: 'edit', kind: record.kind, record })
  }
  const openAddDrawer = (kind?: string) => {
    setDrawer({ open: true, mode: 'new', kind: kind ?? null, record: null })
  }
  const openTestModal = (record: BitableConnection) => {
    setTestModal({ open: true, appToken: record.app_token, tableId: record.table_id })
  }

  return (
    <div style={{ padding: 24, maxWidth: 1280 }}>
      {/* ── 页头 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 20,
        }}
      >
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>多维表格配置</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            安全模块 Bitable 数据源连接与字段映射管理（保存即生效，无需重启）
          </div>
        </div>
        <Space size={12}>
          <span style={{ fontSize: 12, color: UI.steel }}>配置变更实时生效，无需重启</span>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} title="刷新" loading={domainsLoading} />
        </Space>
      </div>

      {/* ── 左右布局 ── */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <BitableDomainList
          domains={domains}
          selected={selectedDomain}
          onSelect={handleSelectDomain}
          loading={domainsLoading}
        />

        <div style={{ flex: 1, minWidth: 0 }}>
          {domainsLoading && domains.length === 0 ? (
            <div style={{ ...CARD_STYLE, padding: 16 }}>
              <Skeleton active paragraph={{ rows: 10 }} />
            </div>
          ) : !selectedDomainInfo ? (
            <div style={{ ...CARD_STYLE, padding: 24 }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用功能域（由代码注册表提供）" />
            </div>
          ) : (
            <>
              {/* 域详情页头 */}
              <div
                style={{
                  ...CARD_STYLE,
                  padding: '12px 16px',
                  marginBottom: 16,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 8,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>域详情 · {selectedDomainInfo.label}</span>
                  <span style={{ fontSize: 12, color: UI.steel, fontFamily: MONO_FONT, marginLeft: 8 }}>
                    {selectedDomainInfo.key}
                  </span>
                  {selectedDomainInfo.purpose && (
                    <div style={{ fontSize: 12, color: UI.muted, marginTop: 2 }}>{selectedDomainInfo.purpose}</div>
                  )}
                </div>
                <Button icon={<SyncOutlined />} loading={resubscribing} onClick={() => void handleResubscribe()}>
                  手动重订阅
                </Button>
              </div>

              {/* 连接配置卡 */}
              <BitableConnectionCard
                domain={selectedDomainInfo}
                connections={connections}
                loading={connLoading}
                onEdit={openEditDrawer}
                onAdd={openAddDrawer}
                onTest={openTestModal}
              />

              {/* 字段映射卡 */}
              <BitableMappingEditor
                domain={selectedDomainInfo}
                kind={mappingKind}
                onKindChange={setMappingKind}
                status={mappingStatus}
                mappings={mappings}
                loading={mappingLoading}
                onOpenAudit={() => setAuditOpen(true)}
                onSaved={handleRefresh}
              />
            </>
          )}
        </div>
      </div>

      {/* 连接编辑/新增抽屉 */}
      <BitableConnectionEditDrawer
        open={drawer.open}
        mode={drawer.mode}
        domain={selectedDomainInfo}
        kind={drawer.kind}
        record={drawer.record}
        onClose={() => setDrawer(CLOSED_DRAWER)}
        onSaved={handleRefresh}
      />

      {/* 测试连接 Modal（行快捷测试入口） */}
      <BitableTestConnectionModal
        open={testModal.open}
        title={selectedDomainInfo ? `测试连接 · ${selectedDomainInfo.label}` : '测试连接'}
        initialAppToken={testModal.appToken}
        initialTableId={testModal.tableId}
        onClose={() => setTestModal((s) => ({ ...s, open: false }))}
      />

      {/* 审计抽屉 */}
      <BitableAuditDrawer open={auditOpen} domain={selectedDomain} onClose={() => setAuditOpen(false)} />
    </div>
  )
}

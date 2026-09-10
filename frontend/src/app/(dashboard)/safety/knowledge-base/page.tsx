'use client'

import { Suspense, useMemo, useState } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { App, Button, Input, Select, Modal, Tooltip, Pagination } from 'antd'
import { SearchOutlined, RobotOutlined, SyncOutlined, ApartmentOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createNewArticleVersion,
  generateKnowledgeCard,
  batchGenerateKnowledgeCards,
  generatePpt,
  generateSummary,
  syncKnowledgeArticles,
} from '@/actions/safety'
import { KnowledgeQueryProvider } from '@/components/safety/KnowledgeQueryProvider'
import DocumentCardGrid from '@/components/safety/DocumentCardGrid'
import KnowledgeSidebar from '@/components/safety/KnowledgeSidebar'
import KnowledgeDetailDrawer from '@/components/safety/KnowledgeDetailDrawer'
import KnowledgeFormModal from '@/components/safety/KnowledgeFormModal'
import { StatItem } from '@/components/safety/knowledgeUI'
import { filterByMenuKey, mapCategoryCountsToMenu } from '@/components/safety/knowledgeConstants'
import {
  fetchKnowledgeArticles,
  fetchKnowledgeSemanticSearch,
  fetchKnowledgeCategoryCounts,
} from '@/lib/api/knowledge'
import type { SafetyKnowledgeArticle } from '@/types/safety'

const PAGE_SIZE = 48

function KnowledgeBaseContent() {
  const { message } = App.useApp()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()

  // ── URL 派生的筛选状态 ──
  const q = searchParams.get('q') || ''
  const statusFilter = searchParams.get('status') || undefined
  const cardFilter = searchParams.get('card') || undefined
  const menuKey = searchParams.get('menu') || null
  const smart = searchParams.get('smart') === '1'
  const page = Math.max(1, Number(searchParams.get('page') || '1'))

  // ── 本地状态 ──
  const [searchText, setSearchText] = useState(q)
  const [syncing, setSyncing] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyKnowledgeArticle | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // ── URL 更新 helper ──
  const patchUrl = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') params.delete(k)
      else params.set(k, v)
    }
    const qs = params.toString()
    router.replace(qs ? pathname + '?' + qs : pathname, { scroll: false })
  }

  // ── 数据查询 ──
  const allQuery = useQuery({
    queryKey: ['knowledge-articles'],
    queryFn: () => fetchKnowledgeArticles({ page: 1, page_size: 500 }),
  })
  const smartQuery = useQuery({
    queryKey: ['knowledge-smart', q],
    queryFn: () => fetchKnowledgeSemanticSearch(q, 1, 500),
    enabled: smart && !!q,
  })
  const statsQuery = useQuery({
    queryKey: ['knowledge-stats'],
    queryFn: fetchKnowledgeCategoryCounts,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['knowledge-articles'] })
    queryClient.invalidateQueries({ queryKey: ['knowledge-stats'] })
    queryClient.invalidateQueries({ queryKey: ['knowledge-smart'] })
  }

  const menuCounts = useMemo(
    () => (statsQuery.data ? mapCategoryCountsToMenu(statsQuery.data.by_category) : new Map<string, number>()),
    [statsQuery.data],
  )

  const rawItems = useMemo(() => {
    return smart && q ? (smartQuery.data?.items ?? []) : (allQuery.data?.items ?? [])
  }, [smart, q, smartQuery.data, allQuery.data])

  // ── 客户端筛选（基于全量数据） ──
  const filtered = useMemo(() => {
    let arr = rawItems
    if (menuKey) arr = filterByMenuKey(arr, menuKey)
    if (statusFilter) arr = arr.filter((a) => a.status === statusFilter)
    if (cardFilter === 'has_card') arr = arr.filter((a) => a.knowledge_card != null)
    else if (cardFilter === 'no_card') arr = arr.filter((a) => !a.knowledge_card)
    return arr
  }, [rawItems, menuKey, statusFilter, cardFilter])

  const pageItems = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  )

  const isLoading = smart && q ? smartQuery.isLoading : allQuery.isLoading
  const loadError = (smart && q ? smartQuery.error : allQuery.error) as Error | null

  // ── 页头统计（优先全库接口） ──
  const stats = useMemo(() => {
    if (statsQuery.data) {
      return {
        total: statsQuery.data.total,
        draft: statsQuery.data.by_status['draft'] || 0,
        published: statsQuery.data.by_status['published'] || 0,
        archived: statsQuery.data.by_status['archived'] || 0,
        withCard: statsQuery.data.with_card,
        withAttachment: statsQuery.data.with_attachment,
      }
    }
    const s = { total: rawItems.length, draft: 0, published: 0, archived: 0, withCard: 0, withAttachment: 0 }
    for (const a of rawItems) {
      if (a.status === 'draft') s.draft++
      else if (a.status === 'published') s.published++
      else if (a.status === 'archived') s.archived++
      if (a.knowledge_card != null) s.withCard++
      if (a.attachment_original_name) s.withAttachment++
    }
    return s
  }, [statsQuery.data, rawItems])

  // ── 事件处理 ──
  const handleSearch = () => {
    patchUrl({ q: searchText.trim() || null, page: '1' })
  }
  const handleMenuSelect = (key: string) => patchUrl({ menu: key || null, page: '1' })
  const handleStatusChange = (v?: string) => patchUrl({ status: v || null, page: '1' })
  const handleCardChange = (v?: string) => patchUrl({ card: v || null, page: '1' })
  const handleSmartToggle = () => patchUrl({ smart: smart ? null : '1', page: '1' })
  const handlePageChange = (p: number) => patchUrl({ page: String(p) })

  const handleSelectCard = (id: string) => {
    setSelectedRowKeys((prev) =>
      prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id],
    )
  }

  const handleEdit = (record: SafetyKnowledgeArticle) => {
    setEditingRecord(record)
    setFormOpen(true)
  }
  const handleViewDetail = (record: SafetyKnowledgeArticle) => {
    setDetailId(record.id)
    setDetailOpen(true)
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncKnowledgeArticles()
      if (res.code === 200 && res.data) {
        message.success('同步完成：创建 ' + res.data.created + '，更新 ' + res.data.updated + '，删除 ' + res.data.deleted)
        refresh()
      } else {
        message.error(res.message || '同步失败')
      }
    } catch {
      message.error('同步请求失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleNewVersion = async (article: SafetyKnowledgeArticle) => {
    const res = await createNewArticleVersion(article.id)
    if (res.code === 200 && res.data) {
      message.success('已创建新版本 v' + res.data.new_article.version)
      setDetailId(res.data.new_article.id)
      refresh()
    } else {
      message.error(res.message || '创建新版本失败')
    }
  }

  const handleFormSuccess = () => {
    setFormOpen(false)
    setEditingRecord(null)
    refresh()
  }

  const handleGenerateCard = async (articleId: string) => {
    const res = await generateKnowledgeCard(articleId)
    if (res.code === 200 && res.data) {
      message.success(res.data.message || '知识卡片生成成功')
      refresh()
    } else {
      message.error(res.message || '生成失败')
    }
  }

  const handleBatchGenerateCards = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择文档')
      return
    }
    Modal.confirm({
      title: '批量生成知识卡片',
      content: '确认为选中的 ' + selectedRowKeys.length + ' 份文档生成知识卡片吗？',
      onOk: async () => {
        const res = await batchGenerateKnowledgeCards(selectedRowKeys)
        if (res.code === 200 && res.data) {
          const d = res.data
          message.success('成功 ' + d.success_count + ' 份，失败 ' + d.failed_count + ' 份')
          setSelectedRowKeys([])
          refresh()
        } else {
          message.error(res.message || '批量生成失败')
        }
      },
    })
  }

  const handleGeneratePpt = async (articleId: string) => {
    const res = await generatePpt(articleId, { template: 'training', style: 'professional' })
    if (res.code === 200 && res.data) {
      message.success(res.data.message || 'PPT 生成成功')
      if (res.data.download_url) {
        window.open('/api/v1/safety/files/' + encodeURIComponent(res.data.download_url), '_blank')
      }
    } else {
      message.error(res.message || 'PPT 生成失败')
    }
  }

  const handleGenerateSummary = async (articleId: string) => {
    const res = await generateSummary(articleId)
    if (res.code === 200 && res.data) {
      message.success(res.data.message || '摘要生成成功')
      refresh()
    } else {
      message.error(res.message || '摘要生成失败')
    }
  }

  // ── Render ──
  return (
    <div style={{ display: 'flex', margin: -24, height: 'calc(100vh - 64px)' }}>
      <KnowledgeSidebar
        selectedKey={menuKey}
        onSelect={handleMenuSelect}
        counts={menuCounts}
        loading={isLoading}
      />

      <div style={{ flex: 1, overflowY: 'auto', padding: 24, minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 20, flexWrap: 'wrap', marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: 24, fontWeight: 650, color: 'var(--color-ink, #1a1a1a)', margin: 0, letterSpacing: '-0.02em', lineHeight: 1.2 }}>
              文档处理中枢
            </h2>
            <p style={{ fontSize: 13, color: 'var(--color-steel, #787671)', margin: '5px 0 0', lineHeight: 1.5 }}>
              法规标准 · 知识卡片 · Agent 注入 · 智能检索
            </p>
          </div>
          <div style={{ display: 'flex', gap: 22, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <StatItem value={stats.total} label='全部文档' />
            <StatItem value={stats.published} label='已发布' color='#1aae39' />
            <StatItem value={stats.draft} label='草稿' color='#5d5b54' />
            <StatItem value={stats.archived} label='已归档' color='#a4a097' />
            <StatItem value={stats.withCard} label='知识卡片' color='var(--color-primary, #5645d4)' />
            <StatItem value={stats.withAttachment} label='含附件' color='#1aae39' />
          </div>
        </div>

        {/* 错误诊断 */}
        {loadError && (
          <div style={{ marginBottom: 20, padding: '12px 16px', background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 8, fontSize: 13, color: '#a8071a', lineHeight: 1.6, wordBreak: 'break-all' }}>
            <strong style={{ fontSize: 14 }}>⚠️ API 请求失败</strong>
            <br />
            {loadError.message}
            <br />
            <button type='button' onClick={() => refresh()} style={{ marginTop: 8, cursor: 'pointer', background: '#a8071a', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', fontSize: 12 }}>
              重试
            </button>
          </div>
        )}

        {/* Filter Toolbar */}
        <div style={{ background: 'var(--color-canvas, #ffffff)', borderRadius: 12, border: '1px solid var(--color-hairline, #e5e3df)', padding: '12px 14px', marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Select
            placeholder='状态'
            allowClear
            value={statusFilter}
            onChange={handleStatusChange}
            style={{ width: 104 }}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'published', label: '已发布' },
              { value: 'archived', label: '已归档' },
            ]}
          />
          <Select
            placeholder='卡片状态'
            allowClear
            value={cardFilter}
            onChange={handleCardChange}
            style={{ width: 126 }}
            options={[
              { value: 'has_card', label: '有知识卡片' },
              { value: 'no_card', label: '无知识卡片' },
            ]}
          />
          <Input
            placeholder={smart ? '如"防爆区域电气安全相关标准"' : '搜索标题 / 内容 / 标签'}
            prefix={<SearchOutlined style={{ color: 'var(--color-stone, #a4a097)' }} />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onPressEnter={handleSearch}
            allowClear
            style={{ width: 252 }}
          />
          <Tooltip title={smart ? '智能搜索（AI 解析查询意图）' : '关键词搜索'}>
            <button
              type='button'
              onClick={handleSmartToggle}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer',
                background: smart ? 'rgba(86, 69, 212, 0.08)' : 'transparent',
                border: smart ? '1px solid var(--color-primary, #5645d4)' : '1px solid var(--color-hairline, #e5e3df)',
                borderRadius: 999, padding: '3px 12px', fontSize: 12, fontWeight: smart ? 600 : 500,
                color: smart ? 'var(--color-primary, #5645d4)' : 'var(--color-steel, #787671)',
                transition: 'all 0.15s ease', lineHeight: '18px',
              }}
            >
              AI
            </button>
          </Tooltip>
          <div style={{ flex: 1 }} />
          <Button icon={<ApartmentOutlined />} onClick={() => router.push('/safety/knowledge-base/graph')}>
            知识图谱
          </Button>
          <Button icon={<SyncOutlined spin={syncing} />} onClick={handleSync} loading={syncing}>
            同步
          </Button>
          <Button type='primary' icon={<SearchOutlined />} onClick={handleSearch}>
            查询
          </Button>
        </div>

        {/* Batch bar */}
        {selectedRowKeys.length > 0 && (
          <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: 'rgba(86, 69, 212, 0.05)', border: '1px solid rgba(86, 69, 212, 0.18)', borderRadius: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-primary, #5645d4)' }}>
              已选 {selectedRowKeys.length} 项
            </span>
            <Button size='small' type='primary' icon={<RobotOutlined />} onClick={handleBatchGenerateCards}>
              批量生成卡片
            </Button>
            <Button size='small' onClick={() => setSelectedRowKeys([])}>
              取消选择
            </Button>
          </div>
        )}

        {/* Card grid */}
        <DocumentCardGrid
          articles={pageItems}
          loading={isLoading}
          selectedCardIds={selectedRowKeys}
          onSelectCard={handleSelectCard}
          onArticleClick={handleViewDetail}
          onEdit={handleEdit}
          onGenerateCard={handleGenerateCard}
          onGeneratePpt={handleGeneratePpt}
          onGenerateSummary={handleGenerateSummary}
        />

        {/* Pagination */}
        {!isLoading && filtered.length > PAGE_SIZE && (
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={filtered.length}
            onChange={handlePageChange}
            showSizeChanger={false}
            showTotal={(t) => '共 ' + t + ' 份'}
            style={{ marginTop: 16, textAlign: 'right' }}
          />
        )}
      </div>

      <KnowledgeFormModal
        open={formOpen}
        editingRecord={editingRecord}
        onClose={() => { setFormOpen(false); setEditingRecord(null) }}
        onSuccess={handleFormSuccess}
      />
      <KnowledgeDetailDrawer
        articleId={detailId}
        open={detailOpen}
        onClose={() => { setDetailOpen(false); setDetailId(null) }}
        onNewVersion={handleNewVersion}
      />
    </div>
  )
}

export default function KnowledgeBasePage() {
  return (
    <KnowledgeQueryProvider>
      <Suspense fallback={null}>
        <KnowledgeBaseContent />
      </Suspense>
    </KnowledgeQueryProvider>
  )
}

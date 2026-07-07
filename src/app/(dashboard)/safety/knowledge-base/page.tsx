'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { App, Button, Input, Select, Modal, Tooltip } from 'antd'
import {
  SearchOutlined,
  RobotOutlined,
  SyncOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import {
  getKnowledgeArticles,
  deleteKnowledgeArticle,
  publishKnowledgeArticle,
  archiveKnowledgeArticle,
  createNewArticleVersion,
  semanticSearchArticles,
  generateKnowledgeCard,
  batchGenerateKnowledgeCards,
  generatePpt,
  generateSummary,
  syncKnowledgeArticles,
} from '@/actions/safety'
import DocumentCardGrid from '@/components/safety/DocumentCardGrid'
import KnowledgeSidebar from '@/components/safety/KnowledgeSidebar'
import KnowledgeDetailDrawer from '@/components/safety/KnowledgeDetailDrawer'
import KnowledgeFormModal from '@/components/safety/KnowledgeFormModal'
import { useKnowledgeStore } from '@/stores/safety'
import type { SafetyKnowledgeArticle } from '@/types/safety'
import { filterByMenuKey, computeMenuCounts } from '@/components/safety/knowledgeConstants'

export default function KnowledgeBasePage() {
  // ── Antd App hook ──────────────────────────────────
  const { message } = App.useApp()
  const router = useRouter()

  // ── Store ──────────────────────────────────────────
  const {
    items,
    total,
    queryParams,
    loading,
    selectedRowKeys,
    setItems,
    setTotal,
    setQueryParams,
    setLoading,
    updateItem,
    removeItem,
    setSelectedRowKeys,
  } = useKnowledgeStore()

  // ── Local state ────────────────────────────────────
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [cardStatusFilter, setCardStatusFilter] = useState<string | undefined>()
  const [smartSearch, setSmartSearch] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedMenuKey, setSelectedMenuKey] = useState<string | null>(null)
  const [menuCounts, setMenuCounts] = useState<Map<string, number>>(new Map())
  const [syncing, setSyncing] = useState(false)

  // Modal/Drawer visibility
  const [formOpen, setFormOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<SafetyKnowledgeArticle | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

  // ── Data loading ───────────────────────────────────
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // 卡片模式使用较大的 page_size 以支持单页浏览
      const pageSize = queryParams.page_size || 200
      let response
      if (smartSearch && searchText) {
        response = await semanticSearchArticles(searchText, queryParams.page || 1, pageSize)
      } else {
        response = await getKnowledgeArticles({
          page: queryParams.page || 1,
          page_size: pageSize,
          status: statusFilter,
          category: categoryFilter,
          keyword: searchText || undefined,
        })
      }
      if (response.code === 200) {
        const data = response.data as SafetyKnowledgeArticle[]
        const totalCount = response.meta?.total || 0

        // 计算菜单计数（基于原始数据，不受筛选影响）
        setMenuCounts(computeMenuCounts(data))

        // Client-side filters
        let filtered = data
        // 菜单分类筛选
        if (selectedMenuKey) {
          filtered = filterByMenuKey(filtered, selectedMenuKey)
        }
        // 知识卡片状态筛选
        if (cardStatusFilter === 'has_card') {
          filtered = filtered.filter((a) => a.knowledge_card != null)
        } else if (cardStatusFilter === 'no_card') {
          filtered = filtered.filter((a) => !a.knowledge_card)
        }

        setItems(filtered)
        setTotal(cardStatusFilter || selectedMenuKey ? filtered.length : totalCount)
        setLoadError(null) // 清除之前的错误
      } else {
        // 诊断：显示后端返回的具体错误
        const errMsg = response.message || `请求失败 (code=${response.code})`
        console.error('[知识库] API 返回非 200:', response)
        setLoadError(errMsg)
        message.error(errMsg)
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err)
      console.error('[知识库] 请求异常:', err)
      setLoadError(errMsg || '加载知识库列表失败')
      message.error('加载知识库列表失败')
    } finally {
      setLoading(false)
    }
  }, [queryParams.page, queryParams.page_size, statusFilter, categoryFilter, cardStatusFilter, smartSearch, searchText, selectedMenuKey, setItems, setLoading, setTotal])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleSearch = () => {
    setQueryParams({ page: 1 })
    loadData()
  }

  // ── Card selection ─────────────────────────────────
  const handleSelectCard = (id: string) => {
    setSelectedRowKeys(
      selectedRowKeys.includes(id)
        ? selectedRowKeys.filter((k) => k !== id)
        : [...selectedRowKeys, id]
    )
  }

  // ── Menu selection ────────────────────────────────
  const handleMenuSelect = useCallback((key: string) => {
    setSelectedMenuKey(key)
    setQueryParams({ page: 1 })
  }, [setQueryParams])

  // ── Sync ──────────────────────────────────────────
  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await syncKnowledgeArticles()
      if (res.code === 200 && res.data) {
        message.success(
          `同步完成：创建 ${res.data.created}，更新 ${res.data.updated}，删除 ${res.data.deleted}`
        )
        loadData()
      } else {
        message.error(res.message || '同步失败')
      }
    } catch {
      message.error('同步请求失败')
    } finally {
      setSyncing(false)
    }
  }

  // ── CRUD actions ───────────────────────────────────
  const handleEdit = (record: SafetyKnowledgeArticle) => {
    setEditingRecord(record)
    setFormOpen(true)
  }

  const handleViewDetail = (record: SafetyKnowledgeArticle) => {
    setDetailId(record.id)
    setDetailOpen(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该知识文档吗？',
      onOk: async () => {
        const response = await deleteKnowledgeArticle(id)
        if (response.code === 200) {
          message.success('删除成功')
          removeItem(id)
        } else {
          message.error(response.message || '删除失败')
        }
      },
    })
  }

  const handlePublish = async (id: string) => {
    const response = await publishKnowledgeArticle(id)
    if (response.code === 200) {
      message.success('发布成功')
      updateItem(id, response.data)
    } else {
      message.error(response.message || '发布失败')
    }
  }

  const handleArchive = async (id: string) => {
    const response = await archiveKnowledgeArticle(id)
    if (response.code === 200) {
      message.success('已归档')
      updateItem(id, response.data)
    } else {
      message.error(response.message || '归档失败')
    }
  }

  const handleNewVersion = async (article: SafetyKnowledgeArticle) => {
    const response = await createNewArticleVersion(article.id)
    if (response.code === 200 && response.data) {
      message.success(`已创建新版本 v${response.data.new_article.version}`)
      setDetailId(response.data.new_article.id)
      loadData()
    } else {
      message.error(response.message || '创建新版本失败')
    }
  }

  const handleFormSuccess = () => {
    setFormOpen(false)
    setEditingRecord(null)
    loadData()
  }

  const handleGenerateCard = async (articleId: string) => {
    const res = await generateKnowledgeCard(articleId)
    if (res.code === 200 && res.data) {
      message.success(res.data.message || '知识卡片生成成功')
      loadData()
    } else {
      message.error(res.message || '生成失败')
    }
  }

  const handleBatchGenerateCards = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择文档')
      return
    }
    Modal.confirm({
      title: '批量生成知识卡片',
      content: `确认为选中的 ${selectedRowKeys.length} 份文档生成知识卡片吗？`,
      onOk: async () => {
        const res = await batchGenerateKnowledgeCards(selectedRowKeys)
        if (res.code === 200 && res.data) {
          const d = res.data
          message.success(`成功 ${d.success_count} 份，失败 ${d.failed_count} 份`)
          setSelectedRowKeys([])
          loadData()
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
        window.open(`/api/v1/safety/files/${encodeURIComponent(res.data.download_url)}`, '_blank')
      }
    } else {
      message.error(res.message || 'PPT 生成失败')
    }
  }

  const handleGenerateSummary = async (articleId: string) => {
    const res = await generateSummary(articleId)
    if (res.code === 200 && res.data) {
      message.success(res.data.message || '摘要生成成功')
      loadData()
    } else {
      message.error(res.message || '摘要生成失败')
    }
  }

  // ── Render ─────────────────────────────────────────
  return (
    <div style={{ display: 'flex', margin: -24, height: 'calc(100vh - 64px)' }}>
      {/* ── Left Sidebar ── */}
      <KnowledgeSidebar
        selectedKey={selectedMenuKey}
        onSelect={handleMenuSelect}
        counts={menuCounts}
        loading={loading}
      />

      {/* ── Right Content ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 24, minWidth: 0 }}>
        {/* ── Header ── */}
        <div style={{ marginBottom: 24 }}>
        <h2
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: '#1a1a1a',
            margin: 0,
            marginBottom: 4,
            lineHeight: 1.3,
          }}
        >
          文档处理中枢
        </h2>
        <p
          style={{
            fontSize: 14,
            color: '#787671',
            margin: 0,
            lineHeight: 1.5,
          }}
        >
          法规标准 · 知识卡片 · Agent 注入 · 智能检索
        </p>
      </div>

      {/* ── 持久化错误诊断 ── */}
      {loadError && (
        <div
          style={{
            marginBottom: 20,
            padding: '12px 16px',
            background: '#fff2f0',
            border: '1px solid #ffccc7',
            borderRadius: 8,
            fontSize: 13,
            color: '#a8071a',
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          <strong style={{ fontSize: 14 }}>⚠️ API 请求失败</strong>
          <br />
          {loadError}
          <br />
          <button
            type="button"
            onClick={() => { setLoadError(null); loadData(); }}
            style={{
              marginTop: 8,
              cursor: 'pointer',
              background: '#a8071a',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              padding: '4px 12px',
              fontSize: 12,
            }}
          >
            重试
          </button>
        </div>
      )}

      {/* ── White Card Container ── */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #e5e3df',
          padding: '16px 20px',
        }}
      >
        {/* ── Filter Bar ── */}
        <div
          style={{
            marginBottom: 16,
            display: 'flex',
            gap: 10,
            alignItems: 'center',
            flexShrink: 0,
          }}
        >
          <Select
            placeholder="状态"
            allowClear
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v)
              setQueryParams({ page: 1 })
            }}
            style={{ width: 100 }}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'published', label: '已发布' },
              { value: 'archived', label: '已归档' },
            ]}
          />
          <Select
            placeholder="卡片状态"
            allowClear
            value={cardStatusFilter}
            onChange={(v) => {
              setCardStatusFilter(v)
              setQueryParams({ page: 1 })
            }}
            style={{ width: 120 }}
            options={[
              { value: 'has_card', label: '有知识卡片' },
              { value: 'no_card', label: '无知识卡片' },
            ]}
          />
          <Input
            placeholder={smartSearch ? '如"防爆区域电气安全相关标准"' : '搜索标题/内容/标签'}
            prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onPressEnter={handleSearch}
            allowClear
            style={{ width: 240 }}
          />

          {/* Smart search toggle */}
          <Tooltip title={smartSearch ? '智能搜索（AI 解析查询意图）' : '关键词搜索'}>
            <button
              type="button"
              onClick={() => setSmartSearch(!smartSearch)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                cursor: 'pointer',
                background: smartSearch ? '#e6e0f5' : 'transparent',
                border: smartSearch ? '1px solid #d6b6f6' : '1px solid transparent',
                borderRadius: 20,
                padding: '2px 10px',
                fontSize: 12,
                fontWeight: smartSearch ? 600 : 400,
                color: smartSearch ? '#7b3ff2' : '#a4a097',
                transition: 'all 0.15s ease',
                lineHeight: '20px',
              }}
            >
              AI
            </button>
          </Tooltip>

          <div style={{ flex: 1 }} />

          <Button
            icon={<ApartmentOutlined />}
            onClick={() => router.push('/safety/knowledge-base/graph')}
          >
            知识图谱
          </Button>

          <Button
            icon={<SyncOutlined spin={syncing} />}
            onClick={handleSync}
            loading={syncing}
          >
            同步
          </Button>

          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            查询
          </Button>
        </div>

        {/* ── Batch Operations Bar ── */}
        {selectedRowKeys.length > 0 && (
          <div
            style={{
              marginBottom: 16,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 12px',
              background: '#f6f5f4',
              borderRadius: 8,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
              已选 {selectedRowKeys.length} 项
            </span>
            <Button
              size="small"
              icon={<RobotOutlined />}
              onClick={handleBatchGenerateCards}
            >
              批量生成卡片
            </Button>
            <Button size="small" onClick={() => setSelectedRowKeys([])}>
              取消选择
            </Button>
          </div>
        )}

        {/* ── Card Grid ── */}
        <DocumentCardGrid
          articles={items}
          loading={loading}
          selectedCardIds={selectedRowKeys}
          onSelectCard={handleSelectCard}
          onArticleClick={handleViewDetail}
          onEdit={handleEdit}
          onGenerateCard={handleGenerateCard}
          onGeneratePpt={handleGeneratePpt}
          onGenerateSummary={handleGenerateSummary}
        />
      </div>

      {/* ── Modals & Drawer ── */}
      <KnowledgeFormModal
        open={formOpen}
        editingRecord={editingRecord}
        onClose={() => {
          setFormOpen(false)
          setEditingRecord(null)
        }}
        onSuccess={handleFormSuccess}
      />

      <KnowledgeDetailDrawer
        articleId={detailId}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false)
          setDetailId(null)
        }}
        onNewVersion={handleNewVersion}
      />
      </div>
    </div>
  )
}

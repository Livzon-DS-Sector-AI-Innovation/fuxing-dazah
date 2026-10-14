'use client'

import { Suspense, useMemo, useState } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { App, Button, Input, Modal, Pagination, Select, Tooltip } from 'antd'
import {
  ApartmentOutlined,
  FileSearchOutlined,
  RobotOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  batchGenerateKnowledgeCards,
  createNewArticleVersion,
  generateKnowledgeCard,
  generatePpt,
  generateSummary,
  syncKnowledgeArticles,
} from '@/actions/safety'
import { KnowledgeQueryProvider } from '@/components/safety/KnowledgeQueryProvider'
import KnowledgeDetailDrawer from '@/components/safety/KnowledgeDetailDrawer'
import KnowledgeFormModal from '@/components/safety/KnowledgeFormModal'
import RagplusEngineBar from '@/components/safety/knowledge/RagplusEngineBar'
import SemanticResultList from '@/components/safety/knowledge/SemanticResultList'
import ArticleTable from '@/components/safety/knowledge/ArticleTable'
import { PageHeader, SectionCard } from '@/components/ui-kit'
import {
  fetchKnowledgeArticles,
  fetchKnowledgeRagplusDocMap,
  fetchKnowledgeSemanticSearch,
} from '@/lib/api/knowledge'
import type { SafetyKnowledgeArticle } from '@/types/safety'

const PAGE_SIZE = 20

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
  const searchMode = searchParams.get('mode') === 'kw' ? 'kw' : 'semantic'
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
  const searching = !!q && searchMode === 'semantic'
  const allQuery = useQuery({
    queryKey: ['knowledge-articles'],
    queryFn: () => fetchKnowledgeArticles({ page: 1, page_size: 1000 }),
    enabled: !searching,
  })
  const smartQuery = useQuery({
    queryKey: ['knowledge-semantic', q],
    queryFn: () => fetchKnowledgeSemanticSearch(q, 1, 100),
    enabled: searching,
  })
  const docMapQuery = useQuery({
    queryKey: ['knowledge-ragplus-doc-map'],
    queryFn: () => fetchKnowledgeRagplusDocMap('regulation'),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['knowledge-articles'] })
    queryClient.invalidateQueries({ queryKey: ['knowledge-semantic'] })
    queryClient.invalidateQueries({ queryKey: ['knowledge-ragplus-doc-map'] })
  }

  const rawItems = useMemo(() => {
    return searching ? [] : (allQuery.data?.items ?? [])
  }, [searching, allQuery.data])

  // ── 客户端筛选（非检索模式，基于全量数据） ──
  const filtered = useMemo(() => {
    let arr = rawItems
    if (statusFilter) arr = arr.filter((a) => a.status === statusFilter)
    if (cardFilter === 'has_card') arr = arr.filter((a) => a.knowledge_card != null)
    else if (cardFilter === 'no_card') arr = arr.filter((a) => !a.knowledge_card)
    return arr
  }, [rawItems, statusFilter, cardFilter])

  const pageItems = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  )

  const isLoading = searching ? smartQuery.isLoading : allQuery.isLoading
  const loadError = (searching ? smartQuery.error : allQuery.error) as Error | null

  // ── 事件处理 ──
  const handleSearch = () => {
    patchUrl({ q: searchText.trim() || null, page: '1' })
  }
  const handleStatusChange = (v?: string) => patchUrl({ status: v || null, page: '1' })
  const handleCardChange = (v?: string) => patchUrl({ card: v || null, page: '1' })
  const handleModeToggle = () => patchUrl({ mode: searchMode === 'semantic' ? 'kw' : null, page: '1' })
  const handlePageChange = (p: number) => patchUrl({ page: String(p) })
  const handleClearSearch = () => {
    setSearchText('')
    patchUrl({ q: null, page: '1' })
  }

  const handleEdit = (record: SafetyKnowledgeArticle) => {
    setEditingRecord(record)
    setFormOpen(true)
  }
  const handleViewDetail = (record: SafetyKnowledgeArticle) => {
    setDetailId(record.id)
    setDetailOpen(true)
  }
  const handleOpenDetailById = (id: string) => {
    setDetailId(id)
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
    <div style={{ margin: -24, height: 'calc(100vh - 64px)', overflowY: 'auto', padding: 24 }}>
      {/* Header */}
      <PageHeader
        breadcrumb={['安全管理', '法规标准与规程']}
        title="法规标准与规程"
        description="法规、标准与规程知识库：条款级语义检索（ragplus-x 引擎）+ 台账清单"
      />

        {/* 引擎状态条（ragplus 库实时总量 + 映射聚合，30s 自动刷新） */}
        <RagplusEngineBar />

        {/* 检索区（ragplus 引用风格结果） */}
        <SectionCard
          title={searching ? `条款级检索结果${smartQuery.data ? `（${smartQuery.data.total} 部法规命中）` : ''}` : '条款级语义检索'}
          description="按业务问题检索法规条款，命中带法规名、条款定位与相似度"
          action={
            searchMode === 'kw' ? (
              <Tooltip title="当前为关键词过滤模式，点击切回条款级检索">
                <Button size="small" onClick={handleModeToggle}>
                  关键词模式
                </Button>
              </Tooltip>
            ) : (
              <Tooltip title="引擎不可用时的回退：按关键词过滤文档">
                <Button size="small" type="text" onClick={handleModeToggle}>
                  切关键词过滤
                </Button>
              </Tooltip>
            )
          }
        >
          <div style={{ display: 'flex', gap: 8, marginBottom: searching ? 14 : 4 }}>
            <Input
              placeholder='如"动火作业前需要办理什么手续""粉尘防爆要求"'
              prefix={<FileSearchOutlined style={{ color: 'var(--color-stone, #a4a097)' }} />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={handleSearch}
              allowClear
              size="large"
              style={{ flex: 1, maxWidth: 560 }}
            />
            <Button type="primary" size="large" icon={<FileSearchOutlined />} onClick={handleSearch}>
              检索
            </Button>
            {searching && (
              <Button size="large" onClick={handleClearSearch}>
                清除
              </Button>
            )}
          </div>
          {searching && (
            <SemanticResultList
              results={smartQuery.data?.items ?? []}
              loading={smartQuery.isLoading}
              mode={searchMode === 'semantic' ? 'engine' : 'keyword'}
              onOpenDetail={handleOpenDetailById}
            />
          )}
        </SectionCard>

        {/* 文档清单（ragplus 式表格） */}
        <div style={{ marginTop: 16 }}>
          <SectionCard
            title={`法规台账${filtered.length > 0 ? `（${filtered.length} 份）` : ''}`}
            description="Bitable 镜像清单 · 引擎入库状态实时可见"
            action={
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {selectedRowKeys.length > 0 && (
                  <Button size="small" type="primary" icon={<RobotOutlined />} onClick={handleBatchGenerateCards}>
                    批量生成卡片（{selectedRowKeys.length}）
                  </Button>
                )}
                <Button size="small" icon={<ApartmentOutlined />} onClick={() => router.push('/safety/knowledge-base/graph')}>
                  知识图谱
                </Button>
                <Button size="small" icon={<SyncOutlined spin={syncing} />} onClick={handleSync} loading={syncing}>
                  同步
                </Button>
              </div>
            }
          >
            {/* 筛选器 */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              <Select
                placeholder="状态"
                allowClear
                value={statusFilter}
                onChange={handleStatusChange}
                style={{ width: 104 }}
                size="small"
                options={[
                  { value: 'draft', label: '草稿' },
                  { value: 'published', label: '已发布' },
                  { value: 'archived', label: '已归档' },
                ]}
              />
              <Select
                placeholder="卡片状态"
                allowClear
                value={cardFilter}
                onChange={handleCardChange}
                style={{ width: 126 }}
                size="small"
                options={[
                  { value: 'has_card', label: '有知识卡片' },
                  { value: 'no_card', label: '无知识卡片' },
                ]}
              />
            </div>

            {/* 错误诊断 */}
            {loadError && (
              <div style={{ marginBottom: 12, padding: '10px 14px', background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 8, fontSize: 13, color: '#a8071a' }}>
                ⚠️ API 请求失败：{loadError.message}
                <button type="button" onClick={() => refresh()} style={{ marginLeft: 10, cursor: 'pointer', background: '#a8071a', color: '#fff', border: 'none', borderRadius: 4, padding: '2px 10px', fontSize: 12 }}>
                  重试
                </button>
              </div>
            )}

            <ArticleTable
              articles={pageItems}
              loading={isLoading || docMapQuery.isLoading}
              docMap={docMapQuery.data ?? {}}
              selectedRowKeys={selectedRowKeys}
              onSelectRowKeys={setSelectedRowKeys}
              onOpenDetail={handleViewDetail}
              onEdit={handleEdit}
              onGenerateCard={handleGenerateCard}
              onGeneratePpt={handleGeneratePpt}
              onGenerateSummary={handleGenerateSummary}
            />

            {!isLoading && filtered.length > PAGE_SIZE && (
              <Pagination
                current={page}
                pageSize={PAGE_SIZE}
                total={filtered.length}
                onChange={handlePageChange}
                showSizeChanger={false}
                showTotal={(t) => '共 ' + t + ' 份'}
                style={{ marginTop: 14, textAlign: 'right' }}
              />
            )}
          </SectionCard>
        </div>

      {/* onClose 只关不清：弹层关闭动画中卸载内容会让遮罩卡在全屏状态挡死页面；数据在下次打开时经 effect 重取/重置 */}
      <KnowledgeFormModal
        open={formOpen}
        editingRecord={editingRecord}
        onClose={() => setFormOpen(false)}
        onSuccess={handleFormSuccess}
      />
      <KnowledgeDetailDrawer
        articleId={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
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

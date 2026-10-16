'use client'

import { Suspense, useMemo, useState } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { Button, Input, Pagination, Select, Tabs, Tooltip } from 'antd'
import {
  FileSearchOutlined,
} from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { KnowledgeQueryProvider } from '@/components/safety/KnowledgeQueryProvider'
import KnowledgeDetailDrawer from '@/components/safety/KnowledgeDetailDrawer'
import RagplusEngineBar from '@/components/safety/knowledge/RagplusEngineBar'
import SemanticResultList from '@/components/safety/knowledge/SemanticResultList'
import ArticleTable from '@/components/safety/knowledge/ArticleTable'
import CrawlMonitorPanel from '@/components/safety/regulation/CrawlMonitorPanel'
import { PageHeader, SectionCard } from '@/components/ui-kit'
import {
  fetchKnowledgeArticles,
  fetchKnowledgeRagplusDocMap,
  fetchKnowledgeSemanticSearch,
} from '@/lib/api/knowledge'
import type { SafetyKnowledgeArticle } from '@/types/safety'

const PAGE_SIZE = 20

/** 双 Tab 白名单（?tab= 直达；非法值回默认，浅同步不进 router 历史） */
const TAB_KEYS = ['ledger', 'monitor'] as const
type KnowledgeTab = (typeof TAB_KEYS)[number]

function KnowledgeBaseContent() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()

  // ── URL 派生的筛选状态 ──
  const q = searchParams.get('q') || ''
  const statusFilter = searchParams.get('status') || undefined
  const searchMode = searchParams.get('mode') === 'kw' ? 'kw' : 'semantic'
  const page = Math.max(1, Number(searchParams.get('page') || '1'))
  const tabParam = searchParams.get('tab')
  const tab: KnowledgeTab = (TAB_KEYS as readonly string[]).includes(tabParam ?? '')
    ? (tabParam as KnowledgeTab)
    : 'ledger'

  // ── 本地状态 ──
  const [searchText, setSearchText] = useState(q)
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

  // Tab 浅同步：只动 tab 参数，保留清单检索的 q/status/mode/page
  const handleTabChange = (key: string) => {
    const params = new URLSearchParams(searchParams.toString())
    if (key === 'ledger') params.delete('tab')
    else params.set('tab', key)
    const qs = params.toString()
    window.history.replaceState(null, '', qs ? pathname + '?' + qs : pathname)
  }

  // ── 数据查询 ──
  const searching = !!q && searchMode === 'semantic'
  const allQuery = useQuery({
    queryKey: ['knowledge-articles'],
    queryFn: () => fetchKnowledgeArticles({ page: 1, page_size: 1000 }),
    enabled: !searching && tab === 'ledger',
  })
  const smartQuery = useQuery({
    queryKey: ['knowledge-semantic', q],
    queryFn: () => fetchKnowledgeSemanticSearch(q, 1, 100),
    enabled: searching && tab === 'ledger',
  })
  const docMapQuery = useQuery({
    queryKey: ['knowledge-ragplus-doc-map'],
    queryFn: () => fetchKnowledgeRagplusDocMap('regulation'),
    enabled: tab === 'ledger',
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
    return arr
  }, [rawItems, statusFilter])

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
  const handleModeToggle = () => patchUrl({ mode: searchMode === 'semantic' ? 'kw' : null, page: '1' })
  const handlePageChange = (p: number) => patchUrl({ page: String(p) })
  const handleClearSearch = () => {
    setSearchText('')
    patchUrl({ q: null, page: '1' })
  }

  const handleViewDetail = (record: SafetyKnowledgeArticle) => {
    setDetailId(record.id)
    setDetailOpen(true)
  }
  const handleOpenDetailById = (id: string) => {
    setDetailId(id)
    setDetailOpen(true)
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

      {/* 双 Tab：清单检索（默认）｜采集监控（?tab=monitor 直达，只读） */}
      <Tabs
        activeKey={tab}
        onChange={handleTabChange}
        items={[
          {
            key: 'ledger',
            label: '清单检索',
            children: (
              <>
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
                      onOpenDetail={handleViewDetail}
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
              </>
            ),
          },
          {
            key: 'monitor',
            label: '采集监控',
            children: <CrawlMonitorPanel />,
          },
        ]}
      />

      {/* onClose 只关不清：弹层关闭动画中卸载内容会让遮罩卡在全屏状态挡死页面；数据在下次打开时经 effect 重取/重置 */}
      <KnowledgeDetailDrawer
        articleId={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
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

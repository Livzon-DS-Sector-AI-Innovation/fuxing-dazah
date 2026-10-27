'use client'

/**
 * 岗位族归类面板（#4，S14 承包商在册人员区块之后）。
 *
 * 全厂岗位名（3.x 全员主档去重，~1400 人）→ AI 归类到 9 标准岗位族
 * （DESIGN v3 §13.1 枚举一次定死）→ 人工确认/改族（置 manual，重跑不覆盖）。
 * 确认流复用票一 AiSuggestionConfirmModal（#2 同构模式）：建议值列内嵌
 * 九族 Select，确认时改过则走修正 API、未改走确认 API。
 * 操作按钮定性=AI 确认流（人对 AI 产物的审核门）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Select, Tag } from 'antd'
import type { TableColumnsType } from 'antd'
import { SectionCard } from '@/components/ui-kit'
import {
  AiSuggestionConfirmModal,
  ConfidenceTag,
} from '@/components/safety/aiConfirm/AiSuggestionConfirmModal'
import {
  classifyOrgPosts,
  confirmOrgPostFamily,
  fetchOrgPostFamilies,
  fetchOrgPostsFamilies,
  updateOrgPostFamily,
  type OrgPostFamilyRow,
} from '@/lib/api/safety/contractor-workers'

/** 9 标准岗位族（§13.1，与后端 POST_FAMILIES 同源定死） */
export const POST_FAMILIES = [
  '特种作业相关',
  '危化工艺操作',
  '一般生产操作',
  '质检与实验',
  '设备维护',
  '物流仓储',
  '辅助后勤',
  '管理职能',
  '其他',
] as const

const FAMILY_OPTIONS = POST_FAMILIES.map(f => ({ value: f, label: f }))

const FAMILY_QUERY = ['safety', 'org-post-families']
const DICT_QUERY = ['safety', 'org-posts-families']

export function OrgPostFamilyPanel() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [edited, setEdited] = useState<Record<string, string>>({})

  // 族×人数聚合（服务端日级缓存，随字典一次拉回）
  const dictQuery = useQuery({
    queryKey: DICT_QUERY,
    queryFn: fetchOrgPostsFamilies,
    staleTime: 10 * 60_000,
  })

  // 待确认工作集（source='ai'，打开才拉）
  const pendingQuery = useQuery({
    queryKey: [...FAMILY_QUERY, 'ai'],
    queryFn: () => fetchOrgPostFamilies('ai'),
    enabled: confirmOpen,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: FAMILY_QUERY })
    void queryClient.invalidateQueries({ queryKey: DICT_QUERY })
  }

  const classifyMutation = useMutation({
    mutationFn: classifyOrgPosts,
    onSuccess: r => {
      const top = Object.entries(r.by_family)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([k, v]) => `${k} ${v}`)
        .join('、')
      message.success(
        `归类完成：${r.classified} 岗（新插 ${r.inserted}/覆盖 ${r.updated}，manual 保留 ${r.manual_kept}）${top ? `；${top}…` : ''}`,
      )
      invalidate()
    },
    onError: e => message.error(e instanceof Error ? e.message : '归类失败'),
  })

  const confirmMutation = useMutation({
    mutationFn: ({ row, family }: { row: OrgPostFamilyRow; family: string }) =>
      family !== row.family
        ? updateOrgPostFamily(row.id, family)
        : confirmOrgPostFamily(row.id),
    onSuccess: (r, { family, row }) => {
      message.success(
        family !== row.family
          ? `已修正：${r.post_name} → ${family}（manual）`
          : `已确认：${r.post_name} → ${r.family}`,
      )
      invalidate()
    },
    onError: e => message.error(e instanceof Error ? e.message : '操作失败'),
  })

  const columns: TableColumnsType<OrgPostFamilyRow> = [
    {
      title: '岗位名',
      dataIndex: 'post_name',
      width: 260,
      ellipsis: true,
    },
    {
      title: 'AI 归类（可改）',
      key: 'family',
      width: 170,
      render: (_, row) => (
        <Select
          size="small"
          style={{ width: 150 }}
          value={edited[row.id] ?? row.family}
          options={FAMILY_OPTIONS}
          onChange={v => setEdited(m => ({ ...m, [row.id]: v }))}
        />
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 76,
      render: (v: string) => <ConfidenceTag value={v} />,
    },
    {
      title: '判断依据',
      dataIndex: 'note',
      ellipsis: true,
    },
  ]

  const pendingCount = pendingQuery.data?.length ?? 0
  const families = dictQuery.data?.families ?? []

  return (
    <SectionCard
      title="岗位族归类（AI）"
      description="全厂岗位（3.x 全员主档去重）→ 9 标准岗位族：AI 批量归类后人工逐条确认或改族（改过/确认即 manual，重跑不覆盖）；Agent「特种作业相关岗位有哪些」由此可答。"
      action={
        <div className="flex items-center gap-2">
          <Button
            size="small"
            loading={classifyMutation.isPending}
            disabled={classifyMutation.isPending}
            onClick={() => classifyMutation.mutate()}
          >
            AI 归类
          </Button>
          <Button size="small" type="primary" ghost onClick={() => setConfirmOpen(true)}>
            确认清单{pendingQuery.data ? `（${pendingCount}）` : ''}
          </Button>
        </div>
      }
    >
      {families.length > 0 ? (
        <div className="flex flex-wrap gap-1.5" data-testid="family-aggregation">
          {families.map(f => (
            <Tag key={f.family} style={{ fontSize: 12, lineHeight: '20px' }}>
              {f.family} {f.headcount}
            </Tag>
          ))}
          <span className="self-center text-[11px] text-[var(--color-steel)]">
            族×在册人数（含未归类）
          </span>
        </div>
      ) : (
        <div className="py-2 text-[12px] text-[var(--color-steel)]">
          {dictQuery.isLoading
            ? '岗位字典加载中…'
            : dictQuery.data?.status === 'live'
              ? '尚无归类行——点击「AI 归类」对全厂岗位批量归类，再到确认清单人工确认。'
              : '岗位字典暂不可用（3.x 平台接口抖动），稍后自动恢复。'}
        </div>
      )}
      <AiSuggestionConfirmModal<OrgPostFamilyRow>
        open={confirmOpen}
        onClose={() => {
          setConfirmOpen(false)
          setEdited({})
        }}
        title="岗位族归类 · 人工确认"
        description="AI 归类（source=ai）为待确认工作集：确认按 AI 值入资产，或在下拉改族后确认（改过置 manual，重跑不覆盖）。确认后 org-posts 聚合与 Agent 岗位族问答即时生效。"
        rows={pendingQuery.data ?? []}
        loading={pendingQuery.isLoading}
        columns={columns}
        onConfirm={row =>
          confirmMutation.mutateAsync({ row, family: edited[row.id] ?? row.family })
        }
        emptyText="暂无待确认归类——点击「AI 归类」生成"
        extraFooter={
          <span className="flex items-center gap-2 text-[12px] text-[var(--color-steel)]">
            <Button
              size="small"
              loading={classifyMutation.isPending}
              disabled={classifyMutation.isPending}
              onClick={() => classifyMutation.mutate()}
            >
              重新归类（manual 行不动）
            </Button>
            <span>未确认行重跑会被 AI 覆盖</span>
          </span>
        }
      />
    </SectionCard>
  )
}

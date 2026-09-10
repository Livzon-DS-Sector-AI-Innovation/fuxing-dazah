'use client'

// 左：域列表导航（design.md §1.3 / §2.2）
// 两行式 item（中文名 13px/600 + ConfigStatusTag ｜ key·表数 12px/muted mono）+ 搜索 + 状态筛选
// 选中态：lavender 底 + 左侧 2px primary 竖条；停用域整块降透明（opacity 0.55）

import { useMemo, useState } from 'react'
import { Empty, Input, Select, Skeleton } from 'antd'

import type { BitableConfigStatus, BitableDomainOverview } from '@/types/safety'
import { CARD_STYLE, ConfigStatusTag, MONO_FONT, UI } from './bitableConfigConstants'

interface BitableDomainListProps {
  domains: BitableDomainOverview[]
  selected: string | null
  onSelect: (key: string) => void
  loading: boolean
}

const STATUS_FILTER_OPTIONS: { value: 'all' | BitableConfigStatus; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'configured', label: '已配置' },
  { value: 'partial', label: '部分配置' },
  { value: 'missing', label: '未配置' },
  { value: 'disabled', label: '已停用' },
]

export default function BitableDomainList({ domains, selected, onSelect, loading }: BitableDomainListProps) {
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | BitableConfigStatus>('all')

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return domains.filter((d) => {
      if (statusFilter !== 'all' && d.config_status !== statusFilter) return false
      if (
        kw &&
        !(d.label.toLowerCase().includes(kw) || d.key.toLowerCase().includes(kw))
      )
        return false
      return true
    })
  }, [domains, keyword, statusFilter])

  const configuredCount = domains.filter((d) => d.config_status === 'configured').length

  return (
    <div style={{ ...CARD_STYLE, width: 260, padding: 16, flexShrink: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: UI.ink, marginBottom: 10 }}>功能域</div>
      <Input.Search
        placeholder="搜索域名 / key"
        allowClear
        size="small"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <Select
        size="small"
        style={{ width: '100%', marginTop: 8 }}
        value={statusFilter}
        options={STATUS_FILTER_OPTIONS}
        onChange={(v) => setStatusFilter(v)}
      />

      <div
        style={{
          marginTop: 12,
          maxHeight: 'calc(100vh - 360px)',
          overflowY: 'auto',
          minHeight: 120,
        }}
      >
        {loading && domains.length === 0 ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={domains.length === 0 ? '暂无可用功能域' : '无匹配的域'}
            style={{ padding: '24px 0' }}
          />
        ) : (
          filtered.map((d) => {
            const isSelected = d.key === selected
            return (
              <button
                key={d.key}
                type="button"
                role="button"
                aria-pressed={isSelected}
                data-testid="bitable-domain-item"
                onClick={() => onSelect(d.key)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  background: isSelected ? UI.cardTintLavender : 'transparent',
                  border: 'none',
                  borderLeft: `2px solid ${isSelected ? UI.primary : 'transparent'}`,
                  borderRadius: 6,
                  padding: '8px 10px',
                  cursor: 'pointer',
                  marginBottom: 4,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 2,
                  opacity: d.config_status === 'disabled' ? 0.55 : 1,
                  fontFamily: 'inherit',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: UI.ink,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {d.label}
                  </span>
                  <ConfigStatusTag status={d.config_status} />
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: UI.muted,
                    fontFamily: MONO_FONT,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {d.key} · {d.kinds.length} 张表
                </div>
              </button>
            )
          })
        )}
      </div>

      {domains.length > 0 && (
        <div style={{ fontSize: 12, color: UI.steel, borderTop: `1px solid ${UI.hairlineSoft}`, paddingTop: 10, marginTop: 8 }}>
          共 {domains.length} 域 · {configuredCount} 已配置
        </div>
      )}
    </div>
  )
}

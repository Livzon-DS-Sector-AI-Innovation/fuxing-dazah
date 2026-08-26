'use client'

import { useState } from 'react'
import { App, Input } from 'antd'
import { HolderOutlined, SearchOutlined } from '@ant-design/icons'
import type { Candidate } from '@/types/hr'
import { transitionCandidateStatus } from '@/actions/hr'
import { useRouter } from 'next/navigation'

const STATUS_COLUMNS = [
  { key: '待筛选', label: '待筛选', color: '#a4a097' },
  { key: '已筛选', label: '已筛选', color: '#0075de' },
  { key: '待部门审核', label: '部门审核', color: '#dd5b00' },
  { key: '面试中', label: '面试中', color: '#7b3ff2' },
  { key: '已面试', label: '已面试', color: '#2a9d99' },
  { key: '录用中', label: '录用中', color: '#1aae39' },
  { key: '已录用', label: '已录用', color: '#5645d4' },
  { key: '待入职审批', label: '入职审批', color: '#e8b830' },
]

function daysSince(dateStr?: string) {
  if (!dateStr) return 0
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / (1000 * 60 * 60 * 24))
}

export default function RecruitmentKanban({ candidates, onRefresh }: { candidates: Candidate[]; onRefresh: () => void }) {
  const { message } = App.useApp()
  const router = useRouter()
  const [dragOverCol, setDragOverCol] = useState<string | null>(null)
  const [searchKeyword, setSearchKeyword] = useState('')

  const kw = searchKeyword.trim().toLowerCase()
  const filtered = kw
    ? candidates.filter(c =>
      (c.name?.toLowerCase().includes(kw)) ||
      (c.phone?.includes(kw)) ||
      (c.position?.toLowerCase().includes(kw)) ||
      (c.department?.toLowerCase().includes(kw))
    )
    : candidates

  const totalByStatus = STATUS_COLUMNS.reduce((acc, col) => {
    acc[col.key] = candidates.filter(c => c.status === col.key).length
    return acc
  }, {} as Record<string, number>)

  const getColumnCandidates = (status: string) =>
    filtered.filter(c => c.status === status)

  const handleDrop = async (candidateId: string, newStatus: string) => {
    try {
      await transitionCandidateStatus(candidateId, { status: newStatus, remark: '看板拖拽' })
      message.success('状态已变更')
      onRefresh()
    } catch (err: any) { message.error(err.message || '操作失败') }
    setDragOverCol(null)
  }

  return (
    <div>
      {/* 紧凑搜索栏 */}
      <div style={{ marginBottom: 6 }}>
        <Input
          size="small"
          placeholder="搜索…"
          prefix={<SearchOutlined />}
          value={searchKeyword}
          onChange={e => setSearchKeyword(e.target.value)}
          allowClear
          style={{ width: 200 }}
        />
        {kw && <span className="ml-2 text-xs text-gray-400">匹配 {filtered.length}/{candidates.length}</span>}
      </div>

      {/* 看板列 */}
      <div className="flex gap-1.5 overflow-x-auto" style={{ minHeight: 120 }}>
        {STATUS_COLUMNS.map(col => {
          const items = getColumnCandidates(col.key)
          const total = totalByStatus[col.key] || 0
          const isOver = dragOverCol === col.key
          return (
            <div
              key={col.key}
              className="flex-shrink-0 rounded-lg"
              style={{
                width: 155,
                background: 'var(--color-surface)',
                border: isOver ? `2px dashed ${col.color}` : '1px solid var(--color-hairline)',
              }}
              onDragOver={e => { e.preventDefault(); setDragOverCol(col.key) }}
              onDragLeave={() => setDragOverCol(null)}
              onDrop={e => {
                e.preventDefault()
                const candidateId = e.dataTransfer.getData('candidateId')
                if (candidateId) handleDrop(candidateId, col.key)
              }}
            >
              {/* 列头 */}
              <div className="flex items-center gap-1 px-2 py-1.5" style={{ borderBottom: `2px solid ${col.color}` }}>
                <span className="text-xs font-semibold" style={{ color: 'var(--color-charcoal)' }}>{col.label}</span>
                <span className="text-[10px] px-1 rounded-full font-semibold" style={{ background: `${col.color}18`, color: col.color }}>
                  {kw ? `${items.length}/${total}` : total}
                </span>
              </div>

              {/* 卡片列表 */}
              <div className="flex flex-col gap-0.5 p-1">
                {items.map(c => {
                  const days = daysSince(c.updated_at)
                  const isStale = days > 7
                  return (
                    <div
                      key={c.id}
                      draggable
                      onDragStart={e => { e.dataTransfer.setData('candidateId', c.id) }}
                      onClick={() => router.push(`/hr/recruitment/${c.id}`)}
                      className="cursor-pointer rounded-md px-1.5 py-1 hover:shadow-sm transition-all"
                      style={{
                        background: isStale ? '#fff5f5' : '#fff',
                        border: isStale ? '1px solid #ffccc7' : '1px solid #f0f0f0',
                      }}
                    >
                      <div className="flex items-center gap-1">
                        <HolderOutlined className="text-[10px] flex-shrink-0" style={{ color: 'var(--color-muted)', cursor: 'grab' }} />
                        <span className="text-xs font-medium truncate" style={{ color: 'var(--color-ink)' }}>{c.name}</span>
                        {isStale && <span className="text-[10px] flex-shrink-0" title={`已停留${days}天`}>⚠️{days}d</span>}
                      </div>
                      <div className="text-[10px] truncate mt-0.5" style={{ color: 'var(--color-steel)' }}>
                        {c.position || ''}{c.education ? `·${c.education}` : ''}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

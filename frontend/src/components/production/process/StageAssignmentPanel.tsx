'use client'

import { useState } from 'react'
import { Tag, App, Empty } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { UserSelect } from '@/components/shared'
import { fetchIdentityPersonnel } from '@/lib/api/identity'
import {
  fetchStageAssignments, createStageAssignment, deleteStageAssignment,
} from '@/actions/production'

import { stageColor } from '@/components/production/shared/stageColor'

interface Props {
  routeId: string
  stageNames: string[]
}

export function StageAssignmentPanel({ routeId, stageNames }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  const { data: assignmentsData } = useQuery({
    queryKey: ['production-stage-assignments', routeId],
    queryFn: async () => {
      const r = await fetchStageAssignments(routeId)
      if (!r.success) throw new Error(r.error ?? '获取失败')
      return r.data ?? []
    },
  })

  const grouped: Record<string, Array<{ id: string; user_id: string }>> = {}
  for (const a of assignmentsData ?? []) {
    grouped[a.stage_name] = grouped[a.stage_name] ?? []
    grouped[a.stage_name].push({ id: a.id, user_id: a.user_id })
  }

  const { data: personnelData } = useQuery({
    queryKey: ['identity-personnel'],
    queryFn: () => fetchIdentityPersonnel({ limit: 9999 }),
    staleTime: 5 * 60 * 1000,
  })
  const getUserName = (userId: string) =>
    personnelData?.items?.find(p => p.id === userId)?.name ?? userId.slice(0, 8)

  const handleAdd = async (stageName: string, userId: string) => {
    const result = await createStageAssignment({
      user_id: userId,
      stage_name: stageName,
      route_id: routeId,
    })
    if (result.success) {
      queryClient.invalidateQueries({ queryKey: ['production-stage-assignments', routeId] })
    } else {
      message.error(result.error ?? '分配失败')
    }
  }

  const handleRemove = async (assignmentId: string) => {
    const result = await deleteStageAssignment(assignmentId)
    if (result.success) {
      queryClient.invalidateQueries({ queryKey: ['production-stage-assignments', routeId] })
    } else {
      message.error(result.error ?? '移除失败')
    }
  }

  if (!stageNames.length) {
    return <Empty description="该路线暂无工序节点，请先编辑工艺" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <div style={{ marginTop: 16 }}>
      <h4 style={{ margin: '0 0 10px', fontSize: 13, fontWeight: 600, color: '#37352f' }}>
        工段负责人
      </h4>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 8,
        }}
      >
        {stageNames.map(stageName => {
          const assignees = grouped[stageName] ?? []
          const color = stageColor(stageName)
          return (
            <StageRow
              key={stageName}
              stageName={stageName}
              color={color}
              assignees={assignees}
              getUserName={getUserName}
              onAdd={userId => handleAdd(stageName, userId)}
              onRemove={handleRemove}
            />
          )
        })}
      </div>
    </div>
  )
}

// ── 单工段行 ──

interface StageRowProps {
  stageName: string
  color: string
  assignees: Array<{ id: string; user_id: string }>
  getUserName: (userId: string) => string
  onAdd: (userId: string) => void
  onRemove: (assignmentId: string) => void
}

function StageRow({ stageName, color, assignees, getUserName, onAdd, onRemove }: StageRowProps) {
  const [adding, setAdding] = useState(false)

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 10px',
        borderRadius: 8,
        background: '#fafaf8',
        border: '1px solid #ede9e4',
        minHeight: 32,
        flexWrap: 'wrap',
      }}
    >
      {/* 工段标签 */}
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 12,
          fontWeight: 500,
          color,
          flexShrink: 0,
          marginRight: 2,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 2,
            background: color,
            flexShrink: 0,
          }}
        />
        {stageName}
      </span>

      {/* 已分配人员 */}
      {assignees.map(a => (
        <Tag
          key={a.id}
          closable
          onClose={() => onRemove(a.id)}
          style={{
            margin: 0,
            fontSize: 12,
            borderRadius: 6,
            padding: '0 6px',
            lineHeight: '22px',
          }}
        >
          {getUserName(a.user_id)}
        </Tag>
      ))}

      {/* 添加按钮 / 选择器 */}
      {adding ? (
        <UserSelect
          size="small"
          style={{ width: 160 }}
          placeholder="选择人员"
          excludeIds={assignees.map(a => a.user_id)}
          onSelect={userId => {
            onAdd(userId)
            setAdding(false)
          }}
        />
      ) : (
        <span
          onClick={() => setAdding(true)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 22,
            height: 22,
            borderRadius: 6,
            cursor: 'pointer',
            color: '#a4a097',
            fontSize: 12,
            border: '1px dashed #d9d6d0',
            transition: 'color 0.15s, border-color 0.15s',
            flexShrink: 0,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.color = '#5645d4'
            e.currentTarget.style.borderColor = '#5645d4'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.color = '#a4a097'
            e.currentTarget.style.borderColor = '#d9d6d0'
          }}
        >
          <PlusOutlined />
        </span>
      )}
    </div>
  )
}

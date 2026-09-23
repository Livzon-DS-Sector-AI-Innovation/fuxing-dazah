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

import { stageColor, stageTint } from '@/components/production/shared/stageColor'

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
        borderRadius: 12,
        background: `linear-gradient(145deg, ${stageTint(stageName, 16)}, ${stageTint(stageName, 8)})`,
        border: `1px solid ${stageTint(stageName, 34)}`,
        boxShadow:
          'inset 0 1px 0 rgba(255,255,255,.86), 0 3px 8px -7px rgba(40,33,91,.55)',
        minHeight: 34,
        flexWrap: 'wrap',
      }}
    >
      {/* 工段标签 */}
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          fontSize: 12,
          fontWeight: 600,
          color,
          flexShrink: 0,
          marginRight: 2,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: color,
            boxShadow: `0 0 0 2px ${stageTint(stageName, 22)}`,
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
            background: 'rgba(255,255,255,.86)',
            borderColor: 'rgba(255,255,255,.9)',
            boxShadow: 'inset 0 1px 0 #fff, 0 1px 2px rgba(55,53,47,.07)',
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
            borderRadius: 7,
            cursor: 'pointer',
            color: '#787671',
            fontSize: 12,
            background: 'rgba(255,255,255,.7)',
            boxShadow: 'inset 0 1px 0 #fff, 0 1px 2px rgba(55,53,47,.08)',
            transition: 'color 0.15s, box-shadow 0.15s, background 0.15s',
            flexShrink: 0,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.color = '#5645d4'
            e.currentTarget.style.background = '#ffffff'
            e.currentTarget.style.boxShadow =
              'inset 0 1px 0 #fff, 0 0 0 2px rgba(86,69,212,.16), 0 2px 4px rgba(55,53,47,.1)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.color = '#787671'
            e.currentTarget.style.background = 'rgba(255,255,255,.7)'
            e.currentTarget.style.boxShadow = 'inset 0 1px 0 #fff, 0 1px 2px rgba(55,53,47,.08)'
          }}
        >
          <PlusOutlined />
        </span>
      )}
    </div>
  )
}

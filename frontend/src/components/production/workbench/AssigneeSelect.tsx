'use client'

import { App } from 'antd'
import { UserSelect } from '@/components/shared'
import {
  createNodeAssignment, deleteNodeAssignment, fetchNodeAssignments,
} from '@/actions/production'
import type { NodeAssigneeInfo } from '@/types/production'

interface Props {
  nodeId: string
  routeId: string
  currentAssignees: NodeAssigneeInfo[]
  onChanged: () => void
}

export function AssigneeSelect({ nodeId, routeId, currentAssignees, onChanged }: Props) {
  const { message } = App.useApp()

  const handleSelect = async (userId: string) => {
    const result = await createNodeAssignment({
      user_id: userId,
      node_id: nodeId,
      route_id: routeId,
    })
    if (result.success) {
      message.success('已指定')
      onChanged()
    } else {
      message.error(result.error ?? '指定失败')
    }
  }

  const handleDeselect = async (userId: string) => {
    const r = await fetchNodeAssignments(routeId, nodeId)
    if (r.success && r.data) {
      const assignment = r.data.find(a => a.user_id === userId)
      if (assignment) {
        const dr = await deleteNodeAssignment(assignment.id)
        if (dr.success) {
          message.success('已移除')
          onChanged()
          return
        }
      }
    }
    message.error('移除失败')
  }

  return (
    <UserSelect
      mode="multiple"
      size="small"
      style={{ minWidth: 120 }}
      placeholder="未分配"
      value={currentAssignees.map(a => a.user_id)}
      onSelect={handleSelect}
      onDeselect={handleDeselect}
    />
  )
}

'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { UserSelect } from '@/components/shared'
import { fetchIdentityPersonnel } from '@/lib/api/identity'
import {
  fetchNodeAssignments, createNodeAssignment, deleteNodeAssignment,
} from '@/actions/production'
import type { AssignedRouteInfo, NodeAssignment } from '@/types/production'

interface Props {
  routes: AssignedRouteInfo[]
  onChanged: () => void
}

export function AssigneeConfig({ routes, onChanged }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  const allRouteIds = routes.map(r => r.route_id)
  const { data: allAssignments } = useQuery({
    queryKey: ['production-all-node-assignments', ...allRouteIds],
    queryFn: async () => {
      const results = await Promise.all(allRouteIds.map(rid => fetchNodeAssignments(rid)))
      const merged: NodeAssignment[] = []
      for (const r of results) {
        if (r.success && r.data) merged.push(...r.data)
      }
      return merged
    },
  })

  const getNodeAssignee = (nodeId: string) =>
    (allAssignments ?? []).find(a => a.node_id === nodeId)

  const { data: personnelData } = useQuery({
    queryKey: ['identity-personnel'],
    queryFn: () => fetchIdentityPersonnel({ limit: 9999 }),
    staleTime: 5 * 60 * 1000,
  })
  const getPersonnelName = (userId: string) =>
    personnelData?.items?.find(p => p.id === userId)?.name ?? userId.slice(0, 8)

  const handleAssign = async (nodeId: string, routeId: string, userId: string) => {
    const existing = (allAssignments ?? []).find(a => a.node_id === nodeId)
    if (existing) await deleteNodeAssignment(existing.id)
    const r = await createNodeAssignment({ user_id: userId, node_id: nodeId, route_id: routeId })
    if (r.success) {
      queryClient.invalidateQueries({ queryKey: ['production-all-node-assignments'] })
      onChanged()
    } else {
      message.error(r.error ?? '分配失败')
    }
  }

  const handleRemove = async (assignmentId: string) => {
    const r = await deleteNodeAssignment(assignmentId)
    if (r.success) {
      queryClient.invalidateQueries({ queryKey: ['production-all-node-assignments'] })
      onChanged()
    } else {
      message.error(r.error ?? '移除失败')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {routes.map(route => (
        <div key={route.route_id} style={{
          background: '#ffffff', borderRadius: 12,
          border: '1px solid #ede9e4', overflow: 'hidden',
        }}>
          {/* 路线头部 */}
          <div style={{
            padding: '12px 18px', background: '#fafaf8',
            borderBottom: '1px solid #ede9e4',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: '#1a1a1a' }}>
              {route.product_name ?? route.route_name}
            </span>
            {route.product_name && route.route_name && (
              <span style={{ color: '#c8c4be' }}>·</span>
            )}
            <span style={{ fontSize: 13, color: '#787671' }}>
              {route.product_name ? route.route_name : ''}
              {route.route_version ? ` v${route.route_version}` : ''}
            </span>
          </div>

          {/* 表格 */}
          <div>
            {route.stages.map(stage => {
              const nodes = stage.nodes
              return (
                <div key={stage.stage_name} style={{
                  borderBottom: '1px solid #f0eeec',
                }}>
                  {nodes.map((node, ni) => {
                    const assignee = getNodeAssignee(node.node_id)
                    return (
                      <div key={node.node_id} style={{
                        display: 'flex', alignItems: 'center', gap: 16,
                        padding: '10px 18px',
                        borderBottom: ni < nodes.length - 1 ? '1px solid #f6f5f4' : 'none',
                      }}>
                        {/* 工段名（首行显示，后续行留空） */}
                        <div style={{ width: 80, flexShrink: 0 }}>
                          {ni === 0 && (
                            <span style={{
                              display: 'inline-block', padding: '2px 10px',
                              borderRadius: 4, fontSize: 12, fontWeight: 500,
                              background: '#f4f0ff', color: '#5645d4',
                            }}>
                              {stage.stage_name}
                            </span>
                          )}
                        </div>

                        {/* 工序名 */}
                        <span style={{
                          fontSize: 13, fontWeight: 500, color: '#37352f',
                          width: 120, flexShrink: 0,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {node.node_name}
                        </span>

                        {/* 当前负责人 */}
                        <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                          {assignee ? (
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: 4,
                              padding: '3px 10px', borderRadius: 4,
                              fontSize: 12, fontWeight: 500,
                              background: '#e8f8e8', color: '#1aae39',
                            }}>
                              {getPersonnelName(assignee.user_id)}
                              <span
                                onClick={() => handleRemove(assignee.id)}
                                style={{
                                  cursor: 'pointer', fontSize: 12, lineHeight: 1,
                                  color: '#1aae39', opacity: 0.6,
                                  padding: '0 2px',
                                }}
                                title="移除"
                              >
                                ×
                              </span>
                            </span>
                          ) : (
                            <span style={{ fontSize: 12, color: '#b5b1a8' }}>未设置</span>
                          )}
                        </div>

                        {/* 选择器 */}
                        <div style={{ width: 220, flexShrink: 0 }}>
                          <UserSelect
                            style={{ width: '100%' }}
                            placeholder={assignee ? '更换负责人' : '选择负责人'}
                            excludeIds={assignee ? [assignee.user_id] : []}
                            onSelect={userId => handleAssign(node.node_id, route.route_id, userId)}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

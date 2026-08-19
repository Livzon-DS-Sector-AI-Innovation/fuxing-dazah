'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { App, Button, Input } from 'antd'
import { fetchMyStageSuffixes, setStageSuffix } from '@/actions/production'
import type { AssignedRouteInfo } from '@/types/production'

interface Props {
  routes: AssignedRouteInfo[]
  onChanged: () => void
}

export function StageSuffixConfig({ routes, onChanged }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()

  const { data: suffixes, isLoading, isError } = useQuery({
    queryKey: ['production-my-stage-suffixes'],
    queryFn: async () => {
      const r = await fetchMyStageSuffixes()
      return r.success ? (r.data ?? []) : []
    },
  })

  const routeNameMap = Object.fromEntries(routes.map(r => [r.route_id, r.route_name]))

  // 本地编辑态：key = `${route_id}|${stage_name}`
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [savingKey, setSavingKey] = useState<string | null>(null)

  if (isLoading) {
    return <div style={{ color: '#787671', fontSize: 13, padding: '8px 0' }}>加载中…</div>
  }
  if (isError) {
    return <div style={{ color: '#e03131', fontSize: 13, padding: '8px 0' }}>工段尾缀加载失败，请刷新重试</div>
  }
  const items = suffixes ?? []
  if (items.length === 0) {
    return <div style={{ color: '#787671', fontSize: 13, padding: '8px 0' }}>你还没有负责的工段</div>
  }

  const handleSave = async (routeId: string, stageName: string, current: string) => {
    const key = `${routeId}|${stageName}`
    const suffix = drafts[key] !== undefined ? drafts[key] : current
    setSavingKey(key)
    const r = await setStageSuffix({ route_id: routeId, stage_name: stageName, suffix })
    setSavingKey(null)
    if (r.success) {
      message.success('尾缀已保存')
      queryClient.invalidateQueries({ queryKey: ['production-my-stage-suffixes'] })
      onChanged()
    } else {
      message.error(r.error ?? '保存失败')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 0' }}>
      <div style={{ fontSize: 12, color: '#787671' }}>
        接收批次时，第一个子批次默认批号 = 基础批号 + 工段尾缀（可修改）
      </div>
      {items.map(item => {
        const key = `${item.route_id}|${item.stage_name}`
        const value = drafts[key] !== undefined ? drafts[key] : item.suffix
        return (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ flex: 0.7, fontSize: 13 }}>
              {routeNameMap[item.route_id] ?? ''} · {item.stage_name}
            </span>
            <Input
              placeholder="尾缀（如 -F1），留空不追加"
              value={value}
              maxLength={50}
              onChange={e => setDrafts(d => ({ ...d, [key]: e.target.value }))}
              style={{ flex: 1.3, borderRadius: 8 }}
            />
            <Button
              size="small"
              loading={savingKey === key}
              onClick={() => handleSave(item.route_id, item.stage_name, item.suffix)}
              style={{ borderRadius: 8 }}
            >
              保存
            </Button>
          </div>
        )
      })}
    </div>
  )
}

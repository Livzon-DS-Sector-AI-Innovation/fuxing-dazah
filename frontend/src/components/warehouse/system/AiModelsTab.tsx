'use client'

// AI 模型 Tab：agent 主模型 / agent_backup 备用 两张可编辑卡 + 变更审计（懒展开）
// 取数：GET /warehouse/system-config/ai-models → data.profiles[]；
// 失败 → 整区 Alert + 重试；保存/开关/测试由卡内直调 Server Actions。

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Skeleton } from 'antd'

import { getWarehouseAiModels } from '@/actions/warehouse'
import type { WarehouseAiModelView } from '@/types/warehouse'
import WarehouseModelCard from './WarehouseModelCard'
import ConfigAuditSection, { type ConfigAuditHandle } from './ConfigAuditSection'
import { CARD_STYLE, UI } from './systemConfigConstants'

const PROFILE_ORDER = ['agent', 'agent_backup'] as const

export default function AiModelsTab({ canUpdate }: { canUpdate: boolean }) {
  const [views, setViews] = useState<WarehouseAiModelView[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const auditRef = useRef<ConfigAuditHandle>(null)

  const applyLoad = useCallback(
    (profiles: WarehouseAiModelView[]) => {
      setViews(profiles)
      setLoadError(null)
    },
    [],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getWarehouseAiModels()
      applyLoad(data.profiles ?? [])
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : '加载 AI 模型配置失败')
    } finally {
      setLoading(false)
    }
  }, [applyLoad])

  // 挂载拉取：setState 全部发生在异步续体中（react-hooks/set-state-in-effect）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await getWarehouseAiModels()
        if (!cancelled) applyLoad(data.profiles ?? [])
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : '加载 AI 模型配置失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [applyLoad])

  /** 保存/开关成功：重拉 GET（卡片 draft 由 view 变化重置）+ 顶刷审计 */
  const refreshAfterWrite = useCallback(() => {
    void load()
    auditRef.current?.refresh()
  }, [load])

  const viewOf = (profile: string): WarehouseAiModelView | null => {
    return views?.find((v) => v.profile === profile) ?? null
  }

  return (
    <div>
      {loading && views === null && !loadError ? (
        <div style={{ ...CARD_STYLE, padding: 16 }}>
          <Skeleton active paragraph={{ rows: 10 }} />
        </div>
      ) : loadError ? (
        <Alert
          type="error"
          showIcon
          style={{ ...CARD_STYLE, padding: 16 }}
          message={<span style={{ fontSize: 13, fontWeight: 600 }}>AI 模型配置加载失败</span>}
          description={<span style={{ fontSize: 12, color: UI.muted }}>{loadError}</span>}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 16,
            alignItems: 'stretch',
          }}
        >
          {PROFILE_ORDER.map((profile) => (
            <WarehouseModelCard
              key={profile}
              profile={profile}
              view={viewOf(profile)}
              canUpdate={canUpdate}
              onSaved={refreshAfterWrite}
              onToggled={refreshAfterWrite}
            />
          ))}
        </div>
      )}

      <ConfigAuditSection ref={auditRef} kind="ai-model" />
    </div>
  )
}

'use client'

// 配置变更审计段（三期从 AiConfigPanel「审计记录」Tab 抽出）
// 模型配置 / 场景配置改动流水（区别于 AI 调用流水），并入「AI 调用审计」Tab 顶层切换。
// 优先消费共享控制器（labels 与 refreshKey 随保存联动）；无 Provider 场景（独立挂载）降级：
// 自取一次场景 labels + refreshKey 恒 0。

import { useEffect, useState } from 'react'
import { Segmented } from 'antd'

import { fetchAiConfig } from '@/actions/safety'
import AiConfigAuditTable from '../AiConfigAuditTable'
import AiScenarioAuditTable from '../AiScenarioAuditTable'
import { useAiConfigControllerOptional } from './AiConfigController'

export default function AiConfigChangeAuditSection() {
  const ctrl = useAiConfigControllerOptional()
  const [auditKind, setAuditKind] = useState<'profile' | 'scenario'>('profile')
  const [fallbackLabels, setFallbackLabels] = useState<Record<string, string>>({})

  useEffect(() => {
    if (ctrl) {
      // 共享数据层在位：触发懒加载并联动 labels/refreshKey
      ctrl.ensure()
      return
    }
    // 无 Provider：自取一次场景 labels（仅展示映射，不参与编辑）
    let cancelled = false
    void (async () => {
      try {
        const res = await fetchAiConfig()
        if (cancelled) return
        if (res.code >= 200 && res.code < 300 && res.data) {
          const map: Record<string, string> = {}
          for (const f of res.data.functions ?? []) map[f.id] = f.label
          setFallbackLabels(map)
        }
      } catch {
        // labels 非关键数据：失败静默，审计表回退显示原始 scenario id
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ctrl])

  return (
    <div>
      {/* 审计子类：模型配置 / 场景配置 */}
      <Segmented
        options={[
          { label: '模型配置', value: 'profile' },
          { label: '场景配置', value: 'scenario' },
        ]}
        value={auditKind}
        onChange={(v) => setAuditKind(v as 'profile' | 'scenario')}
        style={{ marginBottom: 12 }}
      />
      {auditKind === 'profile' ? (
        <AiConfigAuditTable refreshKey={ctrl?.auditRefreshKey ?? 0} />
      ) : (
        <AiScenarioAuditTable
          refreshKey={ctrl?.auditRefreshKey ?? 0}
          scenarioLabels={ctrl?.scenarioLabels ?? fallbackLabels}
        />
      )}
    </div>
  )
}

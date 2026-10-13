'use client'

// 安全模块系统配置中心（design §4，三期合并单页）
// 六 Tab：AI 模型 / AI 场景 / 多维表格 / 定时任务 / 应用配置 / AI 调用审计（含配置变更审计切换）。
// ?tab= 直达对应 Tab；切换以 history.replaceState 浅同步地址栏（可分享/刷新保持，不触发服务端往返）。
// 权限：不加门禁（safety 侧无 system-config 权限码——grill 决策#1；编辑能力与合并前各页一致）。
// AiConfigProvider 包裹全部 Tab：AI 两段共享数据 + 审计段 labels/刷新键联动；懒加载（不看的 Tab 不发请求）。

import { useState } from 'react'
import { Tabs } from 'antd'
import { useSearchParams } from 'next/navigation'

import { UI } from '../schedulerConfigConstants'
import { AiConfigProvider } from '../aiConfig/AiConfigController'
import AiModelsSection from '../aiConfig/AiModelsSection'
import AiScenarioSection from '../aiConfig/AiScenarioSection'
import BitableConfigPanel from '../BitableConfigPanel'
import ScheduledTasksPanel from '../ScheduledTasksPanel'
import AppConfigPanel from '../AppConfigPanel'
import AiAuditPanel from '../AiAuditPanel'

const TAB_KEYS = ['ai-models', 'ai-scenarios', 'bitable', 'scheduler', 'app', 'ai-audits'] as const
type TabKey = (typeof TAB_KEYS)[number]

const DEFAULT_TAB: TabKey = 'ai-models'

export default function SystemConfigPanel() {
  const searchParams = useSearchParams()
  const paramTab = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState<TabKey>(
    TAB_KEYS.includes(paramTab as TabKey) ? (paramTab as TabKey) : DEFAULT_TAB,
  )

  const handleTabChange = (key: string) => {
    setActiveTab(key as TabKey)
    window.history.replaceState(null, '', `/safety/system?tab=${key}`)
  }

  return (
    <div style={{ padding: 24, maxWidth: 1280 }}>
      {/* ── 页头 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>系统配置</div>
        <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
          安全模块系统配置中心（AI 模型 / 场景路由 / 多维表格 / 定时任务 / 应用参数 / 调用审计）
        </div>
        <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>
          配置变更实时生效，无需重启
        </div>
      </div>

      <AiConfigProvider>
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          style={{ marginTop: 8 }}
          items={[
            { key: 'ai-models', label: 'AI 模型', children: <AiModelsSection /> },
            { key: 'ai-scenarios', label: 'AI 场景', children: <AiScenarioSection /> },
            { key: 'bitable', label: '多维表格', children: <BitableConfigPanel /> },
            { key: 'scheduler', label: '定时任务', children: <ScheduledTasksPanel /> },
            { key: 'app', label: '应用配置', children: <AppConfigPanel /> },
            { key: 'ai-audits', label: 'AI 调用审计', children: <AiAuditPanel /> },
          ]}
        />
      </AiConfigProvider>
    </div>
  )
}

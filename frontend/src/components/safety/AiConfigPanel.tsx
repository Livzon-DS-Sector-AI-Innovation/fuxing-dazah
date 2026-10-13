'use client'

// AI 配置中心主面板（三期 prefactor 后 = 薄组合层）
// 数据流/行内保存/审计联动全部下沉到 aiConfig/AiConfigController；
// 本面板只保留：Provider 包裹 + 页头 + 双 Tab（模型配置 = AI 模型段 + AI 场景段 / 审计记录 = 配置变更审计段）。
// 配置单页（/safety/system）合并后本壳由单页 Tab 容器替代，段组件原样复用。

import { useState } from 'react'
import { Tabs } from 'antd'

import { UI } from './schedulerConfigConstants'
import { AiConfigProvider } from './aiConfig/AiConfigController'
import AiModelsSection from './aiConfig/AiModelsSection'
import AiScenarioSection from './aiConfig/AiScenarioSection'
import AiConfigChangeAuditSection from './aiConfig/AiConfigChangeAuditSection'

export default function AiConfigPanel() {
  const [activeTab, setActiveTab] = useState('models')

  return (
    <AiConfigProvider>
      <div style={{ padding: 24, maxWidth: 1280 }}>
        {/* ── 页头 ── */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>AI 配置</div>
          <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
            安全管理模块 AI 模型与调用能力管理（保存即生效，无需重启）
          </div>
          <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>
            配置变更实时生效；飞书业务 Agent 需重启后生效
          </div>
        </div>

        {/* ── 双 Tab：模型配置 / 审计记录（审计懒挂载：首次激活才渲染） ── */}
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'models',
              label: '模型配置',
              children: (
                <div>
                  <AiModelsSection />
                  <div style={{ marginTop: 20 }}>
                    <AiScenarioSection />
                  </div>
                </div>
              ),
            },
            {
              key: 'audits',
              label: '审计记录',
              children: activeTab === 'audits' ? <AiConfigChangeAuditSection /> : null,
            },
          ]}
        />
      </div>
    </AiConfigProvider>
  )
}

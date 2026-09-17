'use client'

// 仓库系统配置中心主面板（对齐 safety/system 布局；design §10）
// 七 Tab：AI 模型 / AI 场景 / 运行参数 / 多维表格 / 定时任务 / 推送任务 / AI 调用审计。
// 权限显隐（usePermission，对齐 safety 范式）：
//   warehouse:system-config:read  → 页面可见（无权限整页 403 Alert，fail-closed）
//   warehouse:system-config:update → 编辑态（开关/保存/测试按钮可用）

import { Alert, Skeleton, Tabs } from 'antd'

import { usePermission } from '@/hooks/usePermission'
import AiModelsTab from './AiModelsTab'
import AiScenariosTab from './AiScenariosTab'
import RuntimeParamsTab from './RuntimeParamsTab'
import BitableTab from './BitableTab'
import SchedulerTasksTab from './SchedulerTasksTab'
import PushTasksTab from './PushTasksTab'
import AiCallAuditTab from './AiCallAuditTab'
import { UI } from './systemConfigConstants'

const READ_PERMISSION = 'warehouse:system-config:read'
const UPDATE_PERMISSION = 'warehouse:system-config:update'

export default function SystemConfigPanel() {
  const { hasPermission, isLoaded } = usePermission()

  if (!isLoaded) {
    return (
      <div style={{ padding: 24, maxWidth: 1280 }}>
        <Skeleton active paragraph={{ rows: 4 }} />
      </div>
    )
  }

  // fail-closed：权限加载完成且无 read 权限 → 整页 403
  if (!hasPermission(READ_PERMISSION)) {
    return (
      <div style={{ padding: 24, maxWidth: 1280 }}>
        <Alert
          type="warning"
          showIcon
          message="无权访问"
          description={
            <span style={{ fontSize: 13 }}>
              当前账号缺少 warehouse:system-config:read 权限，无法查看仓库系统配置中心。
            </span>
          }
        />
      </div>
    )
  }

  const canUpdate = hasPermission(UPDATE_PERMISSION)

  return (
    <div style={{ padding: 24, maxWidth: 1280 }}>
      {/* ── 页头 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: UI.ink }}>系统配置</div>
        <div style={{ fontSize: 13, color: UI.slate, marginTop: 2 }}>
          仓库模块系统配置中心（AI 模型 / 场景熔断 / 运行参数 / 多维表格 / 定时任务 / 调用审计）
        </div>
        <div style={{ fontSize: 12, color: UI.steel, marginTop: 4 }}>
          {canUpdate
            ? '配置变更实时生效，无需重启'
            : '只读模式：当前账号无 warehouse:system-config:update 权限'}
        </div>
      </div>

      <Tabs
        defaultActiveKey="models"
        style={{ marginTop: 8 }}
        items={[
          { key: 'models', label: 'AI 模型', children: <AiModelsTab canUpdate={canUpdate} /> },
          {
            key: 'scenarios',
            label: 'AI 场景',
            children: <AiScenariosTab canUpdate={canUpdate} />,
          },
          {
            key: 'runtime',
            label: '运行参数',
            children: <RuntimeParamsTab canUpdate={canUpdate} />,
          },
          {
            key: 'bitable',
            label: '多维表格',
            children: <BitableTab canUpdate={canUpdate} />,
          },
          {
            key: 'scheduler',
            label: '定时任务',
            children: <SchedulerTasksTab canUpdate={canUpdate} />,
          },
          {
            key: 'push',
            label: '推送任务',
            children: <PushTasksTab canUpdate={canUpdate} />,
          },
          {
            key: 'ai-audits',
            label: 'AI 调用审计',
            children: <AiCallAuditTab />,
          },
        ]}
      />
    </div>
  )
}

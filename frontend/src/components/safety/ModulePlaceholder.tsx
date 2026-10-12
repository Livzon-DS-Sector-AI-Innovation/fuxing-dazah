// 模块占位页统一组件 —— 体系要素矩阵中「未开展」模块的界面化占位。
// 展示模块定位（管什么 / Agent 怎么管）与飞书引导；模块启动建表对接后替换为正式页面。

'use client'

import { Card, Empty, Tag, Typography } from 'antd'

export interface ModulePlaceholderProps {
  /** 模块名（菜单同名，纯文字） */
  name: string
  /** 管什么：模块的体系定位与业务范围 */
  scope: string
  /** Agent 怎么管：当前 Agent 能力现状与建设方向 */
  agentStatus: string
}

const { Paragraph, Title } = Typography

export default function ModulePlaceholder({ name, scope, agentStatus }: ModulePlaceholderProps) {
  return (
    <div style={{ padding: '24px 0', maxWidth: 860 }}>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <Title level={3} style={{ margin: 0 }}>
            {name}
          </Title>
          <Tag color="default">业务未开展</Tag>
        </div>

        <Paragraph type="secondary" style={{ marginBottom: 24 }}>
          本模块为化工安全生产管理体系要素，业务尚未开展。相关操作当前在飞书多维表格中进行，
          模块启动并完成表格对接后，本页将替换为正式功能界面。
        </Paragraph>

        <Card size="small" title="管什么" style={{ marginBottom: 16 }}>
          <Paragraph style={{ margin: 0, whiteSpace: 'pre-line' }}>{scope}</Paragraph>
        </Card>

        <Card size="small" title="Agent 怎么管" style={{ marginBottom: 24 }}>
          <Paragraph style={{ margin: 0, whiteSpace: 'pre-line' }}>{agentStatus}</Paragraph>
        </Card>

        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="业务未开展 —— 请前往飞书多维表格操作"
        />
      </Card>
    </div>
  )
}

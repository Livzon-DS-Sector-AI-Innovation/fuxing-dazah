'use client'

import { DownOutlined, UpOutlined } from '@ant-design/icons'
import { Button, Space } from 'antd'
import { useState, type ReactNode } from 'react'

/**
 * 两层筛选容器（仓储 V2.0 三件套之一）：
 * common 常驻展示；advanced 折叠在"更多筛选"内，点击展开。
 */
export function QueryFilter({
  common,
  advanced,
}: {
  common: ReactNode
  advanced?: ReactNode
}) {
  const [expanded, setExpanded] = useState(false)

  if (!advanced) {
    return (
      <Space wrap style={{ marginBottom: 12 }}>
        {common}
      </Space>
    )
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <Space wrap>
        {common}
        <Button type="link" onClick={() => setExpanded(v => !v)}>
          更多筛选 {expanded ? <UpOutlined /> : <DownOutlined />}
        </Button>
      </Space>
      {expanded && (
        <div style={{ marginTop: 8 }}>
          <Space wrap>{advanced}</Space>
        </div>
      )}
    </div>
  )
}

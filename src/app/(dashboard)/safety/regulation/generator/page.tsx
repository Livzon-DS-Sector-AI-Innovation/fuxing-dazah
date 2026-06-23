'use client'

import { useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { message } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import SopGeneratorPanel from '@/components/safety/SopGeneratorPanel'
import type { OperationRegulation } from '@/types/safety'

export default function SopGeneratorPage() {
  const router = useRouter()

  const handleSopGenerated = useCallback(
    (result: {
      regulation_id: string
      meta: Record<string, string>
      content: string
    }) => {
      message.success('标准化操规生成成功！即将进入审阅编辑器')
      router.push(`/safety/regulation/generator/${result.regulation_id}`)
    },
    [router],
  )

  const handleOpenEditor = useCallback(
    (record: OperationRegulation) => {
      if (!record.content) {
        message.warning('该操规尚未生成标准化内容，请先上传旧版操规进行生成')
        return
      }
      router.push(`/safety/regulation/generator/${record.id}`)
    },
    [router],
  )

  return (
    <div style={{ padding: '24px 28px' }}>
      {/* Page Title Header */}
      <div style={{ marginBottom: 24 }}>
        <h2
          style={{
            fontSize: 22,
            fontWeight: 600,
            color: '#1a1a1a',
            margin: 0,
            marginBottom: 4,
            lineHeight: 1.3,
          }}
        >
          操规标准化生成
        </h2>
        <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
          上传旧版操规初稿 · AI自动分析工艺步骤 · 生成9章标准化安全操作规程
        </p>
      </div>

      {/* Content Card */}
      <div
        style={{
          background: '#ffffff',
          borderRadius: 12,
          border: '1px solid #e5e3df',
          padding: '24px 28px',
        }}
      >
        <SopGeneratorPanel
          onOpenEditor={handleOpenEditor}
          onGenerated={handleSopGenerated}
        />
      </div>
    </div>
  )
}

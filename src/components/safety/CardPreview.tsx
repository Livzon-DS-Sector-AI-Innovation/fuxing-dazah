'use client'

import { Card, Descriptions, Empty, Spin, Tag } from 'antd'
import type { DataSourceItem, HeaderColor } from '@/types/safety'
import { HEADER_COLOR_OPTIONS } from '@/types/safety'
import { previewCard } from '@/actions/safety'
import { useState, useEffect, useCallback } from 'react'

interface CardPreviewProps {
  dataSources: DataSourceItem[]
  cardTemplate: string
  headerColor: HeaderColor
}

export default function CardPreview({ dataSources, cardTemplate, headerColor }: CardPreviewProps) {
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<{
    markdown_preview: string
    variables: Record<string, string>
  } | null>(null)

  const doPreview = useCallback(async () => {
    if (!cardTemplate || dataSources.length === 0) {
      setPreview(null)
      return
    }
    setLoading(true)
    try {
      const res = await previewCard({ data_sources: dataSources, card_template: cardTemplate, header_color: headerColor })
      if (res.code === 200 && res.data) {
        setPreview(res.data)
      }
    } catch {
      // ignore preview errors
    } finally {
      setLoading(false)
    }
  }, [dataSources, cardTemplate, headerColor])

  useEffect(() => {
    const timer = setTimeout(doPreview, 600)
    return () => clearTimeout(timer)
  }, [doPreview])

  const colorInfo = HEADER_COLOR_OPTIONS.find((c) => c.value === headerColor)

  if (!cardTemplate || dataSources.filter((d) => d.enabled).length === 0) {
    return <Empty description="请选择数据来源并填写消息模板" />
  }

  return (
    <Spin spinning={loading}>
      <Card
        size="small"
        title={
          <span>
            预览效果{' '}
            <Tag color={colorInfo?.color}>{colorInfo?.label}</Tag>
          </span>
        }
      >
        {preview && (
          <div>
            <div
              style={{
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 8,
                whiteSpace: 'pre-wrap',
                fontFamily: 'monospace',
                fontSize: 13,
                marginBottom: 12,
              }}
            >
              {preview.markdown_preview}
            </div>
            <Descriptions size="small" column={2} title="变量值预览">
              {Object.entries(preview.variables).map(([key, val]) => (
                <Descriptions.Item key={key} label={key}>
                  <Tag>{val}</Tag>
                </Descriptions.Item>
              ))}
            </Descriptions>
          </div>
        )}
      </Card>
    </Spin>
  )
}

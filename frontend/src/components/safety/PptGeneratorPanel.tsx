'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Button,
  Select,
  Card,
  Space,
  message,
  Spin,
  Empty,
  List,
  Tag,
  Typography,
  Row,
  Col,
} from 'antd'
import {
  FilePptOutlined,
  DownloadOutlined,
  ThunderboltOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { generatePpt, getPptHistory } from '@/actions/safety'
import { fileProxyUrl } from '@/lib/file-url'
import type { GeneratePptRequest, PptGenerationRecord } from '@/types/safety'

const { Text } = Typography

const TEMPLATE_OPTIONS = [
  { value: 'training', label: '安全培训课件', desc: '适用于部门安全培训、新员工安全教育' },
  { value: 'briefing', label: '安全简报', desc: '适用于管理层汇报、安全形势分析' },
  { value: 'audit', label: '审核检查清单', desc: '适用于安全检查对照、合规性审计' },
]

const STYLE_OPTIONS = [
  { value: 'professional', label: '专业蓝白', desc: '正式严谨，适合正式场合' },
  { value: 'modern', label: '现代深色', desc: '深色背景，适合投影演示' },
  { value: 'minimal', label: '极简白底', desc: '白底黑字，适合打印分发' },
]

interface Props {
  articleId: string
  articleTitle?: string
  hasContent: boolean
}

export default function PptGeneratorPanel({
  articleId,
  articleTitle,
  hasContent,
}: Props) {
  const [template, setTemplate] = useState<string>('training')
  const [style, setStyle] = useState<string>('professional')
  const [generating, setGenerating] = useState(false)
  const [history, setHistory] = useState<PptGenerationRecord[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true)
    try {
      const res = await getPptHistory(articleId)
      if (res.code === 200 && res.data) {
        setHistory(res.data.records || [])
      }
    } catch {
      // ignore
    } finally {
      setLoadingHistory(false)
    }
  }, [articleId])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const handleGenerate = async () => {
    if (!hasContent) {
      message.warning('文档缺少正文内容，无法生成 PPT')
      return
    }
    setGenerating(true)
    try {
      const req: GeneratePptRequest = {
        template: template as GeneratePptRequest['template'],
        style: style as GeneratePptRequest['style'],
      }
      const res = await generatePpt(articleId, req)
      if (res.code === 200 && res.data) {
        message.success(res.data.message || 'PPT 生成成功')
        loadHistory()
      } else {
        message.error(res.message || 'PPT 生成失败')
      }
    } catch {
      message.error('PPT 生成失败，请稍后重试')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownload = (record: PptGenerationRecord) => {
    const url = fileProxyUrl(record.download_url)
    window.open(url, '_blank')
  }

  const getTemplateLabel = (t: string) =>
    TEMPLATE_OPTIONS.find((o) => o.value === t)?.label || t

  const getStyleLabel = (s: string) =>
    STYLE_OPTIONS.find((o) => o.value === s)?.label || s

  // Empty state (no content)
  if (!hasContent) {
    return (
      <Empty
        description={
          <span>
            该文档暂无正文内容
            <br />
            <span style={{ color: '#a4a097', fontSize: 13 }}>
              PPT 生成需要文档正文内容。请先通过 Bitable 同步解析文档全文。
            </span>
          </span>
        }
      />
    )
  }

  return (
    <div>
      {/* Generation Panel */}
      <Card
        size="small"
        title={
          <span>
            <FilePptOutlined style={{ marginRight: 8 }} />
            AI 生成 PPT
          </span>
        }
        style={{ marginBottom: 16 }}
      >
        <Row gutter={[16, 12]}>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, fontWeight: 500 }}>
              模板类型
            </div>
            <Select
              value={template}
              onChange={setTemplate}
              style={{ width: '100%' }}
              options={TEMPLATE_OPTIONS.map((o) => ({
                value: o.value,
                label: (
                  <div>
                    <div>{o.label}</div>
                    <div style={{ fontSize: 11, color: '#a4a097' }}>{o.desc}</div>
                  </div>
                ),
              }))}
            />
          </Col>
          <Col span={12}>
            <div style={{ marginBottom: 4, fontSize: 13, fontWeight: 500 }}>
              配色风格
            </div>
            <Select
              value={style}
              onChange={setStyle}
              style={{ width: '100%' }}
              options={STYLE_OPTIONS.map((o) => ({
                value: o.value,
                label: (
                  <div>
                    <div>{o.label}</div>
                    <div style={{ fontSize: 11, color: '#a4a097' }}>{o.desc}</div>
                  </div>
                ),
              }))}
            />
          </Col>
        </Row>

        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Button
            type="primary"
            size="large"
            icon={<ThunderboltOutlined />}
            loading={generating}
            onClick={handleGenerate}
          >
            生成 PPT
          </Button>
          <div style={{ marginTop: 8, color: '#a4a097', fontSize: 12 }}>
            AI 将分析文档内容，自动生成 10-20 页结构化培训课件
          </div>
        </div>
      </Card>

      {/* History */}
      <Card
        size="small"
        title={
          <span>
            <HistoryOutlined style={{ marginRight: 8 }} />
            生成历史
          </span>
        }
      >
        {loadingHistory ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : history.length === 0 ? (
          <Empty
            description="暂无生成记录"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <List
            size="small"
            dataSource={history}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="download"
                    type="link"
                    icon={<DownloadOutlined />}
                    onClick={() => handleDownload(item)}
                  >
                    下载
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <FilePptOutlined style={{ color: '#d4380d' }} />
                      <Text>{item.file_name}</Text>
                    </Space>
                  }
                  description={
                    <Space size="small">
                      <Tag>{getTemplateLabel(item.template)}</Tag>
                      <Tag>{getStyleLabel(item.style)}</Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {item.created_at
                          ? new Date(item.created_at).toLocaleString()
                          : ''}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  )
}

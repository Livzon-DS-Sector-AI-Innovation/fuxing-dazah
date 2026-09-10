'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  Drawer,
  Descriptions,
  Tag,
  Tabs,
  Timeline,
  Button,
  Spin,
  Empty,
  Typography,
  message,
} from 'antd'
import {
  FilePdfOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  FilePptOutlined,
  DownloadOutlined,
  HistoryOutlined,
  RobotOutlined,
  BarChartOutlined,
  ThunderboltOutlined,
  CalendarOutlined,
  UserOutlined,
  ApartmentOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { getKnowledgeArticle, getArticleVersions, generateSummary } from '@/actions/safety'
import { fileProxyUrl } from '@/components/safety/file-url'
import KnowledgeCardEditor from './KnowledgeCardEditor'
import InjectionPreviewModal from './InjectionPreviewModal'
import AgentUsageStats from './AgentUsageStats'
import PptGeneratorPanel from './PptGeneratorPanel'
import type { SafetyKnowledgeArticle, VersionChainItem } from '@/types/safety'
import { KNOWLEDGE_CATEGORY_OPTIONS } from '@/types/safety'
import { getCategoryStyle } from './knowledgeConstants'
import dayjs from 'dayjs'

const { Text, Paragraph } = Typography

interface Props {
  articleId: string | null
  open: boolean
  onClose: () => void
  onNewVersion?: (article: SafetyKnowledgeArticle) => void
}

export default function KnowledgeDetailDrawer({
  articleId,
  open,
  onClose,
  onNewVersion,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [article, setArticle] = useState<SafetyKnowledgeArticle | null>(null)
  const [versionChain, setVersionChain] = useState<VersionChainItem[]>([])
  const [injectionPreviewOpen, setInjectionPreviewOpen] = useState(false)
  const [generatingSummary, setGeneratingSummary] = useState(false)

  const loadArticle = useCallback(async () => {
    if (!articleId || !open) return
    setLoading(true)
    try {
      const [articleRes, versionsRes] = await Promise.all([
        getKnowledgeArticle(articleId),
        getArticleVersions(articleId),
      ])
      if (articleRes.code === 200 && articleRes.data) {
        setArticle(articleRes.data)
      }
      if (versionsRes.code === 200 && versionsRes.data) {
        setVersionChain(versionsRes.data)
      }
    } finally {
      setLoading(false)
    }
  }, [articleId, open])

  useEffect(() => {
    if (articleId && open) {
      loadArticle()
    } else {
      setArticle(null)
      setVersionChain([])
    }
  }, [articleId, open, loadArticle])

  const getCategoryLabel = (cat: string) =>
    KNOWLEDGE_CATEGORY_OPTIONS.find((o) => o.value === cat)?.label || cat

  const getStatusTag = (status: string) => {
    const map: Record<string, { color: string; label: string }> = {
      draft: { color: 'default', label: '草稿' },
      published: { color: 'green', label: '已发布' },
      archived: { color: 'default', label: '已归档' },
    }
    const s = map[status] || { color: 'default', label: status }
    return <Tag color={s.color}>{s.label}</Tag>
  }

  const handleGenerateSummary = async () => {
    if (!article) return
    setGeneratingSummary(true)
    try {
      const res = await generateSummary(article.id)
      if (res.code === 200 && res.data) {
        message.success(res.data.message || '摘要生成成功')
        loadArticle()
      } else {
        message.error(res.message || '摘要生成失败')
      }
    } catch {
      message.error('摘要生成失败')
    } finally {
      setGeneratingSummary(false)
    }
  }

  const renderSummaryTab = () => {
    if (!article?.content) {
      return (
        <Empty description="文档缺少正文内容，无法生成摘要">
          <Text type="secondary">
            摘要从文档正文中 AI 提取。请先通过 Bitable 同步解析文档全文。
          </Text>
        </Empty>
      )
    }

    return (
      <div>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 600 }}>AI 结构化摘要</span>
          <Button
            icon={<ThunderboltOutlined />}
            loading={generatingSummary}
            onClick={handleGenerateSummary}
          >
            {article.summary ? '重新生成' : '生成摘要'}
          </Button>
        </div>

        {article.summary ? (
          <Paragraph
            style={{
              whiteSpace: 'pre-wrap',
              padding: '14px 16px',
              backgroundColor: '#fafaf9',
              borderRadius: 8,
              border: '1px solid #e5e3df',
              fontSize: 14,
              lineHeight: 1.6,
              color: '#37352f',
            }}
          >
            {article.summary}
          </Paragraph>
        ) : (
          <Empty description="尚未生成摘要">
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={generatingSummary}
              onClick={handleGenerateSummary}
            >
              AI 生成摘要
            </Button>
          </Empty>
        )}
      </div>
    )
  }

  const renderAttachmentPreview = () => {
    if (!article?.attachment_path) {
      return <Empty description="暂无附件" />
    }

    const url = fileProxyUrl(article.attachment_path)
    const ext = article.attachment_path.split('.').pop()?.toLowerCase()
    const name = article.attachment_original_name || '附件'

    if (ext === 'pdf') {
      return (
        <div>
          <div style={{ marginBottom: 8 }}>
            <Button
              icon={<DownloadOutlined />}
              href={url}
              target="_blank"
              size="small"
            >
              下载 {name}
            </Button>
          </div>
          <iframe
            src={url}
            loading="lazy"
            style={{ width: '100%', height: 500, border: '1px solid #e5e3df', borderRadius: 8 }}
            title={name}
          />
        </div>
      )
    }

    if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext || '')) {
      return (
        <div style={{ textAlign: 'center' }}>
          <img src={url} alt={name} loading="lazy" style={{ maxWidth: '100%', maxHeight: 500 }} />
        </div>
      )
    }

    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        {ext === 'docx' || ext === 'doc' ? (
          <FileTextOutlined style={{ fontSize: 48, color: '#a4a097' }} />
        ) : ext === 'xlsx' || ext === 'xls' ? (
          <FileExcelOutlined style={{ fontSize: 48, color: '#a4a097' }} />
        ) : (
          <FilePdfOutlined style={{ fontSize: 48, color: '#a4a097' }} />
        )}
        <p style={{ marginTop: 12 }}>
          <Text type="secondary">{name}</Text>
        </p>
        <Button icon={<DownloadOutlined />} href={url} target="_blank">
          下载文件
        </Button>
      </div>
    )
  }

  const renderVersionHistory = () => {
    if (versionChain.length === 0) {
      return (
        <Empty description="暂无版本历史">
          {article && (
            <Timeline
              items={[
                {
                  color: 'green',
                  children: (
                    <div>
                      <Text strong>v{article.version}（当前版本）</Text>
                      <br />
                      <Text type="secondary">
                        {dayjs(article.created_at).format('YYYY-MM-DD HH:mm')}
                      </Text>
                    </div>
                  ),
                },
              ]}
            />
          )}
        </Empty>
      )
    }

    return (
      <Timeline
        items={versionChain.map((v) => ({
          color: v.is_current ? 'green' : 'gray',
          children: (
            <div>
              <Text strong={v.is_current}>
                v{v.version} {v.is_current ? '（当前版本）' : ''}
              </Text>
              <br />
              <Text>{v.title}</Text>
              <br />
              <Text type="secondary">
                {getStatusTag(v.status)}
                {' · '}
                {dayjs(v.created_at).format('YYYY-MM-DD HH:mm')}
              </Text>
            </div>
          ),
        }))}
      />
    )
  }

  const renderFullContent = () => {
    if (!article?.content) {
      return (
        <Empty description="该文档暂无全文内容">
          <Text type="secondary">
            文档全文在 Bitable 附件解析或智能导入时自动提取。
            如果文档在 Bitable 中有附件且已同步，请在详情中查看附件预览。
          </Text>
        </Empty>
      )
    }

    return (
      <Paragraph
        style={{
          whiteSpace: 'pre-wrap',
          maxHeight: 500,
          overflow: 'auto',
          padding: '14px 16px',
          backgroundColor: '#fafaf9',
          borderRadius: 8,
          border: '1px solid #e5e3df',
          fontSize: 14,
          lineHeight: 1.6,
          color: '#37352f',
        }}
      >
        {article.content}
      </Paragraph>
    )
  }

  // ── 详情概览头部 ──
  const renderOverview = () => {
    if (!article) return null
    const style = getCategoryStyle(article.tags, article.category)
    const meta = [
      { icon: <FileTextOutlined />, label: '编号', value: article.article_no || '自动生成' },
      { icon: <ApartmentOutlined />, label: '来源', value: article.source || '-' },
      { icon: <CalendarOutlined />, label: '发布', value: article.publish_date ? dayjs(article.publish_date).format('YYYY-MM-DD') : '-' },
      { icon: <UserOutlined />, label: '作者', value: article.author || '-' },
      { icon: <EyeOutlined />, label: '浏览', value: String(article.view_count || 0) },
    ]
    return (
      <div
        style={{
          display: 'flex',
          gap: 14,
          padding: 16,
          background: 'var(--color-surface-soft, #fafaf9)',
          border: '1px solid var(--color-hairline-soft, #ede9e4)',
          borderRadius: 12,
          marginBottom: 16,
          flexWrap: 'wrap',
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: style.bg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 24,
            flexShrink: 0,
          }}
        >
          {style.emoji}
        </div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--color-ink, #1a1a1a)',
              lineHeight: 1.4,
              marginBottom: 6,
            }}
          >
            {article.title}
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
            {getStatusTag(article.status)}
            <Tag color="purple">v{article.version}</Tag>
            <Tag>{getCategoryLabel(article.category)}</Tag>
          </div>
          <div
            style={{
              display: 'flex',
              gap: 16,
              flexWrap: 'wrap',
              color: 'var(--color-steel, #787671)',
              fontSize: 12,
            }}
          >
            {meta.map((m) => (
              <span key={m.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: 11 }}>{m.icon}</span>
                <span style={{ color: 'var(--color-stone, #a4a097)' }}>{m.label}</span>
                <span style={{ color: 'var(--color-charcoal, #37352f)', fontWeight: 500 }}>
                  {m.value}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // ── 基本信息（完整元数据） ──
  const renderBasicInfo = () => {
    if (!article) return null
    return (
      <div>
        {/* 摘要突出块 */}
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              marginBottom: 8,
              color: 'var(--color-ink, #1a1a1a)',
            }}
          >
            摘要
          </div>
          {article.summary ? (
            <div
              style={{
                whiteSpace: 'pre-wrap',
                padding: '12px 14px',
                backgroundColor: 'var(--color-surface-soft, #fafaf9)',
                borderRadius: 8,
                border: '1px solid var(--color-hairline-soft, #ede9e4)',
                fontSize: 14,
                lineHeight: 1.6,
                color: 'var(--color-charcoal, #37352f)',
                maxHeight: 180,
                overflow: 'auto',
              }}
            >
              {article.summary}
            </div>
          ) : (
            <span style={{ color: 'var(--color-stone, #a4a097)', fontSize: 13 }}>
              暂无摘要，可在「摘要」标签页点击 AI 生成
            </span>
          )}
        </div>

        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="文档编号">
            {article.article_no || '自动生成'}
          </Descriptions.Item>
          <Descriptions.Item label="版本">
            <Tag>v{article.version}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="分类">
            <Tag>{getCategoryLabel(article.category)}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            {getStatusTag(article.status)}
          </Descriptions.Item>
          <Descriptions.Item label="来源">
            {article.source || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="作者/发布单位">
            {article.author || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="发布日期">
            {article.publish_date
              ? dayjs(article.publish_date).format('YYYY-MM-DD')
              : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="浏览次数">
            {article.view_count}
          </Descriptions.Item>
          <Descriptions.Item label="标签" span={2}>
            {article.tags || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="附件">
            {article.attachment_original_name || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(article.created_at).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {article.notes || '-'}
          </Descriptions.Item>
        </Descriptions>
      </div>
    )
  }

  return (
    <>
      <Drawer
        title={article?.title || '文档详情'}
        open={open}
        onClose={onClose}
        size={800}
        loading={loading}
        styles={{
          header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
          body: { padding: '24px' },
        }}
        extra={
          article?.status === 'published' && onNewVersion ? (
            <Button
              type="primary"
              ghost
              icon={<HistoryOutlined />}
              onClick={() => onNewVersion(article)}
            >
              新建版本
            </Button>
          ) : undefined
        }
      >
        {loading ? (
          <div style={{ textAlign: 'center', padding: 80 }}>
            <Spin size="large" />
          </div>
        ) : article ? (
          <Tabs
            defaultActiveKey="basic"
            items={[
              {
                key: 'basic',
                label: '基本信息',
                children: (
                  <div>
                    {renderOverview()}
                    {renderBasicInfo()}
                  </div>
                ),
              },
              {
                key: 'content',
                label: '全文内容',
                children: renderFullContent(),
              },
              {
                key: 'card',
                label: (
                  <span>
                    <RobotOutlined /> 知识卡片
                  </span>
                ),
                children: (
                  <KnowledgeCardEditor
                    article={article}
                    onRefresh={loadArticle}
                    onPreviewInjection={() => setInjectionPreviewOpen(true)}
                  />
                ),
              },
              {
                key: 'stats',
                label: (
                  <span>
                    <BarChartOutlined /> Agent 统计
                  </span>
                ),
                children: <AgentUsageStats articleId={article.id} />,
              },
              {
                key: 'summary',
                label: (
                  <span>
                    <FileTextOutlined /> 摘要
                  </span>
                ),
                children: renderSummaryTab(),
              },
              {
                key: 'ppt',
                label: (
                  <span>
                    <FilePptOutlined /> 生成PPT
                  </span>
                ),
                children: (
                  <PptGeneratorPanel
                    articleId={article.id}
                    articleTitle={article.title}
                    hasContent={!!article.content}
                  />
                ),
              },
              {
                key: 'attachment',
                label: '附件预览',
                children: renderAttachmentPreview(),
              },
              {
                key: 'versions',
                label: '版本历史',
                children: renderVersionHistory(),
              },
            ]}
          />
        ) : (
          <Empty description="文档不存在" />
        )}
      </Drawer>

      <InjectionPreviewModal
        article={article}
        open={injectionPreviewOpen}
        onClose={() => setInjectionPreviewOpen(false)}
      />
    </>
  )
}

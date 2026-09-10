'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Empty, Modal, Spin, Tag } from 'antd'
import { CopyOutlined, LinkOutlined } from '@ant-design/icons'
import { getDrillDocuments } from '@/actions/safety'
import type { DrillDocument } from '@/types/safety'
import { T } from './emergencyDrillConstants'

interface Props {
  open: boolean
  recordId: string
  onClose: () => void
}

export default function DrillDocumentModal({ open, recordId, onClose }: Props) {
  const { message } = App.useApp()
  const [docs, setDocs] = useState<DrillDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<DrillDocument | null>(null)

  const loadDocs = useCallback(async () => {
    if (!recordId) return
    setLoading(true)
    try {
      const res = await getDrillDocuments(recordId)
      if (res.code === 200 && res.data) {
        setDocs(res.data)
        if (res.data.length > 0) setSelected(res.data[0])
      }
    } catch { message.error('加载文档失败') }
    finally { setLoading(false) }
  }, [recordId, message])

  useEffect(() => { if (open) loadDocs() }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const sections = selected?.content_json?.sections as Array<{ heading: string; content: string }> | undefined

  const handleCopy = () => {
    if (!selected) return
    const parts: string[] = []
    const summary = (selected.content_json as Record<string, string>)?.summary
    if (summary) { parts.push(summary); parts.push('') }
    if (sections) {
      for (const sec of sections) {
        parts.push(`${sec.heading}\n${sec.content}`)
        parts.push('')
      }
    }
    if (selected.cited_regulations?.length) {
      parts.push('引用法规：')
      for (const r of selected.cited_regulations) {
        parts.push(`— ${r.title}${r.article ? ` · ${r.article}` : ''}`)
      }
    }
    navigator.clipboard.writeText(parts.join('\n')).then(
      () => message.success('已复制全文到剪贴板'),
      () => message.error('复制失败'),
    )
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingRight: 40 }}>
          <span>{selected?.title || 'AI 演练方案'}</span>
          {selected && (
            <div style={{ display: 'flex', gap: 8 }}>
              {selected.feishu_doc_url && (
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<LinkOutlined />}
                  onClick={() => window.open(selected.feishu_doc_url, '_blank')}
                  style={{ fontSize: 12 }}
                >
                  在飞书中打开
                </Button>
              )}
              <Button size="small" icon={<CopyOutlined />} onClick={handleCopy}
                style={{ fontSize: 12 }}>
                复制全文
              </Button>
            </div>
          )}
        </div>
      }
      width={800}
      footer={null}
      styles={{ body: { padding: '16px 24px', maxHeight: '70vh', overflow: 'auto' } }}
    >
      <Spin spinning={loading}>
        {!selected ? (
          <Empty description="暂无方案文档，请先生成" />
        ) : (
          <>
            {(selected.content_json as Record<string, string>)?.summary && (
              <div style={{
                fontSize: 13, color: '#5d5b54', lineHeight: 1.7,
                padding: '12px 16px', background: T.lavender, borderRadius: 8, marginBottom: 20,
              }}>
                {(selected.content_json as Record<string, string>).summary}
              </div>
            )}

            {sections?.map((sec, i) => (
              <div key={i} style={{ marginBottom: 24 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600, color: '#1a1a1a', marginBottom: 8 }}>
                  {sec.heading}
                </h3>
                <div style={{ fontSize: 14, color: '#37352f', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  {sec.content}
                </div>
              </div>
            ))}

            {/* 引用法规 */}
            {selected.cited_regulations && selected.cited_regulations.length > 0 && (
              <div style={{ marginTop: 24, padding: '12px 16px', background: '#f6f5f4', borderRadius: 8 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#5d5b54', marginBottom: 8 }}>引用法规</div>
                {selected.cited_regulations.map((r, i) => (
                  <Tag key={i} style={{ marginBottom: 4 }}>
                    {r.title}{r.article ? ` · ${r.article}` : ''}
                  </Tag>
                ))}
              </div>
            )}

            {/* 飞书文档状态 */}
            {selected.feishu_doc_status && (
              <div style={{ marginTop: 16, fontSize: 12, color: '#787671' }}>
                <Tag color={selected.feishu_doc_status === 'created' ? 'green' : selected.feishu_doc_status === 'failed' ? 'red' : 'default'}>
                  {selected.feishu_doc_status === 'created' ? '飞书文档已就绪' :
                   selected.feishu_doc_status === 'failed' ? '飞书文档同步失败' :
                   `飞书文档: ${selected.feishu_doc_status}`}
                </Tag>
              </div>
            )}

            {/* 版本切换 */}
            {docs.length > 1 && (
              <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: '#787671' }}>历史版本：</span>
                {docs.map((d) => (
                  <Tag
                    key={d.id}
                    style={{ cursor: 'pointer' }}
                    color={d.id === selected.id ? T.primary : undefined}
                    onClick={() => setSelected(d)}
                  >
                    v{d.version}
                  </Tag>
                ))}
              </div>
            )}
          </>
        )}
      </Spin>
    </Modal>
  )
}

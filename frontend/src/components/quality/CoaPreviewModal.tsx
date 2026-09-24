'use client'

import { useEffect, useState } from 'react'
import { Modal, Spin, Result, Button } from 'antd'
import { downloadReportFile } from '@/actions/quality'

interface Props {
  open: boolean
  reportId: string | null
  title?: string
  onClose: () => void
}

const PREVIEW_STYLE = `
  body { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; color: #333; padding: 16px 20px; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; }
  td, th { border: 1px solid #999; padding: 6px 10px; font-size: 13px; vertical-align: top; }
  p { margin: 6px 0; font-size: 14px; }
  h1, h2, h3 { font-size: 16px; text-align: center; margin: 8px 0; }
`

/** 报告单在线预览：下载 docx → mammoth 转 HTML → iframe 渲染（下载端点已鉴权，走 Server Action）。 */
export default function CoaPreviewModal({ open, reportId, title, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [html, setHtml] = useState('')

  useEffect(() => {
    if (!open || !reportId) return
    let cancelled = false
    ;(async () => {
      // 状态重置放在异步函数内，避免 effect 体内同步 setState
      setLoading(true)
      setError('')
      setHtml('')
      try {
        const blob = await downloadReportFile(reportId)
        // 动态导入 mammoth（体积较大，仅预览时加载）
        const mammoth = (await import('mammoth')).default
        const result = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() })
        if (!cancelled) setHtml(result.value)
      } catch {
        if (!cancelled) setError('预览加载失败，请重试或下载查看')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, reportId])

  return (
    <Modal
      title={title || '报告单预览'}
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={960}
      destroyOnClose
    >
      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin tip="正在生成预览…" />
        </div>
      )}
      {!loading && error && (
        <Result status="warning" title={error} extra={<Button type="primary" onClick={onClose}>关闭</Button>} />
      )}
      {!loading && !error && html && (
        <iframe
          title="coa-preview"
          srcDoc={`<!doctype html><html><head><style>${PREVIEW_STYLE}</style></head><body>${html}</body></html>`}
          style={{ width: '100%', height: '70vh', border: '1px solid #eee', borderRadius: 4 }}
        />
      )}
    </Modal>
  )
}

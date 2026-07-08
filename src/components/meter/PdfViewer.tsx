'use client'

import { useState } from 'react'
import { Button, Spin } from 'antd'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { Document, Page, pdfjs } from 'react-pdf'

pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs'

interface Props {
  url: string
}

export default function PdfViewer({ url }: Props) {
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [loadError, setLoadError] = useState(false)

  if (loadError) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400, color: '#999' }}>
      PDF 加载失败，请尝试下载后查看
    </div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginBottom: 12 }}>
        <Button icon={<LeftOutlined />} disabled={pageNumber <= 1} onClick={() => setPageNumber(p => Math.max(1, p - 1))} />
        <span>第 {pageNumber} / {numPages || '?'} 页</span>
        <Button icon={<RightOutlined />} disabled={pageNumber >= numPages} onClick={() => setPageNumber(p => Math.min(numPages, p + 1))} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', minHeight: 400 }}>
        <Document
          file={url}
          onLoadSuccess={({ numPages: n }: { numPages: number }) => setNumPages(n)}
          onLoadError={() => setLoadError(true)}
          loading={<Spin description="加载中..." />}
        >
          <Page pageNumber={pageNumber} renderTextLayer={false} renderAnnotationLayer={false} />
        </Document>
      </div>
    </div>
  )
}

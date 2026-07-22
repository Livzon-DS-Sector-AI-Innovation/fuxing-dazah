'use client'

interface Props {
  url: string
}

export default function PdfViewer({ url }: Props) {
  return (
    <iframe
      src={url}
      style={{ width: '100%', height: 600, border: 'none' }}
      title="PDF 预览"
    />
  )
}

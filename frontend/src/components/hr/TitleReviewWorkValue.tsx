'use client'

import { useState } from 'react'
import { Image } from 'antd'

/** 审批表单图片证明栏目（值为「文件名 链接」逐行文本）。
    附件列用户实际配置也是图片形式，一并按图片缩略图渲染。 */
const IMAGE_EVIDENCE_KEYS = new Set([
  '外部专业技术职称证书等证明材料上传',
  '证明材料上传（图片）',
  '参加过两项以上本专业或相关专业技术工作、技术管理，技术服务工作的业绩证明材料',
  '两项以上担任项目技术负责人的业绩证明材料',
  '职称评审申报表',
  '业绩成果证明材料',
  '论文论著专利',
  '外部职称证书',
])

interface Props {
  name: string
  value: string
}

/** 图片证据行：缩略图内嵌展示，点击放大预览（灯箱，不触发下载）；加载失败退化为文字 */
function ImageEvidenceLine({ label, url }: { label: string; url: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <span className="block text-[var(--color-steel)]">
        {label || '图片'}（链接已失效，请以飞书审批附件为准）
      </span>
    )
  }
  // 本地转存路径（/uploads/...）拼上后端地址；飞书远程链接直接用
  const src = url.startsWith('/')
    ? `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}${url}`
    : url
  return (
    <div className="block">
      <Image
        src={src}
        alt={label || '图片'}
        width="100%"
        style={{
          maxHeight: 240,
          objectFit: 'contain',
          borderRadius: 6,
          border: '1px solid var(--color-hairline)',
          cursor: 'zoom-in',
        }}
        onError={() => setFailed(true)}
      />
    </div>
  )
}

/** 业绩陈述值：图片证据栏目缩略图在线查看（点击放大），其余保留换行文本 */
export default function TitleReviewWorkValue({ name, value }: Props) {
  if (!IMAGE_EVIDENCE_KEYS.has(name)) {
    return <span className="whitespace-pre-line">{value}</span>
  }
  return (
    <span className="block space-y-2">
      {value.split('\n').filter(Boolean).map((line, i) => {
        const trimmed = line.trim()
        const isLocal = trimmed.startsWith('/uploads/')
        const idx = trimmed.lastIndexOf('http')
        if (isLocal || idx >= 0) {
          const url = isLocal ? trimmed : trimmed.slice(idx)
          const label = !isLocal && idx > 0 ? trimmed.slice(0, idx).trim() : ''
          return <ImageEvidenceLine key={i} label={label} url={url} />
        }
        return <span key={i} className="block whitespace-pre-line">{line}</span>
      })}
    </span>
  )
}

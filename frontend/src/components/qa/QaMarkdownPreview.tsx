'use client'

import type { UrlTransform } from 'react-markdown'
import Markdown from 'react-markdown'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { qaDocumentArtifactContentUrl } from '@/lib/api/qa'
import type { QaDocumentArtifact } from '@/types/qa'

interface QaMarkdownPreviewProps {
  content: string
  fileId: string
  artifact: QaDocumentArtifact
  artifacts: QaDocumentArtifact[]
}

function normalizePath(value: string): string {
  const parts: string[] = []
  for (const part of value.replaceAll('\\', '/').split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      parts.pop()
      continue
    }
    parts.push(part)
  }
  return parts.join('/')
}

function resolveAssetName(markdownName: string, markdownSource: string, artifacts: QaDocumentArtifact[]): string | null {
  let decoded = markdownName
  try {
    decoded = decodeURIComponent(markdownName)
  } catch {
    // 保留原始路径，后续按文件名匹配。
  }
  decoded = decoded.split(/[?#]/, 1)[0]
  const sourceDir = normalizePath(markdownSource).split('/').slice(0, -1).join('/')
  const candidates = [
    normalizePath(decoded),
    normalizePath(`${sourceDir}/${decoded}`),
  ].filter(Boolean)
  const match = artifacts.find((item) => {
    const name = normalizePath(item.source_name)
    return candidates.some((candidate) => name === candidate || name.endsWith(`/${candidate}`))
  })
  return match?.id || null
}

/**
 * MinerU 的 full.md 可能引用 ZIP 内的图片，也可能包含 HTML 表格。
 * 只允许通过已登记的产物 ID 回读图片，Markdown HTML 经过 sanitize 后再渲染。
 */
export function QaMarkdownPreview({ content, fileId, artifact, artifacts }: QaMarkdownPreviewProps) {
  const urlTransform: UrlTransform = (url) => {
    const assetId = resolveAssetName(url, artifact.source_name, artifacts)
    return assetId ? qaDocumentArtifactContentUrl(fileId, assetId) : url
  }

  return (
    <div
      className={[
        'space-y-2 text-[13px] leading-relaxed text-[var(--color-slate)]',
        '[&_h1]:mt-5 [&_h1]:mb-2 [&_h1]:text-[18px] [&_h1]:font-semibold [&_h1]:text-[var(--color-charcoal)]',
        '[&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-[16px] [&_h2]:font-semibold [&_h2]:text-[var(--color-charcoal)]',
        '[&_h3]:mt-4 [&_h3]:mb-1 [&_h3]:text-[14px] [&_h3]:font-semibold [&_h3]:text-[var(--color-charcoal)]',
        '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5',
        '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5',
        '[&_li]:my-0.5',
        '[&_p]:my-1',
        '[&_strong]:font-semibold [&_strong]:text-[var(--color-charcoal)]',
        '[&_a]:text-[var(--color-primary)] [&_a]:underline',
        '[&_code]:rounded [&_code]:bg-[var(--color-surface)] [&_code]:px-1 [&_code]:text-[12px]',
        '[&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-[var(--color-surface)] [&_pre]:p-3',
        '[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-[12px]',
        '[&_th]:border [&_th]:border-[var(--color-hairline)] [&_th]:bg-[var(--color-surface)] [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-medium [&_th]:text-[var(--color-charcoal)]',
        '[&_td]:border [&_td]:border-[var(--color-hairline-soft)] [&_td]:px-2 [&_td]:py-1',
        '[&_img]:max-w-full [&_img]:rounded [&_img]:border [&_img]:border-[var(--color-hairline)]',
      ].join(' ')}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        urlTransform={urlTransform}
      >
        {content}
      </Markdown>
    </div>
  )
}

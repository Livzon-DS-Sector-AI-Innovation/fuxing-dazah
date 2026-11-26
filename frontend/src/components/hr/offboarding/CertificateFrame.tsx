'use client'

// 证明版式预览：用沙箱 iframe 承载后端生成的整页 HTML。
// 那段 HTML 自带 <style>（body / .title / .center 等通用规则），直接注入页面会污染全局样式；
// iframe 把样式隔离开，sandbox="" 同时禁掉脚本。按 A4 宽度渲染后整体缩放到容器宽度，手机上也能看全。

import { useEffect, useRef, useState } from 'react'

const A4_WIDTH = 794 // A4 宽 @ 96dpi
const A4_HEIGHT = 1123

export default function CertificateFrame({
  html,
  height = A4_HEIGHT,
  title = '解除劳动关系证明',
}: {
  html: string
  /** 文档高度（px）；两联版传 2 倍 */
  height?: number
  title?: string
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const update = () => setScale(Math.min(1, wrap.clientWidth / A4_WIDTH))
    update()
    const observer = new ResizeObserver(update)
    observer.observe(wrap)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={wrapRef}
      className="overflow-hidden rounded-[var(--rounded-md)] border border-[var(--color-hairline)] bg-[var(--color-canvas)]"
    >
      <div style={{ height: Math.round(height * scale) }}>
        <iframe
          title={title}
          srcDoc={html}
          sandbox=""
          style={{
            display: 'block',
            width: A4_WIDTH,
            height,
            border: 0,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        />
      </div>
    </div>
  )
}

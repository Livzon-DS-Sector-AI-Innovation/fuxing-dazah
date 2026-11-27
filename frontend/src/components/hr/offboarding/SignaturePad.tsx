'use client'

// 手写签名板：pointer 事件（触屏 / 鼠标 / 触控笔通用），自研不引依赖。
// 导出白底 PNG dataURL（透明底归档后看不见）；笔画用二次贝塞尔中点法做平滑。
// 画布尺寸随容器宽度变化（横竖屏切换、分屏）：每笔写完留一张笔迹快照，尺寸变化后
// 把快照按新宽度铺回去，不让已经写好的签名丢掉。

import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { Button } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

export default function SignaturePad({
  onChange,
  height = 200,
}: {
  /** 每次抬笔给出最新签名图；清空或画布重置时给 null */
  onChange: (dataUrl: string | null) => void
  height?: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const drawing = useRef(false)
  const last = useRef<{ x: number; y: number } | null>(null)
  /** 上一段曲线的终点（中点）：下一段从这里接着画，笔画才连续 */
  const lastMid = useRef<{ x: number; y: number } | null>(null)
  const cssWidth = useRef(0)
  /** 最近一次笔迹的位图快照（按设备像素比保存）；清除后为 null */
  const inkSnapshot = useRef<HTMLCanvasElement | null>(null)
  const [hasInk, setHasInk] = useState(false)
  const [writing, setWriting] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    let width = 0

    const setup = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 3)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, width, height)
      ctx.lineWidth = 2.4
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.strokeStyle = '#111'
    }

    const resize = () => {
      const next = wrap.clientWidth
      // 宽度为 0（标签页切到后台 / 最小化）是瞬时状态，不处理，等恢复到有宽度再说
      if (!next || next === width) return
      width = next
      cssWidth.current = next
      setup()
      // 已经写过字：把笔迹按新宽度铺回去（等比拉伸到新画布）
      if (inkSnapshot.current) {
        canvas.getContext("2d")?.drawImage(inkSnapshot.current, 0, 0, width, height)
      }
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(wrap)
    return () => observer.disconnect()
  }, [height, onChange])

  const point = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  const onDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    // 指针捕获让手指滑出画布也能继续跟踪；个别环境会抛异常（触控笔已抬起等），
    // 失败就不捕获，不能因此中断整次书写
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      // 忽略：降级为不捕获
    }
    const start = point(e)
    drawing.current = true
    last.current = start
    lastMid.current = start
    setWriting(true)
    // 落笔即留点：只点一下不滑动也要有笔迹
    const ctx = e.currentTarget.getContext('2d')
    if (ctx && last.current) {
      ctx.beginPath()
      ctx.arc(last.current.x, last.current.y, ctx.lineWidth / 2, 0, Math.PI * 2)
      ctx.fillStyle = ctx.strokeStyle
      ctx.fill()
    }
  }

  const onMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return
    e.preventDefault()
    const ctx = e.currentTarget.getContext('2d')
    const from = last.current
    const to = point(e)
    const mid = lastMid.current
    if (!ctx || !from || !mid) return
    // 中点法：以当前采样点为控制点，从上一个中点画到下一个中点。
    // 每段必须从上一段的终点接上，否则相邻两段之间会留半段空隙（笔迹呈虚线）
    const next = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 }
    ctx.beginPath()
    ctx.moveTo(mid.x, mid.y)
    ctx.quadraticCurveTo(from.x, from.y, next.x, next.y)
    ctx.stroke()
    last.current = to
    lastMid.current = next
  }

  const onUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return
    drawing.current = false
    last.current = null
    lastMid.current = null
    setWriting(false)
    setHasInk(true)
    onChange(e.currentTarget.toDataURL('image/png'))
    // 留快照：之后画布因尺寸变化重建时据此还原笔迹
    const source = e.currentTarget
    const copy = document.createElement('canvas')
    copy.width = source.width
    copy.height = source.height
    copy.getContext('2d')?.drawImage(source, 0, 0)
    inkSnapshot.current = copy
  }

  const clear = () => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.restore()
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, cssWidth.current, height)
    inkSnapshot.current = null
    setHasInk(false)
    onChange(null)
  }

  return (
    <div className="rounded-[var(--rounded-md)] border border-[var(--color-hairline-strong)] bg-[var(--color-canvas)]">
      <div className="flex items-center justify-between border-b border-[var(--color-hairline)] px-3 py-1.5">
        <span className="text-[12px] text-[var(--color-steel)]">
          {writing ? '书写中…' : '请用手指或触控笔在下方签名'}
        </span>
        <Button size="small" type="text" icon={<DeleteOutlined />} disabled={!hasInk} onClick={clear}>
          清除重签
        </Button>
      </div>
      <div ref={wrapRef} className="relative">
        <canvas
          ref={canvasRef}
          className="block w-full cursor-crosshair"
          style={{ height, touchAction: 'none' }}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
        />
        {!hasInk && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[28px] font-medium tracking-[0.3em] text-[var(--color-muted)]">
            手写签名
          </div>
        )}
      </div>
    </div>
  )
}

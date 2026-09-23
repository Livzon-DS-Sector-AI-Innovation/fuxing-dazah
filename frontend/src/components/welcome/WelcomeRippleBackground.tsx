'use client'

import { useEffect, useRef, type RefObject } from 'react'
import styles from './WelcomeRippleBackground.module.css'

const COLOR_IMAGE_SRC = '/images/welcome/apsaras-color.png'
const COLOR_IMAGE_WIDTH = 1954
const COLOR_IMAGE_HEIGHT = 805
const INITIAL_RADIUS = 8
const MAX_RADIUS = 132
const RADIUS_VARIATION = 0.45
const DOT_LIFETIME = 560
const STAMP_STEP = 12
const MAX_STAMPS = 160

type InkStamp = {
  x: number
  y: number
  born: number
  seed: number
  maxRadius: number
}

type ImageRect = {
  x: number
  y: number
  width: number
  height: number
}

/** 在浅色浮雕底图上，沿鼠标轨迹显现彩色浮雕图。 */
export function WelcomeRippleBackground({
  interactionRef,
}: {
  interactionRef: RefObject<HTMLDivElement | null>
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const root = rootRef.current
    const interaction = interactionRef.current
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!root || !interaction || !canvas || !context) return

    const maskCanvas = document.createElement('canvas')
    const maskContext = maskCanvas.getContext('2d')
    if (!maskContext) return

    const motionMedia = window.matchMedia('(hover: hover) and (prefers-reduced-motion: no-preference)')
    const colorImage = new Image()
    colorImage.decoding = 'async'

    const stamps: InkStamp[] = []
    const imageRect: ImageRect = { x: 0, y: 0, width: 0, height: 0 }
    let width = 0
    let height = 0
    let dpr = 1
    let colorImageReady = false
    let lastX: number | null = null
    let lastY: number | null = null
    let animationFrame = 0
    let running = false

    const clearCanvas = () => {
      context.globalCompositeOperation = 'source-over'
      context.clearRect(0, 0, width, height)
      maskContext.globalCompositeOperation = 'source-over'
      maskContext.clearRect(0, 0, width, height)
    }

    const reset = () => {
      cancelAnimationFrame(animationFrame)
      running = false
      stamps.length = 0
      lastX = null
      lastY = null
      clearCanvas()
    }

    const resize = () => {
      const rect = root.getBoundingClientRect()
      width = rect.width
      height = rect.height
      dpr = Math.min(window.devicePixelRatio || 1, 2)

      const scale = Math.min(width / COLOR_IMAGE_WIDTH, height / COLOR_IMAGE_HEIGHT)
      imageRect.width = COLOR_IMAGE_WIDTH * scale
      imageRect.height = COLOR_IMAGE_HEIGHT * scale
      imageRect.x = (width - imageRect.width) / 2
      imageRect.y = (height - imageRect.height) / 2

      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      maskCanvas.width = canvas.width
      maskCanvas.height = canvas.height
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      maskContext.setTransform(dpr, 0, 0, dpr, 0, 0)
      reset()
    }

    const addStamp = (x: number, y: number) => {
      if (stamps.length >= MAX_STAMPS) stamps.shift()
      stamps.push({
        x,
        y,
        born: performance.now(),
        seed: Math.random() * Math.PI * 2,
        maxRadius: MAX_RADIUS * (1 - RADIUS_VARIATION + Math.random() * RADIUS_VARIATION),
      })
    }

    const stampAlong = (x: number, y: number) => {
      if (lastX === null || lastY === null) {
        addStamp(x, y)
      } else {
        const distance = Math.hypot(x - lastX, y - lastY)
        const steps = Math.min(MAX_STAMPS, Math.max(1, Math.ceil(distance / STAMP_STEP)))
        for (let index = 1; index <= steps; index += 1) {
          addStamp(lastX + ((x - lastX) * index) / steps, lastY + ((y - lastY) * index) / steps)
        }
      }
      lastX = x
      lastY = y
    }

    const carveInk = (
      target: CanvasRenderingContext2D,
      x: number,
      y: number,
      radius: number,
      alpha: number,
      seed: number,
    ) => {
      if (!Number.isFinite(radius) || radius <= 0) return
      const gradient = target.createRadialGradient(x, y, radius * 0.25, x, y, radius)
      gradient.addColorStop(0, `rgba(255, 255, 255, ${0.95 * alpha})`)
      gradient.addColorStop(0.55, `rgba(255, 255, 255, ${0.88 * alpha})`)
      gradient.addColorStop(1, 'rgba(255, 255, 255, 0)')
      target.fillStyle = gradient
      target.beginPath()

      const segments = 32
      for (let index = 0; index <= segments; index += 1) {
        const angle = (index / segments) * Math.PI * 2
        const wobble =
          0.78 +
          0.14 * Math.sin(angle * 3 + seed) +
          0.08 * Math.sin(angle * 7 + seed * 2.1) +
          0.05 * Math.sin(angle * 13 + seed * 0.7)
        const pointRadius = radius * wobble
        const pointX = x + Math.cos(angle) * pointRadius
        const pointY = y + Math.sin(angle) * pointRadius
        if (index === 0) target.moveTo(pointX, pointY)
        else target.lineTo(pointX, pointY)
      }
      target.closePath()
      target.fill()
    }

    const loop = () => {
      const now = performance.now()
      maskContext.globalCompositeOperation = 'source-over'
      maskContext.clearRect(0, 0, width, height)

      for (let index = stamps.length - 1; index >= 0; index -= 1) {
        const stamp = stamps[index]
        const progress = Math.min(1, Math.max(0, (now - stamp.born) / DOT_LIFETIME))
        if (progress >= 1) {
          stamps.splice(index, 1)
          continue
        }
        const easedProgress = 1 - Math.pow(1 - progress, 3)
        const radius = INITIAL_RADIUS + (stamp.maxRadius - INITIAL_RADIUS) * easedProgress
        carveInk(maskContext, stamp.x, stamp.y, radius, 1 - progress * progress, stamp.seed)
      }

      if (!colorImageReady || stamps.length === 0) {
        clearCanvas()
        running = false
        return
      }

      context.globalCompositeOperation = 'source-over'
      context.clearRect(0, 0, width, height)
      context.drawImage(colorImage, imageRect.x, imageRect.y, imageRect.width, imageRect.height)
      context.globalCompositeOperation = 'destination-in'
      context.drawImage(maskCanvas, 0, 0, width, height)
      context.globalCompositeOperation = 'source-over'
      animationFrame = requestAnimationFrame(loop)
    }

    const start = () => {
      if (!motionMedia.matches || !colorImageReady || running) return
      running = true
      animationFrame = requestAnimationFrame(loop)
    }

    const getPoint = (event: PointerEvent) => {
      const rect = root.getBoundingClientRect()
      return [event.clientX - rect.left, event.clientY - rect.top] as const
    }
    const handlePointerMove = (event: PointerEvent) => {
      if (!motionMedia.matches || event.pointerType === 'touch' || document.hidden) return
      const [x, y] = getPoint(event)
      stampAlong(x, y)
      start()
    }
    const handlePointerLeave = () => {
      lastX = null
      lastY = null
    }
    const handleImageLoad = () => {
      colorImageReady = true
      start()
    }

    colorImage.addEventListener('load', handleImageLoad)
    colorImage.src = COLOR_IMAGE_SRC
    resize()
    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(root)
    window.addEventListener('resize', resize)
    motionMedia.addEventListener('change', reset)
    document.addEventListener('visibilitychange', reset)
    interaction.addEventListener('pointerenter', handlePointerMove)
    interaction.addEventListener('pointermove', handlePointerMove)
    interaction.addEventListener('pointerleave', handlePointerLeave)

    return () => {
      cancelAnimationFrame(animationFrame)
      resizeObserver.disconnect()
      window.removeEventListener('resize', resize)
      motionMedia.removeEventListener('change', reset)
      document.removeEventListener('visibilitychange', reset)
      interaction.removeEventListener('pointerenter', handlePointerMove)
      interaction.removeEventListener('pointermove', handlePointerMove)
      interaction.removeEventListener('pointerleave', handlePointerLeave)
      colorImage.removeEventListener('load', handleImageLoad)
    }
  }, [interactionRef])

  return (
    <div ref={rootRef} className={styles.root} aria-hidden="true">
      <div className={styles.image} />
      <canvas ref={canvasRef} className={styles.mask} />
    </div>
  )
}

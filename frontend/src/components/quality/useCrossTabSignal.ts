'use client'

import { useEffect } from 'react'

/**
 * 质量模块跨页面/跨标签页轻量信号：操作方 broadcast，监听方收到后刷新。
 * 使用 BroadcastChannel（同源即通），不依赖全局状态库。
 */
export function useCrossTabSignal(channel: string, onSignal: () => void) {
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return
    const bc = new BroadcastChannel(`quality:${channel}`)
    bc.onmessage = () => onSignal()
    return () => bc.close()
  }, [channel, onSignal])
}

export function broadcastSignal(channel: string) {
  if (typeof BroadcastChannel === 'undefined') return
  new BroadcastChannel(`quality:${channel}`).postMessage('refresh')
}

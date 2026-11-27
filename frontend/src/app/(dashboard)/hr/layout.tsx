'use client'

import { useEffect } from 'react'

export default function HrLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const listened = new WeakSet<HTMLInputElement>()
    let timer: number | undefined
    let idleRounds = 0

    // React 接管过的节点上会挂 __reactFiber$… / __reactProps$… 属性。
    // 整页包在 Suspense 里的路由（离职管理、合同台账）内容是服务端流式分片后到的：节点一进 DOM 就会被下面的观察器扫到，
    // 这时 React 还没水合它，先改属性会报「服务端 HTML 与客户端不一致」的水合错误，所以要等 React 接管后再改
    const isHydrated = (el: HTMLInputElement) => Object.keys(el).some((key) => key.startsWith('__react'))

    const scan = () => {
      let waiting = false
      document.querySelectorAll('input').forEach((el) => {
        if (!isHydrated(el)) {
          waiting = true
          return
        }
        el.setAttribute('autocomplete', 'off')
        // 监听只挂一次（每次扫描都挂会越积越多）
        if (listened.has(el)) return
        listened.add(el)
        el.addEventListener('focus', () => el.setAttribute('autocomplete', 'off'))
      })
      // 还没接管的过一会儿再看；等了很久仍没人接管（不是 React 渲染的输入框）就停，下次 DOM 变化时再扫
      idleRounds = waiting ? idleRounds + 1 : 0
      window.clearTimeout(timer)
      if (waiting && idleRounds <= 600) timer = window.setTimeout(scan, 50)
    }

    // 初始执行 + DOM 变化后再次执行（Ant Design 动态渲染）
    const observer = new MutationObserver(scan)
    observer.observe(document.body, { childList: true, subtree: true })
    scan()
    return () => {
      observer.disconnect()
      window.clearTimeout(timer)
    }
  }, [])
  return <>{children}</>
}

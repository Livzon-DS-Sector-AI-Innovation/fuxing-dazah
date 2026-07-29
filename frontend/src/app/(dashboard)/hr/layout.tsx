'use client'

import { useEffect } from 'react'

export default function HrLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const disableAutocomplete = () => {
      document.querySelectorAll('input').forEach(el => {
        el.setAttribute('autocomplete', 'off')
        el.addEventListener('focus', () => el.setAttribute('autocomplete', 'off'), { once: true })
      })
    }
    // 初始执行 + DOM 变化后再次执行（Ant Design 动态渲染）
    disableAutocomplete()
    const observer = new MutationObserver(() => disableAutocomplete())
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])
  return <>{children}</>
}

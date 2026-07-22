'use client'

import { useEffect } from 'react'

export default function HrLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // 禁止所有输入框的浏览器自动填充
    document.querySelectorAll('input').forEach(el => el.setAttribute('autocomplete', 'off'))
  }, [])
  return <>{children}</>
}

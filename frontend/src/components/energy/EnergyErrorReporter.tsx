'use client'

import { useEffect } from 'react'
import { reportEnergyError } from '@/lib/energy/error-report'

/**
 * energy 模块前端错误上报入口。
 * 挂载后收集未捕获的 JS 异常与未处理的 Promise 拒绝，上报到后端日志文件。
 * API 请求失败由各组件 catch 处显式调用 reportEnergyError 上报。
 */
export function EnergyErrorReporter() {
  useEffect(() => {
    const onError = (e: ErrorEvent) => {
      reportEnergyError({
        message: e.message || '未知前端异常',
        stack: e.error instanceof Error ? e.error.stack : undefined,
        page_url: window.location.href,
      })
    }

    const onRejection = (e: PromiseRejectionEvent) => {
      const reason = e.reason
      reportEnergyError({
        message: reason instanceof Error ? reason.message : String(reason),
        stack: reason instanceof Error ? reason.stack : undefined,
        page_url: window.location.href,
      })
    }

    window.addEventListener('error', onError)
    window.addEventListener('unhandledrejection', onRejection)

    return () => {
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onRejection)
    }
  }, [])

  return null
}

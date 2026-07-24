/**
 * 客户端日志工具
 * 统一管理 console 输出，生产环境可切换为上报服务
 */

type LogLevel = 'info' | 'warn' | 'error'

interface LogEntry {
  level: LogLevel
  message: string
  detail?: Record<string, unknown>
  timestamp: string
}

function format(entry: LogEntry): string {
  const { level, message, detail, timestamp } = entry
  const prefix = `[${timestamp}] [${level.toUpperCase()}]`
  const detailStr = detail ? ' ' + JSON.stringify(detail, null, 0) : ''
  return `${prefix} ${message}${detailStr}`
}

function log(level: LogLevel, message: string, detail?: Record<string, unknown>) {
  const entry: LogEntry = {
    level,
    message,
    detail,
    timestamp: new Date().toISOString(),
  }
  const text = format(entry)
  switch (level) {
    case 'error': console.error(text); break
    case 'warn': console.warn(text); break
    default: console.log(text)
  }
}

/** API 请求错误日志 */
export function logApiError(method: string, url: string, status: number, body?: string) {
  log('error', `API ${method} ${url} → ${status}`, {
    method,
    url,
    status,
    responseBody: body?.slice(0, 500), // 截断长响应
  })
}

/** API 请求成功日志 */
export function logApiSuccess(method: string, url: string, status: number) {
  log('info', `API ${method} ${url} → ${status}`, { method, url, status })
}

/** 业务操作日志 */
export function logAction(action: string, detail?: Record<string, unknown>) {
  log('info', action, detail)
}

/** 通用错误日志 */
export function logError(message: string, detail?: Record<string, unknown>) {
  log('error', message, detail)
}

/** 警告日志 */
export function logWarn(message: string, detail?: Record<string, unknown>) {
  log('warn', message, detail)
}

import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ── 日期格式化 ──
// ponytail: 消除 5+ 处重复的 inline formatDate/formatTime

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('zh-CN')
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '未设置'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

// ── 批号递增 ──
// ponytail: 消除 PlanItemTable / PlanOrderDetailDrawer 5 处重复 regex

const BATCH_NO_RE = /^(.*?)(\d+)(.*)$/

export function incrementBatchNo(current: string): string {
  const m = current.match(BATCH_NO_RE)
  if (!m) return current + '-1'
  const n = String(parseInt(m[2], 10) + 1).padStart(m[2].length, '0')
  return m[1] + n + m[3]
}

export function decrementBatchNo(current: string): string {
  const m = current.match(BATCH_NO_RE)
  if (!m) return current
  const n = parseInt(m[2], 10)
  if (n <= 1) return current
  return m[1] + String(n - 1).padStart(m[2].length, '0') + m[3]
}

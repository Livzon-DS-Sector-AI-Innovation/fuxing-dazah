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
// 惰性前缀 + 非数字尾段，捕获最后一个完整数字段（PO-20260824-001 递增的是
// 001 而不是日期；XHA26189 递增的是 26189 整段而非末位 9，末位 9 才能正确进位），
// 与后端 planning_service._decrement_batch_no 保持同语义。

const BATCH_NO_RE = /^(.*?)(\d+)(\D*)$/

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

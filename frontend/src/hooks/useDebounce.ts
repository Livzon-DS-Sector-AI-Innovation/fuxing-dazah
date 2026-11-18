'use client'

// 共享防抖 hooks（此前各组件手写 debounceRef+setTimeout，三处三种写法）。
// 远程搜索的完整范式 = useDebouncedCallback 防抖 + 请求序号守卫丢弃过期响应
// （防抖只能减少请求，慢请求晚归仍会覆盖新结果，seq 守卫不可省）。

import { useCallback, useEffect, useRef, useState } from 'react'

/** 值防抖：value 变化后 delay ms 内稳定才更新返回值（受控输入 → 派生查询用）。 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debouncedValue
}

/** 防抖回调：delay 内多次调用只执行最后一次；组件卸载自动取消。
 *  fn 更新不重置计时；cancel 用于 reset 等需要立刻丢弃未触发调用的场景。 */
export function useDebouncedCallback<A extends unknown[]>(
  fn: (...args: A) => void,
  delay: number,
) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fnRef = useRef(fn)
  useEffect(() => {
    fnRef.current = fn
  })
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])
  const run = useCallback(
    (...args: A) => {
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        fnRef.current(...args)
      }, delay)
    },
    [delay],
  )
  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])
  return { run, cancel }
}

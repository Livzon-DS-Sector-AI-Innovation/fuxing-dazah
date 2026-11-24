'use client'

// 未保存离开提醒：弹窗/抽屉关闭、点「取消」、浏览器刷新或关标签页时，
// 若有未保存的修改先确认。此前各处都是直接关闭，已填内容静默丢失。

import { useCallback, useEffect, useRef } from 'react'
import { App } from 'antd'

interface UseUnsavedConfirmOptions {
  /** 确认框标题，默认「有尚未保存的修改」 */
  title?: string
  /** 确认框正文，默认提示已填内容会丢失 */
  content?: string
  /** 是否在浏览器刷新/关闭标签页时也拦截（默认 true） */
  guardBeforeUnload?: boolean
}

/**
 * @param dirty 当前是否有未保存的修改
 * @param onDiscard 用户确认放弃后执行（一般是真正关闭弹窗/离开）
 * @returns guard —— 包在 onClose / 取消按钮上调用；用户选择「继续编辑」时不执行 onDiscard
 */
export function useUnsavedConfirm(dirty: boolean, onDiscard: () => void, options: UseUnsavedConfirmOptions = {}) {
  const { modal } = App.useApp()
  // 用 ref 持有最新值：guard 引用保持稳定，可直接放进 onClose / 依赖数组
  const dirtyRef = useRef(dirty)
  const discardRef = useRef(onDiscard)
  const modalRef = useRef(modal)
  useEffect(() => { dirtyRef.current = dirty }, [dirty])
  useEffect(() => { discardRef.current = onDiscard }, [onDiscard])
  useEffect(() => { modalRef.current = modal }, [modal])

  const { guardBeforeUnload = true } = options

  useEffect(() => {
    if (!dirty || !guardBeforeUnload) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty, guardBeforeUnload])

  return useCallback(() => {
    if (!dirtyRef.current) {
      discardRef.current()
      return
    }
    modalRef.current.confirm({
      title: options.title ?? '有尚未保存的修改',
      content: options.content ?? '离开后已填写的内容会丢失，确定放弃吗？',
      okText: '放弃修改',
      okButtonProps: { danger: true },
      cancelText: '继续编辑',
      onOk: () => discardRef.current(),
    })
    // options 只读取初始文案即可，不进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}

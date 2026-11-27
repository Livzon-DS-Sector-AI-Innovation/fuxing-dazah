/**
 * 复制文本到剪贴板，返回是否成功（失败时由调用方提示，不静默）。
 *
 * 本系统走公司内网的 http 地址访问，不是安全上下文，`navigator.clipboard` 在那里
 * 不存在（localhost / https 才有）。所以优先用 Async Clipboard，拿不到或被拒绝时
 * 退回 `execCommand('copy')`——它要求在点击事件的调用栈里同步执行，这里没有 await
 * 介于其间的异步跳转才能成立。
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 权限被拒、文档失焦等：走下面的兜底
  }
  return legacyCopy(text)
}

function legacyCopy(text: string): boolean {
  const previousFocus = document.activeElement as HTMLElement | null
  const field = document.createElement('textarea')
  field.value = text
  field.setAttribute('readonly', '')
  field.style.cssText = 'position:fixed;top:0;left:0;opacity:0'
  document.body.append(field)
  field.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    field.remove()
    // 选中临时输入框可能把焦点挪走：失败也要还原
    previousFocus?.focus({ preventScroll: true })
  }
}

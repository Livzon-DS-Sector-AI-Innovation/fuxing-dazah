/**
 * 客户端下载辅助：将 Server Action 返回的 base64 文件内容落地为浏览器下载。
 */

function base64ToBlob(base64: string, mimeType?: string): Blob {
  const byteChars = atob(base64)
  const byteNumbers = new Array(byteChars.length)
  for (let i = 0; i < byteChars.length; i++) {
    byteNumbers[i] = byteChars.charCodeAt(i)
  }
  return new Blob([new Uint8Array(byteNumbers)], mimeType ? { type: mimeType } : undefined)
}

/** base64 转 blob URL，用于 iframe 内嵌预览（如 PDF）。用完需 URL.revokeObjectURL 释放 */
export function base64ToObjectUrl(base64: string, mimeType: string): string {
  return window.URL.createObjectURL(base64ToBlob(base64, mimeType))
}

export function downloadBase64File(base64: string, filename: string): void {
  const blob = base64ToBlob(base64)
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

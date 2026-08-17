'use client'

// 工具箱客户端能力：执行产物下载。
// 工具列表/会话读取由 page.tsx 在服务端用 lib/http-client 的 apiGet 完成（自动带 token）。

/** 下载执行产物（凭 cookie 认证，浏览器自动携带）。 */
export async function fetchFileDownload(url: string): Promise<Blob> {
  const res = await fetch(url, { credentials: 'include' })
  if (!res.ok) throw new Error(`下载失败: ${res.status}`)
  return res.blob()
}

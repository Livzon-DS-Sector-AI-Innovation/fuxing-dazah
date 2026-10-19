import { notFound } from 'next/navigation'

/**
 * 兜底路由：未匹配到页面时仍落到 dashboard 路由组内，
 * 让 not-found 页面复用 AppShell（顶栏 + 侧边栏），避免点击失效菜单后整条侧边栏消失。
 */
export default function DashboardCatchAllPage() {
  notFound()
}

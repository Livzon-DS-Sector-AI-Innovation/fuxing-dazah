import { redirect } from 'next/navigation'

// 旧入口（单页 + query 切换）已拆分为独立页面 → 重定向到「变更审批」
export default function EhsChangeLegacyRedirect() {
  redirect('/safety/ehs-change/apply')
}

import { redirect } from 'next/navigation'

// 仓储管理首页默认进入库存管理
export default function WarehousePage() {
  redirect('/warehouse/inventory')
}

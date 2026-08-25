// 工具箱使用权限页：配置每个工具的使用人员与配置人员（仅系统超级管理员）
// 后端 /toolbox/tool-grants 由 require_admin 兜底，非超管请求 403 → 此处渲染无权限提示

import { apiGet } from '@/lib/http-client'

import { ToolPermissionManager } from '@/components/toolbox'
import type { PersonnelOption, ToolGrantInfo, ToolInfo } from '@/types/toolbox'

export const dynamic = 'force-dynamic'

const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'

interface PersonnelRawItem {
  id: string
  name: string
  employee_no: string | null
  department: string | null
}

interface PersonnelPage {
  items: PersonnelRawItem[]
}

export default async function ToolboxPermissionsPage() {
  let tools: ToolInfo[] = []
  let grants: ToolGrantInfo[] = []
  let personnel: PersonnelOption[] = []
  let forbidden = false
  let errorMessage: string | null = null
  try {
    const [toolsData, grantsData, personnelData] = await Promise.all([
      apiGet<ToolInfo[]>(`${API_BASE}/api/v1/toolbox/tools`, { cache: 'no-store' }),
      apiGet<ToolGrantInfo[]>(`${API_BASE}/api/v1/toolbox/tool-grants`, { cache: 'no-store' }),
      apiGet<PersonnelPage>(`${API_BASE}/api/v1/identity/personnel?offset=0&limit=9999`, {
        cache: 'no-store',
      }),
    ])
    tools = toolsData
    grants = grantsData
    personnel = (personnelData.items ?? []).map((p) => ({
      id: p.id,
      name: p.name,
      employee_no: p.employee_no,
      department: p.department,
    }))
  } catch (e) {
    // 仅 403 判定为无权限；后端 5xx/网络错误显示真实信息，避免误导排查
    const status = (e as { status?: number } | null)?.status
    if (status === 403) {
      forbidden = true
    } else {
      errorMessage = e instanceof Error ? e.message : '页面数据加载失败'
    }
  }

  if (forbidden) {
    return (
      <p className="p-6 text-[15px] text-[var(--color-stone)]">
        无权限访问此页面：使用权限配置仅对系统超级管理员开放
      </p>
    )
  }

  if (errorMessage) {
    return (
      <p className="p-6 text-[15px] text-[var(--color-stone)]">
        页面数据加载失败：{errorMessage}，请稍后重试或联系管理员
      </p>
    )
  }

  return <ToolPermissionManager tools={tools} initialGrants={grants} personnel={personnel} />
}

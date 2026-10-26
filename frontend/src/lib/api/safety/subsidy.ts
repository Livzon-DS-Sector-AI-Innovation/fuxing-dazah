import type {
  GuardianSubsidySummary,
  SubsidySourceDept,
} from '@/types/safety'
import { apiGet, API_BASE_URL } from '@/lib/http-client'

/** 监护补贴可查询部门（台账三部门） */
export async function fetchSubsidySources(): Promise<SubsidySourceDept[]> {
  return apiGet(`${API_BASE_URL}/api/v1/safety/subsidy/sources`)
}

/** 监护补贴统计（台账部门只读查询，口径与 AI 助手/月报一致） */
export async function fetchGuardianSubsidySummary(
  department: string,
  year: number,
  month: number,
): Promise<GuardianSubsidySummary> {
  const sp = new URLSearchParams({
    department,
    year: String(year),
    month: String(month),
  })
  return apiGet(
    `${API_BASE_URL}/api/v1/safety/subsidy/guardian-summary?${sp.toString()}`,
  )
}

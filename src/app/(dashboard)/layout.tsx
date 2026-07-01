import '@/lib/http-server'
import { AppShell } from "@/components/layout/AppShell"
import { AntdProvider } from "@/components/AntdProvider"
import { PermissionProvider } from "@/components/PermissionProvider"
import { apiGet } from "@/lib/http-client"
import '@/lib/dayjs-config'

async function fetchInitialPermissions() {
  try {
    const API_BASE = process.env.API_BASE_URL || 'http://localhost:8000'
    const data: any = await apiGet(`${API_BASE}/api/v1/identity/me`)
    return {
      permissions: (data.permissions as string[]) ?? [],
      roles: (data.roles as string[]) ?? [],
      dataScopes: (data.data_scopes as Record<string, string>) ?? {},
    }
  } catch {
    return { permissions: [], roles: [], dataScopes: {} }
  }
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const perm = await fetchInitialPermissions()

  return (
    <AntdProvider>
      <PermissionProvider
        initialPermissions={perm.permissions}
        initialRoles={perm.roles}
        initialDataScopes={perm.dataScopes}
      >
        <AppShell>{children}</AppShell>
      </PermissionProvider>
    </AntdProvider>
  )
}

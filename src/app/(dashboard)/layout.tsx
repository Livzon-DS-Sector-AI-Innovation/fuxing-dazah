import { AppShell } from "@/components/layout/AppShell"
import '@/lib/dayjs-config'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <AppShell>{children}</AppShell>
}

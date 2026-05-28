import { TopNav } from "./TopNav"
import { Sidebar } from "./Sidebar"

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <TopNav />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto bg-[var(--color-surface)] p-6">
          {children}
        </main>
      </div>
    </div>
  )
}

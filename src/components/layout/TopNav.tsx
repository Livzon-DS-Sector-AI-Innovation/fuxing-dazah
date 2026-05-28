"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { moduleMenus } from "@/lib/menu-config"
import { ModuleIcon, SearchIcon, BellIcon } from "@/components/icons"

export function TopNav() {
  const pathname = usePathname()
  const activeModule = pathname.split("/")[1] || "production"

  return (
    <header className="h-16 bg-[var(--color-canvas)] border-b border-[var(--color-hairline)] flex items-center px-5 shrink-0">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mr-10 shrink-0">
        <div className="w-7 h-7 rounded-[var(--rounded-md)] bg-[var(--color-primary)] flex items-center justify-center">
          <span className="text-white text-xs font-semibold">D</span>
        </div>
        <span className="text-[var(--color-charcoal)] text-[15px] font-semibold tracking-tight">
          大杂烩
        </span>
      </div>

      {/* Module Tabs */}
      <nav className="flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-hide h-full">
        {moduleMenus.map((mod) => {
          const isActive = activeModule === mod.key
          return (
            <Link
              key={mod.key}
              href={mod.path}
              className={`
                flex items-center gap-1.5 px-3 h-full text-[14px] font-medium transition-colors whitespace-nowrap relative
                ${isActive
                  ? "text-[var(--color-ink)]"
                  : "text-[var(--color-steel)] hover:text-[var(--color-charcoal)]"
                }
              `}
            >
              <ModuleIcon name={mod.icon} className="w-4 h-4" />
              {mod.label}
              {isActive && (
                <span className="absolute bottom-0 left-3 right-3 h-[2px] bg-[var(--color-primary)] rounded-full" />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Right Section */}
      <div className="flex items-center gap-1 ml-4 shrink-0">
        <button className="w-8 h-8 flex items-center justify-center rounded-[var(--rounded-sm)] text-[var(--color-steel)] hover:text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] transition-colors">
          <SearchIcon className="w-[18px] h-[18px]" />
        </button>
        <button className="w-8 h-8 flex items-center justify-center rounded-[var(--rounded-sm)] text-[var(--color-steel)] hover:text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] transition-colors relative">
          <BellIcon className="w-[18px] h-[18px]" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-[var(--color-error)] rounded-full" />
        </button>
        <div className="ml-2 w-8 h-8 rounded-full bg-[var(--color-primary)] flex items-center justify-center text-white text-xs font-semibold">
          J
        </div>
      </div>
    </header>
  )
}

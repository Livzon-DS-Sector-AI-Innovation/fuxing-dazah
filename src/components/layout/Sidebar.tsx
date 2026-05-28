"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { getModuleByKey } from "@/lib/menu-config"

export function Sidebar() {
  const pathname = usePathname()
  const moduleKey = pathname.split("/")[1] || "production"
  const currentModule = getModuleByKey(moduleKey)

  if (!currentModule) return null

  return (
    <aside className="w-56 bg-[var(--color-canvas)] border-r border-[var(--color-hairline)] flex flex-col shrink-0 overflow-y-auto">
      {/* Module Title */}
      <div className="px-4 pt-5 pb-3">
        <h2 className="text-[18px] font-semibold text-[var(--color-charcoal)]">
          {currentModule.label}
        </h2>
      </div>

      {/* Sub Menu */}
      <nav className="flex-1 px-2 pb-4">
        <ul className="space-y-0.5">
          {currentModule.children.map((item) => {
            const isActive = pathname === item.path || pathname.startsWith(item.path + "/")
            return (
              <li key={item.key}>
                <Link
                  href={item.path}
                  className={`
                    flex items-center px-3 py-2 text-[14px] rounded-[var(--rounded-md)] transition-colors
                    ${isActive
                      ? "text-[var(--color-primary)] bg-[var(--color-primary)]/5 font-medium"
                      : "text-[var(--color-charcoal)] hover:bg-[var(--color-surface)] hover:text-[var(--color-ink)]"
                    }
                  `}
                >
                  {item.label}
                </Link>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-[var(--color-hairline-soft)]">
        <p className="text-[12px] text-[var(--color-stone)]">
          v0.1.0
        </p>
      </div>
    </aside>
  )
}

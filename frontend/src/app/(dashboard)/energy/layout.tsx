import type { ReactNode } from 'react'
import { EnergyQueryProvider } from '@/components/energy'

export default function EnergyLayout({ children }: { children: ReactNode }) {
  return <EnergyQueryProvider>{children}</EnergyQueryProvider>
}

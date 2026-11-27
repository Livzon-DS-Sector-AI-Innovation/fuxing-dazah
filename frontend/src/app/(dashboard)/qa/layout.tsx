import type { ReactNode } from 'react'
import { QaQueryProvider } from '@/components/qa'

export default function QaLayout({ children }: { children: ReactNode }) {
  return <QaQueryProvider>{children}</QaQueryProvider>
}

import { PersonnelPage, PersonnelQueryProvider } from '@/components/equipment'

export default function Page() {
  return (
    <PersonnelQueryProvider>
      <PersonnelPage />
    </PersonnelQueryProvider>
  )
}

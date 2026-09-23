import { QaWorkspace } from '@/components/qa'

export const dynamic = 'force-dynamic'

export default async function QaDocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <QaWorkspace view="documents" documentId={id} />
}


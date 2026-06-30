import HrChatbot from '@/components/hr/HrChatbot'

export default function HrLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>
    {children}
    <HrChatbot />
  </>
}

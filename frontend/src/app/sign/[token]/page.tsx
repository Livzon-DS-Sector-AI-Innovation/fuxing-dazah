import { SignClient } from './SignClient'

export default async function SignPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params
  return <SignClient token={token} />
}

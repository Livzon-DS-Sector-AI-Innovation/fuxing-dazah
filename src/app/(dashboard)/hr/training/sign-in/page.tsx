import { SignInSheetClient } from '@/components/hr'

export default function SignInSheetPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          培训签到表
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          填写培训信息，选择受训部门和人员，生成培训签到表
        </p>
      </div>

      <SignInSheetClient />
    </div>
  )
}

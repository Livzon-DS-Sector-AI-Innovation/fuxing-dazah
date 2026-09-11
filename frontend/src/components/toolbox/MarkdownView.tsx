'use client'

// 轻量 Markdown 渲染（react-markdown）：工具执行结果里键名以 _md 结尾的字符串值
// 走此渲染（如翻译校验报告）。样式用 Tailwind 任意变体按子元素覆盖，遵守 DESIGN.md。

import Markdown from 'react-markdown'

export function MarkdownView({ text }: { text: string }) {
  return (
    <div
      className={[
        'space-y-2 text-[13px] leading-relaxed text-[var(--color-slate)]',
        '[&_h1]:mt-5 [&_h1]:mb-2 [&_h1]:text-[16px] [&_h1]:font-semibold [&_h1]:text-[var(--color-charcoal)]',
        '[&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-[14px] [&_h2]:font-semibold [&_h2]:text-[var(--color-charcoal)]',
        '[&_h3]:mt-4 [&_h3]:mb-1 [&_h3]:text-[13px] [&_h3]:font-semibold [&_h3]:text-[var(--color-charcoal)]',
        '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5',
        '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5',
        '[&_li]:my-0.5',
        '[&_p]:my-1',
        '[&_strong]:text-[var(--color-charcoal)] [&_strong]:font-semibold',
        '[&_hr]:my-4 [&_hr]:border-0 [&_hr]:border-t [&_hr]:border-[var(--color-hairline)]',
        '[&_a]:text-[var(--color-primary)] [&_a]:underline',
        '[&_code]:rounded [&_code]:bg-[var(--color-surface)] [&_code]:px-1 [&_code]:text-[12px]',
        '[&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-[var(--color-surface)] [&_pre]:p-3',
        '[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-[12px]',
        '[&_th]:border [&_th]:border-[var(--color-hairline)] [&_th]:bg-[var(--color-surface)] [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-medium [&_th]:text-[var(--color-charcoal)]',
        '[&_td]:border [&_td]:border-[var(--color-hairline-soft)] [&_td]:px-2 [&_td]:py-1',
      ].join(' ')}
    >
      <Markdown>{text}</Markdown>
    </div>
  )
}

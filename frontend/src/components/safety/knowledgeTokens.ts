// 知识库模块设计 token（与全局 --color-* 变量对齐，减少内联魔法数字）

export const KB = {
  color: {
    primary: 'var(--color-primary, #5645d4)',
    primarySoft: 'rgba(86, 69, 212, 0.08)',
    ink: 'var(--color-ink, #1a1a1a)',
    charcoal: 'var(--color-charcoal, #37352f)',
    slate: 'var(--color-slate, #5d5b54)',
    steel: 'var(--color-steel, #787671)',
    stone: 'var(--color-stone, #a4a097)',
    canvas: 'var(--color-canvas, #ffffff)',
    surface: 'var(--color-surface, #f6f5f4)',
    surfaceSoft: 'var(--color-surface-soft, #fafaf9)',
    hairline: 'var(--color-hairline, #e5e3df)',
    hairlineSoft: 'var(--color-hairline-soft, #ede9e4)',
    success: '#1aae39',
    successBg: '#e7f7ec',
  },
  radius: {
    sm: 6,
    md: 8,
    lg: 12,
    card: 14,
    pill: 999,
  },
  font: {
    mono: '"SF Mono", "Fira Code", ui-monospace, monospace',
  },
} as const

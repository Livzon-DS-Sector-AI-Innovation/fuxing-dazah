// 工具识别色：由工具 id 稳定映射到 pastel tint（浅底 + 深色墨水），
// 工具卡片与执行页共用，保证同一工具在两处同色。

const TINTS = [
  '#ffe8d4', // peach
  '#fde0ec', // rose
  '#d9f3e1', // mint
  '#e6e0f5', // lavender
  '#dcecfa', // sky
  '#fef7d6', // yellow
  '#f8f5e8', // cream
]

// tint 浅底 → 深色节点（步骤轨道与图标首字共用）
const TINT_INKS = [
  '#793400', // peach → brand-orange-deep
  '#a02e6d', // rose → brand-pink-deep
  '#1aae39', // mint → brand-green
  '#7b3ff2', // lavender → brand-purple
  '#0075de', // sky → link-blue
  '#523410', // yellow → brand-brown
  '#5d5b54', // cream → slate
]

export interface ToolTint {
  bg: string
  ink: string
}

export function toolTint(toolId: string): ToolTint {
  const idx = toolId.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0) % TINTS.length
  return { bg: TINTS[idx], ink: TINT_INKS[idx] }
}

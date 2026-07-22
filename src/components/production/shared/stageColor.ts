// ponytail: shared stage color palette — one hash fn, one palette
const STAGE_COLORS = [
  '#5645d4', '#1aae39', '#dd5b00', '#0075de', '#d4380d',
  '#08979c', '#9341c9', '#d41c7a', '#6e41e2', '#3b82f6',
]

export function stageColor(name: string) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) | 0
  return STAGE_COLORS[Math.abs(h) % STAGE_COLORS.length]
}

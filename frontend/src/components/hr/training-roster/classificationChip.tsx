// 分类胶囊与色点：名单单元格、勾选面板、分类管理抽屉共用同一套外观。

export interface ChipColor {
  bg: string
  text: string
  dot: string
}

interface ClassificationChipProps {
  name: string
  color: ChipColor
  /** 不在分类清单里的残留标签：加虚线描边，与正常分类区分 */
  orphan?: boolean
}

/** 分类胶囊：过渡色底 + 同色系深字，圆角 4px（DESIGN.md rounded-xs「Tag chips」） */
export function ClassificationChip({ name, color, orphan }: ClassificationChipProps) {
  return (
    <span
      className="inline-flex h-[22px] max-w-full items-center rounded-[var(--rounded-xs)] px-2 text-[12px] leading-none whitespace-nowrap"
      style={{
        background: color.bg,
        color: color.text,
        boxShadow: orphan ? `inset 0 0 0 1px ${color.dot}` : undefined,
      }}
    >
      <span className="truncate">{name}</span>
    </span>
  )
}

export function ColorDot({ color, className }: { color: ChipColor; className?: string }) {
  return (
    <span
      className={`inline-block size-2 shrink-0 rounded-full ${className ?? ''}`}
      style={{ background: color.dot }}
    />
  )
}

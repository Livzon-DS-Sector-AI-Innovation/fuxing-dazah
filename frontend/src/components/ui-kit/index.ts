// 仓库级 UI 套件（ui-kit）：从仓储 2.0 驾驶舱底座抽出，安全 3.0 面板与仓储共用。
// 消费方一律 `import { ... } from '@/components/ui-kit'`，禁止跨模块引用对方命名空间。
export { StatCard, StatDelta } from './StatCard'
export { EmptyGuide } from './EmptyGuide'
export { StatusTag } from './StatusTag'
export { SectionCard } from './SectionCard'
export { FeedGroup, FeedRow } from './FeedGroup'
export { PageHeader } from './PageHeader'
export { DonutChart, RankBarChart, TrendAreaChart, ensureWarehouseTheme, type ChartTone } from './charts'
export { TONE_STYLE, TONE_TAG_COLOR, TONE_HEX, type Tone } from './tokens'

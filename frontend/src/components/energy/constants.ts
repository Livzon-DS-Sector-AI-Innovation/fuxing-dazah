import { EnergyType } from '@/types/energy'

export const energyTypeLabels: Record<EnergyType, { text: string; color: string }> = {
  electricity:   { text: '电耗数据',   color: 'blue' },
  water:         { text: '水耗数据',   color: 'cyan' },
  steam:         { text: '蒸汽数据',   color: 'orange' },
  cooling:       { text: '冷量数据',   color: 'purple' },
  compressed_air:{ text: '压缩空气数据', color: 'geekblue' },
  nitrogen:      { text: '氮气数据',   color: 'volcano' },
  natural_gas:   { text: '天然气数据', color: 'gold' },
}

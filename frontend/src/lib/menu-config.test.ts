import { describe, expect, it } from 'vitest'
import { moduleMenus, type SubMenuItem } from './menu-config'

const safety = moduleMenus.find((m) => m.key === 'safety')

/** 展平 safety 菜单的所有叶子项（一期为纯平铺 + group，无嵌套） */
function safetyItems(): SubMenuItem[] {
  const children = safety?.children ?? []
  const flat: SubMenuItem[] = []
  for (const c of children) {
    if (c.children?.length) flat.push(...c.children)
    else flat.push(c)
  }
  return flat
}

const RETIRED_PATHS = [
  '/safety/hazard',
  '/safety/hazard-identification', // 流程页退役，仅保留 /ledger
  '/safety/check',
  '/safety/training',
  '/safety/contractor',
  '/safety/accident',
  '/safety/regulation',
  '/safety/daily-risk-report',
  '/safety/special-ops/personnel',
  '/safety/ehs-change/apply',
  '/safety/ehs-change/acceptance',
  '/safety/ehs-change/urs',
  '/safety/info-query',
  '/safety/chemical-inventory',
  '/safety/msds',
  '/safety/fire-alarms',
  '/safety/central-alarms',
]

const EXPECTED_GROUPS = [
  '工作台',
  '体系治理',
  '风险管控',
  '隐患治理',
  '人员管理',
  '现场管理',
  '应急处置',
  '检查监督',
  '持续改进',
  '系统',
]

describe('safety 菜单结构（体系要素分组，3.0）', () => {
  it('模块存在且为平铺结构（无嵌套子菜单）', () => {
    expect(safety).toBeDefined()
    for (const c of safety?.children ?? []) {
      expect(c.children, `「${c.label}」不应再有嵌套子菜单`).toBeUndefined()
    }
  })

  it('分组齐全且顺序符合方案 §2', () => {
    const groups: string[] = []
    for (const c of safety?.children ?? []) {
      if (c.group && groups[groups.length - 1] !== c.group) groups.push(c.group)
    }
    expect(groups).toEqual(EXPECTED_GROUPS)
  })

  it('标签纯文字——不含体系编号（S1/S2…）与 emoji', () => {
    for (const c of safety?.children ?? []) {
      expect(c.label).not.toMatch(/\bS\d+\b/)
      expect(c.label).not.toMatch(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
    }
  })

  it('退役路径不出现在菜单中', () => {
    const paths = safetyItems().map((i) => i.path)
    for (const p of RETIRED_PATHS) {
      expect(paths, `退役路径 ${p} 不应出现在菜单`).not.toContain(p)
    }
  })

  it('disabled 仅限「全流程监督」（三期新建），且无路径', () => {
    const disabled = safetyItems().filter((i) => i.disabled)
    expect(disabled.map((i) => i.label)).toEqual(['全流程监督'])
    expect(disabled[0].path).toBe('')
  })

  it('系统组收口为 2 项：系统配置单页 + AI 助手对话（三期）', () => {
    const systemGroup = safetyItems().filter((i) => i.group === '系统')
    expect(systemGroup.map((i) => i.label)).toEqual(['系统配置', 'AI 助手对话'])
    expect(systemGroup[0].path).toBe('/safety/system')
  })

  it('启用项路由与页面一一对应（快照）', () => {
    const enabled = safetyItems().filter((i) => !i.disabled)
    expect(enabled.map((i) => i.path)).toEqual([
      '/safety',
      '/safety/goals',
      '/safety/knowledge-base',
      '/safety/hazard-identification/ledger',
      '/safety/hazard-ledger',
      '/safety/cert-warnings',
      '/safety/training-behavior',
      '/safety/occupational-health',
      '/safety/facilities',
      '/safety/chemicals',
      '/safety/special-ops',
      '/safety/risk-reporting',
      '/safety/alarms',
      '/safety/ehs-change',
      '/safety/contractor-admission',
      '/safety/emergency-drill',
      '/safety/incidents',
      '/safety/system',
      '/safety/agent-chat',
    ])
  })

  it('菜单项 key 全局唯一', () => {
    const keys = (safety?.children ?? []).map((c) => c.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})

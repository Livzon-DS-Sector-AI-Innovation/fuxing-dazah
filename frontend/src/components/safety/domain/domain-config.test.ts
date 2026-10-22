/**
 * 三域页面配置完整性（3.0 四期 1-C）：口径与 DESIGN 蓝本对齐的静态守卫。
 * goals 已改走体系标准核查引擎（components/safety/goals，2026-10-21），不在本配置内。
 */
import { describe, expect, it } from 'vitest'

import { DOMAIN_PAGE_CONFIGS } from './domain-config'

describe('DOMAIN_PAGE_CONFIGS（蓝本口径配置）', () => {
  it('三域齐备，key 对齐前端菜单', () => {
    expect(Object.keys(DOMAIN_PAGE_CONFIGS)).toEqual([
      'training-behavior',
      'facilities',
      'incidents',
    ])
  })

  it('每域 6 张统计卡，key 与后端 stats 键一一对应（蓝本各域统计口径表）', () => {
    const expected: Record<string, string[]> = {
      'training-behavior': [
        'training_total', 'completion_rate', 'pass_rate',
        'retraining_due_30d', 'violation_total', 'violation_open',
      ],
      facilities: [
        'equipment_total', 'special_equipment', 'inspection_overdue',
        'inspection_due_30d', 'inspection_pass_rate', 'inactive_equipment',
      ],
      incidents: [
        'incident_total', 'accident_count', 'near_miss_count',
        'investigating_count', 'capa_open', 'capa_overdue',
      ],
    }
    for (const [key, statKeys] of Object.entries(expected)) {
      expect(
        DOMAIN_PAGE_CONFIGS[key as keyof typeof DOMAIN_PAGE_CONFIGS].statCards.map((c) => c.key),
      ).toEqual(statKeys)
    }
  })

  it('每域主台账列与蓝本主台账字段一致（抽查首列与关键字段）', () => {
    expect(
      DOMAIN_PAGE_CONFIGS['training-behavior'].columns.map((c) => c.dataIndex),
    ).toEqual(
      expect.arrayContaining(['name', 'planned_at', 'status', 'next_retraining_at']),
    )
    expect(
      DOMAIN_PAGE_CONFIGS.facilities.columns.map((c) => c.dataIndex),
    ).toEqual(expect.arrayContaining(['equipment_no', 'category', 'status']))
    expect(
      DOMAIN_PAGE_CONFIGS.incidents.columns.map((c) => c.dataIndex),
    ).toEqual(expect.arrayContaining(['incident_no', 'occurred_at', 'level', 'status']))
  })

  it('每域分组对齐菜单分组名', () => {
    expect(DOMAIN_PAGE_CONFIGS['training-behavior'].group).toBe('人员管理')
    expect(DOMAIN_PAGE_CONFIGS.facilities.group).toBe('现场管理')
    expect(DOMAIN_PAGE_CONFIGS.incidents.group).toBe('持续改进')
  })

  it('接入引导都指向蓝本与多维表格配置路径', () => {
    for (const config of Object.values(DOMAIN_PAGE_CONFIGS)) {
      expect(config.guideDescription).toMatch(/飞书多维表格/)
      expect(config.guideDescription).toMatch(/多维表格配置/)
      expect(config.blueprintRef).toMatch(/^DESIGN-安全模块3\.0四期/)
      expect(config.healthNote).toMatch(/warn 判据/)
    }
  })
})

import { describe, expect, it } from 'vitest'
import asset from '@/data/tiji-risk-districts.json'
import { BUILDINGS, BUILDING_FAMILIES, DIST_TO_BUILDING } from './f2-buildings'

// 资产分区（64 平台分区 + 本地补建罐区 9001）必须被 33 栋建筑全部收编，
// 每个分区恰归一栋（含子单元）——丢区或双归属都会让落点数据丢失/重复
describe('f2-buildings 建筑级配置自洽', () => {
  it('33 栋、编号 1-33 连续唯一', () => {
    expect(BUILDINGS).toHaveLength(33)
    expect(BUILDINGS.map(b => b.id)).toEqual(
      Array.from({ length: 33 }, (_, i) => i + 1),
    )
  })

  it('资产全部 distId 恰归一栋建筑（无丢失、无双归属）', () => {
    // 声明总数=资产分区数且声明值无重复 → 恰好一一对应（双归属会让
    // Map 静默覆盖、总数仍对，必须按声明列表数钉）
    const declared = BUILDINGS.flatMap(b => [
      ...b.distIds,
      ...b.subunits.flatMap(su => su.distIds),
    ])
    expect(declared).toHaveLength(asset.districts.length)
    expect(new Set(declared).size).toBe(declared.length)
    expect(DIST_TO_BUILDING.size).toBe(asset.districts.length)
    for (const d of asset.districts) {
      expect(DIST_TO_BUILDING.get(d.distId)).toBeDefined()
    }
    // 配置声明的每个 distId 都真实存在于资产（防手误收编不存在的分区）
    const assetIds = new Set(asset.districts.map(d => d.distId))
    for (const distId of declared) {
      expect(assetIds.has(distId), `配置收编了资产没有的分区 ${distId}`).toBe(true)
    }
  })

  it('雷帕（dist29）数据归 1 号楼（平台几何错位拍板特例）', () => {
    expect(DIST_TO_BUILDING.get('29')).toBe(1)
    expect(BUILDINGS.find(b => b.id === 1)!.distIds).toContain('29')
  })

  it('五个子单元归属正确（27→1 / 28+25→3 / 26→4 / 30→16）', () => {
    expect(DIST_TO_BUILDING.get('27')).toBe(1)
    expect(DIST_TO_BUILDING.get('28')).toBe(3)
    expect(DIST_TO_BUILDING.get('25')).toBe(3)
    expect(DIST_TO_BUILDING.get('26')).toBe(4)
    expect(DIST_TO_BUILDING.get('30')).toBe(16)
  })

  it('每栋必有责任部门、产线明细与已定义色系族', () => {
    for (const b of BUILDINGS) {
      expect(b.depts.length, `建筑 ${b.id} 缺责任部门`).toBeGreaterThan(0)
      expect(b.lines.length, `建筑 ${b.id} 缺产线明细`).toBeGreaterThan(0)
      expect(BUILDING_FAMILIES[b.family], `建筑 ${b.id} 色系族未定义`).toBeTruthy()
    }
  })
})

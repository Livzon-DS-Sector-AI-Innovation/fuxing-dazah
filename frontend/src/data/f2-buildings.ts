/**
 * 厂区风险分区 · 建筑级两级模型配置（2026-10 分区大改；2026-11-06 足迹合并修订）。
 *
 * 权威方案：飞书「建筑级编号对照表」（本地同版备份
 * .scratch/f2-facility-map/分区大改-建筑级方案.md）。
 * 模型：25 栋建筑（图上唯一编号 1-25，一建筑一号）+ 建筑内子单元
 * （产线/部门/回收单元，表格 └ 行、图上随母建筑小号标注）；旧 64 分区按
 * 收编映射归并。26 提三图上无轮廓，本期不做。
 *
 * 2026-11-06 足迹合并（用户拍板「同建筑不能有多个标号」）：平台对同一栋
 * 楼的多次描绘/强重叠轮廓（嵌套≥60% 或互叠≥45%）合并为一栋，被并楼宇转
 * └ 子单元行。33→25 迁移对照：旧1→1，旧2+3→2，旧4+5→3，旧6+9→4，
 * 旧7+10+11→5，旧12+8→6，旧18+31→7，旧19+20→8，旧13→9，旧14→10，
 * 旧15→11，旧16→12，旧17→13，旧21→14，旧22→15，旧23→16，旧24→17，
 * 旧25→18，旧26→19，旧27→20，旧28→21，旧29→22，旧30→23，旧32→24，
 * 旧33→25。
 *
 * 雷帕特例（拍板）：dist29 的平台几何画在旧 2 号楼共用轮廓组——29 的
 * 数据/落点/弹窗归 1 号楼（车间一），渲染不单独画轮廓。
 */

/** 色系族 key（按主责部门归并 11 族；当日有落点用各族 active 色） */
export type BuildingFamilyKey =
  | 'refining1'
  | 'refining2'
  | 'refining4'
  | 'refining5'
  | 'refiningShared'
  | 'fermentation'
  | 'finishing'
  | 'quality'
  | 'warehouse'
  | 'env'
  | 'utility'

export interface BuildingFamily {
  key: BuildingFamilyKey
  /** 图例文字 */
  label: string
  fillBase: string
  fillActive: string
  strokeBase: string
  strokeActive: string
}

/** 色系族（浅底深描，active=当日有落点强调态） */
export const BUILDING_FAMILIES: Record<BuildingFamilyKey, BuildingFamily> = {
  refining1: {
    key: 'refining1', label: '提炼一部',
    fillBase: '#e7eefb', fillActive: '#c7d9f5', strokeBase: '#9fb9e6', strokeActive: '#4f7ecf',
  },
  refining2: {
    key: 'refining2', label: '提炼二部',
    fillBase: '#e4f4f1', fillActive: '#bfe8e1', strokeBase: '#93cfc5', strokeActive: '#3f9e8e',
  },
  refining4: {
    key: 'refining4', label: '提炼四部',
    fillBase: '#e8f4e5', fillActive: '#c9e7c0', strokeBase: '#a0cb92', strokeActive: '#5a9a48',
  },
  refining5: {
    key: 'refining5', label: '提炼五部',
    fillBase: '#eeecfb', fillActive: '#d4cdf4', strokeBase: '#b1a4e2', strokeActive: '#7a62c7',
  },
  refiningShared: {
    key: 'refiningShared', label: '提炼多部共用',
    fillBase: '#ebedf4', fillActive: '#d0d6e6', strokeBase: '#a9b1ca', strokeActive: '#6b78a5',
  },
  fermentation: {
    key: 'fermentation', label: '发酵',
    fillBase: '#fbf2e2', fillActive: '#f3dfb4', strokeBase: '#e0bd74', strokeActive: '#b3862b',
  },
  finishing: {
    key: 'finishing', label: '精制',
    fillBase: '#f8ecef', fillActive: '#efd0d9', strokeBase: '#dea2b1', strokeActive: '#bf5f7b',
  },
  quality: {
    key: 'quality', label: '质控',
    fillBase: '#e4f3f7', fillActive: '#c0e4ed', strokeBase: '#8bc6d7', strokeActive: '#3791ab',
  },
  warehouse: {
    key: 'warehouse', label: '仓储',
    fillBase: '#f4efe7', fillActive: '#e4d7c2', strokeBase: '#c2aa88', strokeActive: '#93693a',
  },
  env: {
    key: 'env', label: '环保',
    fillBase: '#edf2df', fillActive: '#d9e4bd', strokeBase: '#b5c78c', strokeActive: '#7a9145',
  },
  utility: {
    key: 'utility', label: '公用辅助',
    fillBase: '#f0efec', fillActive: '#dcdad5', strokeBase: '#bcbab2', strokeActive: '#87857c',
  },
}

export interface BuildingSubunit {
  /** 子单元名（溶剂回收/工程中心等） */
  name: string
  /** 收编的资产分区 id（数据/落点归子单元所属建筑） */
  distIds: string[]
  /** 子单元责任部门 */
  dept: string
}

export interface BuildingDef {
  /** 图上唯一编号 1-25 */
  id: number
  /** 建筑名称；null=待业务部门命名 */
  name: string | null
  /** 收编的资产分区 id（主体成员；子单元在 subunits 内单独声明） */
  distIds: string[]
  subunits: BuildingSubunit[]
  /** 责任部门（跨部门建筑多值） */
  depts: string[]
  /** 产线/岗位明细（弹窗展示一句话） */
  lines: string
  family: BuildingFamilyKey
}

/** 25 栋建筑定案表（编号/名称/收编/子单元/责任部门/产线明细；空名待业务部门确认） */
export const BUILDINGS: BuildingDef[] = [
  {
    id: 1,
    name: '车间一',
    distIds: ['1', '11', '29'],
    // 29=提四雷帕：几何在旧 2 号楼共用轮廓组（数据归本楼、不单独画轮廓）
    subunits: [{ name: '异丙醇回收', distIds: ['27'], dept: '提炼工程四部' }],
    depts: ['提炼工程五部'],
    lines: '达托（一楼/二楼结晶）、达巴（三楼制备/粗提/合成）、雷帕/子囊（四楼，拍板归本楼）；中控室、制水岗在本楼',
    family: 'refining5',
  },
  {
    id: 2,
    name: '车间二',
    distIds: ['9', '21', '22', '23', '24', '10', '4'],
    subunits: [{ name: '乙腈回收＋丙醇回收', distIds: ['28', '25'], dept: '提炼工程四部' }],
    depts: ['提炼工程四部', '提炼工程五部', '提炼工程六部'],
    lines: '两栋连体：达托新线楼（五部；雷帕/子囊、氟雷/艾默共线、莫西、阿福＝四部）＋达巴新线＋非达楼（五部）＋替考楼（六部，四楼防火三洁净区）',
    family: 'refiningShared',
  },
  {
    id: 3,
    name: null,
    distIds: ['7', '20'],
    subunits: [{ name: '乙醇回收', distIds: ['26'], dept: '提炼工程四部' }],
    depts: ['提炼工程四部'],
    lines: '米尔贝肟（二楼合成、三楼层析＋合成、粗提/精制/高规）＋塞拉；米贝＝精制段（同楼）',
    family: 'refining4',
  },
  {
    id: 4,
    name: null,
    distIds: ['53', '63', '54', '60'],
    subunits: [],
    depts: ['提炼工程一部', '提炼工程二部'],
    lines: '万古A线离交/精制（一部）；庆大（二楼）、多黏（四楼）＝二部产线（跨部门）',
    family: 'refining1',
  },
  {
    id: 5,
    name: null,
    distIds: ['61', '65', '64', '67', '41'],
    subunits: [],
    depts: ['提炼工程一部', '提炼技术精进中心'],
    lines: '万古B线离交/精制/纯化、成盐；提炼技术精进中心在楼内',
    family: 'refining1',
  },
  {
    id: 6,
    name: null,
    distIds: ['75', '72', '66', '59', '56', '55', '62'],
    subunits: [],
    depts: ['提炼工程二部', '提炼工程一部'],
    lines: '妥布粗提/精制、庆大/磺黏共线粗提、黏干/阿卡、酸化过滤（二部）；万古C线离交（一部，平台几何在本楼内待核）',
    family: 'refining2',
  },
  {
    id: 7,
    name: null,
    distIds: ['6', '5', '31'],
    subunits: [],
    depts: ['质量控制部（QC部）', '检测组', '菌种中心', '行政后勤部'],
    lines: 'QC（试剂间）、检测组、菌种中心；办公室在楼内（行政后勤部）',
    family: 'quality',
  },
  {
    id: 8,
    name: null,
    distIds: ['38', '43', '44'],
    subunits: [],
    depts: ['仓储部'],
    lines: '原辅料库＋成品包材库（同楼）、仓储部成品仓',
    family: 'warehouse',
  },
  {
    id: 9,
    name: '罐区',
    distIds: ['9001'],
    subunits: [],
    depts: ['提炼工程四部'],
    lines: '溶媒回收罐区（溶剂储罐1#-22#、槽车卸车点、新罐区/旧罐区）',
    family: 'refining4',
  },
  {
    id: 10,
    name: '接罐站',
    distIds: ['48'],
    subunits: [],
    depts: ['提炼工程一部', '提炼工程二部', '提炼工程五部'],
    lines: '万古b/c线接罐站、达托离交接罐站（一二楼）、提二接罐站',
    family: 'refiningShared',
  },
  {
    id: 11,
    name: '发酵车间',
    distIds: ['12', '14', '15', '16', '17', '19'],
    subunits: [],
    depts: ['发酵工程部'],
    lines: '发酵一部（101-112三楼/201-213二楼）、发酵工程部（301-325/401-402·万古线）；配料/消毒/机修/化验/工艺/值班',
    family: 'fermentation',
  },
  {
    id: 12,
    name: null,
    distIds: ['73', '70', '69', '68'],
    subunits: [{ name: '半合成工程中心', distIds: ['30'], dept: '提炼半合成工程中心' }],
    depts: ['精制工程一部'],
    lines: '1#/2#/3#冻干线（含3#无菌线）、喷雾塔（四楼）',
    family: 'finishing',
  },
  {
    id: 13,
    name: null,
    distIds: ['74', '71'],
    subunits: [],
    depts: ['精制工程一部'],
    lines: '小喷（一楼冻干机房）、E#冻干线',
    family: 'finishing',
  },
  {
    id: 14,
    name: '危化品库',
    distIds: ['37'],
    subunits: [],
    depts: ['仓储部'],
    lines: '危化品（三楼?）；危废库（危库二/三）属仓储、待建模',
    family: 'warehouse',
  },
  {
    id: 15,
    name: '环保水处理',
    distIds: ['2'],
    subunits: [],
    depts: ['环保工程中心'],
    lines: 'A/C池气浮、SBR、雨水收集池、高浓废水罐',
    family: 'env',
  },
  {
    id: 16,
    name: '环保RTO',
    distIds: ['3'],
    subunits: [],
    depts: ['环保工程中心'],
    lines: '废气处理（一期/发酵背后）',
    family: 'env',
  },
  {
    id: 17,
    name: '环保固废',
    distIds: ['51'],
    subunits: [],
    depts: ['环保工程中心'],
    lines: '一般固废仓库',
    family: 'env',
  },
  {
    id: 18,
    name: '环保化验室',
    distIds: ['50'],
    subunits: [],
    depts: ['环保工程中心'],
    lines: '二楼化验室',
    family: 'env',
  },
  {
    id: 19,
    name: '环保水热矿化',
    distIds: ['52'],
    subunits: [],
    depts: ['环保工程中心'],
    lines: '水热矿化（硝酸卸车）',
    family: 'env',
  },
  {
    id: 20,
    name: '空冷班组（动力）',
    distIds: ['76'],
    subunits: [],
    depts: ['动力部'],
    lines: '动力车间、新动力车间、综合泵房、空压站、冷却塔、制水',
    family: 'utility',
  },
  {
    id: 21,
    name: '消防控制室',
    distIds: ['77'],
    subunits: [],
    depts: ['安全工程中心'],
    lines: '消控室（仅消防；「中控室」＝1 号楼车间一中控）',
    family: 'utility',
  },
  {
    id: 22,
    name: '配电房',
    distIds: ['45'],
    subunits: [],
    depts: ['设备工程部'],
    lines: '配电',
    family: 'utility',
  },
  {
    id: 23,
    name: '仪表',
    distIds: ['47'],
    subunits: [],
    depts: ['设备工程部'],
    lines: '仪表',
    family: 'utility',
  },
  {
    id: 24,
    name: '食堂',
    distIds: ['33'],
    subunits: [],
    depts: ['行政后勤部'],
    lines: '食堂',
    family: 'utility',
  },
  {
    id: 25,
    name: '配酸碱配制',
    distIds: ['49'],
    subunits: [],
    depts: ['提炼工程二部'],
    lines: '提一/提二共用浓配区（外围卸酸）',
    family: 'refining2',
  },
]

/** distId（资产分区 id，含子单元）→ 建筑编号；资产 65 分区全覆盖、恰归一栋 */
export const DIST_TO_BUILDING: ReadonlyMap<string, number> = new Map(
  BUILDINGS.flatMap(b => [
    ...b.distIds,
    ...b.subunits.flatMap(su => su.distIds),
  ].map(distId => [distId, b.id] as const)),
)

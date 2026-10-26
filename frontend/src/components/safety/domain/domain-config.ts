/**
 * 四新域页面配置（3.0 四期 1-C）——「空态即设计」的口径载体。
 * goals 已改走体系标准核查引擎（components/safety/goals，2026-10-21）。
 *
 * 每域：统计卡（key=后端 stats 键）、台账列（dataIndex=蓝本英文字段）、
 * 面包屑分组（=menu-config 分组名）、健康度口径说明与接入引导文案。
 * 字段唯一事实源：docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md。
 */
import type { Tone } from '@/components/ui-kit'
import type { DomainPageKey } from '@/lib/api/safety/domain-pages'

export interface DomainStatCardConfig {
  /** 后端 stats 键（蓝本统计口径英文字段） */
  key: string
  label: string
  tone: Tone
  /** 值后缀（如 %） */
  unit?: string
  /** 未接入/无值时的说明 */
  hint: string
}

export interface DomainColumnConfig {
  title: string
  /** 蓝本主台账英文字段 */
  dataIndex: string
  width?: number
}

export interface DomainSecondaryLedgerConfig {
  /** 副台账区块标题（如「违章行为档案」） */
  title: string
  description: string
  columns: DomainColumnConfig[]
  /** 行详情 Drawer 附加字段（表格未展示的列；配置后行可点击） */
  detailFields?: DomainColumnConfig[]
}

export interface DomainPageConfig {
  key: DomainPageKey
  /** 页面标题（菜单同名） */
  title: string
  /** 菜单分组名（面包屑第二段） */
  group: string
  description: string
  statCards: DomainStatCardConfig[]
  ledgerTitle: string
  ledgerDescription: string
  columns: DomainColumnConfig[]
  /** 副台账区块（后端 secondary_ledger；无则本域无副台账） */
  secondaryLedger?: DomainSecondaryLedgerConfig
  /** 本域健康度口径说明（ok/warn 判据） */
  healthNote: string
  /** 未接入时的建表引导 */
  guideDescription: string
  /** 蓝本章节引用（引导文案内注明） */
  blueprintRef: string
}

export const DOMAIN_PAGE_CONFIGS: Record<DomainPageKey, DomainPageConfig> = {
  'training-behavior': {
    key: 'training-behavior',
    title: '教育培训与行为管控',
    group: '人员管理',
    description: '培训计划、实施与签到台账；复训追踪；违章行为档案与纠正闭环',
    statCards: [
      { key: 'training_total', label: '年度培训场次', tone: 'default', hint: '当年非取消场次' },
      { key: 'completion_rate', label: '培训完成率', tone: 'default', unit: '%', hint: '已完成/(未开始+进行中+已完成)' },
      { key: 'pass_rate', label: '考核合格率', tone: 'ok', unit: '%', hint: '考试场次合格/实到' },
      { key: 'retraining_due_30d', label: '待复训(30天内)', tone: 'warn', hint: '下次复训日期 30 天内' },
      { key: 'violation_total', label: '年度违章次数', tone: 'warn', hint: '当年违章登记数' },
      { key: 'violation_open', label: '违章未纠正', tone: 'danger', hint: '状态=纠正中（预警）' },
    ],
    ledgerTitle: '培训计划与实施台账',
    ledgerDescription: '主台账=培训计划与实施表；违章行为档案见下方区块',
    columns: [
      { title: '培训名称', dataIndex: 'name', width: 200 },
      { title: '培训类别', dataIndex: 'category', width: 110 },
      { title: '计划日期', dataIndex: 'planned_at', width: 110 },
      { title: '实施日期', dataIndex: 'held_at', width: 110 },
      { title: '讲师', dataIndex: 'lecturer', width: 90 },
      { title: '实到人数', dataIndex: 'actual_count', width: 90 },
      { title: '考核方式', dataIndex: 'assessment', width: 90 },
      { title: '状态', dataIndex: 'status', width: 80 },
      { title: '下次复训', dataIndex: 'next_retraining_at', width: 110 },
    ],
    secondaryLedger: {
      title: '违章行为档案',
      description: '全量含跨年（客户端分页）；未纠正行计入统计卡预警，纠正闭环在飞书侧维护',
      columns: [
        { title: '违章日期', dataIndex: 'occurred_at', width: 100 },
        { title: '违章人员', dataIndex: 'person_name', width: 90 },
        { title: '所属单位', dataIndex: 'department', width: 110 },
        { title: '违章类别', dataIndex: 'category', width: 90 },
        { title: '违章等级', dataIndex: 'level', width: 80 },
        { title: '违章描述', dataIndex: 'description', width: 260 },
        { title: '处理方式', dataIndex: 'handling', width: 90 },
        { title: '状态', dataIndex: 'status', width: 80 },
        { title: '关联隐患编号', dataIndex: 'related_hazard_no', width: 120 },
      ],
      detailFields: [
        { title: '纠正措施', dataIndex: 'corrective_action' },
        { title: '定向培训要点卡', dataIndex: 'retraining_note' },
        { title: '证据附件', dataIndex: 'evidence_files' },
        { title: 'AI判级建议', dataIndex: 'ai_level_suggestion' },
        { title: '备注', dataIndex: 'note' },
      ],
    },
    healthNote: 'warn 判据：违章未纠正>0，或培训计划逾期未实施；ok 判据：违章全部纠正且无逾期计划',
    guideDescription:
      '在飞书多维表格按蓝本字段建立「培训计划与实施/违章行为档案」两张表，' +
      '经系统配置 → 多维表格配置为对应表配好连接后，本页自动出数（页面零改码）',
    blueprintRef: 'DESIGN-安全模块3.0四期-四新域表结构与页面口径 §3',
  },
  facilities: {
    key: 'facilities',
    title: '设备设施管理',
    group: '现场管理',
    description: '设备设施安全台账；检验/校验到期督办；安全设施完好性监控',
    statCards: [
      { key: 'equipment_total', label: '设备总数', tone: 'default', hint: '在用设备（不含报废）' },
      { key: 'special_equipment', label: '特种设备', tone: 'info', hint: '类别=特种设备' },
      { key: 'inspection_overdue', label: '检验逾期', tone: 'danger', hint: '下次检验日期已过（预警）' },
      { key: 'inspection_due_30d', label: '30天内到期', tone: 'warn', hint: '下次检验日期 30 天内' },
      { key: 'inspection_pass_rate', label: '检验合格率', tone: 'ok', unit: '%', hint: '各设备最近一次检验合格占比' },
      { key: 'inactive_equipment', label: '停用/维修中', tone: 'default', hint: '状态=停用或维修中' },
    ],
    ledgerTitle: '设备设施台账',
    ledgerDescription: '主台账=设备设施台账表；检验校验记录见下方区块',
    columns: [
      { title: '设备编号', dataIndex: 'equipment_no', width: 110 },
      { title: '设备名称', dataIndex: 'name', width: 160 },
      { title: '设备类别', dataIndex: 'category', width: 110 },
      { title: '位置/区域', dataIndex: 'location', width: 120 },
      { title: '责任部门', dataIndex: 'department', width: 130 },
      { title: '责任人', dataIndex: 'owner', width: 90 },
      { title: '设备状态', dataIndex: 'status', width: 90 },
    ],
    secondaryLedger: {
      title: '检验校验记录',
      description: '检验逾期/到期统计见上方统计卡；本表为逐台记录（接入后零改码出数）',
      columns: [
        { title: '设备编号', dataIndex: 'equipment_no', width: 110 },
        { title: '设备名称', dataIndex: 'equipment_name', width: 150 },
        { title: '检验类别', dataIndex: 'category', width: 100 },
        { title: '上次检验日期', dataIndex: 'last_inspected_at', width: 110 },
        { title: '下次检验日期', dataIndex: 'next_inspected_at', width: 110 },
        { title: '检验机构', dataIndex: 'agency', width: 140 },
        { title: '检验结果', dataIndex: 'result', width: 90 },
      ],
      detailFields: [
        { title: '检验周期（月）', dataIndex: 'cycle_months' },
        { title: '报告附件', dataIndex: 'report_file' },
        { title: '备注', dataIndex: 'note' },
      ],
    },
    healthNote: 'warn 判据：存在检验逾期的设备；ok 判据：无逾期（30 天内到期仅提示）',
    guideDescription:
      '在飞书多维表格按蓝本字段建立「设备设施台账/检验校验记录」两张表，' +
      '经系统配置 → 多维表格配置为对应表配好连接后，本页自动出数（页面零改码）',
    blueprintRef: 'DESIGN-安全模块3.0四期-四新域表结构与页面口径 §4',
  },
  incidents: {
    key: 'incidents',
    title: '事故事件管理',
    group: '持续改进',
    description: '事故与事件登记、分级与调查跟踪；CAPA 措施闭环监控',
    statCards: [
      { key: 'incident_total', label: '年度事件总数', tone: 'default', hint: '当年登记的全部事件' },
      { key: 'accident_count', label: '其中事故', tone: 'danger', hint: '类别=事故' },
      { key: 'near_miss_count', label: '未遂事件', tone: 'warn', hint: '类别=未遂事件' },
      { key: 'investigating_count', label: '调查中', tone: 'info', hint: '状态=调查中' },
      { key: 'capa_open', label: 'CAPA 未闭环', tone: 'warn', hint: '进行中+已逾期' },
      { key: 'capa_overdue', label: 'CAPA 逾期', tone: 'danger', hint: '状态=已逾期（预警）' },
    ],
    ledgerTitle: '事故事件登记台账',
    ledgerDescription: '主台账=事故事件登记表；CAPA 措施跟踪见下方区块',
    columns: [
      { title: '事件编号', dataIndex: 'incident_no', width: 110 },
      { title: '发生日期', dataIndex: 'occurred_at', width: 110 },
      { title: '事发地点', dataIndex: 'location', width: 120 },
      { title: '事发部门', dataIndex: 'department', width: 130 },
      { title: '事件类别', dataIndex: 'category', width: 100 },
      { title: '事件等级', dataIndex: 'level', width: 100 },
      { title: '伤亡人数', dataIndex: 'casualty_count', width: 90 },
      { title: '直接损失(万)', dataIndex: 'direct_loss', width: 110 },
      { title: '状态', dataIndex: 'status', width: 90 },
    ],
    secondaryLedger: {
      title: 'CAPA 措施跟踪',
      description: '未闭环/逾期统计见上方统计卡；本表为逐条措施（接入后零改码出数）',
      columns: [
        { title: '关联事件编号', dataIndex: 'incident_no', width: 120 },
        { title: '措施类型', dataIndex: 'type', width: 90 },
        { title: '措施描述', dataIndex: 'description', width: 220 },
        { title: '责任部门', dataIndex: 'department', width: 120 },
        { title: '责任人', dataIndex: 'owner', width: 90 },
        { title: '完成期限', dataIndex: 'deadline', width: 110 },
        { title: '完成日期', dataIndex: 'completed_at', width: 110 },
        { title: '验证结果', dataIndex: 'verify_result', width: 90 },
        { title: '状态', dataIndex: 'status', width: 90 },
      ],
      detailFields: [
        { title: '验证人', dataIndex: 'verifier' },
        { title: '备注', dataIndex: 'note' },
      ],
    },
    healthNote: 'warn 判据：CAPA 逾期>0，或调查中超 30 天未结案；ok 判据：CAPA 无逾期',
    guideDescription:
      '在飞书多维表格按蓝本字段建立「事故事件登记/CAPA 措施跟踪」两张表，' +
      '经系统配置 → 多维表格配置为对应表配好连接后，本页自动出数（页面零改码）',
    blueprintRef: 'DESIGN-安全模块3.0四期-四新域表结构与页面口径 §5',
  },
}

export function getDomainConfig(domain: DomainPageKey): DomainPageConfig {
  return DOMAIN_PAGE_CONFIGS[domain]
}

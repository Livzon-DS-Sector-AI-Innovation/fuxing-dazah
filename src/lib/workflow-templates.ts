/**
 * 内置 AI 工作流模板 —— 单一数据源
 *
 * - AIWorkflowConfigClient（配置页）：合并 DB 记录时作为 fallback
 * - 危险源辨识详情页（业务页）：派生 WORKFLOW_STEPS 展示步骤信息
 * - 特殊作业等其他模块：获取对应工作流的步骤定义
 *
 * 新增/修改工作流只需维护这一个文件。
 */
import type { WorkflowStepItem } from '@/types/safety'

// ═══════════════════════════════════════════
// 类型
// ═══════════════════════════════════════════

export interface BuiltInWorkflow {
  module_code: string
  workflow_name: string
  workflow_description: string
  trigger_event: string
  icon: string // emoji
  script_configs: WorkflowStepItem[]
}

/** 精简后的步骤信息，供详情页 Steps 组件使用 */
export interface WorkflowStepInfo {
  num: number
  title: string
  desc: string
  expected_keys: string[]
}

// ═══════════════════════════════════════════
// 暂不开放的 AI 工作流 module_code
// ═══════════════════════════════════════════

export const EXCLUDED_MODULE_CODES = new Set([
  'regulation-revision',   // 操规AI修订管道（未开发）
])

// ═══════════════════════════════════════════
// 工作流模板数据
// ═══════════════════════════════════════════

export const BUILT_IN_WORKFLOWS: BuiltInWorkflow[] = [
  {
    module_code: 'hazard-identification',
    workflow_name: '危险源辨识AI工作流',
    workflow_description:
      '7步AI危险源辨识与风险评价：附件解析→危险源辨识→固有风险评价→现有控制措施→残余风险评价→建议措施→措施后风险评价',
    trigger_event: 'submit',
    icon: '🤖',
    script_configs: [
      {
        script_number: 1,
        name: '附件解析',
        is_enabled: true,
        expected_keys: ['specific_activity', 'equipment_facilities', 'raw_auxiliary_materials'],
        input_info: '从用户提交的表单和上传的SOP/操作规程附件中提取文本内容。读取：部门、岗位、生产步骤（人工填写）、岗位资料附件（人工上传）。若附件无法读取则不执行并说明原因。',
        work_rules: '1. 仅提取与当前岗位、当前生产步骤直接相关的信息，不做跨岗位泛化\n2. 仅基于附件文本和知识库提取，不得编造未出现的信息\n3. 本步骤仅提取基础作业信息，不进行危险源识别或风险判断\n4. 每条提取结果需附依据来源\n5. 信息不足时填写「待人工确认」\n6. 不擅自修改、推断或美化原文内容',
        reference_docs: '企业岗位操作规程（用户上传附件）\nGB/T 13861-2022《生产过程危险和有害因素分类与代码》\n企业知识库：产品一览表、建（构）筑物一览表、安全管理制度清单',
        output_format: '{"specific_activity":"作业活动名称及操作过程描述","equipment_facilities":"涉及的主要设备设施","raw_auxiliary_materials":"涉及的原辅料（含危化品、蒸汽、氮气等）"}',
      },
      {
        script_number: 2,
        name: '危险源辨识',
        is_enabled: true,
        expected_keys: ['hazard_type', 'possible_accident', 'unsafe_behavior'],
        input_info: '工作流1输出经人工审核确认后读取：部门、岗位、生产步骤、岗位资料附件（人工）、具体作业活动、设备设施、原辅料（工作流1+人工确认）。',
        work_rules: '1. 从「人、机、料、法、环」五个维度系统辨识危险源\n   - 人：不安全行为、操作失误、疲劳、无证上岗等\n   - 机：设备故障、防护缺失、安全装置失效等\n   - 料：危险化学品、高温/高压介质、易燃易爆物质等\n   - 法：操作规程缺陷、管理制度缺失、培训不足等\n   - 环：照明不良、噪声、高温、有毒气体、作业空间受限等\n2. 依据GB 6441确定危险类型（物体打击、机械伤害、触电、灼烫、火灾、高处坠落、容器爆炸、中毒和窒息等）\n3. 判断可能导致的最典型事故类型\n4. 描述人的不规范作业行为表现（与当前岗位、当前操作直接对应）\n5. 仅基于表格字段与知识库，不输出无依据内容\n6. 信息不足时填写「待人工确认」',
        reference_docs: 'GB 6441-1986《企业职工伤亡事故分类》\nGB/T 13861-2022《生产过程危险和有害因素分类与代码》\n《危险化学品企业安全风险隐患排查治理导则》\n企业风险分级管控管理制度\n企业岗位操作规程',
        output_format: '{"hazard_type":"按GB 6441分类的危险类型","possible_accident":"可能导致的典型事故","unsafe_behavior":"人的不规范作业行为表现"}',
      },
      {
        script_number: 3,
        name: '固有风险评价',
        is_enabled: true,
        expected_keys: ['l_inherent', 'e_inherent', 'c_inherent', 'd_inherent', 'inherent_risk_level', 'inherent_risk_label'],
        input_info: '工作流2输出经人工审核确认后读取：部门、岗位、生产步骤（人工）、具体作业活动、设备设施、原辅料（人工）、危险类型、可能导致事故、不规范作业行为表现（工作流2+人工确认）。',
        work_rules: '1. 采用LEC法，公式 D = L × E × C\n2. 仅评价「未考虑任何现有控制措施前」的固有风险，不得将现有控制措施纳入评分\n3. 评分依据：\n   - L（可能性，0.1~10）：结合岗位、作业活动、危险类型评估事故发生概率\n   - E（暴露频率，0.5~10）：结合作业频次、接触时长评估人员暴露程度\n   - C（严重性，1~100）：结合事故类型、设备设施、原辅料评估后果严重程度\n4. 如知识库中已有LEC评分标准与风险分级标准，优先按知识库标准执行\n5. 风险等级判定：D≥320→level_1（重大）、160≤D<320→level_2（较大）、70≤D<160→level_3（一般）、D<70→level_4（低）\n6. 若L、E、C任一字段无法判定，填写「待人工确认」，此时D值和风险等级也填「待人工确认」\n7. 必须基于人工确认后的危险源信息进行评价',
        reference_docs: 'LEC风险评价法标准（格雷厄姆-金尼法）\n企业风险分级管控管理制度\n企业知识库：危险有害因素辨识结果表',
        output_format: '{"l_inherent":3,"e_inherent":6,"c_inherent":15,"d_inherent":270,"inherent_risk_level":"level_1","inherent_risk_label":"重大风险"}',
      },
      {
        script_number: 4,
        name: '现有控制措施',
        is_enabled: true,
        expected_keys: ['existing_engineering_controls', 'existing_management_controls', 'existing_ppe', 'existing_emergency_measures'],
        input_info: '工作流3输出经人工审核确认后读取：全部前置人工字段、L/E/C/D（固有）、固有风险等级（工作流3+人工确认）。',
        work_rules: '1. 仅识别和提取当前岗位、当前生产步骤、当前危险源已存在的控制措施\n2. 不输出建议新增措施，不输出优化措施，仅输出当前已存在、可从资料中获得依据的措施\n3. 四个维度：\n   - 工程控制措施：通风、联锁、报警、防护装置、隔离、泄压、接地、检测等\n   - 管理控制措施：规程、培训、巡检、作业许可、交接班、警示标识、制度管理等\n   - 个人防护措施（PPE）：防护装备、佩戴要求、使用要求\n   - 应急措施：事故应急处置流程、现场应急器材配置、报警与撤离要求、急救处置等\n4. 每项措施尽量附简要依据来源\n5. 信息不足时填写「待人工确认」\n6. 必须基于人工确认后的危险源和固有风险信息进行分析',
        reference_docs: 'AQ/T 4234《职业病危害监察导则》\n企业PPE配置标准\n企业安全管理制度汇编（安全操作规程、特殊作业管理制度、巡检制度等）\n企业应急预案及应急处置卡\n企业知识库：工艺设施安全检查表',
        output_format: '{"existing_engineering_controls":"具体工程措施及依据","existing_management_controls":"具体管理措施及依据","existing_ppe":"具体PPE配置及佩戴要求","existing_emergency_measures":"具体应急措施及器材配置"}',
      },
      {
        script_number: 5,
        name: '残余风险评价',
        is_enabled: true,
        expected_keys: ['l_residual', 'e_residual', 'c_residual', 'd_residual', 'residual_risk_level', 'residual_risk_label'],
        input_info: '工作流4输出经人工审核确认后读取：全部前置人工字段、L/E/C/D（固有）、固有风险等级（人工确认）、现有工程/管理/PPE/应急控制措施（工作流4+人工确认）。',
        work_rules: '1. 评价「现有控制措施全部纳入考虑后」的残余风险\n2. 不得假设未填写、未体现、未确认的控制措施已经实施\n3. 不得无依据过度降低风险\n4. L（残余）：优先考虑工程控制、联锁、防护、隔离、自动化、报警、管理、培训等对事故发生可能性的削减作用；若措施能明显降低概率则可合理下降，否则保持与固有一致\n5. E（残余）：结合措施对人员接触频次、暴露时长、暴露范围的影响判断\n6. C（残余）：仅当现有措施能明确降低事故后果严重程度时才可下降；若措施主要作用于预防而不能减轻后果，C保持与固有一致\n7. 残余风险通常不应高于固有风险\n8. 个人防护措施通常优先影响后果严重性或局部暴露，不应替代工程控制和管理控制\n9. 应急措施主要用于降低事故扩大后果，不应直接大幅降低事故发生可能性\n10. 信息不足时填写「待人工确认」',
        reference_docs: 'LEC风险评价法标准\n企业风险分级管控管理制度\n企业知识库：危险有害因素辨识结果表',
        output_format: '{"l_residual":1,"e_residual":3,"c_residual":15,"d_residual":45,"residual_risk_level":"level_4","residual_risk_label":"低风险"}',
      },
      {
        script_number: 6,
        name: '建议措施',
        is_enabled: true,
        expected_keys: ['needs_recommendation', 'recommendation_type', 'recommendation_content', 'recommendation_priority'],
        input_info: '工作流5输出经人工审核确认后读取：全部前置人工字段、L/E/C/D（残余）、残余风险等级（工作流5+人工确认）、管控等级（人工）。',
        work_rules: '风险控制层级（优先顺序）：消除/替代 → 工程控制 → 管理控制 → 个体防护 → 应急优化\n\n是否需提出建议措施（needs_recommendation）：\n- 残余风险level_1或level_2：原则上必须提出建议措施 →「是」\n- 残余风险level_3且现有措施存在明显缺口 →「是」\n- 残余风险level_4且现有措施充分 → 可输出「否」\n- 依据不足 →「待人工确认」\n\n建议措施类型（recommendation_type）：消除/替代、工程控制、管理控制、个体防护、应急处置优化（一种或多种）\n\n建议措施内容（recommendation_content）：\n1. 必须具体、可执行、与当前危险源直接相关\n2. 不得空泛表述（如「加强管理」「注意安全」）\n3. 优先考虑消除或替代危险源\n4. 不得重复输出已存在且有效的现有控制措施\n5. 依据不足 →「待人工确认」\n\n建议措施优先级（recommendation_priority）：\n- 高：重大风险、高风险或可能导致严重事故\n- 中：较大风险或需尽快完善控制\n- 低：一般风险且仅需局部优化',
        reference_docs: 'GB/T 12801-2008《生产过程安全卫生要求总则》\nGB 5083-2023《生产设备安全卫生设计总则》\nHG 20571-2014《化工企业安全卫生设计规范》\n企业风险分级管控管理制度\n行业最佳实践、同类企业事故教训',
        output_format: '{"needs_recommendation":"是","recommendation_type":"工程控制、管理控制","recommendation_content":"具体可执行的建议措施内容","recommendation_priority":"高"}',
      },
      {
        script_number: 7,
        name: '措施后风险评价',
        is_enabled: true,
        expected_keys: ['l_post', 'e_post', 'c_post', 'd_post', 'post_risk_level', 'post_risk_label'],
        input_info: '工作流6输出经人工审核确认后读取：全部前置人工字段、L/E/C/D（残余）、残余风险等级（人工确认）、管控等级（人工）、建议措施内容（工作流6+人工确认）。',
        work_rules: '1. 仅评价「现有控制措施 + 已采纳建议措施」共同作用下的风险水平\n2. 不得假设未填写、未确认、不可执行的建议措施已经有效落地\n3. 仅将明确采纳、明确实施的措施纳入评价\n4. L（措施后）：结合已实施建议措施对事故发生可能性的进一步削减作用判断；优先考虑消除/替代、工程改造、联锁、自动化等对概率的影响\n5. E（措施后）：结合建议措施对人员接触频次、暴露时长、暴露范围的进一步降低作用判断\n6. C（措施后）：仅当建议措施能明确降低事故后果严重程度时才可下降；若主要作用于预防而不能减轻后果，C保持与残余一致\n7. 措施后风险通常不应高于原残余风险\n8. 风险下降幅度应与建议措施的类型、针对性、实施深度相匹配\n9. 不得仅因「提出了建议」就默认风险下降\n10. 个体防护和应急优化通常不能替代消除、替代、工程控制和管理控制的核心作用\n11. 信息不足时填写「待人工确认」',
        reference_docs: 'LEC风险评价法标准\n企业风险分级管控管理制度\n企业风险管控层级规定\nGB/T 12801-2008《生产过程安全卫生要求总则》',
        output_format: '{"l_post":1,"e_post":2,"c_post":7,"d_post":14,"post_risk_level":"level_4","post_risk_label":"低风险"}',
      },
    ],
  },
  {
    module_code: 'hazard',
    workflow_name: '隐患排查AI工作流',
    workflow_description:
      '2步AI隐患分析（自动执行）：创建隐患后自动调用视觉模型识别隐患 → 文本模型生成整改建议 → 台账中人工审核',
    trigger_event: 'create',
    icon: '🔍',
    script_configs: [
      {
        script_number: 1,
        name: 'AI隐患识别',
        description: 'AI分析缺陷图片，自动识别隐患类型、等级、类别、描述和重点缺陷',
        is_enabled: true,
        expected_keys: ['hazard_type', 'hazard_level', 'hazard_category', 'description', 'location', 'key_defect', 'major_hazard_basis'],
        input_info: '从用户提交的表单和上传的缺陷图片中提取信息。读取：部门、地点、缺陷图片、检查类别。若图片无法读取则不执行并说明原因。',
        work_rules: '1. 基于图片内容+上下文，按GB/T 13861-2022和化工企业隐患分类标准识别隐患\n2. 从「人、物、环、管」四个维度判断隐患分类（hazard_type）\n3. 判定隐患等级（hazard_level）：重大/较大/一般\n4. 确定隐患类别（hazard_category）\n5. 生成隐患描述（description）：客观、具体、包含位置+缺陷+风险\n6. 识别重点缺陷（key_defect）\n7. 所有隐患都必须提供判定依据（major_hazard_basis），说明判定理由和参照标准\n8. 仅基于图片内容和已填写信息，不编造\n9. 信息不足时填写「待人工确认」',
        reference_docs: 'GB/T 13861-2022《生产过程危险和有害因素分类与代码》\n《危险化学品企业安全风险隐患排查治理导则》\n《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准》\n企业安全管理制度汇编\n企业安全检查标准',
        output_format: '{"hazard_type":"unsafe_condition","hazard_level":"major","hazard_category":"equipment","description":"具体隐患描述","location":"具体部位","key_defect":"关键缺陷","major_hazard_basis":"重大隐患判定依据或空"}',
      },
      {
        script_number: 2,
        name: 'AI整改建议',
        description: 'AI基于已识别的隐患信息，自动生成针对性管控措施和纠正预防措施',
        is_enabled: true,
        expected_keys: ['corrective_preventive_measures'],
        input_info: '读取步骤1输出（经人工审核确认后）：隐患分类、等级、类别、描述、地点、重点缺陷。',
        work_rules: '1. 基于已识别的隐患信息，生成针对性整改措施\n2. 纠正预防措施（corrective_preventive_measures）：根本性整改方案\n   - 纠正措施：修复、更换、改造具体缺陷\n   - 预防措施：防止同类隐患再次发生的系统性措施\n3. 措施必须具体、可执行、与隐患直接相关\n4. 不得空泛表述（如「加强管理」「注意安全」）\n5. 重大隐患须明确整改措施的具体要求\n6. 信息不足时填写「待人工确认」',
        reference_docs: 'GB/T 12801-2008《生产过程安全卫生要求总则》\nHG 20571-2014《化工企业安全卫生设计规范》\n企业安全管理制度汇编\n企业应急预案及应急处置卡\n行业最佳实践',
        output_format: '{"corrective_preventive_measures":"具体纠正预防措施"}',
      },
    ],
  },
  {
    module_code: 'special-ops-critical',
    workflow_name: 'AI关键作业判定',
    workflow_description:
      '特殊作业报备提交时自动识别是否属于关键作业（动火/受限空间/高处/吊装），辅助安全管理人员快速分级审批',
    trigger_event: 'submit',
    icon: '🏗️',
    script_configs: [
      {
        script_number: 1,
        name: 'AI关键作业判定',
        input_info:
          '## 报备信息\n' +
          '从特殊作业报备中获取以下信息：\n' +
          '- 作业类型（动火/受限空间/高处/吊装/临时用电/盲板抽堵/动土/断路）\n' +
          '- 作业级别（特级/一级/二级）\n' +
          '- 作业地点\n' +
          '- 作业部门\n' +
          '- 作业内容描述\n' +
          '- 风险等级\n' +
          '- 安全措施\n' +
          '- 风险评估\n' +
          '- 应急消防器材配置',
        work_rules:
          '## 任务\n' +
          '判定当前特殊作业报备是否属于「关键风险作业」。\n\n' +
          '## 判定标准（参照 GB 30871-2022）\n' +
          '1. 特级或一级动火作业\n' +
          '2. 受限空间内涉及易燃易爆、有毒有害介质的作业\n' +
          '3. 30米以上的高处作业\n' +
          '4. 涉及重大危险源的临时用电\n' +
          '5. 涉及有毒有害、易燃易爆介质的盲板抽堵\n' +
          '6. 超过5米的深基坑动土作业\n' +
          '7. 大型或特大型起重吊装（100吨以上或非常规起重）\n' +
          '8. 涉及有毒有害、易燃易爆介质的管线打开\n' +
          '9. 两个及以上特殊作业类型的交叉作业\n' +
          '10. 风险等级为一级或二级的高风险作业\n\n' +
          '## 约束\n' +
          '- 仅基于报备中已填写的信息进行判定，不得编造未提供的信息\n' +
          '- 信息不足时倾向于不判定为关键作业\n' +
          '- 遵循保守原则：不确定时不判定为关键作业\n' +
          '- 你是一名化工安全专家，严格按照 GB 30871-2022 标准判定',
        reference_docs:
          '## 参考标准\n' +
          '- GB 30871-2022《危险化学品企业特殊作业安全规范》\n' +
          '- 企业特殊作业安全管理制度\n' +
          '- 企业风险分级管控标准',
        output_format:
          '## 输出格式\n' +
          '返回 JSON 格式（只返回 JSON，不要额外说明）：\n' +
          '```json\n' +
          '{\n' +
          '  "is_critical": true,\n' +
          '  "reason": "判定理由（说明符合哪些关键作业判定条件，或不符合的原因）"\n' +
          '}\n' +
          '```',
        expected_keys: ['is_critical', 'reason'],
        is_enabled: true,
      },
    ],
  },
  {
    module_code: 'special-ops-export',
    workflow_name: 'AI智能导出（自然语言解析）',
    workflow_description:
      '支持自然语言筛选条件输入，AI 解析意图后智能导出台账 Excel，简化数据检索流程',
    trigger_event: 'manual_start',
    icon: '📊',
    script_configs: [
      {
        script_number: 1,
        name: 'AI智能导出（自然语言解析）',
        input_info:
          '## 用户输入\n' +
          '用户通过自然语言描述台账筛选条件，例如：\n' +
          '- "查看所有动火作业"\n' +
          '- "上周高处作业的台账"\n' +
          '- "关键作业中未完成的"\n' +
          '- "生产部的受限空间作业"\n' +
          '\n' +
          '需要将用户的自然语言输入解析为结构化的筛选参数。',
        work_rules:
          '## 任务\n' +
          '将用户的自然语言查询转换为结构化的特殊作业台账筛选条件。\n\n' +
          '## 可用筛选字段\n' +
          '- operation_type: hot_work/confined_space/height_work/temporary_electricity/blind_plate/excavation/lifting/road_breaking\n' +
          '- operation_level: special/grade1/grade2\n' +
          '- risk_level: level_1/level_2/level_3/level_4\n' +
          '- department: 部门名称（字符串）\n' +
          '- date_from: 开始日期 YYYY-MM-DD\n' +
          '- date_to: 结束日期 YYYY-MM-DD\n' +
          '- keyword: 模糊搜索关键词\n' +
          '- is_critical: true/false\n\n' +
          '## 映射规则\n' +
          '- 作业类型：动火作业→hot_work, 受限空间→confined_space, 高处作业→height_work, 临时用电→temporary_electricity, 盲板抽堵→blind_plate, 动土作业→excavation, 起重吊装→lifting, 断路作业→road_breaking\n' +
          '- 风险等级：一级/重大→level_1, 二级/较大→level_2, 三级/一般→level_3, 四级/低→level_4\n' +
          '- 作业级别：特级→special, 一级→grade1, 二级→grade2\n\n' +
          '## 约束\n' +
          '- 无法识别的字段设为 null\n' +
          '- 对时间表达（今天、本周、上月等）正确计算日期范围\n' +
          '- 保留用户原始输入中的关键词\n' +
          '- 你是一个数据库查询助手，只返回 JSON',
        reference_docs:
          '## 参考\n' +
          '- 特殊作业报备数据模型（八大特殊作业类型）\n' +
          '- GB 30871-2022《危险化学品企业特殊作业安全规范》分类标准\n' +
          '- 企业风险分级管控标准',
        output_format:
          '## 输出格式\n' +
          '返回 JSON 格式（未匹配字段设为 null，只返回 JSON 不要额外说明）：\n' +
          '```json\n' +
          '{\n' +
          '  "operation_type": null,\n' +
          '  "operation_level": null,\n' +
          '  "risk_level": null,\n' +
          '  "department": null,\n' +
          '  "date_from": null,\n' +
          '  "date_to": null,\n' +
          '  "keyword": null,\n' +
          '  "is_critical": null,\n' +
          '  "explanation": "用中文简述你理解的筛选条件"\n' +
          '}\n' +
          '```',
        expected_keys: [
          'operation_type', 'operation_level', 'risk_level',
          'department', 'date_from', 'date_to',
          'keyword', 'is_critical', 'explanation',
        ],
        is_enabled: true,
      },
    ],
  },
  {
    module_code: 'hazard-identification-export',
    workflow_name: 'AI危险源辨识台账智能导出',
    workflow_description:
      '统一工作流：AI 解析自然语言筛选条件 → 查询数据 → AI 格式化生成 HTML 报告 → 导出 PDF。覆盖解析和报告生成两阶段',
    trigger_event: 'manual_start',
    icon: '📋',
    script_configs: [
      {
        script_number: 1,
        name: 'AI智能导出（解析+格式化）',
        input_info:
          '## 用户输入（第一阶段：解析筛选条件）\n' +
          '用户通过自然语言描述要导出哪些危险源辨识记录，例如：\n' +
          '- "上月所有重大风险记录"\n' +
          '- "生产部的设备相关危险源"\n' +
          '- "合成岗位最近三个月的数据"\n' +
          '- "一级和二级风险的记录"\n\n' +
          '## 查询数据（第二阶段：生成分析报告）\n' +
          '系统根据解析结果查询数据库，返回结构化的台账数据摘要：\n' +
          '- 记录总数、风险等级分布、部门/岗位分布\n' +
          '- 高风险记录详情（一级/二级风险）\n' +
          '- 全部记录列表（含编号、部门、岗位、作业活动、危险类型、' +
          '固有/残余LEC值及风险等级、现有控制措施、管控层级、责任人等）',
        work_rules:
          '## 第一阶段：解析筛选条件\n' +
          '将用户的自然语言查询转换为结构化的危险源辨识台账筛选条件。\n\n' +
          '可用筛选字段：\n' +
          '- department: 部门名称\n' +
          '- position: 岗位名称\n' +
          '- risk_level: level_1(重大)/level_2(较大)/level_3(一般)/level_4(低)\n' +
          '- date_from / date_to: YYYY-MM-DD\n' +
          '- keyword: 模糊搜索关键词\n\n' +
          '约束：无法识别的字段设为 null；正确计算时间表达（今天、本周、上月等）；只返回 JSON。\n\n' +
          '## 第二阶段：生成分析报告\n' +
          '根据查询结果生成一份专业的危险源辨识台账分析报告。\n\n' +
          '报告结构：\n' +
          '1. 报告概述：筛选条件、时间范围、记录总数\n' +
          '2. 风险分布分析：按部门/岗位/风险等级统计\n' +
          '3. 重点风险项：逐条列出高风险（一级/二级）记录，评估控制措施充分性\n' +
          '4. 管控措施现状：工程/管理/PPE/应急措施的覆盖情况\n' +
          '5. 改进建议：基于数据的安全管理建议\n\n' +
          '约束：中文撰写、数据准确不编造、表格使用 HTML table、标题 h2/h3',
        reference_docs:
          '## 参考\n' +
          '- 危险源辨识数据模型（HazardIdentification）\n' +
          '- LEC风险评价法标准\n' +
          '- 企业风险分级管控管理制度',
        output_format:
          '## 第一阶段输出（JSON筛选条件，只返回 JSON）\n' +
          '{"department":null,"position":null,"risk_level":null,' +
          '"date_from":null,"date_to":null,"keyword":null,' +
          '"explanation":"用中文简述你理解的筛选条件"}\n\n' +
          '## 第二阶段输出（完整 HTML 文档，可直接生成 PDF）\n' +
          '样式：A4横向(297mm×210mm)、正文10pt/h2:14pt/h3:12pt、' +
          '文字#333、表头背景#5645D4白色文字加粗、表格边框0.5pt solid #ddd、' +
          '斑马纹#f7f6fb、风险标签色(一级红/二级橙/三级蓝/四级绿)、' +
          "font-family: 'SimSun','Microsoft YaHei',sans-serif; " +
          '@page{size:A4 landscape;margin:15mm}',
        expected_keys: [
          'department', 'position', 'risk_level',
          'date_from', 'date_to', 'keyword', 'explanation',
        ],
        is_enabled: true,
      },
    ],
  },
]

// ═══════════════════════════════════════════
// 辅助函数
// ═══════════════════════════════════════════

/** 按 module_code 查询内置工作流 */
export function getBuiltInWorkflow(moduleCode: string): BuiltInWorkflow | undefined {
  return BUILT_IN_WORKFLOWS.find((w) => w.module_code === moduleCode)
}

/** 描述映射：为每个步骤生成简短中文描述 */
const STEP_DESC_MAP: Record<number, string> = {
  1: 'AI提取附件中的作业活动、设备设施、原辅料信息',
  2: 'AI从人机料法环五个维度系统辨识危险源与事故类型',
  3: 'AI进行LEC固有风险评价（未考虑现有控制措施前）',
  4: 'AI识别现有工程/管理/PPE/应急四类控制措施',
  5: 'AI对现有控制措施生效后的残余风险进行LEC评价',
  6: 'AI按风险控制层级提出针对性改进建议措施',
  7: 'AI评价建议措施实施后的风险水平',
}

/** 获取指定工作流的精简步骤列表（供详情页 Steps 组件使用） */
export function getWorkflowStepList(moduleCode: string): WorkflowStepInfo[] {
  const wf = getBuiltInWorkflow(moduleCode)
  if (!wf) return []
  return wf.script_configs
    .filter((s) => s.is_enabled)
    .map((s) => ({
      num: s.script_number,
      title: s.name,
      desc: s.description || STEP_DESC_MAP[s.script_number] || s.name,
      expected_keys: s.expected_keys || [],
    }))
}

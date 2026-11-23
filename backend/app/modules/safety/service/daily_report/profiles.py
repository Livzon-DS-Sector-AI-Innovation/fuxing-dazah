"""人员工作画像——按人定制日报格式的事实源 + 系统留痕源匹配。

来源：飞书文档《安全工程中心人员工作画像与AI日报自动预览配置方案》
（X9ebdPjCfoGsahxlSBpcdstMnGc，2026-11-18 V1.0，依据 11-12~17 历史日报归纳）。

定制口径（用户拍板 2026-11-19）：整体框架统一五段式，每人按画像注入——
① 表单提示语 ② AI 评价查漏方向 ③ 质量红线（禁模糊词/未核实标待确认）。
**画像是参考不是限定（用户纠偏 2026-11-19）**：当日做了画像外的工作照写照评；
画像内业务当天未开展，不得要求补充、更不得建议编造（§3.1 画像不作为任务
已发生的证明）。

系统留痕源匹配（用户拍板 2026-11-19）：多数「可核实成果」在本系统有
Bitable/模块留痕——system_sources 按人登记（域/kind/人员锚点/日期锚点/
可提取事实），供后续 AI 预览自动生成与核对消费（§3.2 P2 数据源）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SystemSource:
    """一条系统留痕源：画像「可核实成果」的系统匹配。

    匹配规则（画像方案 §3.1/§3.2）：按 anchor 字段（人）+ date_field（日）
    归属任务，只提取实际数量与状态；协同工作分别提取本人动作，不重复计入。
    module 非空 = 非 Bitable 的模块级来源（PG/轮询链路）。
    """

    domain: str                    # bitable 域（module 来源可空）
    kind: str                      # 域内 kind
    anchor: str                    # 人员锚点字段名
    date_field: str                # 日期锚点字段名
    extracts: str                  # 可提取事实（一句）
    module: str = ""               # 模块级来源标识


@dataclass(frozen=True)
class PersonProfile:
    """单人工作画像。"""

    name: str
    direction: str                 # 主要方向（速览表）
    scope: str                     # 主要工作范围（详表）
    common_works: str              # 常见工作内容（速览表）
    keywords: tuple[str, ...]      # 匹配关键词
    verifiable: tuple[str, ...]    # 优先提取的可核实成果
    periodic: str = ""             # 周期性规则（§4.3，有据可查者才写）
    system_sources: tuple[SystemSource, ...] = field(default_factory=tuple)


PROFILES: dict[str, PersonProfile] = {
    p.name: p
    for p in (
        PersonProfile(
            name="王海霞",
            direction="安全评价、设计与项目合规",
            scope="安全评价、工程项目安全合规、设计院协调、监管检查及EHS变更审核",
            common_works="安评报告、设计专篇、EHS变更、监管检查回复、现场巡查",
            keywords=("安评报告", "设计专篇", "评价机构", "设计院", "验收评价", "泄爆设计",
                      "EHS变更", "专项检查", "监管回复", "特殊作业"),
            verifiable=("安评报告审核状态", "设计专篇/报价协调事项", "变更审核数量", "监管回复进度"),
            system_sources=(
                SystemSource("ehs_change", "approval", "变更发起人/当前处理人", "发起时间",
                             "变更审核数量、申请状态与最新进展"),
                SystemSource("external_audit_hazard", "emergency_bureau", "责任人", "检查时间",
                             "监管检查缺陷项与回复进展"),
            ),
        ),
        PersonProfile(
            name="吴晓伟",
            direction="工程变更与设备设施安全",
            scope="工程变更现场评估及验收、设备设施安全核查、三查四定、规程和技术文件审核",
            common_works="变更评估/验收、三查四定、URS审核、规程审核",
            keywords=("变更验收", "现场评估", "三查四定", "URS审核", "安全操作规程", "设备改造",
                      "管网改造", "联锁摘除", "图纸核查", "作业票"),
            verifiable=("变更评估/验收项目数量及结论", "待整改项", "规程或URS审核结果"),
            system_sources=(
                SystemSource("ehs_change", "acceptance", "发起人", "验收日期",
                             "变更验收项目数、验收意见与结论"),
                SystemSource("ehs_change", "approval", "当前处理人", "发起时间",
                             "变更审批中节点与待整改项"),
                SystemSource("interlock_change", "approval", "申请人", "发起时间",
                             "联锁/安全附件变更审批与恢复状态"),
                SystemSource("facilities", "equipment_ledger", "到期提醒人员", "到期日期",
                             "设备台账与检验到期情况"),
            ),
        ),
        PersonProfile(
            name="黄腾禹",
            direction="特殊作业与施工安全监督",
            scope="特殊作业过程安全管控、施工现场巡检及承包商违章纠正、约谈与考核",
            common_works="作业票审批、风险作业巡检、承包商检查、违章约谈",
            keywords=("动火", "受限空间", "高处", "吊装", "电子作业票", "作业风险", "计划外作业",
                      "承包商", "约谈", "违章", "考核单"),
            verifiable=("各类作业数量、风险等级与计划外数量", "巡检问题", "签批票数", "考核/约谈记录"),
            system_sources=(
                SystemSource("special_op", "daily", "特殊作业审批人", "发起时间",
                             "签批票数、作业类型/分级与计划外作业"),
                SystemSource("key_risk_op", "daily", "发起人", "作业开始时间",
                             "关键风险作业审批节点"),
                SystemSource("training_behavior", "violation", "违章人员", "违章日期",
                             "违章处理方式、约谈与考核状态"),
                SystemSource("contractor_admission", "admission", "对接人员", "创建日期",
                             "承包商培训状态与材料完整度"),
                SystemSource("hazard", "hazard", "检查人员", "检查日期",
                             "巡检发现隐患条数与级别"),
                SystemSource("", "", "", "", "作业票规则命中与漏审复查", module="workticket_review"),
            ),
        ),
        PersonProfile(
            name="柯乾",
            direction="消防与监测设施管理",
            scope="消防设施、气体报警探头、视频监控及维保供应商管理，兼现场安全巡查",
            common_works="气体探头核查、消防维保、消防改造、视频监控",
            keywords=("消防维保", "气体探头", "可燃气体报警", "氧含量报警", "消防管网", "消防改造",
                      "消防培训", "视频监控", "AI视频识别", "安全标识"),
            verifiable=("探头核对点位及差异", "消防维保进度", "消防设施整改项", "监控在线情况"),
            system_sources=(
                SystemSource("fire_alarm", "alarm", "处置人员", "报警时间",
                             "消防报警处理情况与AI分析维度"),
                SystemSource("facilities", "fire_equipment_ledger", "到期提醒人员", "到期日期",
                             "消防器材点位、到期与整改项"),
                SystemSource("central_alarm", "alarm", "岗位", "日期",
                             "可燃气体/氧含量等中控报警情况"),
                SystemSource("", "", "", "", "消防点检记录AI审核结果（灭火器/消火栓）",
                             module="fire_inspection"),
            ),
        ),
        PersonProfile(
            name="徐媛",
            direction="隐患治理与制度管理",
            scope="隐患排查整改跟踪、安全管理制度编修、重大隐患自查、专项检查；兼顾作业票与培训",
            common_works="隐患整改、重大隐患自查、制度修订、专项检查",
            keywords=("隐患整改", "重大隐患自查", "53条自查报告", "管理制度", "厂区通行规定",
                      "楼梯专项检查", "现场巡查", "新员工培训", "作业票"),
            verifiable=("隐患条数与整改状态", "自查报告/制度版本", "专项检查区域", "培训人数"),
            system_sources=(
                SystemSource("hazard", "hazard", "整改责任人", "检查日期",
                             "隐患条数、级别与整改状态（含AI评分）"),
                SystemSource("external_audit_hazard", "defect_summary", "责任人", "检查时间",
                             "外审/自查缺陷整改状态"),
                SystemSource("training_behavior", "training", "讲师", "实施日期",
                             "培训场次、应到实到与考核合格人数"),
                SystemSource("", "", "", "", "督办通报与整改催办轮次", module="progress_dunning"),
            ),
        ),
        PersonProfile(
            name="林莉鑫",
            direction="职业健康与危化品核查",
            scope="职业健康体检、岗位职业病危害因素核查、职业危害检测、危化品库存核对及办事员事务",
            common_works="职业健康体检、危害因素、危化品超量核查、采购报销",
            keywords=("岗前体检", "在岗体检", "离岗体检", "年度体检", "岗位调动", "职业病危害因素",
                      "职业危害检测", "危化品超量", "超品种", "劳保物料", "采购", "报销"),
            verifiable=("体检人数/报告份数", "岗位危害核对结果", "危化品库存核查差异", "报销/采购单据状态"),
            system_sources=(
                SystemSource("oh", "exam_registry", "姓名", "体检时间",
                             "体检人数、体检类型与流程状态"),
                SystemSource("oh", "hazard_factor", "岗位", "登记时间",
                             "岗位危害因素核对结果"),
                SystemSource("chemical_inventory", "inventory", "部门", "最后更新时间",
                             "危化品超量/超品种风险标记"),
                SystemSource("labor_supply", "product", "部门", "最后更新时间",
                             "劳保物料领用与库存"),
            ),
        ),
        PersonProfile(
            name="季志勇",
            direction="易制毒易制爆与防雷检测",
            scope="易制毒与易制爆化学品监管登记、账物核查、公安检查对接、防雷防静电检测",
            common_works="出入库监管登记、库存核对、防雷防静电检测",
            keywords=("易制毒", "易制爆", "出入库", "监管平台", "盐酸", "硫酸", "硝酸", "账物相符",
                      "禁毒大队", "摄像头", "防雷", "防静电", "EHS审计整改"),
            verifiable=("平台出入库笔数", "库存核对结果", "检测区域及结论", "监管材料提交状态"),
            system_sources=(
                SystemSource("chemical_inventory", "inventory", "部门", "最后更新时间",
                             "易制毒/易制爆品类库存核对（按品类过滤）"),
            ),
        ),
        PersonProfile(
            name="许垚鹏",
            direction="安全培训与数字化应用",
            scope="新员工及外来人员安全培训、厂牌办理、每周安全视频答题、相关方安全管理、消防二维码及AI应用",
            common_works="新员工/外来人员、厂牌、每周视频、消防二维码、AI隐患评分",
            keywords=("三级教育", "厂级培训", "外来人员审核", "厂牌", "人脸录入", "每周安全视频",
                      "问卷星", "年度考试", "相关方协议", "灭火器", "消火栓", "二维码", "点检",
                      "AI隐患评分", "LECX", "隐患通报"),
            verifiable=("培训人数、厂牌张数、答题参与情况", "二维码/点位数量", "隐患复核条数", "协议整理成果"),
            periodic="每周一匹配安全视频发布/答题相关事项；每周四匹配未整改隐患通报；每周五匹配答题数据统计",
            system_sources=(
                SystemSource("visitor_notice", "notice", "发起人", "申请日期",
                             "外来人员预报备人数与审批状态"),
                SystemSource("oh", "new_employee", "姓名", "入职时间",
                             "新员工入职与培训对象"),
                SystemSource("training_behavior", "training", "讲师", "实施日期",
                             "培训人数与考核结果"),
                SystemSource("contractor_admission", "admission", "对接人员", "创建日期",
                             "相关方协议与培训状态"),
                SystemSource("", "", "", "", "消防二维码点检审核（灭火器/消火栓）",
                             module="fire_inspection"),
                SystemSource("", "", "", "", "AI隐患评分轮次与条数", module="ai_hazard_scoring"),
            ),
        ),
    )
}


def profile_for(name: str) -> PersonProfile | None:
    """按姓名取画像（唯一标识优先原则下的辅助匹配，§3.1）。"""
    if not name:
        return None
    return PROFILES.get(name.strip())


def sources_for(name: str) -> tuple[SystemSource, ...]:
    """按姓名取该人的系统留痕源清单（自动预览/核对用）。"""
    p = profile_for(name)
    return p.system_sources if p is not None else ()


def form_hints(profile: PersonProfile | None) -> dict[str, str]:
    """表单各段提示语（无画像回落通用口径）。"""
    if profile is None:
        return {}
    works_sample = "、".join(profile.keywords[:4])
    verify_sample = "；".join(profile.verifiable[:2])
    return {
        "work": f"当日实际工作（不限于你的常见方向：{works_sample}等）；写明对象/数量/结论",
        "done": f"写可核实成果（如{verify_sample}）；画像外工作同样如实写",
        "coord": "需协调的问题、协同对象、期望反馈时间；确无填「暂无」",
        "risk": "未解决的隐患/异常/合规问题及下一步措施；无记录填「暂无」",
        "plan": "未完成任务、明确截止与周期安排；可不填",
    }

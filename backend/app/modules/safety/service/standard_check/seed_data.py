"""体系标准核查表——建表 schema 与标准清单 v1（2026-10-21）。

数据事实源=DESIGN-安全目标责任与绩效模块-体系标准符合性核查引擎-20261021.md
附录 A（55 条：16 自动 + 5 半自动 + 4 待接入 + 30 人工；半自动一期按人工勾选）。
播种脚本 scripts/seed_standard_check.py 消费本模块；安环科终审后直接在
Bitable 改行，本清单只是初版种子。
"""

from __future__ import annotations

from typing import Any

TABLE_NAME = "体系标准核查表"
DOMAIN = "goals"
KIND = "standard_check"

# 飞书字段类型：1=文本 3=单选 4=多选 5=日期 11=人员
_ELEMENTS = (
    "目标职责", "制度化管理", "教育培训", "现场管理",
    "风险管控与隐患治理", "应急管理", "事故管理", "持续改进",
)
_PERIODS = ("年度", "半年", "季度", "月度", "长周期(3年)")
_OPERATORS = ("≥", "≤", "=")
_UNITS = ("次", "%", "人", "天", "学时", "起", "条", "项")
_MANUAL_RESULTS = ("已完成", "未完成", "不适用")

# 16 个已注册取数器键 + 4 个待接入预分配键（接入后零改清单）
_METRIC_KEYS = (
    "drill.count.comprehensive_or_special", "drill.count.site_handling",
    "drill.count.evacuation",
    "hazard.on_time_close_rate", "hazard.major_close_rate", "hazard.register_count",
    "hazard_id.count.year",
    "oh.exam_rate", "workticket.audit_rate",
    "facility.on_time_close_rate",
    "contractor.admit_rate", "contractor.agreement_rate",
    "visitor.notice_rate", "visitor.insurance_rate",
    "msds.coverage_rate", "regulation.ingest_count",
    # ── 待接入（incidents 建表后注册取数器；training 两键已接入）──
    "training.completion_rate", "training.record_integrity",
    "accident.severe.count",
    "incident.near_miss_rate", "capa.on_time_close_rate",
)


def _field(name: str, ftype: int, options: tuple[str, ...] | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {"field_name": name, "type": ftype}
    if options is not None:
        field["property"] = {"options": [{"name": o} for o in options]}
    return field


def table_schema() -> dict[str, Any]:
    """建表请求体（飞书 POST /apps/{app_token}/tables）。"""
    return {
        "table": {
            "name": TABLE_NAME,
            "default_view_name": "全部标准",
            "fields": [
                _field("标准编号", 1),
                _field("年度", 3, ()),
                _field("标准条款", 1),
                _field("依据", 1),
                _field("要素归属", 3, _ELEMENTS),
                _field("指标键", 3, _METRIC_KEYS),
                _field("比较符", 3, _OPERATORS),
                _field("目标值", 1),
                _field("单位", 3, _UNITS),
                _field("周期", 3, _PERIODS),
                _field("责任部门", 4, ()),
                _field("责任人", 11),
                _field("上次完成日期", 5),
                _field("人工核查结果", 3, _MANUAL_RESULTS),
                _field("备注", 1),
            ],
        }
    }


def _s(
    no: str,
    clause: str,
    basis: str,
    element: str,
    *,
    period: str = "年度",
    metric_key: str | None = None,
    operator: str | None = None,
    target: str | None = None,
    unit: str | None = None,
    note: str | None = None,
) -> dict[str, str | None]:
    return {
        "no": no, "clause": clause, "basis": basis, "element": element,
        "period": period, "metric_key": metric_key, "operator": operator,
        "target": target, "unit": unit, "note": note,
    }


# ═══════════════════════════════════════════════════════════════
# 标准清单 v1（附录 A 全量，55 条）
# ═══════════════════════════════════════════════════════════════

STANDARDS: list[dict[str, str | None]] = [
    # ── 一、目标职责（8）──
    _s("D1-01", "年度安全生产目标文件已制定下发，目标可测量、可考核并分解到部门/岗位",
       "GB/T 33000-2016 §5.1.1", "目标职责"),
    _s("D1-02", "全员安全生产责任制已建立、公示并纳入考核", "安全生产法§4/§22", "目标职责"),
    _s("D1-03", "各级安全责任书按年度签订完成（纸档下发签收存档）", "公司制度", "目标职责"),
    _s("D1-04", "设置安全生产管理机构并配备专职安全生产管理人员", "安全生产法§24", "目标职责"),
    _s("D1-05", "主要负责人与安管人员经考核合格，安全合格证在有效期内",
       "安全生产法§27；生产经营单位安全培训规定§9", "目标职责", note="半自动：cert 证书台账可辅助核对"),
    _s("D1-06", "主要负责人/安管人员年度再培训≥16学时", "安全培训规定§9", "目标职责",
       target="16", unit="学时"),
    _s("D1-07", "安全生产费用按财资〔2022〕25号档次足额提取、专款专用并建台账",
       "财资〔2022〕25号；安全生产法§23", "目标职责"),
    _s("D1-08", "每年至少一次标准化自评，形成绩效评定报告并向员工通报",
       "GB/T 33000-2016 §5.8.1", "目标职责", note="本系统年度导出即素材"),
    # ── 二、制度化管理（6）──
    _s("D2-01", "安全生产规章制度清单现行有效并定期评审修订", "GB/T 33000-2016 §5.2", "制度化管理"),
    _s("D2-02", "岗位操作规程现行有效（发布/修订受控）", "GB/T 33000-2016 §5.2.3", "制度化管理"),
    _s("D2-03", "新改扩建项目安全设施「三同时」手续完备", "安全生产法§33", "制度化管理",
       note="按项目核查，每年核对档案"),
    _s("D2-04", "法规标准识别收录持续更新", "GB/T 33000-2016 §5.2.1", "制度化管理",
       period="季度", metric_key="regulation.ingest_count", operator="≥", target="1", unit="次"),
    _s("D2-05", "合规性评价按期开展并输出评价报告", "GB/T 33000-2016 §5.2", "制度化管理"),
    _s("D2-06", "危险化学品登记证在有效期内（3年复核换证）", "危险化学品登记管理办法", "制度化管理",
       period="长周期(3年)", note="半自动：登记证到期日录入证书台账后可查"),
    # ── 三、教育培训（7）──
    _s("D3-01", "新上岗从业人员岗前三级教育≥72学时", "安全培训规定§13", "教育培训",
       target="100", unit="%", note="覆盖率100%，学时台账核对"),
    _s("D3-02", "从业人员年度再培训≥20学时", "安全培训规定§13", "教育培训", target="20", unit="学时"),
    _s("D3-03", "转岗/离岗一年以上复岗人员重新培训", "安全生产法§28", "教育培训", note="按事件核查"),
    _s("D3-04", "特种作业/特种设备作业人员持证上岗率100%", "安全生产法§30；特种设备安全法§14",
       "教育培训", period="季度", target="100", unit="%", note="半自动：cert 台账出持证与临期清单"),
    _s("D3-05", "年度培训计划完成率≥95%", "公司制度", "教育培训",
       metric_key="training.completion_rate", operator="≥", target="95", unit="%",
       note="S6 建表接入后自动核查（2026-10-22 起）"),
    _s("D3-06", "外来人员入厂安全培训报备率100%", "公司制度", "教育培训",
       period="月度", metric_key="visitor.notice_rate", operator="=", target="100", unit="%"),
    _s("D3-07", "培训台账与签到考核记录完整", "安全培训规定", "教育培训", period="季度",
       metric_key="training.record_integrity", operator="≥", target="100", unit="%",
       note="完整=签到附件非空且考核留痕齐（S6 2026-10-22 接入自动核查）"),
    # ── 四、现场管理（13，含职业健康）──
    _s("D4-01", "特殊作业实行作业许可，作业票审核覆盖率100%", "GB 30871-2022", "现场管理",
       period="月度", metric_key="workticket.audit_rate", operator="=", target="100", unit="%"),
    _s("D4-02", "特殊作业现场监护人配置落实", "GB 30871-2022", "现场管理",
       period="月度", note="月度抽查，作业票数据辅助"),
    _s("D4-03", "劳动防护用品按标准配备发放，台账完备", "安全生产法§45", "现场管理",
       note="labor_supply 台账辅助"),
    _s("D4-04", "工作场所安全警示标识完好有效", "GB 2894；GBZ 158", "现场管理", period="季度"),
    _s("D4-05", "承包商准入审核完成率（资质/培训）100%", "安全生产法§49；GB/T 33000 §5.4", "现场管理",
       period="季度", metric_key="contractor.admit_rate", operator="=", target="100", unit="%"),
    _s("D4-06", "相关方安全生产管理协议签订率100%", "安全生产法§49", "现场管理",
       period="季度", metric_key="contractor.agreement_rate", operator="=", target="100", unit="%"),
    _s("D4-07", "危化品储存合规（分类/禁忌隔离/台账相符）", "危险化学品安全管理条例", "现场管理",
       period="季度", note="chemical_inventory 库存辅助核对"),
    _s("D4-08", "在册危化品 SDS 配备覆盖率100%", "GB/T 16483；危化品条例§15", "现场管理",
       period="季度", metric_key="msds.coverage_rate", operator="=", target="100", unit="%"),
    _s("D4-09", "职业病危害因素检测（危害严重单位每年≥1次）", "工作场所职业卫生管理规定§20",
       "现场管理", target="1", unit="次"),
    _s("D4-10", "职业健康体检率100%（上岗/在岗/离岗）", "职业病防治法§35", "现场管理",
       metric_key="oh.exam_rate", operator="=", target="100", unit="%"),
    _s("D4-11", "职业病危害项目如实申报", "职业病防治法§16", "现场管理"),
    _s("D4-12", "安全附件/特种设备/消防器材校验按期完成率100%", "特种设备安全法；公司设施管理要求",
       "现场管理", period="季度", metric_key="facility.on_time_close_rate", operator="=", target="100", unit="%"),
    _s("D4-13", "外来人员保险有效期填报率≥90%", "公司外来人员管理要求", "现场管理",
       period="月度", metric_key="visitor.insurance_rate", operator="≥", target="90", unit="%"),
    # ── 五、风险管控与隐患治理（7）──
    _s("D5-01", "年度危险源辨识与风险评价全覆盖≥1次", "GB/T 33000 §5.5；安全生产法§41",
       "风险管控与隐患治理", metric_key="hazard_id.count.year", operator="≥", target="1", unit="次"),
    _s("D5-02", "风险分级管控清单与四色图维护更新", "公司制度", "风险管控与隐患治理"),
    _s("D5-03", "隐患排查持续开展（当月有排查登记）", "安全生产法§41", "风险管控与隐患治理",
       period="月度", metric_key="hazard.register_count", operator="≥", target="1", unit="条",
       note="判定=登记数≥1，点开凭据看登记明细"),
    _s("D5-04", "隐患按期整改完成率≥95%", "公司年度目标", "风险管控与隐患治理",
       period="季度", metric_key="hazard.on_time_close_rate", operator="≥", target="95", unit="%"),
    _s("D5-05", "重大事故隐患整改闭环率100%", "安全生产法§41", "风险管控与隐患治理",
       period="季度", metric_key="hazard.major_close_rate", operator="=", target="100", unit="%"),
    _s("D5-06", "重大危险源辨识评估备案并监控", "危化品条例；40号令", "风险管控与隐患治理",
       note="二期自动：库存×GB 18218 临界量比对"),
    _s("D5-07", "危化品企业安全评价（每3年≥1次）", "危化品条例§22", "风险管控与隐患治理",
       period="长周期(3年)", note="判定=上次完成日期≤3年"),
    # ── 六、应急管理（8）──
    _s("D6-01", "综合或专项应急预案演练每半年≥1次", "应急预案管理办法§33（危化品加严）", "应急管理",
       period="半年", metric_key="drill.count.comprehensive_or_special", operator="≥", target="1", unit="次"),
    _s("D6-02", "现场处置方案演练每半年≥1次", "应急预案管理办法§33", "应急管理",
       period="半年", metric_key="drill.count.site_handling", operator="≥", target="1", unit="次"),
    _s("D6-03", "应急疏散演练年度≥1次", "GB/T 33000 §5.6（公司口径）", "应急管理",
       metric_key="drill.count.evacuation", operator="≥", target="1", unit="次"),
    _s("D6-04", "应急预案已评审发布并向主管部门备案（发布后20个工作日内）", "应急预案管理办法",
       "应急管理", note="按修订核查，每年核对档案"),
    _s("D6-05", "应急预案定期评估（每3年≥1次）", "应急预案管理办法§35", "应急管理",
       period="长周期(3年)", note="判定=上次完成日期≤3年"),
    _s("D6-06", "从业人员经应急预案培训告知", "安全生产法§47", "应急管理"),
    _s("D6-07", "应急器材物资配备完好并定期检查", "安全生产法§44；GB/T 33000 §5.6", "应急管理",
       period="季度", note="半自动：消防器材换药/报废到期引擎在 facilities"),
    _s("D6-08", "建筑消防设施每年全面检测≥1次", "消防法§16", "应急管理",
       target="1", unit="次", note="半自动：设施台账检测记录辅助"),
    # ── 七、事故管理（4）──
    _s("D7-01", "生产安全事故为零（死亡/重伤）", "公司目标", "事故管理",
       metric_key="accident.severe.count", operator="≤", target="0", unit="起",
       note="待 incidents 域建表接入后自动核查"),
    _s("D7-02", "事故按规定及时报告（接报后1小时内）", "事故报告和调查处理条例§9", "事故管理",
       note="按事件核查"),
    _s("D7-03", "事故调查处理「四不放过」与档案完备", "条例；GB/T 33000 §5.7", "事故管理", note="按事件核查"),
    _s("D7-04", "未遂/轻微事件登记建档率100%", "GB/T 33000 §5.7", "事故管理",
       period="季度", metric_key="incident.near_miss_rate", operator="=", target="100", unit="%",
       note="待 incidents 域建表接入后自动核查"),
    # ── 八、持续改进（2）──
    _s("D8-01", "绩效评定输出改进措施并落实闭环", "GB/T 33000 §5.8.2", "持续改进",
       note="年度 snapshot 导出即素材"),
    _s("D8-02", "纠正措施（CAPA）按期闭环率100%", "GB/T 33000 §5.8", "持续改进",
       period="季度", metric_key="capa.on_time_close_rate", operator="=", target="100", unit="%",
       note="待 incidents/CAPA 建表接入后自动核查"),
]


def row_fields(standard: dict[str, str | None], year: str) -> dict[str, Any]:
    """单条标准 → Bitable 行 fields（年度由脚本注入当年）。"""
    return {
        "标准编号": standard["no"],
        "年度": year,
        "标准条款": standard["clause"],
        "依据": standard["basis"],
        "要素归属": standard["element"],
        "指标键": standard["metric_key"],
        "比较符": standard["operator"],
        "目标值": standard["target"],
        "单位": standard["unit"],
        "周期": standard["period"],
        "备注": standard["note"],
    }

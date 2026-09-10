"""Bitable 配置域注册表 — 安全模块多维表格配置的代码唯一事实源。

14 域 / 24 条连接行（backend-design §1）。本文件是：

1. **migration 播种的来源**（单向导出，禁止手抄，防双份常量漂移）；
2. **运行时 fallback**：DB 缺行/停用时 store 回退到 ``default_connection`` /
   ``default_mappings``（保证重启/迁移空窗期不断数据）。

- ``default_connection``：固化 ``.env.development`` 第 33-107 行当前值
  （``SAFETY_FEISHU_BITABLE_*``）+ 三处代码硬编码值
  （special_op / key_risk_op / central_alarm 的 env default）；
- ``default_mappings``：固化各 handler 现有映射 dict
  （``BITABLE_TO_MODEL`` / ``*_TO_MODEL`` / mapper 函数），来源对照见
  backend-design §2.3。

本模块零副作用导入（不 import feishu/ 或 service/ 包，避免触发 on_event 注册），
migration 可直接引用。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Literal

# 字段类型语义对齐 app/modules/safety/audit/parser.py（text/person/multi_select/
# single_select/attachment/datetime/enum/combined_text）
FieldType = Literal[
    "text", "person", "multi_select", "single_select",
    "attachment", "datetime", "enum", "combined_text",
]

SubscribeType = Literal["drive", "record"]  # drive=需 ensure 订阅；record=无需


@dataclass(frozen=True)
class DefaultConnection:
    """单表默认连接（migration 播种 + 运行时 fallback 值）。"""

    app_token: str
    table_id: str
    extra_table_ids: tuple[str, ...] = ()  # 仅 central_alarm 使用（白名单其余表）
    note: str = ""


@dataclass(frozen=True)
class KindInfo:
    """单表类型配置（kind 是稳定 table 类型 key，DB 只能改值不能新增 kind）。"""

    kind: str
    label: str                       # 表中文名（如「体检记录表」）
    default_connection: DefaultConnection | None = None
    default_mappings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DomainInfo:
    """单域配置。"""

    key: str
    label: str                       # 中文标签
    purpose: str                     # 用途说明
    subscribe: SubscribeType
    kinds: tuple[KindInfo, ...]

    def get_kind(self, kind: str) -> KindInfo:
        """返回域内 kind，未知抛 ValueError（消息以「未知表类型」开头）。"""
        for info in self.kinds:
            if info.kind == kind:
                return info
        raise ValueError(f"未知表类型: {kind}")


def _m(
    source_field: str | None,
    target_field: str,
    field_type: FieldType = "text",
    default_value: Any = None,
    value_map: dict[str, Any] | None = None,
    optional: bool = False,
) -> dict[str, Any]:
    """构造一条映射项（结构见 backend-design §2.2）。"""
    return {
        "source_field": source_field,
        "target_field": target_field,
        "field_type": field_type,
        "default_value": default_value,
        "value_map": value_map or {},
        "optional": optional,
    }


# ═══════════════════════════════════════════════════════════════
# 14 域注册表（值来源见各域注释；禁止在 migration 中手抄）
# ═══════════════════════════════════════════════════════════════

_DOMAINS: tuple[DomainInfo, ...] = (
    # ── hazard 隐患登记（Bitable↔HazardReport 双向同步）────────────
    DomainInfo(
        key="hazard",
        label="隐患登记",
        purpose="Bitable 隐患登记表 ↔ HazardReport 双向同步",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="hazard",
                label="隐患登记表",
                default_connection=DefaultConnection(
                    app_token="UKlobrKj3aQ24XsBRkTcqdL0nkc",
                    table_id="tblpZUnbQPPR6sp7",
                    note="隐患登记闭环业务主表（双向同步）",
                ),
                default_mappings=(
                    # ← feishu/bitable_handler.py BITABLE_TO_MODEL + 各 *_MAP
                    _m("检查日期", "discovered_at", "datetime"),
                    _m("检查人员", "discovered_by_name", "person"),
                    _m("检查人员.部门", "inspector_department", "multi_select"),
                    _m("检查类别", "inspection_category", "multi_select"),
                    _m("隐患描述", "description", "text"),
                    _m("整改责任人.部门", "department", "multi_select"),
                    _m("隐患责任人.部门", "department", "multi_select", optional=True),
                    _m("整改责任人", "rectification_responsible_person_name", "person"),
                    _m("隐患分类（AI）", "hazard_type", "enum",
                       default_value="unsafe_condition",
                       value_map={
                           "人的不安全行为": "unsafe_action",
                           "物的不安全状态": "unsafe_condition",
                           "环境的不安全因素": "environmental",
                           "管理的缺陷": "management_defect",
                       }),
                    _m("隐患类别（AI）", "hazard_category", "enum",
                       value_map={
                           "设备设施": "equipment",
                           "危化储存": "hazardous_storage",
                           "应急管理": "emergency_mgmt",
                           "仪表+电气": "instrument_electrical",
                           "防雷防静电": "lightning_antistatic",
                           "职业健康+劳保防护": "occupational_health",
                           "三违作业": "violation_operation",
                           "6S": "six_s",
                           "标签标识": "label_signage",
                           "工艺管理": "process_mgmt",
                           "承包商缺陷": "contractor_defect",
                           "内页资料": "documentation",
                           "特殊作业": "special_operation",
                       }),
                    _m("隐患级别", "hazard_level_manual", "enum",
                       value_map={"一般隐患": "general", "较大隐患": "serious", "重大隐患": "major"}),
                    _m("隐患描述（AI）", "key_defect", "text"),
                    _m("隐患判定依据（AI）", "major_hazard_basis", "text"),
                    _m("缺陷图片", "defect_photos", "attachment"),
                    _m("整改后图片", "rectification_photos", "attachment"),
                    _m("整改状态", "rectification_status", "enum",
                       value_map={"已关闭": "closed", "未关闭": "pending", "整改中": "in_progress"}),
                    _m("纠正预防措施", "rectification_reply", "text"),
                    _m("整改期限", "deadline", "datetime"),
                    _m("整改完成时间", "actual_completion_date", "datetime"),
                    _m("目前进展", "progress_note", "text"),
                    _m("部门负责人复核", "verify_level_1_status", "enum",
                       value_map={"已同意": "approved", "未同意": "rejected", "无需复核": "no_review_needed"}),
                    _m("分管领导复核", "verify_level_2_status", "enum",
                       value_map={"已同意": "approved", "未同意": "rejected", "无需复核": "no_review_needed"}),
                    _m("检查人员复核", "verify_level_3_status", "enum",
                       value_map={"已同意": "approved", "未同意": "rejected", "无需复核": "no_review_needed"}),
                    _m("隐患编号", "hazard_no", "text"),
                    _m("整改建议（AI）", "corrective_preventive_measures", "text"),
                    _m("督办等级", "supervision_level", "single_select",
                       value_map={"红色预警": "红色预警", "一般预警": "一般预警", "已关闭": "closed"}),
                ),
            ),
        ),
    ),
    # ── knowledge 知识库法规（法规标准单向同步 + 写回编号）────────
    DomainInfo(
        key="knowledge",
        label="知识库法规",
        purpose="法规标准清单 → 平台单向同步 + 写回编号",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="collection",
                label="安全法规标准",
                default_connection=DefaultConnection(
                    app_token="IkYTw6PJPiKZTCkfuNQc7IqEnzd",
                    table_id="tbl85HKWCTfyf6rw",
                    note="安全法规标准表（法规同步+编号回写）",
                ),
                default_mappings=(
                    # ← feishu/knowledge_bitable_handler.py KNOWLEDGE_BITABLE_TO_MODEL
                    _m("法律法规及标准名称", "title", "text"),
                    _m("法规类别", "category", "enum",
                       value_map={
                           "安全类": "laws_regulations",
                           "建筑防火与消防": "laws_regulations",
                           "特种设备": "standards",
                           "特殊作业": "standards",
                           "职业健康": "laws_regulations",
                           "环境类": "laws_regulations",
                           "化学品管理": "laws_regulations",
                           "其他相关法规": "other",
                           "二职业健康类": "laws_regulations",
                           "三环境保护类": "laws_regulations",
                       }),
                    _m("颁布机关", "source", "text"),
                    _m("颁布修订日期", "publish_date", "datetime"),
                    _m("实施日期", "implementation_date", "datetime"),
                    _m("法规状态", "status", "enum",
                       value_map={
                           "现行有效": "published",
                           "现行有效(新)": "published",
                           "征求意见中": "draft",
                           "即将实施": "published",
                       }),
                    _m("核心要点总结", "summary", "text"),
                    _m("备注", "notes", "text"),
                ),
            ),
            KindInfo(
                kind="collection_env",
                label="环保法规标准",
                default_connection=DefaultConnection(
                    app_token="IkYTw6PJPiKZTCkfuNQc7IqEnzd",
                    table_id="tbltLzMUiur8rBAL",
                    note="环保法规标准表（法规同步+编号回写）",
                ),
                default_mappings=(
                    # 与 collection 完全一致（2026-09-01 法规标准分家复制字段结构）
                    _m("法律法规及标准名称", "title", "text"),
                    _m("法规类别", "category", "enum",
                       value_map={
                           "安全类": "laws_regulations",
                           "建筑防火与消防": "laws_regulations",
                           "特种设备": "standards",
                           "特殊作业": "standards",
                           "职业健康": "laws_regulations",
                           "环境类": "laws_regulations",
                           "化学品管理": "laws_regulations",
                           "其他相关法规": "other",
                           "二职业健康类": "laws_regulations",
                           "三环境保护类": "laws_regulations",
                       }),
                    _m("颁布机关", "source", "text"),
                    _m("颁布修订日期", "publish_date", "datetime"),
                    _m("实施日期", "implementation_date", "datetime"),
                    _m("法规状态", "status", "enum",
                       value_map={
                           "现行有效": "published",
                           "现行有效(新)": "published",
                           "征求意见中": "draft",
                           "即将实施": "published",
                       }),
                    _m("核心要点总结", "summary", "text"),
                    _m("备注", "notes", "text"),
                ),
            ),
        ),
    ),
    # ── emergency_drill 应急演练（主表 + 采集表镜像，drive 文档事件）──
    DomainInfo(
        key="emergency_drill",
        label="应急演练",
        purpose="演练主表 + 采集表镜像（drive 文档事件，2026-09-08 自 record 事件迁移，原事件类型飞书从不推送）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="main",
                label="演练计划统计表",
                default_connection=DefaultConnection(
                    app_token="BH9tbLqr3aWNIOsaaGJcIVOZnKb",
                    table_id="tbl7A0yeqmS8rGXK",
                    note="应急演练主表",
                ),
                default_mappings=(
                    # ← feishu/emergency_drill_bitable_handler.py BITABLE_TO_MODEL/PERSON_FIELDS/ATTACHMENT_FIELDS
                    _m("计划时间", "plan_time", "datetime"),
                    _m("演练类型", "drill_type", "single_select"),
                    _m("演练内容", "drill_content", "text"),
                    _m("组织人", "organizer", "text"),
                    _m("演练部门", "department", "single_select"),
                    _m("组织人 (人员 )", "organizer_person", "person"),
                    _m("参演人员", "participants", "multi_select"),
                    _m("配合部门", "coop_department", "multi_select"),
                    _m("课时", "duration", "text"),
                    _m("备  注", "notes", "text"),
                    _m("提醒人员", "alert_person", "text"),
                    _m("实施时间", "execution_time", "datetime"),
                    _m("演练问题", "issues", "text"),
                    _m("整改时间", "rectification_time", "datetime"),
                    _m("整改责任人", "rectification_person", "text"),
                    _m("确认人", "confirmer", "text"),
                    _m("状态", "status", "single_select"),
                    _m("提醒人员 (人员 )", "alert_person_data", "person"),
                    _m("整改责任人", "rectification_person_data", "person"),
                    _m("确认人", "confirmer_data", "person"),
                    _m("演练方案（AI）", "drill_plan_file", "attachment"),
                    _m("演练方案（定稿）", "plan_final_file", "attachment"),
                    _m("签到表", "signin_file", "attachment"),
                    _m("演练评估表", "eval_form_file", "attachment"),
                    _m("演练记录表", "drill_record_file", "attachment"),
                    _m("演练评估表（AI）", "eval_ai_file", "attachment"),
                ),
            ),
            KindInfo(
                kind="collection",
                label="演练计划收录表",
                default_connection=DefaultConnection(
                    app_token="BH9tbLqr3aWNIOsaaGJcIVOZnKb",
                    table_id="tbllHpBIhqePyNpF",
                    note="应急演练采集表（同 app_token）",
                ),
                default_mappings=(
                    # ← feishu/emergency_drill_collection_handler.py 字段提取
                    _m("日期", "upload_date", "datetime"),
                    _m("演练计划附件", "attachment", "attachment"),
                    _m("人员", "person_data", "person"),
                    _m("部门", "department", "multi_select"),
                ),
            ),
        ),
    ),
    # ── msds MSDS 台账（采集入口 + 收录台账，drive 文档事件）─────────
    DomainInfo(
        key="msds",
        label="MSDS 台账",
        purpose="采集入口表 + 收录台账表（drive 文档事件，2026-09-08 自 record 事件迁移，原事件类型飞书从不推送）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="collection",
                label="供应商资料采集表",
                default_connection=DefaultConnection(
                    app_token="MAzwb6JWzaA4MPswdqacyo0XnSf",
                    table_id="tbliik0SMjj81wTv",
                    note="MSDS 供应商资料表（采集入口）",
                ),
                default_mappings=(
                    # ← feishu/msds_collection_handler.py 字段提取
                    _m("日期", "source_date", "datetime"),
                    _m("供应商资料", "attachment", "attachment"),
                    _m("人员", "person_data", "person"),
                ),
            ),
            KindInfo(
                kind="registry",
                label="MSDS 收录台账表",
                default_connection=DefaultConnection(
                    app_token="MAzwb6JWzaA4MPswdqacyo0XnSf",
                    table_id="tblKkRgXgIDGY0LG",
                    note="MSDS 收录台账表",
                ),
                default_mappings=(
                    # ← feishu/msds_bitable_handler.py BITABLE_TO_MODEL（MSDS 表 29 列）
                    _m("物质名称", "name", "text"),
                    _m("CAS号", "cas_no", "text"),
                    _m("分子式", "molecular_formula", "text"),
                    _m("UN编号", "un_no", "text"),
                    _m("日期", "source_date", "datetime"),
                    _m("危险性说明", "hazard_statement", "text"),
                    _m("外观与现状", "appearance", "text"),
                    _m("溶解性", "solubility", "text"),
                    _m("熔点", "melting_point", "text"),
                    _m("沸点", "boiling_point", "text"),
                    _m("闪点", "flash_point", "text"),
                    _m("相对密度", "relative_density", "text"),
                    _m("爆炸上限", "explosion_upper_limit", "text"),
                    _m("爆炸下限", "explosion_lower_limit", "text"),
                    _m("自燃温度", "autoignition_temperature", "text"),
                    _m("分解温度", "decomposition_temperature", "text"),
                    _m("PC-TWA", "pc_twa", "text"),
                    _m("PC-STEL", "pc_stel", "text"),
                    _m("MAC", "mac", "text"),
                    _m("健康危害", "health_hazard", "text"),
                    _m("环境危害", "environmental_hazard", "text"),
                    _m("急救措施", "first_aid", "text"),
                    _m("消防措施", "fire_fighting", "text"),
                    _m("泄漏应急处理", "leakage_response", "text"),
                    _m("废弃处置", "waste_disposal", "text"),
                    _m("接触控制与个体防护", "exposure_controls", "text"),
                    _m("操作处置与储存注意事项", "handling_storage", "text"),
                    _m("稳定性和反应性", "stability_reactivity", "text"),
                    _m("MSDS附件", "msds_attachment", "attachment"),
                ),
            ),
        ),
    ),
    # ── chemical_inventory 危化品库存（总表镜像 + 风险回填）────────
    DomainInfo(
        key="chemical_inventory",
        label="危化品库存",
        purpose="库存总表镜像 + 风险标记/风险说明系统回填",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="inventory",
                label="危化品库存总表",
                default_connection=DefaultConnection(
                    app_token="QoUXbLVcQaYAO7sod1CcUH3JnVd",
                    table_id="tbl78IlFOo3f1fj1",
                    note="危化品库存总表（固定行每日更新）",
                ),
                default_mappings=(
                    # ← feishu/chemical_inventory_bitable_handler.py INVENTORY_BITABLE_TO_MODEL + *_LABEL_TO_ENUM
                    _m("部门", "department", "enum",
                       value_map={
                           "仓储部": "warehouse", "提炼一部": "extraction_1",
                           "提炼二期": "extraction_2", "提炼二部": "extraction_2b",
                           "发酵一部": "fermentation_1", "发酵二部": "fermentation_2",
                           "菌种中心": "strain", "QC": "qc", "环保": "env",
                           "精制": "purification", "提炼半合成工程中心": "semi_synth",
                           "提炼技术精进中心": "tech_refine", "其他": "other",
                       }),
                    _m("存放部位", "storage_location", "text"),
                    _m("物料名称", "material_name", "text"),
                    _m("包装规格", "package_spec", "text"),
                    _m("库存数量", "quantity", "text"),
                    _m("单位", "unit", "enum",
                       value_map={"kg": "kg", "g": "g", "T": "T", "L": "L", "ml": "ml", "瓶": "bottle"}),
                    _m("现场物料总量(T)", "total_quantity_t", "text"),
                    _m("库存上限", "max_limit", "text"),
                    _m("上限单位", "max_limit_unit", "text"),
                    _m("危险性", "hazard_classes", "enum",
                       value_map={
                           "易燃": "flammable", "易爆": "explosive", "易制毒": "precursor_drug",
                           "易制爆": "precursor_explosive", "腐蚀": "corrosive", "毒性": "toxic",
                           "氧化剂": "oxidizer", "刺激性": "irritant",
                       }),
                    _m("品类", "category", "text"),
                    _m("最后更新时间", "last_updated_at", "datetime"),
                    _m("备注", "remark", "text"),
                    _m("风险标记", "risk_flag", "enum", value_map={"正常": "normal", "预警": "warn"}),
                    _m("风险说明", "risk_note", "text"),
                ),
            ),
        ),
    ),
    # ── oh 职业健康（单文档 6 表镜像）───────────────────────────
    DomainInfo(
        key="oh",
        label="职业健康",
        purpose="单文档 6 表镜像（人员汇总/体检记录/岗位/危害因素/转岗离岗申请/新员工登记）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="person_master",
                label="人员汇总表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tblfraFQs5A4zeaP",
                    note="OH 人员汇总表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_person_master_fields
                    _m("姓名", "name", "person"),
                    _m("姓名（文本）", "name", "text", optional=True),
                    _m("姓名.工号", "employee_no", "text"),
                    _m("身份证号码", "id_card_no", "text"),
                    _m("姓名.部门", "department", "text"),
                    _m("岗位", "position", "text"),
                    _m("性别", "gender", "single_select"),
                    _m("婚姻状况", "marital_status", "single_select"),
                    _m("手机号码", "phone", "text"),
                    _m("总工龄（年）", "total_work_years", "text", optional=True),
                    _m("接害工龄（年）", "hazard_exposure_years", "text", optional=True),
                    _m("体检类别", "last_exam_type", "enum",
                       value_map={
                           "岗前": "pre_employment", "新员工": "pre_employment",
                           "在岗": "periodic", "在岗期间": "periodic", "在职": "periodic",
                           "年度": "periodic", "离岗": "post_employment", "离职": "post_employment",
                           "转岗": "transfer", "调岗": "transfer",
                           "应急": "emergency", "特殊情况": "emergency",
                       }),
                    _m("在岗状态", "work_status", "enum",
                       value_map={"在岗": "on_post", "离岗": "off_post",
                                  "岗前": "pre_employment", "转岗": "transfer"}),
                    _m("最后一次体检时间", "last_exam_at", "datetime"),
                    _m("接触危害因素", "hazard_factors", "multi_select"),
                    _m("安全员", "safety_officer", "person"),
                ),
            ),
            KindInfo(
                kind="exam_registry",
                label="体检记录表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tbljzHA31sCgCo1U",
                    note="OH 体检记录表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_exam_registry_fields
                    _m("姓名", "employee_name", "person"),
                    _m("体检号", "exam_no", "text"),
                    _m("身份证号码", "id_card_no", "text"),
                    _m("体检类型", "exam_type", "enum",
                       default_value="periodic",
                       value_map={
                           "岗前": "pre_employment", "新员工": "pre_employment",
                           "在岗": "periodic", "在岗期间": "periodic", "在职": "periodic",
                           "年度": "periodic", "离岗": "post_employment", "离职": "post_employment",
                           "转岗": "transfer", "调岗": "transfer",
                           "应急": "emergency", "特殊情况": "emergency",
                       }),
                    _m("流程状态", "status", "enum",
                       value_map={"未体检": "pending", "已体检": "completed"}),
                    _m("性别", "gender", "single_select"),
                    _m("婚姻状况", "marital_status", "single_select"),
                    _m("年龄", "age", "text"),
                    _m("电话", "phone", "text"),
                    _m("部门", "department", "text"),
                    _m("岗位", "position", "text"),
                    _m("登记时间", "scheduled_date", "datetime"),
                    _m("体检时间", "exam_date", "datetime"),
                    _m("报告日期", "report_date", "datetime"),
                    _m("总工龄", "total_work_years", "text"),
                    _m("接害工龄", "hazard_exposure_years", "text"),
                    _m("危害因素", "hazard_factors", "multi_select"),
                    _m("防护措施", "protection_measures", "text"),
                    _m("体检报告附件", "attachments", "attachment"),
                    _m("体检结果", "exam_result", "text"),
                    _m("检查结论", "exam_conclusion", "text"),
                    _m("处理意见", "treatment_advice_raw", "text"),
                    _m("纸质报告留存", "paper_report_kept", "enum",
                       value_map={"是": "yes", "否": "no"}),
                    _m("是否已同步汇总表", "synced_to_summary", "single_select"),
                    _m("Source Table", "source_table", "text", optional=True),
                    _m("Source Record ID", "source_record_id", "text", optional=True),
                    _m("AI智能解读", "ai_interpretation", "text", optional=True),
                    _m("体检机构", "exam_agency", "text", optional=True),
                ),
            ),
            KindInfo(
                kind="position",
                label="岗位信息表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tbltC7GCXLP6NouX",
                    note="OH 岗位信息表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_position_fields
                    _m("部门", "department", "text"),
                    _m("岗位", "position", "text"),
                    _m("职务", "job_title", "text"),
                    _m("危害因素", "hazard_factors", "multi_select"),
                ),
            ),
            KindInfo(
                kind="hazard_factor",
                label="危害因素 PPE 表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tbl6lcHDN6WIf44a",
                    note="OH 危害因素 PPE 表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_hazard_factor_fields
                    _m("危害因素名称", "factor_name", "text"),
                    _m("呼吸防护用品", "ppe_respiratory", "text"),
                ),
            ),
            KindInfo(
                kind="exam_application",
                label="转岗离岗申请表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tbl28F5wVaovF1Zg",
                    note="OH 转岗离岗申请表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_exam_application_fields
                    _m("申请状态", "apply_status", "single_select"),
                    _m("申请编号", "application_no", "text"),
                    _m("审批流程", "approval_flow", "single_select"),
                    _m("审批节点", "approval_node", "text"),
                    _m("当前处理人", "current_handler", "person"),
                    _m("发起人", "initiator_name", "person"),
                    _m("发起时间", "submitted_at", "datetime"),
                    _m("完成时间", "completed_at", "datetime"),
                    _m("体检类型", "exam_type", "single_select"),
                    _m("姓名", "employee_name", "person"),
                    _m("身份证号码", "id_card_no", "text"),
                    _m("部门", "department", "text"),
                    _m("工种", "position", "text"),
                    _m("转入部门", "new_department", "text"),
                    _m("转入岗位", "new_position", "text"),
                    _m("转岗日期", "transfer_date", "datetime"),
                    _m("离岗日期", "leave_date", "datetime"),
                    _m("部门安全员", "dept_safety_officer", "person"),
                    _m("申请人", "applicant_name", "person"),
                    _m("申请日期", "apply_date", "datetime"),
                ),
            ),
            KindInfo(
                kind="new_employee",
                label="新员工登记表",
                default_connection=DefaultConnection(
                    app_token="Ea0abVsMzacU5VsF4K5cBH0kngb",
                    table_id="tblU8vVUUqiOYY14",
                    note="OH 新员工登记表",
                ),
                default_mappings=(
                    # ← feishu/oh_bitable_handler.py map_new_employee_fields
                    _m("姓名", "employee_name", "person"),
                    _m("身份证号码", "id_card_no", "text"),
                    _m("电话", "phone", "text"),
                    _m("性别", "gender", "single_select"),
                    _m("婚姻状况", "marital_status", "single_select"),
                    _m("部门", "department", "text"),
                    _m("工种", "position", "text"),
                    _m("登记时间", "scheduled_date", "datetime"),
                    _m("体检时间", "exam_date", "datetime"),
                    _m("检查结论", "exam_conclusion", "text"),
                    _m("处理意见", "treatment_advice_raw", "text"),
                    _m("备注", "notes", "text"),
                    _m("入职时间", "hire_date", "datetime"),
                    _m("工作年限（第一份工作入职时间）", "first_job_date", "datetime"),
                    _m("总工龄", "total_work_years", "text"),
                    _m("流程状态", "flow_status", "single_select"),
                ),
            ),
        ),
    ),
    # ── fire_alarm 消防报警（火灾报警表同步）────────────────────
    DomainInfo(
        key="fire_alarm",
        label="消防报警",
        purpose="火灾报警信息表同步",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="alarm",
                label="火灾报警信息表",
                default_connection=DefaultConnection(
                    app_token="MGX1bLhasaRx6usKOodcVpXGnTb",
                    table_id="tblgtwoBn4SMBSGj",
                    note="消防报警记录表",
                ),
                default_mappings=(
                    # ← service/fire_alarm/bitable_mapper.py map_bitable_fields
                    _m("报警时间", "alarm_time", "datetime"),
                    _m("报警类型", "alarm_type", "single_select"),
                    _m("报警部门", "department", "text"),
                    _m("报警部门负责人", "department_leader_name", "person"),
                    _m("报警部门负责人.部门", "department", "text", optional=True),
                    _m("报警楼栋", "building", "text"),
                    _m("报警部位", "location", "text"),
                    _m("报警性质", "alarm_nature", "single_select"),
                    _m("报警原因分类", "cause_category", "single_select"),
                    _m("具体报警原因", "cause_description", "text"),
                ),
            ),
        ),
    ),
    # ── central_alarm 中控报警（15 表白名单同步）─────────────────
    DomainInfo(
        key="central_alarm",
        label="中控报警",
        purpose="15 表白名单同步（主表 + extra_table_ids 白名单）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="alarm",
                label="中控报警统计表（白名单主表）",
                default_connection=DefaultConnection(
                    app_token="OdMRbCWr3aNEZKsFz94cAt12nzh",
                    table_id="tblpO3p8tMal4B1n",
                    extra_table_ids=(
                        "tblqwBhprwCZcpCp", "tblJ6Tt0V8lNhxKy", "tblHvWwh2NRcgk2A",
                        "tblivTu1wN9JJIfv", "tblvWbXdrx282OAw", "tblWWztfPQTIJXEw",
                        "tblPhO4rjLFRdBAL", "tblvXo7W3hSTHn7Q", "tblrZl7EfccGdYvg",
                        "tblIST5RYnGGz1zc", "tblLhez3NmikW12Q", "tbl0Cw9HdKbF6jRj",
                        "tblBoLEBUXPnM8qo", "tblvqjeuHQ6JTFga",
                    ),
                    note="中控报警统计表（白名单主表，另含 14 张白名单表）",
                ),
                default_mappings=(
                    # ← service/central_alarm/bitable_mapper.py map_bitable_fields
                    _m("日期", "alarm_date", "datetime"),
                    _m("岗位", "post", "text"),
                    _m("报警情况说明", "alarm_description", "text"),
                    _m("特殊情况说明", "special_note", "text"),
                ),
            ),
        ),
    ),
    # ── ehs_change EHS 变更（变更审批 + 变更验收，drive 文档事件）───
    DomainInfo(
        key="ehs_change",
        label="EHS 变更",
        purpose="变更审批 + 变更验收表同步（drive 文档事件，2026-09-08 自 record 事件迁移，原事件类型飞书从不推送）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="approval",
                label="变更审批表",
                default_connection=DefaultConnection(
                    app_token="X7mEbClq3asgrlsofZJczNiCnwb",
                    table_id="tblt0Rv0UaXZT4AK",
                    note="EHS 变更审批表",
                ),
                default_mappings=(
                    # ← feishu/ehs_change_bitable.py map_approval_fields
                    _m("申请状态", "status", "enum",
                       value_map={
                           "已通过": "approved", "审批中": "under_review", "已拒绝": "rejected",
                           "已撤回": "withdrawn", "已取消": "cancelled", "已终止": "terminated",
                       }),
                    _m("申请编号", "change_no", "text"),
                    _m("变更申请编号", "bt_change_no", "text", optional=True),
                    _m("变更名称", "title", "text"),
                    _m("变更分类", "change_type", "enum",
                       value_map={
                           "工艺技术变更": "process_tech",
                           "设备设施变更": "equipment_facility",
                           "管理变更": "management",
                       }),
                    _m("变更级别", "change_grade", "enum",
                       value_map={
                           "重大": "major", "重大变更": "major",
                           "一般": "general", "一般（需总经理审批）": "general", "一般变更": "general",
                       },
                       default_value="general"),
                    _m("变更时效", "change_duration", "enum",
                       value_map={
                           "临时变更": "temporary", "永久性变更": "permanent", "紧急变更": "emergency",
                       },
                       default_value="permanent"),
                    _m("变更申请部门", "department", "multi_select"),
                    _m("申请变更原因", "description", "text"),
                    _m("预计实施日期", "expected_start", "datetime"),
                    _m("预计效果", "expected_effect", "text"),
                    _m("变更发起人", "applicant_name", "person"),
                    _m("需更新的文件资料", "documents_to_update", "text"),
                    _m("变更状态", "bt_change_status", "text"),
                    _m("变更计划内容", "bt_plan_content", "text"),
                    _m("变更风险评估及建议措施", "bt_risk_measures", "text"),
                    _m("当前处理人", "current_handler", "person", optional=True),
                    _m("是否可以体现", "can_reflect", "single_select", optional=True),
                    _m("AI预审意见", "ai_pre_review", "text", optional=True),
                ),
            ),
            KindInfo(
                kind="acceptance",
                label="变更验收表",
                default_connection=DefaultConnection(
                    app_token="X7mEbClq3asgrlsofZJczNiCnwb",
                    table_id="tblaNPRi14i8CgS5",
                    note="EHS 变更验收表（同 app_token）",
                ),
                default_mappings=(
                    # ← feishu/ehs_change_bitable.py map_acceptance_fields
                    _m("申请状态", "status", "enum",
                       value_map={
                           "已通过": "approved", "审批中": "under_review", "已拒绝": "rejected",
                           "已撤回": "withdrawn", "已取消": "cancelled", "已终止": "terminated",
                       }),
                    _m("申请编号", "change_no", "text"),
                    _m("变更编号", "bt_change_no", "text", optional=True),
                    _m("变更名称", "title", "text"),
                    _m("变更级别", "change_grade", "enum",
                       value_map={
                           "重大": "major", "重大变更": "major",
                           "一般": "general", "一般（需总经理审批）": "general", "一般变更": "general",
                       },
                       default_value="general"),
                    _m("发起人部门", "department", "text"),
                    _m("发起人", "applicant_name", "person"),
                    _m("验收意见（可另附验收报告）", "bt_acceptance_comment", "text"),
                    _m("审批流程", "approval_flow", "single_select", optional=True),
                    _m("当前处理人", "current_handler", "person", optional=True),
                    _m("审批节点", "approval_node", "text", optional=True),
                    _m("关联审批", "related_approval", "text", optional=True),
                    _m("验收日期", "acceptance_date", "datetime", optional=True),
                ),
            ),
        ),
    ),
    # ── contractor_admission 相关方准入（准入条件表同步，drive 文档事件）──
    DomainInfo(
        key="contractor_admission",
        label="相关方准入",
        purpose="准入条件表同步（drive 文档事件，需 Drive 订阅；2026-08-31 自 record 事件迁移）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="admission",
                label="相关方准入表",
                default_connection=DefaultConnection(
                    app_token="YCvbbUYRqastNrse3k2coyOSnAb",
                    table_id="tblVWu4ENcUJWoDT",
                    note="相关方准入条件表",
                ),
                default_mappings=(
                    # ← feishu/contractor_admission_bitable.py map_fields
                    _m("作业单位名称", "company_name", "text"),
                    _m("相关方类型", "related_party_type", "single_select"),
                    _m("承包商负责人", "contact_person", "text"),
                    _m("承包商负责人联系电话", "contact_phone", "text"),
                    _m("对接人员", "liaison_user_name", "person"),
                    _m("入厂日期", "entry_date", "datetime"),
                    _m("开始日期", "start_date", "datetime"),
                    _m("结束日期", "end_date", "datetime"),
                    _m("材料失效日期", "material_expiry_date", "datetime"),
                    _m("实际提交日期", "actual_submit_date", "datetime"),
                    _m("实际完成日期", "actual_complete_date", "datetime"),
                    _m("提交状态", "submit_status", "single_select"),
                    _m("培训状态", "training_status", "single_select"),
                    _m("备注", "notes", "text"),
                    _m("承包商安全管理协议", "safety_agreement_files", "attachment"),
                    _m("合作类安全管理协议", "safety_agreement_files", "attachment", optional=True),
                    _m("劳务派遣安全管理协议", "safety_agreement_files", "attachment", optional=True),
                    _m("企业营业执照", "business_license_files", "attachment"),
                    _m("现场作业保险凭证", "insurance_files", "attachment"),
                    _m("承包商考核细则", "assessment_rules_files", "attachment"),
                    _m("员工证明盖章文件", "employee_cert_files", "attachment"),
                    _m("现场负责人盖章文件", "on_site_leader_stamp_files", "attachment"),
                ),
            ),
        ),
    ),
    # ── cert 持证台账（特种作业证 wiki + 监护人 A/B 证 base）──────
    DomainInfo(
        key="cert",
        label="持证台账",
        purpose="特种作业证（独立 wiki token）+ 监护人 A/B 证（共用 base token）镜像",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="special_op",
                label="特种作业证表",
                default_connection=DefaultConnection(
                    app_token="VyYmwLlZsi2sXDkkIa6cEISsnpg",
                    table_id="tblVapKErODx0sbi",
                    note="特种作业证台账（独立 wiki token）",
                ),
                default_mappings=(
                    # ← feishu/cert_bitable.py map_special_op_cert_fields
                    _m("姓名 (人员 )", "person_name", "person"),
                    _m("姓名", "person_name", "text", optional=True),
                    _m("部门", "department", "text"),
                    _m("作业类别", "operation_type", "single_select"),
                    _m("项目", "project", "single_select"),
                    _m("证件编号", "certificate_no", "text"),
                    _m("取证日期", "issue_date", "datetime"),
                    _m("再复审时间", "next_review_date", "datetime"),
                    _m("复审频次", "review_frequency", "single_select"),
                ),
            ),
            KindInfo(
                kind="guardian_a",
                label="监护人 A 证表",
                default_connection=DefaultConnection(
                    app_token="QNKibNfd2aIxSEsvWaJc13G6nCb",
                    table_id="tblQM8w21RNqizSt",
                    note="监护人 A 证台账",
                ),
                default_mappings=(
                    # ← feishu/cert_bitable.py map_guardian_cert_fields
                    _m("姓名", "person_name", "person"),
                    _m("部门", "department", "text"),
                    _m("取证日期", "issue_date", "datetime"),
                    _m("第一次复审截止日期", "first_review_deadline", "datetime"),
                    _m("第二次复审截止日期", "second_review_deadline", "datetime"),
                    _m("应换证日期", "should_renew_date", "datetime"),
                    _m("已换证日期", "renewed_date", "datetime"),
                    _m("证件类型", "notes", "single_select", optional=True),
                ),
            ),
            KindInfo(
                kind="guardian_b",
                label="监护人 B 证表",
                default_connection=DefaultConnection(
                    app_token="QNKibNfd2aIxSEsvWaJc13G6nCb",
                    table_id="tblb4yrziI6BnPG2",
                    note="监护人 B 证台账（同 base token）",
                ),
                default_mappings=(
                    # ← feishu/cert_bitable.py map_guardian_cert_fields
                    _m("姓名", "person_name", "person"),
                    _m("部门", "department", "text"),
                    _m("取证日期", "issue_date", "datetime"),
                    _m("第一次复审截止日期", "first_review_deadline", "datetime"),
                    _m("第二次复审截止日期", "second_review_deadline", "datetime"),
                    _m("应换证日期", "should_renew_date", "datetime"),
                    _m("已换证日期", "renewed_date", "datetime"),
                    _m("证件类型", "notes", "single_select", optional=True),
                ),
            ),
        ),
    ),
    # ── hazard_id 危险源辨识（AI 脚本流转 + 平台镜像）────────────
    DomainInfo(
        key="hazard_id",
        label="危险源辨识",
        purpose="AI 脚本流转 + 平台镜像（人工优先，脚本4 现有控制措施 AI 优先）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="identification",
                label="危险源辨识表",
                default_connection=DefaultConnection(
                    app_token="JxDcbWxcqarIqIsIs69cQ4Xinf8",
                    table_id="tbl3tDcJfGgP3yl9",
                    note="危险源辨识登记表（AI 脚本流转）",
                ),
                default_mappings=(
                    # ← service/hazard_identification_bitable.py _BASE_FIELDS/_AI_MANUAL_PAIRS/
                    #   _D_VALUE_PAIRS/_SCRIPT8_FIELDS（人工优先列为主，脚本4 取 AI 列）
                    _m("岗位（人工）", "position", "text"),
                    _m("生产步骤（人工）", "production_step", "text"),
                    _m("作业频次（人工）", "operation_frequency", "text"),
                    _m("操作人数（人工）", "operator_count", "text"),
                    _m("具体作业活动（人工）", "specific_activity", "text"),
                    _m("设备设施（人工）", "equipment_facilities", "text"),
                    _m("原辅料（人工）", "raw_auxiliary_materials", "text"),
                    _m("危险类型（人工）", "hazard_type", "multi_select"),
                    _m("可能导致事故（人工）", "possible_accident", "text"),
                    _m("不规范作业行为表现（人工）", "unsafe_behavior", "text"),
                    _m("可能性L（固有）（人工）", "l_inherent", "text"),
                    _m("暴露频率E（固有）（人工）", "e_inherent", "text"),
                    _m("严重性C（固有）（人工）", "c_inherent", "text"),
                    _m("现有工程控制措施（AI）", "existing_engineering_controls", "text"),
                    _m("现有管理控制措施（AI）", "existing_management_controls", "text"),
                    _m("现有个人防护措施（AI）", "existing_ppe", "text"),
                    _m("现有应急措施（AI）", "existing_emergency_measures", "text"),
                    _m("可能性L (残余）(人工)", "l_residual", "text"),
                    _m("暴露频率E (残余）(人工)", "e_residual", "text"),
                    _m("严重程度C （残余）(人工)", "c_residual", "text"),
                    _m("是否需提出建议措施（人工）", "needs_recommendation", "single_select"),
                    _m("建议措施类型（人工）", "recommendation_type", "multi_select"),
                    _m("建议措施内容（人工）", "recommendation_content", "text"),
                    _m("建议措施优先级（人工）", "recommendation_priority", "single_select"),
                    _m("L（采取建议措施）（人工）", "l_post", "text"),
                    _m("E（采取建议措施）（人工）", "e_post", "text"),
                    _m("C（采取建议措施）(人工)", "c_post", "text"),
                    _m("风险值D（固有）（人工）", "d_inherent", "text"),
                    _m("风险值D （残余）(人工)", "d_residual", "text"),
                    _m("风险值 D（采取建议措施后）（人工）", "d_post", "text"),
                    _m("固有风险等级（福建AI）", "inherent_risk_level_fj", "single_select"),
                    _m("工程措施排查内容（人工）", "engineering_check_items_manual", "text"),
                    _m("管理措施排查内容（人工）", "management_check_items_manual", "text"),
                    _m("个人防护措施排查内容（人工）", "ppe_check_items_manual", "text"),
                    _m("应急措施排查内容（人工）", "emergency_check_items_manual", "text"),
                    _m("提交人员", "submitter_name", "person"),
                    _m("审核人员", "reviewer_name", "person"),
                    _m("AI流程节点进度", "ai_flow_node_progress", "text"),
                ),
            ),
        ),
    ),
    # ── special_op 特殊作业日报（代码硬编码值固化）────────────────
    DomainInfo(
        key="special_op",
        label="特殊作业日报",
        purpose="全厂特殊作业一览表同步（原代码硬编码 app_token）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="daily",
                label="全厂特殊作业一览表",
                default_connection=DefaultConnection(
                    app_token="Lxn3bKHo9aVc7fsSp6YcLBgdnKh",
                    table_id="tblgcMQZ1mzsEolK",
                    note="特殊作业日报表（原代码硬编码）",
                ),
                default_mappings=(
                    # ← service/special_operation_daily_report.py map_bitable_fields
                    _m("作业类型", "operation_type", "enum",
                       value_map={
                           "动火作业": "hot_work", "受限空间": "confined_space",
                           "高处作业": "height_work", "吊装作业": "lifting",
                           "临时用电": "temporary_electricity", "动土作业": "excavation",
                           "断路作业": "road_breaking", "盲板抽堵": "blind_plate",
                           "常规作业": "hot_work",
                       }),
                    _m("作业分级", "operation_level", "enum",
                       default_value="grade2",
                       value_map={
                           "特级/Ⅳ级": "special", "一级（Ⅰ级）": "grade1",
                           "二级（Ⅱ级）": "grade2", "三级（Ⅲ级）": "grade2",
                           "不涉及": "not_applicable",
                       }),
                    _m("申请部门", "department", "text"),
                    _m("发起人部门", "initiator_department", "text", optional=True),
                    _m("作业内容", "work_description", "text"),
                    _m("作业地点", "location", "text"),
                    _m("作业时间_开始时间", "planned_start_time", "datetime"),
                    _m("作业时间_结束时间", "planned_end_time", "datetime"),
                    _m("作业时间_时长", "work_duration_hours", "text"),
                    _m("作业人员类型", "personnel_type", "single_select"),
                    _m("动火方式", "fire_work_method", "text", optional=True),
                    _m("高处作业方式", "height_work_method", "text", optional=True),
                    _m("作业高度(米)", "work_height", "text", optional=True),
                    _m("吊物质量(吨)", "lifting_weight", "text", optional=True),
                    _m("施工单位", "contractor_name", "text", optional=True),
                    _m("是否涉及其他特殊作业", "has_other_operations", "single_select", optional=True),
                    _m("涉及特殊作业类型", "other_operation_types", "multi_select", optional=True),
                    _m("周末节假日/非上班时段（关键作业）", "is_weekend_holiday", "single_select", optional=True),
                    _m("是否国家法定节假日", "is_national_holiday", "single_select", optional=True),
                    _m("非上班时间段/节假日", "holiday_period", "single_select", optional=True),
                    _m("报备类型", "report_type", "enum",
                       value_map={"计划内作业": "planned", "计划外作业": "unplanned"}),
                    _m("发起人", "initiator_name", "person"),
                    _m("作业票审批人类型", "approver_type", "single_select", optional=True),
                    _m("安全工程中心审批人", "safety_approver_name", "person", optional=True),
                    _m("审批人", "approver_name", "person"),
                    _m("申请编号", "approval_no", "text"),
                    _m("作业计划", "work_plan_url", "text"),
                    _m("作业方案", "work_scheme_url", "text"),
                    _m("已经通过签批的特殊作业票以及关联票", "approved_permit_url", "text"),
                    _m("发起时间", "submitted_at", "datetime"),
                    _m("完成时间", "completed_at", "datetime"),
                    _m("审批节点", "approval_node", "text"),
                ),
            ),
        ),
    ),
    # ── key_risk_op 关键风险作业（代码硬编码值固化）───────────────
    DomainInfo(
        key="key_risk_op",
        label="关键风险作业",
        purpose="每日关键风险预报表同步（原代码硬编码 app_token）",
        subscribe="drive",
        kinds=(
            KindInfo(
                kind="daily",
                label="每日关键风险预报表",
                default_connection=DefaultConnection(
                    app_token="LTZ1buQJaaLMxKsNcF2c13QPnrh",
                    table_id="tblEnatX5fxfwMlI",
                    note="关键风险作业日报表（原代码硬编码）",
                ),
                default_mappings=(
                    # ← service/key_risk_operation_report.py map_bitable_fields
                    _m("申请编号", "report_no", "text"),
                    _m("申请状态", "apply_status", "single_select"),
                    _m("审批节点", "approval_node", "text"),
                    _m("审批流程", "approval_flow", "single_select"),
                    _m("当前处理人", "current_handler", "person"),
                    _m("发起人", "initiator_name", "person"),
                    _m("发起人部门", "initiator_department", "text"),
                    _m("发起时间", "submitted_at", "datetime"),
                    _m("完成时间", "completed_at", "datetime"),
                    _m("部门", "department", "single_select"),
                    _m("区域", "area", "single_select"),
                    _m("作业内容", "operation_content", "text"),
                    _m("作业开始时间", "start_time", "datetime"),
                    _m("作业结束时间", "end_time", "datetime"),
                    _m("时长", "duration_hours", "text"),
                    _m("备注", "notes", "text"),
                    _m("个人防护", "personal_protection", "single_select"),
                    _m("准备措施", "preparation_measures", "single_select"),
                    _m("操作注意事项", "operation_precautions", "single_select"),
                    _m("应急措施", "emergency_measures", "single_select"),
                    _m("现场作业监护人", "guardian", "person"),
                    _m("现场监护人", "site_guardian", "person"),
                    _m("部门安全员", "dept_safety_officer", "person"),
                    _m("SourceID", "source_id", "text", optional=True),
                ),
            ),
        ),
    ),
)

# 构造时断言：域 key 唯一（重复 key 会在 dict 推导时静默覆盖，故显式校验）
REGISTRY: dict[str, DomainInfo] = {d.key: d for d in _DOMAINS}
assert len(REGISTRY) == len(_DOMAINS), "Bitable 域注册表存在重复 domain key"
for _domain in _DOMAINS:
    _kind_keys = [k.kind for k in _domain.kinds]
    assert len(_kind_keys) == len(set(_kind_keys)), (
        f"Bitable 域 {_domain.key} 存在重复 kind key"
    )


def _apply_env_overrides() -> dict[str, DomainInfo]:
    """按 ``SAFETY_BITABLE_APP_TOKEN_{DOMAIN_KEY}`` 覆盖各域 app_token。

    代码内默认值是本厂测试版 Base token（与 .env.development 一致）；换环境
    部署时用同名 env 键覆盖，不需改代码。DB 活行优先级始终高于本 registry。
    """
    overridden: dict[str, DomainInfo] = {}
    for domain in _DOMAINS:
        env_key = f"SAFETY_BITABLE_APP_TOKEN_{domain.key.upper()}"
        token = os.environ.get(env_key, "").strip()
        if not token:
            overridden[domain.key] = domain
            continue
        new_domain = domain
        new_kinds = []
        for kind in domain.kinds:
            if kind.default_connection is not None:
                kind = replace(
                    kind,
                    default_connection=replace(
                        kind.default_connection, app_token=token
                    ),
                )
            new_kinds.append(kind)
        new_domain = replace(new_domain, kinds=tuple(new_kinds))
        overridden[domain.key] = new_domain
    return overridden


# 环境覆盖在导入时应用一次（registry 是迁移播种源 + 运行时 fallback）
REGISTRY = _apply_env_overrides()


def get_domain(key: str) -> DomainInfo:
    """未知域名抛 ValueError（消息以「未知域名」开头，与 scheduler 校验惯例一致）。"""
    domain = REGISTRY.get(key)
    if domain is None:
        raise ValueError(f"未知域名: {key}")
    return domain


def iter_connection_kinds() -> Iterator[tuple[DomainInfo, KindInfo]]:
    """遍历全部 (域, kind) 连接行（共 24 行），供 migration 播种与断言测试使用。"""
    for domain in _DOMAINS:
        for kind in domain.kinds:
            if kind.default_connection is not None:
                yield domain, kind


def iter_mapping_kinds() -> Iterator[tuple[DomainInfo, KindInfo]]:
    """遍历全部 (域, kind) 映射行（共 24 行，每 kind 一行）。"""
    for domain in _DOMAINS:
        for kind in domain.kinds:
            if kind.default_mappings:
                yield domain, kind

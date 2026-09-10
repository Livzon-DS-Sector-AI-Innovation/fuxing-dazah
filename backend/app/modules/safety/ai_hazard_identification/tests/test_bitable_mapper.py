"""Ticket 01 — map_bitable_to_model 纯逻辑映射测试。

用真实 Bitable 字段样本构造 fixtures（脚本1-8 双份字段 + 公式字段 + 提交/审核人员），
覆盖：人工优先、无部门派生、脚本8 双份字段、公式字段（D值/等级）读取。
"""

from app.modules.safety.service.hazard_identification_bitable import (
    map_bitable_to_model,
)


def _person(name: str, oid: str) -> list[dict]:
    return [{"name": name, "opend_id": oid}]


def _rich_text(text: str) -> list[dict]:
    """Bitable 富文本字段的典型格式。"""
    return [{"type": "text", "text": text, "style": {}}]


# 一条接近真实的 Bitable 记录字段样本（脚本1-8 + 公式 + 人员 + 状态）
SAMPLE_FIELDS = {
    # 基础
    "岗位（人工）": "发酵车间主操",
    "生产步骤（人工）": "发酵罐灭菌操作",
    "作业频次（人工）": "每周",
    # 脚本1
    "具体作业活动（AI）": _rich_text("人工投料、灭菌"),
    "具体作业活动（人工）": _rich_text("人工投料（手工确认）"),
    "设备设施（AI）": "发酵罐、蒸汽管道",
    "设备设施（人工）": "",
    "原辅料（AI）": _rich_text("培养基、蒸汽"),
    "原辅料（人工）": _rich_text("培养基"),
    # 脚本2
    "危险类型（AI）": "设备设施缺陷",
    "危险类型（人工）": "人的不安全行为",
    "可能导致事故（AI）": "烫伤、灼伤",
    "可能导致事故（人工）": "",
    "不规范作业行为表现（AI）": "未佩戴防护",
    "不规范作业行为表现（人工）": "",
    # 脚本3（D 值为公式字段，AI/人工 各一列）
    "可能性L（固有）（AI）": 3,
    "可能性L（固有）（人工）": 6,
    "暴露频率E（固有）（AI）": 3,
    "暴露频率E（固有）（人工）": 6,
    "严重性C（固有）（AI）": 15,
    "严重性C（固有）（人工）": 15,
    "风险值D（固有）（AI）": 540,          # 公式计算结果
    "风险值D（固有）（人工）": 540,          # 公式计算结果
    # 脚本4
    "现有工程控制措施（AI）": "通风系统",
    "现有工程控制措施（人工）": "",
    "现有管理控制措施（AI）": "安全操作规程",
    "现有管理控制措施（人工）": "安全操作规程 + 交接班",
    "现有个人防护措施（AI）": "防护面屏",
    "现有个人防护措施（人工）": "",
    "现有应急措施（AI）": "应急物资",
    "现有应急措施（人工）": "",
    # 脚本5（D 值为公式字段；实际字段名括号混用：半角开+全角闭）
    "可能性L(残余）（AI）": 1,
    "可能性L (残余）(人工)": 2,
    "暴露频率E(残余）（AI）": 3,
    "暴露频率E (残余）(人工)": 3,
    "严重程度C（残余）（AI）": 7,
    "严重程度C （残余）(人工)": 7,
    "风险值D（残余）（AI）": 42,
    "风险值D （残余）(人工)": 42,
    # 脚本6
    "是否需提出建议措施（AI）": "是",
    "是否需提出建议措施（人工）": "是",
    "建议措施类型（AI）": "工程技术",
    "建议措施类型（人工）": "",
    "建议措施内容（AI）": "增设联锁",
    "建议措施内容（人工）": "",
    "建议措施优先级（AI）": "高",
    "建议措施优先级（人工）": "",
    # 脚本7（D 值为公式字段；人工字段措辞为「采取建议措施」，与 AI 字段不同）
    "L（建议措施采取后）（AI）": 0.5,
    "L（采取建议措施）（人工）": 1,
    "E（建议措施采取后）（AI）": 2,
    "E（采取建议措施）（人工）": 2,
    "C（建议措施采取后）（AI）": 7,
    "C（采取建议措施）(人工)": 7,
    "风险值D（建议措施采取后）（AI）": 14,
    "风险值 D（采取建议措施后）（人工）": 14,
    # 脚本8（AI + 人工 各一列）
    "工程措施排查内容（AI）": "（1）检查通风系统是否运行正常。",
    "工程措施排查内容（人工）": "（1）检查通风系统是否运行正常。\n（2）检查排风口是否畅通。",
    "管理措施排查内容（AI）": "（1）检查安全操作规程是否现场可获取。",
    "管理措施排查内容（人工）": "",
    "个人防护措施排查内容（AI）": "（1）检查防护面屏是否完好。",
    "个人防护措施排查内容（人工）": "",
    "应急措施排查内容（AI）": "（1）检查应急物资是否齐全。",
    "应急措施排查内容（人工）": "",
    # 提交/审核人员（Bitable 字段带「（人工）」后缀）
    "提交人员（人工）": _person("张工", "ou_submit123"),
    "审核人员（人工）": _person("李工", "ou_review456"),
    # 状态
    "AI流程节点进度": "待AI评价残余风险",
    "脚本1（人工审核状态）": "已审核",
    "脚本2（人工审核状态）": "已审核",
    "脚本3（人工审核状态）": "已审核",
    "脚本4（人工审核状态）": "待审核",
    "脚本5（人工审核状态）": "待审核",
    "脚本6（人工审核状态）": "待审核",
    "脚本7（人工审核状态）": "待审核",
    "脚本8（人工审核状态）": "待审核",
}


class TestManualPreference:
    """人工优先：人工值非空取人工，否则取 AI 值。"""

    def test_manual_non_empty_takes_manual(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["specific_activity"] == "人工投料（手工确认）"

    def test_manual_empty_falls_back_to_ai(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["equipment_facilities"] == "发酵罐、蒸汽管道"
        assert out["existing_engineering_controls"] == "通风系统"

    def test_both_empty_is_none(self):
        fields = dict(SAMPLE_FIELDS)
        fields["设备设施（AI）"] = ""
        fields["设备设施（人工）"] = ""
        out = map_bitable_to_model(fields)
        assert out["equipment_facilities"] is None

    def test_rich_text_manual_wins(self):
        fields = dict(SAMPLE_FIELDS)
        fields["具体作业活动（人工）"] = _rich_text("手工投料（复核后）")
        out = map_bitable_to_model(fields)
        assert out["specific_activity"] == "手工投料（复核后）"


class TestDepartmentDerivation:
    """无部门字段 → 从提交人员经 resolve_department 派生，派不到置空。"""

    def test_explicit_department_wins(self):
        out = map_bitable_to_model(SAMPLE_FIELDS, department="原料药生产部")
        assert out["department"] == "原料药生产部"

    def test_derived_from_submitter(self):
        out = map_bitable_to_model(
            SAMPLE_FIELDS,
            resolve_department=lambda submitter: "生产部" if submitter == "张工" else None,
        )
        assert out["department"] == "生产部"

    def test_unresolvable_department_is_none(self):
        out = map_bitable_to_model(
            SAMPLE_FIELDS,
            resolve_department=lambda submitter: None,
        )
        assert out["department"] is None

    def test_no_resolver_no_department_is_none(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["department"] is None


class TestScript8DualFields:
    """脚本8 四类排查内容 AI + 人工 各一列。"""

    def test_dual_columns_present(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["engineering_check_items_ai"].startswith("（1）检查通风系统")
        assert out["engineering_check_items_manual"] == (
            "（1）检查通风系统是否运行正常。\n（2）检查排风口是否畅通。"
        )

    def test_empty_manual_side_is_none(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["management_check_items_manual"] is None
        assert out["management_check_items_ai"].startswith("（1）检查安全操作规程")

    def test_all_eight_columns_present(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        for col in [
            "engineering_check_items_ai", "engineering_check_items_manual",
            "management_check_items_ai", "management_check_items_manual",
            "ppe_check_items_ai", "ppe_check_items_manual",
            "emergency_check_items_ai", "emergency_check_items_manual",
        ]:
            assert col in out


class TestFormulaFields:
    """公式字段（D 值/风险等级）只读镜像。"""

    def test_d_values_read_as_float(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["d_inherent"] == 540.0
        assert out["d_residual"] == 42.0
        assert out["d_post"] == 14.0

    def test_risk_levels_derived_from_d(self):
        """风险等级按平台阈值由 D 推导（Bitable 公式阈值 160/70/20 与平台一致）。"""
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["inherent_risk_level"] == "level_1"
        assert out["inherent_risk_label"] == "一级/重大风险"
        assert out["residual_risk_level"] == "level_3"
        assert out["residual_risk_label"] == "三级/一般风险"
        assert out["post_risk_level"] == "level_4"
        assert out["post_risk_label"] == "四级/低风险"

    def test_control_level_derived_from_inherent(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["control_level"] == "公司级"

    def test_missing_formula_is_none(self):
        fields = dict(SAMPLE_FIELDS)
        fields.pop("风险值D（固有）（AI）", None)
        fields.pop("风险值D（固有）（人工）", None)
        out = map_bitable_to_model(fields)
        assert out["d_inherent"] is None
        assert out["inherent_risk_level"] is None
        assert out["inherent_risk_label"] is None
        assert out["control_level"] is None


class TestLecFloatConversion:
    """L/E/C 数值列（模型为 float）必须解析为 float，不能落成字符串。"""

    LEC_KEYS = [
        "l_inherent", "e_inherent", "c_inherent",
        "l_residual", "e_residual", "c_residual",
        "l_post", "e_post", "c_post",
    ]

    def test_manual_preference_float(self):
        """人工优先且返回 float：L(固有) AI=3 人工=6 → 6.0。"""
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["l_inherent"] == 6.0
        assert out["c_inherent"] == 15.0  # AI=人工 同值
        assert out["l_post"] == 1.0  # AI=0.5 人工=1 → 人工
        assert out["e_post"] == 2.0

    def test_residual_lec_paren_quirk_matches(self):
        """残余 LEC 实际字段名括号混用（半角开+全角闭）→ 归一化后仍能匹配并取 float。"""
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["l_residual"] == 2.0  # 人工 2 > AI 1
        assert out["e_residual"] == 3.0
        assert out["c_residual"] == 7.0

    def test_post_manual_wording_matches(self):
        """措施后人工字段实际措辞「采取建议措施」→ 归一化 + 候选名匹配到 float。"""
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["l_post"] == 1.0
        assert out["c_post"] == 7.0

    def test_ai_fallback_float(self):
        """人工空 → 回退 AI 且返回 float。"""
        fields = dict(SAMPLE_FIELDS)
        for fname in ("可能性L（固有）（人工）", "暴露频率E（固有）（人工）"):
            fields[fname] = ""
        out = map_bitable_to_model(fields)
        assert out["l_inherent"] == 3.0  # AI=3
        assert out["e_inherent"] == 3.0  # AI=3

    def test_all_lec_keys_are_float(self):
        """9 个 L/E/C 键全部为 float（或 None），不出现字符串。"""
        out = map_bitable_to_model(SAMPLE_FIELDS)
        for key in self.LEC_KEYS:
            value = out[key]
            assert isinstance(value, float), f"{key}={value!r} 应为 float"

    def test_unparseable_lec_is_none(self):
        """AI/人工均无法解析为数值 → None（不抛错、不写字符串）。"""
        fields = dict(SAMPLE_FIELDS)
        fields["可能性L（固有）（AI）"] = "高"
        fields["可能性L（固有）（人工）"] = "不确定"
        out = map_bitable_to_model(fields)
        assert out["l_inherent"] is None

    def test_empty_lec_is_none(self):
        fields = dict(SAMPLE_FIELDS)
        for fname in (
            "可能性L（固有）（AI）", "可能性L（固有）（人工）",
            "暴露频率E（固有）（AI）", "暴露频率E（固有）（人工）",
        ):
            fields[fname] = ""
        out = map_bitable_to_model(fields)
        assert out["l_inherent"] is None
        assert out["e_inherent"] is None


class TestPeopleAndStatus:
    """提交/审核人员 + AI流程节点 + 各脚本审核状态。"""

    def test_people_extracted(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["submitter_name"] == "张工"
        assert out["submitter_feishu_id"] == "ou_submit123"
        assert out["reviewer_name"] == "李工"
        assert out["reviewer_feishu_id"] == "ou_review456"

    def test_node_progress(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["ai_node_progress"] == "pending_script5"

    def test_node_completed_maps_to_enum(self):
        fields = dict(SAMPLE_FIELDS)
        fields["AI流程节点进度"] = "AI 流程结束"
        out = map_bitable_to_model(fields)
        assert out["ai_node_progress"] == "completed"

    def test_node_script8_maps_to_enum(self):
        fields = dict(SAMPLE_FIELDS)
        fields["AI流程节点进度"] = "待人工审核检查清单"
        out = map_bitable_to_model(fields)
        assert out["ai_node_progress"] == "pending_script8"

    def test_node_all_labels_map(self):
        """Bitable 全部 9 种节点标签 → 平台枚举（1-8 + 结束），供前端筛选/展示。"""
        labels = {
            "待危险源信息AI提取": "pending_script1",
            "待AI危险源辨识": "pending_script2",
            "待AI固有风险评价": "pending_script3",
            "待AI输入现有控制措施": "pending_script4",
            "待AI评价残余风险": "pending_script5",
            "待AI提出建议措施": "pending_script6",
            "待AI评价采取措施后的残余风险": "pending_script7",
            "待人工审核检查清单": "pending_script8",
            "AI 流程结束": "completed",
        }
        for label, expected in labels.items():
            fields = dict(SAMPLE_FIELDS)
            fields["AI流程节点进度"] = label
            out = map_bitable_to_model(fields)
            assert out["ai_node_progress"] == expected, f"{label} → {expected}"

    def test_review_statuses_mapped_to_enum(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["script1_review_status"] == "approved"
        assert out["script3_review_status"] == "approved"
        assert out["script4_review_status"] == "pending"

    def test_unknown_review_status_passthrough(self):
        fields = dict(SAMPLE_FIELDS)
        fields["脚本2（人工审核状态）"] = "审核中"
        out = map_bitable_to_model(fields)
        assert out["script2_review_status"] == "审核中"

    def test_empty_review_status_falls_back_to_pending(self):
        """Bitable 无审核状态 → 回落列默认 pending（列 NOT NULL，禁止写 None）。"""
        fields = dict(SAMPLE_FIELDS)
        fields.pop("脚本6（人工审核状态）", None)
        fields.pop("脚本7（人工审核状态）", None)
        out = map_bitable_to_model(fields)
        assert out["script6_review_status"] == "pending"
        assert out["script7_review_status"] == "pending"

    def test_record_metadata(self):
        out = map_bitable_to_model(
            SAMPLE_FIELDS,
            feishu_record_id="recABC123",
            feishu_url="https://feishu.cn/base/xxx",
            feishu_table_id="tbl3tDcJfGgP3yl9",
        )
        assert out["feishu_record_id"] == "recABC123"
        assert out["feishu_url"] == "https://feishu.cn/base/xxx"
        assert out["feishu_table_id"] == "tbl3tDcJfGgP3yl9"


class TestOverallStatus:
    """整体状态：Bitable 节点「AI 流程结束」→ completed（导出/统计依赖），否则 draft。"""

    def test_completed_node_maps_to_completed(self):
        fields = dict(SAMPLE_FIELDS)
        fields["AI流程节点进度"] = "AI 流程结束"
        out = map_bitable_to_model(fields)
        assert out["ai_node_progress"] == "completed"
        assert out["overall_status"] == "completed"

    def test_pending_node_maps_to_draft(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["overall_status"] == "draft"

    def test_missing_node_is_draft(self):
        fields = dict(SAMPLE_FIELDS)
        fields.pop("AI流程节点进度", None)
        out = map_bitable_to_model(fields)
        # 节点缺失不写 ai_node_progress（列 NOT NULL，DB 默认 pending_input 承担），
        # 但 overall_status 始终派生为 draft
        assert out.get("ai_node_progress") is None
        assert out["overall_status"] == "draft"


class TestSnapshot:
    """bitable_snapshot 保留完整字段（AI/人工双份 + 公式结果）。"""

    def test_snapshot_is_full_copy(self):
        out = map_bitable_to_model(SAMPLE_FIELDS)
        assert out["bitable_snapshot"] == SAMPLE_FIELDS
        assert "具体作业活动（AI）" in out["bitable_snapshot"]
        assert "风险值D（固有）（AI）" in out["bitable_snapshot"]
        assert "风险值D （残余）(人工)" in out["bitable_snapshot"]

    def test_snapshot_not_mutated_by_input_change(self):
        fields = dict(SAMPLE_FIELDS)
        out = map_bitable_to_model(fields)
        fields["岗位（人工）"] = "改了"
        assert out["bitable_snapshot"]["岗位（人工）"] == "发酵车间主操"

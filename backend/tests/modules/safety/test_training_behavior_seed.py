"""S6 教育培训与行为管控：两表 schema 与三违回填行构造测试（一期 R1 底座）。

蓝本列名是域页分析（domain_pages._analyze_training）与 D3 取数器的直读契约
——改名即断链，本测试逐列锁定名称/类型/枚举。回填口径：隐患表
"隐患类别（AI）=三违作业"行 → 违章档案初始行，幂等键=关联隐患编号。
"""

from __future__ import annotations

from app.modules.safety.service.training_behavior import seed_data

# ── 蓝本 §3.2 + 微增 3 列 ──────────────────────────────────────
_TRAINING_FIELDS = (
    "培训名称", "培训类别", "计划日期", "实施日期", "培训形式",
    "组织部门", "讲师", "应到人数", "实到人数", "签到表",
    "考核方式", "考核合格人数", "状态", "下次复训日期", "备注",
    "培训学时", "课件与试卷", "关联违章编号",
)
# ── 蓝本 §3.3 + 微增 2 列 ──────────────────────────────────────
_VIOLATION_FIELDS = (
    "违章日期", "违章人员", "所属单位", "违章类别", "违章等级",
    "违章描述", "处理方式", "纠正措施", "状态", "关联隐患编号",
    "定向培训", "备注", "证据附件", "AI判级建议",
)


def _fields(schema: dict) -> dict[str, dict]:
    return {f["field_name"]: f for f in schema["table"]["fields"]}


def _options(field: dict) -> list[str]:
    return [o["name"] for o in field.get("property", {}).get("options", [])]


class TestTableSchemas:
    def test_training_field_names_exact(self) -> None:
        fields = _fields(seed_data.table_schema_training())
        assert tuple(fields) == _TRAINING_FIELDS

    def test_training_key_types_and_enums(self) -> None:
        fields = _fields(seed_data.table_schema_training())
        assert fields["培训学时"]["type"] == 2          # 数字
        assert fields["课件与试卷"]["type"] == 17        # 附件
        assert fields["签到表"]["type"] == 17
        assert fields["讲师"]["type"] == 11              # 人员
        assert fields["组织部门"]["type"] == 4           # 多选
        assert fields["计划日期"]["type"] == 5           # 日期
        assert _options(fields["培训类别"]) == [
            "入厂三级教育", "年度复训", "专项培训", "转岗培训", "外来人员培训",
        ]
        assert _options(fields["培训形式"]) == ["线下", "线上", "实操"]
        assert _options(fields["考核方式"]) == ["考试", "签到", "实操评估", "无需考核"]
        assert _options(fields["状态"]) == ["未开始", "进行中", "已完成", "已取消"]

    def test_violation_field_names_exact(self) -> None:
        fields = _fields(seed_data.table_schema_violation())
        assert tuple(fields) == _VIOLATION_FIELDS

    def test_violation_key_types_and_enums(self) -> None:
        fields = _fields(seed_data.table_schema_violation())
        assert fields["违章人员"]["type"] == 11
        assert fields["所属单位"]["type"] == 4
        assert fields["证据附件"]["type"] == 17
        assert _options(fields["违章类别"]) == ["操作违章", "指挥违章", "防护缺失", "纪律违章"]
        assert _options(fields["违章等级"]) == ["一般", "严重", "重大"]
        assert _options(fields["处理方式"]) == ["批评教育", "罚款", "停工培训", "待岗"]
        assert _options(fields["状态"]) == ["纠正中", "已纠正"]

    def test_domain_kind_constants_match_registry(self) -> None:
        assert seed_data.DOMAIN == "training_behavior"
        assert seed_data.KIND_TRAINING == "training"
        assert seed_data.KIND_VIOLATION == "violation"


def _hazard_fields(
    no: str = "YH-2026-001",
    category: str = "三违作业",
    desc_ai: str | None = "未佩戴安全帽登高作业",
    desc: str | None = None,
    date_ms: int | None = 1_762_934_400_000,  # 2025-11-12 16:00 UTC ≈ 北京 11-13
) -> dict:
    fields: dict = {"隐患编号": no, "隐患类别（AI）": category}
    if desc_ai is not None:
        fields["隐患描述（AI）"] = desc_ai
    if desc is not None:
        fields["隐患描述"] = desc
    if date_ms is not None:
        fields["检查日期"] = date_ms
    return fields


class TestViolationRowFromHazard:
    def test_full_mapping(self) -> None:
        row = seed_data.violation_row_from_hazard(_hazard_fields())
        assert row["关联隐患编号"] == "YH-2026-001"
        assert row["违章描述"] == "未佩戴安全帽登高作业"
        assert row["状态"] == "纠正中"
        assert row["违章日期"] == 1_762_934_400_000  # ms 原值透传
        assert "回流" in row["备注"]

    def test_desc_fallback_to_manual_column(self) -> None:
        row = seed_data.violation_row_from_hazard(
            _hazard_fields(desc_ai=None, desc="人工登记的违章描述")
        )
        assert row["违章描述"] == "人工登记的违章描述"

    def test_missing_date_omitted(self) -> None:
        row = seed_data.violation_row_from_hazard(_hazard_fields(date_ms=None))
        assert "违章日期" not in row


class TestPlanBackfill:
    def test_filters_non_violation_and_dedupes(self) -> None:
        records = [
            {"record_id": "r1", "fields": _hazard_fields(no="YH-1")},
            {"record_id": "r2", "fields": _hazard_fields(no="YH-2", category="设备设施")},
            {"record_id": "r3", "fields": _hazard_fields(no="YH-3", category="三违作业")},
            # 批内重复编号：只取第一条
            {"record_id": "r4", "fields": _hazard_fields(no="YH-1")},
        ]
        plan = seed_data.plan_backfill(records, existing_nos={"YH-3"})
        assert [r["关联隐患编号"] for r in plan] == ["YH-1"]

    def test_empty_when_all_backfilled(self) -> None:
        records = [{"record_id": "r1", "fields": _hazard_fields(no="YH-1")}]
        assert seed_data.plan_backfill(records, existing_nos={"YH-1"}) == []

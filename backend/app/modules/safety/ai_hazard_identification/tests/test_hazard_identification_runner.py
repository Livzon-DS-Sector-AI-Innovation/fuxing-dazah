"""Ticket 06 — HazardIdentificationScriptRunner 生产 run_script 适配器测试。

覆盖：effective dict → Plugin Input 构建（按字段过滤 + None→"" 归一）、
脚本 1-8 全量 Input 构建、代表性脚本端到端执行（fake ai_service）、
AI 失败 → None。fake ai_service 无网络/无真实 AI 依赖。
"""

from app.modules.safety.ai_hazard_identification.schemas import PluginConfig
from app.modules.safety.service.hazard_identification_runner import (
    HazardIdentificationScriptRunner,
)

# ── fake AI 服务：按 expected_keys 返回预设 dict（须通过各脚本规则引擎验证）──
_RAW_BY_SCRIPT = {
    2: {
        "hazard_type": "化学灼伤、腐蚀灼伤",
        "possible_accident": "未确认罐压为0即打开罐盖，残余压力导致盐酸喷溅造成操作人员化学灼伤",
        "unsafe_behavior": "未执行罐压确认步骤即打开罐盖；未规范佩戴防飞溅面屏",
    },
    3: {
        "lec": {
            "l_value": 3, "e_value": 6, "c_value": 15,
            "d_value": 270, "risk_level": "level_1", "risk_label": "重大风险",
        },
    },
}


class _FakeAIService:
    """记录调用并返回预设 raw dict 的 fake ai_service（插件经 chat_parsed 消费）。"""

    def __init__(self, raw: dict | None = None, raise_error: bool = False):
        self.raw = raw
        self.raise_error = raise_error
        self.calls: list[dict] = []

    async def chat_parsed(self, messages, expected_keys=None, temperature=None, max_tokens=None):
        self.calls.append(
            {"messages": messages, "expected_keys": expected_keys,
             "temperature": temperature, "max_tokens": max_tokens}
        )
        if self.raise_error:
            raise RuntimeError("AI 服务不可用")
        return self.raw or {}


def _effective(script: int) -> dict:
    """构造脚本 N 的最小有效 effective dict（对应 bitable_service._build_script_input 产物）。"""
    base = {
        "department": "原料药生产部",
        "position": "发酵车间主操",
        "production_step": "发酵罐灭菌操作",
        "specific_activity": "人工投料",
        "equipment_facilities": "发酵罐、蒸汽管道",
        "raw_auxiliary_materials": "培养基、蒸汽",
    }
    if script == 1:
        return base | {"attachment_text": "岗位操作规程……"}
    if script == 2:
        return base
    base2 = base | {
        "hazard_type": "设备设施缺陷", "possible_accident": "烫伤", "unsafe_behavior": "未佩戴防护",
    }
    if script == 3:
        return base2
    base3 = base2 | {"l_inherent": 3, "e_inherent": 6, "c_inherent": 15}
    if script == 4:
        return base3
    base4 = base3 | {
        "existing_engineering_controls": "通风系统", "existing_management_controls": "安全操作规程",
        "existing_ppe": "防护面屏", "existing_emergency_measures": "应急物资",
    }
    if script == 5:
        return base4
    base5 = base4 | {"l_residual": 1, "e_residual": 3, "c_residual": 7}
    if script == 6:
        return base5
    base6 = base5 | {"recommendation_content": "增设联锁", "recommendation_type": "工程技术"}
    if script == 7:
        return base6
    # 脚本8：专取 4 类现有控制措施（人工）
    return {
        "engineering_controls": "通风系统", "management_controls": "安全操作规程",
        "ppe": "防护面屏", "emergency_measures": "应急物资",
    }


class TestBuildInputModel:
    """effective dict → Plugin Input 模型构建。"""

    async def test_all_scripts_build_successfully(self):
        runner = HazardIdentificationScriptRunner()
        for script in range(1, 9):
            input_model = runner._build_input_model(script, _effective(script))
            assert input_model is not None, f"脚本{script} Input 构建失败"
            # 必填 str 字段全部非空（None→"" 归一生效）
            for name, field in type(input_model).model_fields.items():
                if field.is_required() and field.annotation is str:
                    assert getattr(input_model, name) != "", f"脚本{script} 必填字段 {name} 为空"

    async def test_script2_input_has_core_fields(self):
        runner = HazardIdentificationScriptRunner()
        m = runner._build_input_model(2, _effective(2))
        assert m.department == "原料药生产部"
        assert m.specific_activity == "人工投料"
        assert m.equipment_facilities == "发酵罐、蒸汽管道"

    async def test_script8_input_uses_manual_measures_keys(self):
        runner = HazardIdentificationScriptRunner()
        m = runner._build_input_model(8, _effective(8))
        assert m.engineering_controls == "通风系统"
        assert m.ppe == "防护面屏"
        assert m.emergency_measures == "应急物资"

    async def test_none_required_str_coerced_to_empty(self):
        # 部门解析不到 → None；必填 str 字段应归一为 "" 而非报错
        runner = HazardIdentificationScriptRunner()
        effective = _effective(2)
        effective["department"] = None
        m = runner._build_input_model(2, effective)
        assert m.department == ""

    async def test_unknown_extra_keys_filtered_out(self):
        # effective 中 Input 模型未声明的字段（如 submitter_name/bitable_snapshot）被过滤
        runner = HazardIdentificationScriptRunner()
        effective = _effective(2) | {"submitter_name": "张三", "bitable_snapshot": {"x": 1}}
        m = runner._build_input_model(2, effective)
        assert not hasattr(m, "bitable_snapshot")


class TestCallEndToEnd:
    """runner.__call__ 代表性脚本端到端（fake ai_service，脚本2 关闭 RAG 避免真实检索）。"""

    async def test_script2_executes_and_returns_output(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[2])
        runner = HazardIdentificationScriptRunner(ai_service=ai, enable_rag=False)
        out = await runner(2, _effective(2))
        assert out.hazard_type == "化学灼伤、腐蚀灼伤"
        assert "灼伤" in out.possible_accident
        assert "罐盖" in out.unsafe_behavior
        assert len(ai.calls) == 1
        # prompt 结构：system 角色 + user prompt
        assert ai.calls[0]["messages"][0]["role"] == "system"
        assert ai.calls[0]["temperature"] == 0.05  # 默认低温度
        assert ai.calls[0]["max_tokens"] == 4096  # 插件配置默认 max_tokens（seed 配置一致）

    async def test_script3_lec_output_shape(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[3])
        runner = HazardIdentificationScriptRunner(ai_service=ai)
        out = await runner(3, _effective(3))
        assert out.lec.l_value == 3
        assert out.lec.d_value == 270
        assert out.lec.risk_level == "level_1"

    async def test_custom_config_temperature_respected(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[2])
        runner = HazardIdentificationScriptRunner(
            ai_service=ai, config=PluginConfig(temperature=0.1), enable_rag=False,
        )
        await runner(2, _effective(2))
        assert ai.calls[0]["temperature"] == 0.1

    async def test_ai_failure_returns_none(self):
        ai = _FakeAIService(raise_error=True)
        runner = HazardIdentificationScriptRunner(ai_service=ai, enable_rag=False)
        assert await runner(2, _effective(2)) is None

    async def test_missing_required_input_returns_none(self):
        # effective 缺必填字段 → Input 构建失败 → None（不抛异常）
        runner = HazardIdentificationScriptRunner(
            ai_service=_FakeAIService(_RAW_BY_SCRIPT[2]), enable_rag=False,
        )
        assert await runner(2, {}) is None


class TestRagInjection:
    """脚本2 RAG 知识增强注入（fake rag_loader，无真实 DB/网络）。"""

    async def test_script2_injects_rag_into_prompt(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[2])

        async def fake_rag_loader(effective: dict) -> str | None:
            # 确认查询描述来自 effective
            assert effective["department"] == "原料药生产部"
            return "## 相关法规条款\n\n《危险化学品安全管理条例》测试条款"

        runner = HazardIdentificationScriptRunner(ai_service=ai, rag_loader=fake_rag_loader)
        out = await runner(2, _effective(2))
        assert out is not None
        prompt = ai.calls[0]["messages"][1]["content"]
        assert "## 参考文档（知识库）" in prompt
        assert "《危险化学品安全管理条例》测试条款" in prompt

    async def test_rag_not_applied_to_other_scripts(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[3])

        async def fake_rag_loader(effective: dict) -> str | None:
            raise AssertionError("脚本3 不应触发 RAG")

        runner = HazardIdentificationScriptRunner(ai_service=ai, rag_loader=fake_rag_loader)
        out = await runner(3, _effective(3))
        assert out is not None
        prompt = ai.calls[0]["messages"][1]["content"]
        assert "## 参考文档（知识库）" not in prompt

    async def test_rag_loader_failure_degrades_gracefully(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[2])

        async def failing_rag_loader(effective: dict) -> str | None:
            raise RuntimeError("知识库不可用")

        runner = HazardIdentificationScriptRunner(ai_service=ai, rag_loader=failing_rag_loader)
        # RAG 失败不阻断辨识：输出正常返回，prompt 无参考文档段
        out = await runner(2, _effective(2))
        assert out is not None
        prompt = ai.calls[0]["messages"][1]["content"]
        assert "## 参考文档（知识库）" not in prompt

    async def test_rag_disabled_skips_loader(self):
        ai = _FakeAIService(_RAW_BY_SCRIPT[2])

        async def fake_rag_loader(effective: dict) -> str | None:
            raise AssertionError("enable_rag=False 不应触发 RAG")

        runner = HazardIdentificationScriptRunner(
            ai_service=ai, enable_rag=False, rag_loader=fake_rag_loader,
        )
        assert await runner(2, _effective(2)) is not None

    def test_build_rag_query_joins_core_fields(self):
        query = HazardIdentificationScriptRunner._build_rag_query(_effective(2))
        assert "原料药生产部" in query
        assert "人工投料" in query
        assert "发酵罐、蒸汽管道" in query
        assert "培养基、蒸汽" in query

    def test_build_rag_query_skips_empty_and_none(self):
        assert HazardIdentificationScriptRunner._build_rag_query({}) == ""
        assert HazardIdentificationScriptRunner._build_rag_query(
            {"department": "", "specific_activity": None}
        ) == ""

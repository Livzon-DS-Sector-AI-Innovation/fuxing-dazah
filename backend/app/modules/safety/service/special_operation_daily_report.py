"""特殊作业日报 Service — 风险判定引擎 + 报告生成 + 推送编排.

基于 SpecialOperationReport 数据，提供:
1. RiskAssessmentEngine — V2 纯规则风险判定
2. ReportBuilder — Markdown 模板引擎
3. SpecialOperationDailyReportService — Bitable 同步 + 日报生成 + 推送
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import SpecialOperationReport
from app.modules.safety.schemas.special_op_daily import (
    AIDailyAnalysisResult,
    DailyReportResponse,
    RiskAssessmentResult,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Bitable 配置（app_token/table_id 由配置中心 store 提供，见 sync_from_bitable）
# ═══════════════════════════════════════════════════════════

# 日报推送目标 — 特殊作业自动分配群
DAILY_REPORT_CHAT_ID = "oc_d102e1a11eaaa9a1de3b41859de9d0c1"

# ═══════════════════════════════════════════════════════════
# 类型推断关键词库
# ═══════════════════════════════════════════════════════════

TYPE_INFERENCE_RULES: dict[str, list[str]] = {
    "受限空间": ["下罐", "进罐", "罐内", "洗罐", "清罐", "拆搅拌", "罐壁打磨", "蛇管", "盘管", "列管", "入罐"],
    "动火作业": ["焊接", "电焊", "气焊", "切割", "气割", "打磨", "抛光", "明火", "烘烤", "热处理"],
    "高处作业": ["高空", "爬高", "屋顶", "管廊", "桥架", "外墙", "脚手架", "二楼及以上楼层", "登高"],
    "吊装作业": ["吊装", "吊运", "起重", "吊车", "行车", "葫芦", "倒链", "卸车"],
    "临时用电": ["临时用电", "接电", "焊机", "配电箱", "探伤", "拍片", "X光", "射线"],
}

HIGH_RISK_ZONE_KEYWORDS = ["罐区", "洁净区"]


# ═══════════════════════════════════════════════════════════
# RiskAssessmentEngine — V2 纯规则判定
# ═══════════════════════════════════════════════════════════

class RiskAssessmentEngine:
    """特殊作业日报风险判定引擎（V3.5）。

    判定优先级（一旦匹配即返回）:
    1. 高风险（14 条规则）
    2. 中风险（19 条规则）
    3. 低风险（14 条规则）
    4. 兜底规则

    V3.5 新增维度: 动火方式风险分级、登高方式×高度联动、吊装质量分级、罐号分级
    新字段取值优先级: 表单字段 → 文本推断 → 兜底默认中风险
    """

    # operation_type 英文 → 中文（与 ReportBuilder 保持一致）
    _OP_TYPE_EN2CN: dict[str, str] = {
        "hot_work": "动火作业",
        "confined_space": "受限空间",
        "height_work": "高处作业",
        "lifting": "吊装作业",
        "temporary_electricity": "临时用电",
        "excavation": "动土作业",
        "road_breaking": "断路作业",
        "blind_plate": "盲板抽堵",
    }

    # 动火方式风险分级
    _HIGH_RISK_FIRE = ("电焊", "气割", "等离子切割机", "氩弧焊")
    _MEDIUM_RISK_FIRE = ("切割机", "角磨机")
    _LOW_RISK_FIRE = ("电钻", "冲击钻", "塑料焊")

    # 登高方式 × 作业高度 风险矩阵
    _HEIGHT_RISK_MATRIX: dict[str, dict[str, str]] = {
        "门式脚手架": {"<5": "low", "5-15": "high", ">=15": "high"},
        "扣件式脚手架": {"<5": "low", "5-15": "medium", ">=15": "high"},
        "高处作业车": {"<5": "low", "5-15": "low", ">=15": "medium"},
        "固定式直爬梯": {"<5": "low", "5-15": "high", ">=15": "high"},
        "便携式钢直梯": {"<5": "low", "5-15": "high", ">=15": "high"},
    }

    @classmethod
    def _cn_type(cls, op_type: str | None) -> str:
        if not op_type:
            return ""
        return cls._OP_TYPE_EN2CN.get(op_type, op_type)

    @classmethod
    def _get_fire_risk(cls, report: SpecialOperationReport) -> str | None:
        """动火方式风险分级。返回 high/medium/low/None"""
        method = (report.fire_work_method or "").strip()
        if not method:
            return None  # 无数据，走兜底
        if any(m in method for m in cls._HIGH_RISK_FIRE):
            return "high"
        if any(m in method for m in cls._MEDIUM_RISK_FIRE):
            return "medium"
        if any(m in method for m in cls._LOW_RISK_FIRE):
            return "low"
        return "medium"  # "其他" → 默认中风险

    @classmethod
    def _get_height_risk(cls, report: SpecialOperationReport) -> str | None:
        """登高方式 × 作业高度 联合判定。返回 high/medium/low/None"""
        method = (report.height_work_method or "").strip()
        height = report.work_height
        if not method:
            return None
        matrix = cls._HEIGHT_RISK_MATRIX.get(method)
        if not matrix:
            if height is not None and height >= 5:
                return "high"
            return "medium"  # "其他" + <5m → 中风险（默认）
        if height is None:
            return "medium"  # 无高度数据 → 保守中风险
        if height < 5:
            return matrix.get("<5", "medium")
        if height < 15:
            return matrix.get("5-15", "medium")
        return matrix.get(">=15", "medium")

    @classmethod
    def _get_lifting_risk(cls, report: SpecialOperationReport) -> str | None:
        """吊装质量分级。≥40t高风险，<40t中风险"""
        w = report.lifting_weight
        if w is None:
            return None
        return "high" if w >= 40 else "medium"

    @classmethod
    def _tank_grade(cls, report: SpecialOperationReport) -> str | None:
        """发酵工程部罐号分级。返回 high/medium/low/None（非发酵工程部或非受限空间）"""
        op_type = cls._cn_type(report.operation_type)
        dept = report.department or ""
        loc = report.location or ""
        if dept != "发酵工程部" or op_type != "受限空间":
            return None
        import re
        # 从地点提取罐号首数字
        m = re.search(r'(\d){3,}', loc)
        if not m:
            return "medium"  # 无法识别罐号，保守中风险
        first_digit = m.group(1)[0]
        if first_digit == "3":
            return "high"
        if first_digit in ("2", "4"):
            return "medium"
        if first_digit == "1":
            return "low"
        return "medium"

    # ── 主判定入口 ──

    @classmethod
    def assess(cls, report: SpecialOperationReport) -> RiskAssessmentResult:
        """V3.5 风险判定。"""
        op_type_raw = cls._cn_type(report.operation_type)
        description = report.work_description or ""
        location = report.location or ""
        dept = report.department or ""
        personnel = report.personnel_type or ""
        dur = report.work_duration_hours
        is_off = cls._is_off_hours(report)

        inferred = cls._infer_types(op_type_raw, description, location)
        all_types = cls._merge_types(op_type_raw, inferred, report)

        # 预计算新维度
        fire_risk = cls._get_fire_risk(report)
        height_risk = cls._get_height_risk(report)
        lifting_risk = cls._get_lifting_risk(report)
        tank_grade = cls._tank_grade(report)

        # ── 高风险判定 ──
        high = cls._assess_high(all_types, report, description, location,
                                fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off)
        if high:
            return RiskAssessmentResult(risk_level="high", matched_rules=high, inferred_types=inferred)

        # ── 中风险判定 ──
        medium = cls._assess_medium(all_types, report, description, location,
                                    fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off)
        if medium:
            return RiskAssessmentResult(risk_level="medium", matched_rules=medium, inferred_types=inferred)

        # ── 低风险判定 ──
        low = cls._assess_low(all_types, report, description, location,
                              fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off)
        if low:
            return RiskAssessmentResult(risk_level="low", matched_rules=low, inferred_types=inferred)

        # ── 兜底 ──
        fb_level, fb_reason = cls._assess_fallback(all_types, report)
        return RiskAssessmentResult(risk_level=fb_level, matched_rules=[fb_reason], inferred_types=inferred)

    @classmethod
    def _infer_types(cls, op_type_raw: str, description: str, location: str) -> list[str]:
        inferred = []
        combined = f"{description} {location}"
        for type_name, keywords in TYPE_INFERENCE_RULES.items():
            if type_name == op_type_raw:
                continue
            for kw in keywords:
                if kw in combined:
                    inferred.append(type_name)
                    break
        return inferred

    @classmethod
    def _merge_types(cls, op_type_raw: str, inferred: list[str], report: SpecialOperationReport) -> set[str]:
        all_types: set[str] = set()
        if op_type_raw and op_type_raw != "常规作业":
            all_types.add(op_type_raw)
        for t in inferred:
            all_types.add(t)
        other = report.other_operation_types or []
        if isinstance(other, list):
            for t in other:
                cn = cls._cn_type(t)
                if cn and cn != "常规作业":
                    all_types.add(cn)
        return all_types

    @classmethod
    def _is_off_hours(cls, report: SpecialOperationReport) -> bool:
        if report.is_weekend_holiday == "是":
            return True
        if report.is_national_holiday == "是":
            return True
        start = report.planned_start_time
        if start:
            from datetime import timedelta
            bj = start + timedelta(hours=8)  # UTC → 北京时间
            if bj.hour >= 18 or bj.hour < 8:
                return True
        return False

    # ════════════════ V3.5 高风险（14 条）════════════════

    @classmethod
    def _assess_high(cls, all_types, report, description, location,
                     fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off) -> list[str] | None:
        m = []
        # 1
        if "动火作业" in all_types and "受限空间" in all_types:
            m.append("动火作业+受限空间同时存在")
        # 2
        if len(all_types) >= 3:
            m.append(f"三种及以上特殊作业类型叠加（{', '.join(sorted(all_types))}）")
        # 3
        if is_off and "动火作业" in all_types and ("高处作业" in all_types or "临时用电" in all_types):
            m.append("夜间/周末动火+高处作业或临时用电")
        # 4
        is_danger = any(kw in (location or "") for kw in HIGH_RISK_ZONE_KEYWORDS)
        if is_danger and ("动火作业" in all_types or "受限空间" in all_types):
            m.append(f"洁净区/罐区{'动火' if '动火作业' in all_types else '受限空间'}作业")
        # 5
        has_tank = any(kw in (description or "") for kw in ("下罐", "进罐", "清罐", "入罐"))
        if has_tank and len(all_types) >= 2:
            m.append("下罐/清罐叠加其他特殊作业")
        # 6
        if "受限空间" in all_types and personnel == "非公司人员":
            m.append("受限空间+外部承包商")
        # 7 动火方式高风险 + 受限空间/罐区
        if fire_risk == "high" and ("受限空间" in all_types or is_danger):
            m.append("高风险动火方式+受限空间/罐区环境")
        # 8-12 登高方式 × 高度
        if height_risk == "high":
            method = report.height_work_method or "其他"
            h = report.work_height
            m.append(f"{method}+作业高度≥5m（{h}m）" if h else f"{method}+危险高度")
        # 13 吊装质量≥40t
        if lifting_risk == "high":
            m.append(f"吊装质量≥40t（{report.lifting_weight}t）")
        # 14 发酵工程部罐号3开头 → 高风险
        if tank_grade == "high":
            m.append("发酵工程部受限空间+3开头罐号（高风险罐号）")
        return m if m else None

    # ════════════════ V3.5 中风险（19 条）════════════════

    @classmethod
    def _assess_medium(cls, all_types, report, description, location,
                       fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off) -> list[str] | None:
        m = []
        # 1 受限空间（发酵工程部1开头罐除外——走低风险）
        if "受限空间" in all_types and tank_grade != "low":
            m.append("受限空间作业")
        # 2
        if "吊装作业" in all_types:
            m.append("吊装作业")
        # 3
        if "动火作业" in all_types and len(all_types) >= 2 and "受限空间" not in all_types:
            m.append("动火作业+其他特殊作业（不含受限空间）")
        # 4
        if is_off and "动火作业" in all_types:
            m.append("夜间/周末实施动火作业")
        # 5
        if personnel == "非公司人员" and any(t in all_types for t in ("动火作业", "吊装作业", "受限空间")):
            m.append("外部人员实施动火/吊装/受限空间")
        # 6
        if "高处作业" in all_types and any(kw in (location or "") for kw in ("塔顶", "管廊", "夹层", "屋顶")):
            m.append("高处作业+塔顶/管廊/夹层/屋顶")
        # 7
        has_cut = any(kw in (description or "") for kw in ("焊接", "切割", "拆除"))
        if has_cut and dur and dur > 4:
            m.append(f"焊接/切割/拆除>4h（{dur}h）")
        # 8
        if dur and dur > 8 and len(all_types) == 1:
            m.append(f"单一特殊作业时长>8h（{dur}h）")
        # 9
        if personnel == "其他相关方" and len(all_types) >= 1:
            m.append("多个承包商同时作业")
        # 10
        if "高处作业" in all_types and personnel == "非公司人员":
            m.append("高处作业+外部承包商")
        # 11 动火方式中风险 + >4h
        if fire_risk == "medium" and dur and dur > 4:
            m.append(f"中风险动火方式+作业时长>4h（{dur}h）")
        # 12 动火方式"其他" + 任何动火
        if fire_risk == "medium" and "动火作业" in all_types:
            m.append("动火方式为其他/未明确+动火场景")
        # 13-15 登高方式 × 高度 中风险
        if height_risk == "medium":
            method = report.height_work_method or "其他"
            h = report.work_height
            m.append(f"{method}+中风险高度（{h}m）" if h else f"{method}+中风险高度组合")
        # 16 吊装 <40t
        if lifting_risk == "medium":
            m.append(f"吊装质量<40t（{report.lifting_weight}t）")
        # 17 低风险动火 + 洁净区/罐区
        is_danger = any(kw in (location or "") for kw in HIGH_RISK_ZONE_KEYWORDS)
        if fire_risk == "low" and is_danger:
            m.append("低风险动火方式+洁净区/罐区环境")
        # 18 发酵工程部罐号2/4开头 → 中风险
        if tank_grade == "medium":
            m.append("发酵工程部受限空间+2/4开头罐号（中风险罐号）")
        # 19 发酵工程部1开头罐 + 动火/外部承包商 → 升级中风险（原为低风险）
        if tank_grade == "low" and (personnel == "非公司人员"):
            if any(t in all_types for t in ("动火作业", "吊装作业")):
                m.append("发酵工程部1开头罐+动火/外部承包商（升级中风险）")
        return m if m else None

    # ════════════════ V3.5 低风险（14 条）════════════════

    @classmethod
    def _assess_low(cls, all_types, report, description, location,
                    fire_risk, height_risk, lifting_risk, tank_grade, dept, personnel, dur, is_off) -> list[str] | None:
        m = []
        # 1-5 登高方式低风险组合
        if height_risk == "low":
            method = report.height_work_method or "其他"
            m.append(f"{method}+作业高度<5m")
        # 6 单一临时用电
        if all_types == {"临时用电"}:
            m.append("单一临时用电作业")
        # 7 白班单一动火（非高风险动火方式）
        if all_types == {"动火作业"} and not is_off and fire_risk != "high":
            m.append("正常工作时段单一动火作业（非高风险动火方式）")
        # 8 一般安装/维修类
        if any(kw in (description or "") for kw in ("安装", "配管", "电仪", "维修", "保温")) and len(all_types) <= 1:
            m.append("一般安装/配管/电仪/维修/保温作业")
        # 9
        is_cleaning = any(kw in (description or "") for kw in ("清洗", "清洁", "清扫"))
        has_tank = any(kw in (description or "") for kw in ("下罐", "进罐", "清罐", "入罐"))
        if is_cleaning and not has_tank:
            m.append("清洗/清洁类作业（非下罐）")
        # 10 适中时长
        if len(all_types) == 1 and dur and 2 <= dur <= 8 and fire_risk != "high" and height_risk != "high":
            m.append(f"单一特殊作业时长2-8h（{dur}h）")
        # 11 管道/阀门类
        if any(kw in (description or "") for kw in ("管道", "阀门", "泵", "管线")) and fire_risk != "high":
            m.append("管道/阀门/泵类作业（不涉及高风险动火）")
        # 12 低风险动火 + 普通区域 + 内部人员
        is_danger = any(kw in (location or "") for kw in HIGH_RISK_ZONE_KEYWORDS)
        if fire_risk == "low" and not is_danger and personnel == "公司人员":
            m.append("低风险动火方式+普通作业区域+公司内部人员")
        # 13 发酵工程部1开头罐 → 低风险
        if tank_grade == "low":
            m.append("发酵工程部受限空间+1开头罐号（无动火+非外部承包商）")
        # 14 全满足低风险
        if not m:
            if (len(all_types) <= 1 and not is_off and (dur is None or dur <= 2)
                    and personnel == "公司人员"
                    and not is_danger
                    and not any(kw in (description or "") for kw in ("焊接", "切割", "拆除", "吊运", "清罐", "高空", "赶工", "抢修", "紧急"))):
                m.append("低风险全满足规则")
        return m if m else None

    # ════════════════ 兜底 ════════════════

    @classmethod
    def _assess_fallback(cls, all_types: set[str], report: SpecialOperationReport) -> tuple[str, str]:
        personnel = report.personnel_type or ""
        dur = report.work_duration_hours
        location = report.location or ""
        if all_types and len(all_types) >= 1:
            return "medium", "有特殊作业类型但未匹配到特定规则"
        if personnel == "非公司人员":
            return "medium", "外部承包商作业（无特殊作业类型）"
        if dur and dur > 4:
            return "medium", f"作业时长>4小时（{dur}h）"
        if any(kw in (location or "") for kw in HIGH_RISK_ZONE_KEYWORDS):
            return "medium", "危险区域作业（罐区/洁净区）"
        return "low", "常规低风险作业"


# ═══════════════════════════════════════════════════════════
# AIAnalyst — RAG 检索 + AI 增强分析
# ═══════════════════════════════════════════════════════════

# STABLE — 单条记录分析 prompt（每条高风险作业独立调用，互不混淆）
_PER_RECORD_SYSTEM_PROMPT = """你是一个化工企业特殊作业安全管理专家。你将收到一条高风险作业的详细信息，请分析并输出：

1. **enhanced_reason**: 用自然语言重写风险描述（40-100字）
   - 综合：作业类型、地点、内容、时长、人员、关联类型
   - 聚焦核心风险点，不照抄原文
   - 风险描述基于实际数据，不是基于"规则判定"文字

2. **control_measure**: 针对性的管控措施（30-60字）
   - 具体可操作，不说空话
   - 基于作业类型、风险等级和实际场景

## 输出格式
严格返回 JSON：{"enhanced_reason": "...", "control_measure": "..."}

## ⚠️ 重要判断规则
- 是否"夜间"：看作业时间的小时数。开始时间 00:00-08:00 或 18:00-24:00 为夜间；08:00-18:00 为白班。
- 是否"周末/节假日"：看特殊时段标记。只有明确标注了"特殊时段: 是"才是周末/节假日。
- 不要在风险描述中写入与作业时间、特殊时段标记矛盾的内容。
- "规则判定"字段仅供参考，当它与实际数据（时间、地点、内容、特殊时段标记）矛盾时，以实际数据为准。
- 管控措施要贴合具体作业场景"""

# STABLE — 汇总分析 prompt（所有单条分析完成后执行）
_AGGREGATE_SYSTEM_PROMPT = """你是一个化工企业特殊作业安全管理专家。输入中有当日全部高风险作业清单（按部门分组）和逐条分析摘要，请生成一段"高风险作业概况"文字：

## 生成要求
1. **完整性**：必须将清单中每一条高风险作业都纳入概括，不得遗漏任何一项
2. **格式**：
   - 以"高风险作业集中在"开头，按部门归类
   - 同一部门的多个作业用顿号"、"或分号";"分隔
   - 不同部门之间用逗号"，"隔开
   - 结尾为"为今日重点监管区域"（次日预警场景结尾为"为次日重点监管区域"）
3. **内容要素**：每条作业须包含"部门+作业类型—作业内容"
   - 作业类型示例：动火作业、受限空间作业、吊装作业
   - 作业内容简要提炼即可，无需时间、单位、管控措施等信息
   - 禁止笼统表述如"动火作业居多""火灾爆炸风险突出"等
4. **enhanced_tips**：1-3 条，每条一句话，对应当日高风险的针对性措施，不得编号

## 输出格式
严格返回 JSON：{"summary": "...", "enhanced_tips": ["...", "..."]}（enhanced_tips 为 1-3 条，每条一句话，对应当日高风险的针对性措施，不得编号）

## 示例
高风险作业集中在A部门动火作业—管道焊接、设备安装，B部门受限空间作业—下罐清洗，C部门吊装作业—设备吊运，为今日重点监管区域。"""


class AIAnalyst:
    """AI + RAG 日报增强分析器（V2：每条高风险作业独立 AI 调用，避免混淆）。

    流程:
    1. 对每条高风险记录 → RAG 检索 → 独立 AI 调用 → {enhanced_reason, control_measure}
    2. 所有单条完成后 → 汇总 AI 调用 → {summary, enhanced_tips}
    3. 任何环节失败返回空结果，报告退化为纯规则版本。
    """

    def __init__(self, session):
        self.session = session

    async def analyze(
        self,
        report_date: date,
        mode: str,
        reports: list[SpecialOperationReport],
        stats: dict[str, int],
    ) -> AIDailyAnalysisResult | None:
        """执行 RAG 检索 + AI 分析。失败返回 None。"""
        import asyncio
        import logging

        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.schemas.special_op_daily import AIDailyAnalysisResult
        from app.modules.safety.service.config import create_ai_service

        logger = logging.getLogger(__name__)
        high = sorted(
            [r for r in reports if r.daily_risk_level == "high"],
            key=ReportBuilder._sort_key,
        )
        if not high:
            return None

        try:
            ai_service = create_ai_service("text")
        except Exception:
            logger.warning("创建 AI 服务失败，回退纯规则报告")
            return None

        # ── Phase 1: 每条高风险作业独立分析（并行）──
        from app.core.database import async_session_factory

        async def analyze_one(idx: int, r: SpecialOperationReport) -> dict | None:
            """分析单条高风险作业。失败返回 None。"""
            try:
                # RAG 检索 — 使用独立 session 避免并发冲突
                rag_md = ""
                try:
                    from app.modules.safety.knowledge.retriever import (
                        SafetyKnowledgeRetriever,
                    )
                    cn_type = ReportBuilder._cn_label(r.operation_type)
                    rag_query = f"特殊作业安全规范 {cn_type} {r.daily_risk_reason or ''}"
                    async with async_session_factory() as rag_session:
                        retriever = SafetyKnowledgeRetriever(rag_session)
                        ctx = await retriever.retrieve(
                            description=rag_query[:200],
                            categories=["laws_regulations", "standards", "management_systems"],
                            target_chunks=4,
                        )
                        rag_md = ctx.markdown or ""
                except Exception:
                    pass

                # 构建单条 prompt
                user_prompt = self._build_single_prompt(r, rag_md)

                with ai_audit_scope(
                    scenario="daily_report_analysis",
                    resource_type="special_op_daily_report",
                    channel="system",
                ):
                    result = await ai_service.chat_parsed(
                        messages=[
                            {"role": "system", "content": _PER_RECORD_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        expected_keys=["enhanced_reason", "control_measure"],
                        temperature=0.3,
                    )
                    return {
                        "idx": idx,
                        "enhanced_reason": result.get("enhanced_reason", ""),
                        "control_measure": result.get("control_measure", ""),
                    }
            except Exception:
                logger.warning("单条 AI 分析失败 idx=%d", idx)
                return None

        # 限流并行 — 最多 3 条同时调用，避免 API 限流超时
        sem = asyncio.Semaphore(3)

        async def analyze_with_limit(idx: int, r: SpecialOperationReport) -> dict | None:
            async with sem:
                return await analyze_one(idx, r)

        tasks = [analyze_with_limit(i, r) for i, r in enumerate(high[:15])]
        per_results = await asyncio.gather(*tasks, return_exceptions=True)

        enhanced_reasons: dict[str, str] = {}
        control_measures: dict[str, str] = {}
        per_summaries: list[str] = []
        for result in per_results:
            if isinstance(result, Exception) or result is None:
                continue
            key = str(result["idx"] + 1)
            enhanced_reasons[key] = result["enhanced_reason"]
            control_measures[key] = result["control_measure"]
            r = high[result["idx"]]
            cn = ReportBuilder._cn_label(r.operation_type)
            per_summaries.append(f"作业{key}: {cn} {r.department} - {result['enhanced_reason'][:60]}")

        if not enhanced_reasons:
            logger.warning("所有单条 AI 分析失败，回退纯规则报告")
            return None

        # ── Phase 2: 汇总分析 ──
        summary = ""
        enhanced_tips: list[str] = []
        try:
            aggregate_prompt = self._build_aggregate_prompt(report_date, mode, high,
                                                            per_summaries, stats)
            with ai_audit_scope(
                scenario="daily_report_analysis",
                resource_type="special_op_daily_report",
                channel="system",
            ):
                agg_result = await ai_service.chat_parsed(
                    messages=[
                        {"role": "system", "content": _AGGREGATE_SYSTEM_PROMPT},
                        {"role": "user", "content": aggregate_prompt},
                    ],
                    expected_keys=["summary", "enhanced_tips"],
                    temperature=0.3,
                )
                summary = agg_result.get("summary", "")
                enhanced_tips = agg_result.get("enhanced_tips", [])
        except Exception:
            logger.warning("汇总 AI 分析失败")

        return AIDailyAnalysisResult(
            summary=summary,
            enhanced_reasons=enhanced_reasons,
            control_measures=control_measures,
            enhanced_tips=enhanced_tips,
        )

    @classmethod
    def _build_single_prompt(cls, r: SpecialOperationReport, rag_md: str) -> str:
        """构建单条记录的分析 prompt。"""
        cn_type = ReportBuilder._cn_label(r.operation_type)
        lines = [
            "## 高风险作业分析",
            f"- 作业类型: {cn_type}",
            f"- 部门: {r.department or '?'}",
            f"- 地点: {r.location or '未知'}",
        ]
        if r.work_description:
            lines.append(f"- 作业内容: {r.work_description[:120]}")
        if r.planned_start_time:
            from datetime import timedelta
            bj_start = r.planned_start_time + timedelta(hours=8)
            lines.append(f"- 作业时间: {bj_start.strftime('%m/%d %H:%M')}")
            if r.planned_end_time:
                bj_end = r.planned_end_time + timedelta(hours=8)
                lines.append(f"  — {bj_end.strftime('%H:%M')}")
        if r.work_duration_hours:
            lines.append(f"- 时长: {r.work_duration_hours}h")
        if r.personnel_type:
            lines.append(f"- 人员类型: {r.personnel_type}")
        if r.contractor_name:
            lines.append(f"- 施工单位: {r.contractor_name}")
        lines.append(f"- 规则判定: {r.daily_risk_reason or ''}")
        # 特殊时段（恒输出 是/否）
        is_special = (r.is_weekend_holiday or "") == "是" or (r.is_national_holiday or "") == "是"
        lines.append(f"- 特殊时段: {'是' if is_special else '否'}")
        # 关联作业
        other_types = []
        ot = r.other_operation_types or []
        if isinstance(ot, list):
            for t in ot:
                other_types.append(ReportBuilder._cn_label(t) if isinstance(t, str) else str(t))
        if other_types:
            lines.append(f"- 关联类型: {'、'.join(other_types)}")
        if rag_md:
            lines.append(f"- 参考法规: {rag_md[:1200]}")
        return "\n".join(lines)

    @classmethod
    def _build_aggregate_prompt(
        cls,
        report_date: date,
        mode: str,
        high: list,
        per_summaries: list[str],
        stats: dict,
    ) -> str:
        """构建汇总分析 prompt。"""
        mode_label = "特殊作业日报" if ReportBuilder._is_today_family(mode) else "特殊作业次日预警"
        # 按部门分组统计高风险（与逐条 AI 分析上限 high[:15] 对齐）
        dept_groups: dict[str, list] = {}
        for r in high[:15]:
            d = r.department or "?"
            dept_groups.setdefault(d, []).append(r)
        dept_lines = []
        for d, items in sorted(dept_groups.items(), key=lambda x: -len(x[1])):
            dept_lines.append(f"- {d}: {len(items)}项")
            for i, r in enumerate(items, 1):
                cn = ReportBuilder._cn_label(r.operation_type)
                if not cn.endswith("作业"):
                    cn += "作业"
                content = (r.work_description or "").strip()
                line = f"   {i}. {cn}"
                if content:
                    line += f"—{content[:30]}"
                dept_lines.append(line)
        total_n = stats.get("effective_total", stats.get("total", 0) - stats.get("excluded", 0))
        total_line = (
            f"总作业: {total_n} 项（高: {stats['high']} / 中: {stats['medium']} / 低: {stats['low']}）"
        )
        if stats.get("excluded", 0) > 0:
            total_line += f"（另含已排除 {stats['excluded']} 项）"
        dept_header = "## 高风险按部门分布"
        if len(high) > 15:
            dept_header += "（仅显示前 15 条）"
        lines = [
            "## 汇总任务",
            f"{mode_label} - {report_date.strftime('%Y年%m月%d日')}",
            total_line,
            "",
            dept_header,
        ]
        lines.extend(dept_lines)
        lines.append("")
        lines.append("## 各高风险作业分析摘要")
        for s in per_summaries:
            lines.append(f"- {s}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# ReportBuilder
# ═══════════════════════════════════════════════════════════

class ReportBuilder:
    """日报 Markdown 模板引擎。"""

    # operation_type 英文 → 中文标签
    _OP_TYPE_EN2CN: dict[str, str] = {
        "hot_work": "动火作业",
        "confined_space": "受限空间",
        "height_work": "高处作业",
        "lifting": "吊装作业",
        "temporary_electricity": "临时用电",
        "excavation": "动土作业",
        "road_breaking": "断路作业",
        "blind_plate": "盲板抽堵",
    }

    @classmethod
    def _cn_label(cls, op_type: str | None) -> str:
        """英文枚举 → 中文标签"""
        if not op_type:
            return "常规"
        return cls._OP_TYPE_EN2CN.get(op_type, op_type)

    @staticmethod
    def _is_today_family(mode: str) -> bool:
        """今日族模式(today / afternoon):沿用当日日报标题/标签。

        17点日报(afternoon)属于当日日报家族,与次日预警(tomorrow)区分。
        """
        return mode in ("today", "afternoon")

    @staticmethod
    def _bj_time(dt: datetime | None) -> str:
        """UTC → 北京时间字符串"""
        if dt is None:
            return ""
        from datetime import timedelta
        bj = dt + timedelta(hours=8)
        return bj.strftime('%m/%d %H:%M')

    @classmethod
    def _sort_key(cls, r: SpecialOperationReport) -> tuple:
        """高风险排序键：按 risk_reason 严重度 → 时长降序 → 部门 → 时间"""
        reason = r.daily_risk_reason or ""
        # "叠加" / "同时存在" 排最前
        has_overlap = 0 if ("叠加" in reason or "同时存在" in reason) else 1
        # 外部承包商次之
        has_external = 0 if (r.personnel_type or "") == "非公司人员" else 1
        dur = -(r.work_duration_hours or 0)  # 时长降序
        return (has_overlap, has_external, dur, r.department or "", r.planned_start_time or datetime.min)

    @classmethod
    def _new_ops_section(cls, report_date: date, reports: list, mode: str) -> list[str]:
        """构建「今日新增计划外作业」段落。

        计划外 = 当天北京时间 08:00 之后新提交（发起）的特殊作业，
        不依赖多维表「报备类型」字段：
        - afternoon（17点日报）: 窗口为 08:00 ~ 17:00
        - today（机器人随时查询）: 窗口为 08:00 ~ 当前查询时刻
        提交时间取 submitted_at（发起时间），缺失时回退 created_at。
        """
        start = datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc)  # BJT 08:00
        if mode == "afternoon":
            end = start + timedelta(hours=9)  # BJT 17:00
        else:
            end = datetime.now(timezone.utc)

        def _new_ts(r) -> datetime:
            if r.submitted_at:
                return r.submitted_at
            if r.created_at:
                return r.created_at
            return datetime.min.replace(tzinfo=timezone.utc)

        new = [r for r in reports if start <= _new_ts(r) < end]
        lines = ["", "🔔 今日新增计划外作业", "━━━━━━━━━━━━━━━━━━━━"]
        if not new:
            lines.append("• 今日新增计划外作业: 0 项")
            return lines
        lines.append(f"• 今日新增计划外作业: {len(new)} 项")
        # 类型分布 + 涉及部门
        type_counts: dict[str, int] = {}
        dept_set: set[str] = set()
        for r in new:
            cn = cls._cn_label(r.operation_type)
            type_counts[cn] = type_counts.get(cn, 0) + 1
            if r.department:
                dept_set.add(r.department)
        type_parts = [f"{t} {c}项" for t, c in type_counts.items()]
        if type_parts:
            lines.append(f"  {'  '.join(type_parts)}")
        if dept_set:
            lines.append(f"  涉及部门: {'、'.join(sorted(dept_set))}")
        # 逐条明细(按发起时间升序)
        ordered = sorted(new, key=_new_ts)
        for i, r in enumerate(ordered, 1):
            cn = cls._cn_label(r.operation_type)
            lines.append(f"{i}. 【{cn}】{r.department or '?'}")
            if r.location:
                lines.append(f"   📍 地点: {r.location}")
            if r.work_description:
                lines.append(f"   📝 内容: {r.work_description[:60]}")
            time_parts = []
            if r.planned_start_time:
                start = cls._bj_time(r.planned_start_time)
                if r.planned_end_time:
                    end = cls._bj_time(r.planned_end_time)[-5:]
                    dur = f"（{r.work_duration_hours}h）" if r.work_duration_hours else ""
                    time_parts.append(f"⏱ 计划: {start} — {end}{dur}")
                else:
                    dur = f"（{r.work_duration_hours}h）" if r.work_duration_hours else ""
                    time_parts.append(f"⏱ 计划: {start}{dur}")
            if time_parts:
                lines.append(f"   {''.join(time_parts)}")
            level = {"high": "高", "medium": "中", "low": "低"}.get(r.daily_risk_level, "中")
            lines.append(f"   ⚠️ 风险: {level}")
        return lines

    @classmethod
    def build(cls, report_date: date, mode: str, reports: list[SpecialOperationReport],
              stats: dict[str, int],
              ai_analysis: AIDailyAnalysisResult | None = None) -> str:
        is_today_mode = cls._is_today_family(mode)  # 17点日报沿用当日标题/标签
        title = "📋 【特殊作业日报】" if is_today_mode else "🔮 【特殊作业次日预警】"
        date_str = report_date.strftime("%Y年%m月%d日")

        high = sorted([r for r in reports if r.daily_risk_level == "high"], key=cls._sort_key)
        medium = [r for r in reports if r.daily_risk_level == "medium"]
        low = [r for r in reports if r.daily_risk_level == "low"]
        dept_set = sorted({(r.department or "?") for r in reports})

        # 增强版风险描述映射 + 管控措施映射（按 1-based 索引）
        enhanced_map = ai_analysis.enhanced_reasons if ai_analysis else {}
        control_map = ai_analysis.control_measures if ai_analysis else {}

        # ── 作业概况统计 ──
        mode_label = "今日" if is_today_mode else "次日"
        # 按作业类型计数
        type_counts: dict[str, int] = {}
        # 关联作业（涉及 ≥2 种特殊作业类型）
        associated = 0
        for r in reports:
            cn = cls._cn_label(r.operation_type)
            type_counts[cn] = type_counts.get(cn, 0) + 1
            # 统计关联作业
            all_types: set[str] = {cn}
            other = r.other_operation_types or []
            if isinstance(other, list):
                for t in other:
                    all_types.add(cls._cn_label(t) if isinstance(t, str) else str(t))
            inferred = r.inferred_operation_types or []
            if isinstance(inferred, list):
                for t in inferred:
                    all_types.add(str(t))
            if len(all_types) >= 2:
                associated += 1
        # 按模板顺序排列类型
        _type_order = ["动火作业", "受限空间", "高处作业", "吊装作业", "临时用电", "动土作业", "断路作业", "盲板抽堵"]
        type_parts = []
        for t in _type_order:
            cnt = type_counts.get(t, 0)
            if cnt > 0:
                type_parts.append(f"{t} {cnt}项")
        if associated > 0:
            type_parts.append(f"关联作业 {associated}项")

        # 风险集中区域叙事：高风险逐条点名（部门+作业类型—作业内容），中风险按部门+类型×N汇总
        summary = cls._build_zone_summary(high, medium, mode_label)

        lines = [f"{title} {date_str}", "", "📊 作业概况", "━━━━━━━━━━━━━━━━━━━━"]
        lines.append(f"• {mode_label}计划作业: {len(reports)} 项")
        if type_parts:
            lines.append(f"  {'  '.join(type_parts)}")
        lines.append(f"• 涉及部门: {'、'.join(dept_set[:8])}{'…' if len(dept_set) > 8 else ''}")
        lines.append(f"• 高风险: {len(high)} 项 | 中风险: {len(medium)} 项 | 低风险: {len(low)} 项")
        if summary:
            lines.append(f"  {summary}")

        # 今日新增计划外作业对比总结段：17点日报(固定08:00~17:00窗口)与机器人随时查询(08:00~当前时刻)均渲染
        if mode != "tomorrow":
            lines.extend(cls._new_ops_section(report_date, reports, mode))

        if high:
            lines.append("")
            lines.append(f"🔴 重点关注（高风险 {len(high)} 项）")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for idx, r in enumerate(high[:15], 1):
                cn_type = cls._cn_label(r.operation_type)
                lines.append(f"{idx}. 【{cn_type}】{r.department or '?'}")
                lines.append(f"   📍 地点: {r.location or '未知'}")
                if r.work_description:
                    lines.append(f"   📝 内容: {r.work_description[:60]}")
                # 时间 + 单位行
                time_parts = []
                if r.planned_start_time:
                    start = cls._bj_time(r.planned_start_time)
                    if r.planned_end_time:
                        end = cls._bj_time(r.planned_end_time)[-5:]
                        dur = f"（{r.work_duration_hours}h）" if r.work_duration_hours else ""
                        time_parts.append(f"⏱ {start} — {end}{dur}")
                    else:
                        dur = f"（{r.work_duration_hours}h）" if r.work_duration_hours else ""
                        time_parts.append(f"⏱ {start}{dur}")
                unit = r.contractor_name or r.personnel_type or ""
                if unit:
                    time_parts.append(f"  单位: {unit}")
                if time_parts:
                    lines.append(f"   {''.join(time_parts)}")
                # AI 重写的风险描述优先，回退规则引擎结果
                ai_reason = enhanced_map.get(str(idx), "")
                reason = ai_reason if ai_reason else (r.daily_risk_reason or "高风险作业")
                lines.append(f"   ⚠️ 风险: {reason}")
                # AI 管控措施优先，回退规则引擎
                ai_ctrl = control_map.get(str(idx), "")
                ctrl = ai_ctrl if ai_ctrl else cls._control_measure(r)
                if ctrl:
                    lines.append(f"   📝 管控: {ctrl}")
            if len(high) > 15:
                lines.append(f"   …共 {len(high)} 项高风险作业")

        if medium:
            lines.append("")
            lines.append(f"🟡 常规作业（中风险 {len(medium)} 项）")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            by_type: dict[str, list] = {}
            for r in medium:
                cn_label = cls._cn_label(r.operation_type)
                by_type.setdefault(cn_label, []).append(r)
            for t, items in by_type.items():
                depts = sorted({r.department or "?" for r in items})
                lines.append(f"• {t} ×{len(items)} （{'、'.join(depts[:5])}{'…' if len(depts) > 5 else ''}）")

        if low:
            lines.append("")
            lines.append(f"🟢 低风险作业（{len(low)} 项）")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            by_type_low: dict[str, list] = {}
            for r in low:
                cn_label = cls._cn_label(r.operation_type)
                by_type_low.setdefault(cn_label, []).append(r)
            for t, items in by_type_low.items():
                depts = sorted({r.department or "?" for r in items})
                lines.append(f"• {t} ×{len(items)} （{'、'.join(depts[:5])}{'…' if len(depts) > 5 else ''}）")

        if stats.get("excluded", 0) > 0:
            lines.append("")
            lines.append(f"ℹ️ 排除: {stats['excluded']} 条（发酵工程部受限空间等）")

        lines.append("")
        lines.append("📌 安全提示")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        # AI 生成的安全提示优先，回退规则引擎（上限前 3 条）
        if ai_analysis and ai_analysis.enhanced_tips:
            import re
            for i, tip in enumerate(ai_analysis.enhanced_tips[:3], 1):
                # 去掉 AI 可能自带的前导编号
                tip = re.sub(r'^\d+[\.\、\)]\s*', '', tip).strip()
                lines.append(f"{i}. {tip}")
        else:
            tips = cls._tips(high, medium)
            for i, tip in enumerate(tips, 1):
                lines.append(f"{i}. {tip}")

        return "\n".join(lines)

    @classmethod
    def _build_zone_summary(cls, high: list, medium: list, mode_label: str) -> str | None:
        """风险集中区域叙事。

        高风险逐条点名"部门+作业类型—作业内容"；中风险按"部门+作业类型×N项"汇总，
        两段合并成一句，均纳入"重点监管区域"结论。
        """
        if not high and not medium:
            return None

        def _cn(r) -> str:
            cn = cls._cn_label(r.operation_type)
            return cn if cn.endswith("作业") else cn + "作业"

        # 高风险段：逐条点名作业内容
        hi_parts = []
        dept_groups: dict[str, list] = {}
        for r in high:
            dept_groups.setdefault(r.department or "?", []).append(r)
        for d, items in sorted(dept_groups.items(), key=lambda x: -len(x[1])):
            type_groups: dict[str, list[str]] = {}
            for r in items:
                type_groups.setdefault(_cn(r), []).append((r.work_description or "").strip())
            dept_parts = []
            for cn, contents in type_groups.items():
                valid = [c[:25] for c in contents if c]
                dept_parts.append(f"{cn}—{'、'.join(valid)}" if valid else cn)
            hi_parts.append(f"{d}{'、'.join(dept_parts)}")

        # 中风险段：按部门+作业类型×N 汇总计数
        med_parts = []
        dept_groups_m: dict[str, dict[str, int]] = {}
        for r in medium:
            cn = _cn(r)
            dept_groups_m.setdefault(r.department or "?", {}).setdefault(cn, 0)
            dept_groups_m[r.department or "?"][cn] += 1
        for d, type_counts in sorted(dept_groups_m.items(), key=lambda x: -sum(x[1].values())):
            med_parts.append(f"{d}{'、'.join(f'{t}×{c}项' for t, c in type_counts.items())}")

        segments = []
        if hi_parts:
            segments.append(f"高风险作业集中在{'，'.join(hi_parts)}")
        if med_parts:
            segments.append(f"中风险作业集中在{'，'.join(med_parts)}")
        return f"{'；'.join(segments)}，为{mode_label}重点监管区域。"

    @classmethod
    def _tips(cls, high: list, medium: list) -> list[str]:
        tips = []
        all_r = high + medium
        # 用中文标签判断
        cn_types = {cls._cn_label(r.operation_type) for r in all_r}
        if "受限空间" in cn_types:
            tips.append('受限空间作业严格执行"先通风、再检测、后作业"')
        if "动火作业" in cn_types:
            tips.append("动火作业清理周边可燃物，配备灭火器材")
        if "高处作业" in cn_types:
            tips.append("高处作业正确佩戴安全带（全身式），高挂低用")
        if any((r.personnel_type or "") == "非公司人员" for r in all_r):
            tips.append("外部承包商作业加强入场安全教育和现场监管")
        if any((r.is_weekend_holiday or "") == "是" for r in all_r):
            tips.append("节假日/非上班时段作业加强监护值班")
        if not tips:
            tips = ["各作业负责人认真检查安全措施落实情况", "发现异常立即停止作业并上报"]
        return tips[:6]

    @classmethod
    def _control_measure(cls, r: SpecialOperationReport) -> str | None:
        """V3.5 根据风险判定生成管控措施建议。"""
        reason = r.daily_risk_reason or ""
        cn_type = cls._cn_label(r.operation_type)
        # 动火+受限空间
        if "动火作业+受限空间同时存在" in reason:
            return "严格执行受限空间作业票，动火与受限人员分离操作，罐内连续气体检测"
        # 三种叠加
        if "三种及以上" in reason:
            return "多工种交叉作业须统一指挥，指定专职监护人全程旁站，每2小时轮换"
        # 夜间/周末动火
        if "夜间/周末" in reason and "动火" in reason:
            return "升级管理审批，确保现场照明充足，增派监护人，视频监控全覆盖"
        # 罐区动火
        if "罐区" in reason and "动火" in reason:
            return "罐区动火前可燃气体检测合格，作业点15m内无可燃物，消防车现场待命"
        # 受限空间+外包
        if "受限空间+外部承包商" in reason:
            return "承包商人员须持受限空间作业证，入场前专项安全交底并签字确认"
        # 下罐/清罐
        if "下罐" in reason:
            return "先通风、再检测、后作业，罐内氧含量18%-21%，配备隔离式呼吸器"
        # 高处
        if cn_type == "高处作业":
            return "安全带高挂低用，作业下方设警戒区，工具系防坠绳"
        # 吊装
        if cn_type == "吊装作业":
            return "吊装半径内禁止人员停留，信号工持证上岗，风力>6级停止作业"
        # 外包通用
        if (r.personnel_type or "") == "非公司人员":
            return "核查承包商人员资质和保险，属地部门全程旁站监护"
        # 长时长
        if r.work_duration_hours and r.work_duration_hours > 8:
            return "超8小时作业安排轮换，每4小时强制休息30分钟"
        return None


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════

class SpecialOperationDailyReportService:
    """特殊作业日报业务服务。

    数据基础: SpecialOperationReport（source=bitable 为飞书同步记录）
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.engine = RiskAssessmentEngine()
        self.builder = ReportBuilder()
        self.analyst = AIAnalyst(session)

    # ── Bitable 字段映射 ──

    @staticmethod
    def map_bitable_fields(fields: dict) -> dict[str, Any]:
        """将 Bitable 原始字段映射为 SpecialOperationReport 字段。"""

        def _name(v):
            if isinstance(v, str):
                return v
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    return first.get("name", "")
                return str(first)
            if isinstance(v, dict):
                return v.get("name", "")
            return None

        def _text(v):
            if isinstance(v, str):
                return v
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict):
                    return first.get("text", "")
                return str(first)
            return None

        def _url(v):
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return v.get("link", "")
            return None

        def _ts(v):
            if v is None:
                return None
            try:
                return datetime.fromtimestamp(int(v) / 1000.0)
            except (TypeError, ValueError, OSError):
                return None

        def _float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # 映射 Bitable 字段 → SpecialOperationReport
        op_type_raw = fields.get("作业类型", "")
        op_level_raw = fields.get("作业分级", "")
        dept = fields.get("申请部门", "") or _text(fields.get("发起人部门")) or ""
        desc = _text(fields.get("作业内容"))
        location = _text(fields.get("作业地点"))
        start_ts = fields.get("作业时间_开始时间")
        end_ts = fields.get("作业时间_结束时间")

        # 中文 → 英文枚举映射
        _OP_TYPE_CN2EN = {
            "动火作业": "hot_work", "受限空间": "confined_space",
            "高处作业": "height_work", "吊装作业": "lifting",
            "临时用电": "temporary_electricity", "动土作业": "excavation",
            "断路作业": "road_breaking", "盲板抽堵": "blind_plate",
            "常规作业": "hot_work",
        }
        _OP_LEVEL_CN2EN = {
            "特级/Ⅳ级": "special", "一级（Ⅰ级）": "grade1",
            "二级（Ⅱ级）": "grade2", "三级（Ⅲ级）": "grade2",
            "不涉及": "not_applicable",
        }
        op_type = _OP_TYPE_CN2EN.get(op_type_raw, op_type_raw)
        op_level = _OP_LEVEL_CN2EN.get(op_level_raw, op_level_raw or "grade2")

        # 生成 report_no
        # report_no 在 sync 时由 feishu_record_id 覆写，此处仅占位
        report_no = f"BT-{_ts(start_ts).strftime('%Y%m%d%H%M%S') if _ts(start_ts) else datetime.now().strftime('%Y%m%d%H%M%S')}"

        return {
            "report_no": report_no,
            "source": "bitable",
            "feishu_record_id": None,  # 由调用方设置
            "operation_type": op_type,
            "operation_level": op_level or "grade2",
            "department": dept,
            "location": location,
            "work_description": desc,
            "planned_start_time": _ts(start_ts),
            "planned_end_time": _ts(end_ts),
            "work_duration_hours": _float(fields.get("作业时间_时长")),
            "personnel_type": fields.get("作业人员类型"),
            # V3.5 新增字段（从其他数据源同步，API 暂不可读时取 None）
            "fire_work_method": _text(fields.get("动火方式")),
            "height_work_method": _text(fields.get("高处作业方式")),
            "work_height": _float(fields.get("作业高度(米)")),
            "lifting_weight": _float(fields.get("吊物质量(吨)")),
            "contractor_name": _text(fields.get("施工单位")),
            "has_other_operations": fields.get("是否涉及其他特殊作业"),
            "other_operation_types": fields.get("涉及特殊作业类型") if isinstance(fields.get("涉及特殊作业类型"), list) else None,
            "is_weekend_holiday": fields.get("周末节假日/非上班时段（关键作业）"),
            "is_national_holiday": fields.get("是否国家法定节假日"),
            "holiday_period": fields.get("非上班时间段/节假日"),
            "report_type": "planned" if fields.get("报备类型") == "计划内作业" else ("unplanned" if fields.get("报备类型") == "计划外作业" else None),
            "initiator_department": _text(fields.get("发起人部门")),
            "initiator_name": _name(fields.get("发起人")),
            "approver_type": fields.get("作业票审批人类型"),
            "safety_approver_name": _name(fields.get("安全工程中心审批人")),
            "approver_name": _name(fields.get("审批人")),
            "approval_no": _url(fields.get("申请编号")),
            "work_plan_url": _url(fields.get("作业计划")),
            "work_scheme_url": _url(fields.get("作业方案")),
            "approved_permit_url": _url(fields.get("已经通过签批的特殊作业票以及关联票")),
            "submitted_at": _ts(fields.get("发起时间")),
            "completed_at": _ts(fields.get("完成时间")),
            "approval_node": _text(fields.get("审批节点")),
            "risk_level": None,  # 保备自身的风险等级（level_1~4），Bitable 没有对应字段
            "status": "approved",  # Bitable 记录已完成审批
            "notes": None,
        }

    # ── Bitable 同步 ──

    async def sync_from_bitable(self) -> int:
        """从飞书 Bitable 全量同步到 SpecialOperationReport。

        以 feishu_record_id 为唯一键做 upsert，存在则更新，不存在则创建。
        同步后自动执行日报风险判定。

        注意：使用 GET /records 而非 POST /records/search，
        因为 search_records 的分页机制有 bug（无限循环）。
        """
        import httpx

        from app.modules.safety.bitable_config.store import store
        from app.modules.safety.feishu.client import get_safety_tenant_token

        # 连接配置从配置中心 store 读取（原代码硬编码 app_token/table_id）
        conn = store.get_connection("special_op", "daily")
        if conn is None or not conn.enabled:
            logger.warning("特殊作业 Bitable 连接未配置或已停用（special_op/daily），跳过同步")
            return 0

        records = []
        page_token = None
        # 2026-09-08：原 max_pages=10（×200/页=2000 条）已低于表现有 2033 条，
        # 08:00 全量对账静默漏掉尾部记录；放宽到 50 页（1 万条），触顶时显式报错
        # 而非静默截断（参照中控报警 MAX_PAGES=50 的量级）。
        max_pages = 50
        truncated = False

        async with httpx.AsyncClient(timeout=30) as http:
            token = await get_safety_tenant_token()
            h = {"Authorization": f"Bearer {token}"}
            for _ in range(max_pages):
                params: dict = {"page_size": 200}
                if page_token:
                    params["page_token"] = page_token
                resp = await http.get(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{conn.app_token}/tables/{conn.table_id}/records",
                    headers=h, params=params,
                )
                d = resp.json()
                items = d.get("data", {}).get("items", [])
                records.extend(items)
                has_more = d.get("data", {}).get("has_more", False)
                page_token = d.get("data", {}).get("page_token")
                if not has_more or not page_token:
                    break
            else:
                truncated = True
        if truncated:
            logger.error(
                "特殊作业全量同步达到分页上限(max_pages=%d, 已拉 %d 条)仍未拉完，"
                "本轮对账截断——表规模超出预期，请扩大上限或清理历史数据",
                max_pages, len(records),
            )

        synced = 0
        for rec in records:
            try:
                record_id = rec.get("record_id", "")
                if not record_id:
                    continue
                fields = rec.get("fields", {})
                mapped = self.map_bitable_fields(fields)
                mapped["feishu_record_id"] = record_id
                mapped["report_no"] = f"BT-{record_id[-12:]}"  # 确保唯一

                # 查找已有记录
                stmt = select(SpecialOperationReport).where(
                    SpecialOperationReport.feishu_record_id == record_id,
                    SpecialOperationReport.source == "bitable",
                    SpecialOperationReport.is_deleted == False,  # noqa: E712
                )
                result = await self.session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # UPDATE — 只更新 Bitable 字段，保留平台分析字段
                    for k, v in mapped.items():
                        if v is not None and k not in ("report_no", "status"):
                            setattr(existing, k, v)
                else:
                    # INSERT
                    existing = SpecialOperationReport(**mapped)
                    self.session.add(existing)

                # 日报风险判定
                assessment = self.engine.assess(existing)
                existing.daily_risk_level = assessment.risk_level
                existing.daily_risk_reason = "; ".join(assessment.matched_rules) if assessment.matched_rules else None
                existing.inferred_operation_types = assessment.inferred_types if assessment.inferred_types else None
                existing.is_excluded = assessment.is_excluded
                existing.exclusion_reason = assessment.exclusion_reason

                synced += 1
            except Exception:
                logger.exception("同步 Bitable 记录失败: record_id=%s", rec.get("record_id"))

        return synced

    # ── 查询 ──

    async def get_reports_by_date(self, target_date: date,
                                  include_excluded: bool = False) -> list[SpecialOperationReport]:
        start_dt = datetime.combine(target_date, datetime.min.time())
        end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        stmt = select(SpecialOperationReport).where(
            SpecialOperationReport.source == "bitable",
            SpecialOperationReport.planned_start_time >= start_dt,
            SpecialOperationReport.planned_start_time < end_dt,
            SpecialOperationReport.is_deleted == False,  # noqa: E712
        )
        if not include_excluded:
            stmt = stmt.where(SpecialOperationReport.is_excluded == False)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stats(self, target_date: date | None = None) -> dict:
        target_date = target_date or date.today()
        reports = await self.get_reports_by_date(target_date, include_excluded=False)
        return {
            "date": target_date.isoformat(),
            "total": len(reports),
            "high": sum(1 for r in reports if r.daily_risk_level == "high"),
            "medium": sum(1 for r in reports if r.daily_risk_level == "medium"),
            "low": sum(1 for r in reports if r.daily_risk_level == "low"),
        }

    async def check_and_sync_incremental(self) -> dict:
        """增量同步诊断：只补拉「本地最新修改之后」Bitable 新增/变更且本地缺失的记录。

        与全量 sync_from_bitable 的区别：以本地最大 updated_at 为时间锚点
        （锚点延时冗余），用 Bitable「发起时间」isGreater 增量拉取（实验验证：
        「修改时间」系统字段过滤不可用 InvalidFilter；「发起时间」普通字段可用，
        且其语义正是新增作业的提交时间）。实时 WS 正常时通常 0~几 条，秒级完成，
        供 Agent 工具生成日报前做数据新鲜度检查，替代全量同步。

        返回:
            {
                "status": "fresh"|"synced"|"skipped"|"error",
                "cutoff": "<本地最大 updated_at ISO>",
                "bitable_recent": int,   # 锚点后 Bitable 变更记录数
                "pulled": int,           # 本次补录的缺失记录数
                "local_total": int,      # 本地记录总数
                "elapsed_ms": int,
            }
        """
        import time

        from app.modules.safety.bitable_config.store import store
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        t0 = time.monotonic()
        conn = store.get_connection("special_op", "daily")
        if conn is None or not conn.enabled:
            return {"status": "skipped", "reason": "special_op/daily 连接未配置或已停用"}

        try:
            # 1. 本地时间锚点
            from sqlalchemy import func

            max_updated = (
                await self.session.execute(
                    select(func.max(SpecialOperationReport.updated_at)).where(
                        SpecialOperationReport.source == "bitable",
                        SpecialOperationReport.is_deleted == False,  # noqa: E712
                    )
                )
            ).scalar()
            if max_updated is None:
                # 本地无数据 → 首次全量
                n = await self.sync_from_bitable()
                return {
                    "status": "synced", "cutoff": None,
                    "bitable_recent": n, "pulled": n,
                    "local_total": n,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                }

            # 锚点回退 24h 冗余：即使锚点后无修改，也检查近一天内的新增，
            # 防 WS 断线期间旧记录入库时间晚于锚点的窗口缝隙。
            cutoff_dt = max_updated - timedelta(hours=24)
            cutoff_ms = int(cutoff_dt.timestamp() * 1000)

            # 2. Bitable 增量查询（发起时间 > 锚点；修改时间系统字段过滤不可用）
            client = SafetyBitableClient(
                app_token=conn.app_token, table_id=conn.table_id
            )
            try:
                recent = await client.list_all_records(
                    filter_info={
                        "conjunction": "and",
                        "conditions": [
                            {
                                "field_name": "发起时间",
                                "operator": "isGreater",
                                "value": ["ExactDate", str(cutoff_ms)],
                            }
                        ],
                    },
                    automatic_fields=True,
                    page_size=200,
                )
            except Exception:
                # 增量过滤失败（字段缺失等）→ 退化为全量
                logger.warning("增量查询失败，退化为全量同步", exc_info=True)
                n = await self.sync_from_bitable()
                return {
                    "status": "synced", "cutoff": cutoff_dt.isoformat(),
                    "bitable_recent": n, "pulled": n,
                    "local_total": n,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                }

            # 3. 本地已有 record_id 集合
            local_rows = (
                await self.session.execute(
                    select(SpecialOperationReport.feishu_record_id).where(
                        SpecialOperationReport.source == "bitable",
                        SpecialOperationReport.is_deleted == False,  # noqa: E712
                    )
                )
            ).all()
            local_ids = {r[0] for r in local_rows if r[0]}

            # 4. 锚点后发起、但本地缺失的记录 → upsert
            pulled = 0
            for rec in recent:
                record_id = rec.get("record_id", "")
                if not record_id or record_id in local_ids:
                    continue
                try:
                    await self._upsert_one_from_fields(
                        record_id, rec.get("fields", {})
                    )
                    pulled += 1
                except Exception:
                    logger.exception(
                        "增量同步 upsert 失败: record_id=%s", record_id
                    )

            if pulled:
                await self.session.commit()

            status = "fresh" if pulled == 0 else "synced"
            return {
                "status": status,
                "cutoff": cutoff_dt.isoformat(),
                "bitable_recent": len(recent),
                "pulled": pulled,
                "local_total": len(local_ids),
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as exc:
            logger.exception("增量同步诊断异常")
            return {"status": "error", "error": str(exc)}

    async def _upsert_one_from_fields(self, record_id: str, fields: dict) -> None:
        """单条记录 upsert（增量同步复用，逻辑与 sync_from_bitable 一致）。"""
        mapped = self.map_bitable_fields(fields)
        mapped["feishu_record_id"] = record_id
        mapped["report_no"] = f"BT-{record_id[-12:]}"  # 确保唯一

        stmt = select(SpecialOperationReport).where(
            SpecialOperationReport.feishu_record_id == record_id,
            SpecialOperationReport.source == "bitable",
            SpecialOperationReport.is_deleted == False,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            for k, v in mapped.items():
                if v is not None and k not in ("report_no", "status"):
                    setattr(existing, k, v)
        else:
            existing = SpecialOperationReport(**mapped)
            self.session.add(existing)

        assessment = self.engine.assess(existing)
        existing.daily_risk_level = assessment.risk_level
        existing.daily_risk_reason = "; ".join(assessment.matched_rules) if assessment.matched_rules else None
        existing.inferred_operation_types = assessment.inferred_types if assessment.inferred_types else None
        existing.is_excluded = assessment.is_excluded
        existing.exclusion_reason = assessment.exclusion_reason

    # ── 日报生成与推送 ──

    async def generate_and_push(self, target_date: date | None = None,
                                mode: str = "today",
                                target_chats: list[str] | None = None,
                                push: bool = True) -> DailyReportResponse:
        target_date = target_date or date.today()

        all_reports = await self.get_reports_by_date(target_date, include_excluded=True)
        effective = [r for r in all_reports if not r.is_excluded]
        excluded_count = len(all_reports) - len(effective)

        high = [r for r in effective if r.daily_risk_level == "high"]
        medium = [r for r in effective if r.daily_risk_level == "medium"]
        low = [r for r in effective if r.daily_risk_level == "low"]

        stats = {"total": len(all_reports), "effective_total": len(effective),
                 "high": len(high), "medium": len(medium),
                 "low": len(low), "excluded": excluded_count}

        # AI 增强分析（RAG + DeepSeek）
        ai_analysis = None
        if high:
            try:
                ai_analysis = await self.analyst.analyze(
                    report_date=target_date,
                    mode=mode,
                    reports=effective,
                    stats=stats,
                )
            except Exception:
                logger.warning("AI 分析失败，回退纯规则报告")

        markdown = self.builder.build(target_date, mode, effective, stats, ai_analysis=ai_analysis)

        # 标记已分析
        for r in effective:
            r.daily_report_date = target_date

        # 2026-09-03：推送前先提交收口长事务。AI 分析可达 10+ 分钟，事务一直
        # 挂着；此前推送成功后再 commit，长连接一旦死亡 → 任务标 failed →
        # 重试重复推送（当日 08:13/08:14 两张重复卡片的根因）。推送之后
        # 不再有任何 DB 写操作，commit 失败只可能发生在推送前（重试不重复）。
        await self.session.commit()

        mode_label = "特殊作业日报" if self.builder._is_today_family(mode) else "特殊作业次日预警"
        # 发送目标唯一来源：调度器配置（[] = 显式无目标不推送）；未传参(None)时保留默认群（手动 API 兼容）
        target_list = target_chats if target_chats is not None else [DAILY_REPORT_CHAT_ID]
        push_results = []
        if push:
            for chat_id in target_list:
                try:
                    msg_id = await send_group_card(
                        chat_id=chat_id,
                        title=f"{mode_label} - {target_date.strftime('%Y-%m-%d')}",
                        content=markdown,
                    )
                    push_results.append({"chat_id": chat_id, "success": msg_id is not None, "message_id": msg_id})
                except Exception as exc:
                    logger.exception("推送失败: chat_id=%s", chat_id)
                    push_results.append({"chat_id": chat_id, "success": False, "error": str(exc)})
            # 任一目标推送失败（异常或未返回 message_id）视为任务失败：
            # 抛出让调度器标记 failed，进入自动重试/告警流程，避免静默丢失
            if not push_results or not all(r.get("success") for r in push_results):
                failed = next((r.get("error") for r in push_results if not r.get("success")), "未返回 message_id")
                raise RuntimeError(f"日报推送失败: {failed}") from None

        return DailyReportResponse(
            report_date=target_date, mode=mode,
            total=len(all_reports), excluded=excluded_count,
            high_risk=len(high), medium_risk=len(medium), low_risk=len(low),
            markdown_report=markdown, push_results=push_results,
            logs_analyzed=[r.id for r in effective],
        )

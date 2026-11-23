"""AI 日报预览自动生成——按人拉系统留痕，生成五段式「AI预览版·待本人确认」。

数据读取优先级对齐画像方案 §3.2：P1=本人确认记录（本链不涉及，正式提交流程已有）
P2=当天各业务 Bitable 记录（本链主源，按 system_sources 拉取）；画像只做查漏
提示不充当完成证明。事实边界 §3.3：无数据不写"无"，标"待本人确认"。

一期口径（2026-11-19 演示/评审轮）：
- 只拉 Bitable 域源；module 级源（作业票审核/点检AI审核/AI评分/督办）待下期接
- 快照类表（危化品库存等无逐日行）按风险行计数，不做当日过滤
- 无留痕者发确定性骨架卡（不调 LLM），如实标注
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.service.config import create_ai_service

from . import cards, profiles

logger = logging.getLogger(__name__)

PREVIEW_TIMEOUT_SECONDS = 120

#: 各域抽样展示字段（事实清单里的样例列）
_SAMPLE_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("special_op", "daily"): ("作业类型", "作业分级", "作业地点"),
    ("key_risk_op", "daily"): ("作业内容", "区域", "审批节点"),
    ("ehs_change", "approval"): ("变更名称", "申请状态", "变更级别"),
    ("ehs_change", "acceptance"): ("变更名称", "验收意见（可另附验收报告）", "变更级别"),
    ("interlock_change", "approval"): ("岗位及设备设施名称", "申请状态", "安全设施类型"),
    ("hazard", "hazard"): ("隐患描述", "隐患级别", "整改责任人"),
    ("visitor_notice", "notice"): ("进厂外来人员姓名", "单位名称", "申请状态"),
    ("oh", "exam_registry"): ("姓名", "体检类型", "流程状态"),
    ("oh", "new_employee"): ("姓名", "部门", "危害因素"),
    ("training_behavior", "training"): ("培训名称", "实到人数", "状态"),
    ("training_behavior", "violation"): ("违章人员", "违章类别", "状态"),
    ("contractor_admission", "admission"): ("作业单位名称", "培训状态", "提交状态"),
    ("external_audit_hazard", "defect_summary"): ("缺陷项描述", "整改状态", "责任人"),
    ("external_audit_hazard", "emergency_bureau"): ("缺陷项描述", "整改状态", "责任人"),
    ("fire_alarm", "alarm"): ("报警部位", "报警性质", "处理情况"),
    ("facilities", "fire_equipment_ledger"): ("车间", "灭火器类型", "到期日期"),
}

#: 快照类源（无逐日业务行，按风险/在库行计数）
_SNAPSHOT_DOMAINS = {"chemical_inventory", "labor_supply"}

#: 源标识 → 中文名（用户拍板 2026-11-19：卡片不出现任何英文标识）
CN_LABELS: dict[str, str] = {
    "special_op/daily": "特殊作业日报",
    "key_risk_op/daily": "关键风险作业",
    "ehs_change/approval": "EHS变更审批",
    "ehs_change/acceptance": "EHS变更验收",
    "interlock_change/approval": "联锁与安全附件变更",
    "hazard/hazard": "隐患登记",
    "visitor_notice/notice": "外来人员预报备",
    "oh/exam_registry": "职业健康体检",
    "oh/hazard_factor": "岗位危害因素",
    "oh/new_employee": "新员工台账",
    "training_behavior/training": "培训实施记录",
    "training_behavior/violation": "违章档案",
    "contractor_admission/admission": "相关方准入",
    "chemical_inventory/inventory": "危化品库存",
    "labor_supply/product": "劳保物料",
    "facilities/fire_equipment_ledger": "消防器材台账",
    "facilities/equipment_ledger": "设备设施台账",
    "external_audit_hazard/defect_summary": "外审缺陷整改",
    "external_audit_hazard/emergency_bureau": "监管检查整改",
    "fire_alarm/alarm": "消防报警",
    "central_alarm/alarm": "中控报警",
    "workticket_review": "作业票审核",
    "fire_inspection": "消防点检AI审核",
    "ai_hazard_scoring": "AI隐患评分",
    "progress_dunning": "隐患督办通报",
}


def _cn_label(key: str) -> str:
    return CN_LABELS.get(key, key)


@dataclass(frozen=True)
class SourceFacts:
    """单源当日事实。"""

    source: str          # domain/kind 或 module 名
    extracts: str        # 可提取事实说明
    total_today: int = 0        # 当日总行数（快照类=在库/风险行数）
    mine_today: int = 0         # 其中本人锚点命中
    samples: tuple[str, ...] = field(default_factory=tuple)
    note: str = ""              # 快照/无锚点等口径说明


def _plain(value: Any) -> str:
    from .store import plain

    return plain(value)


def _ms(value: Any) -> int | None:
    text = _plain(value)
    if text.isdigit() and len(text) >= 13:
        return int(text)
    return None


def _bj_day_bounds(date_key: str) -> tuple[int, int]:
    from zoneinfo import ZoneInfo

    start = datetime.fromisoformat(date_key).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(start.timestamp() * 1000), int(start.timestamp() * 1000) + 86_400_000


async def _collect_one(
    src: profiles.SystemSource,
    name: str,
    date_key: str,
) -> SourceFacts:
    """拉单个 Bitable 源的当日事实（排序取近页 + 客户端按日/按人过滤）。"""
    from app.modules.safety.bitable_config.store import store as bstore
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    label = f"{src.domain}/{src.kind}" if src.domain else src.module
    if not src.domain:
        return SourceFacts(source=src.module or "?", extracts=src.extracts,
                           note="数据接入中，暂不可查")
    conn = bstore.get_connection(src.domain, src.kind)
    if conn is None or not conn.table_id:
        return SourceFacts(source=label, extracts=src.extracts, note="未配置连接")
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    snapshot = src.domain in _SNAPSHOT_DOMAINS
    if snapshot:
        items = await client.list_all_records(strict=False)
        risk = [r for r in items if _plain(r["fields"].get("风险标记"))]
        samples = tuple(
            f"{_plain(r['fields'].get('物料名称'))}（{_plain(r['fields'].get('风险说明'))[:30]}）"
            for r in risk[:3] if _plain(r["fields"].get("物料名称"))
        )
        return SourceFacts(
            source=label, extracts=src.extracts,
            total_today=len(risk), samples=samples,
            note="当前风险标记行数（存量口径，非当日新增）",
        )

    anchor_fields = [a.strip() for a in src.anchor.split("/") if a.strip()]
    lo, hi = _bj_day_bounds(date_key)
    # 排序字段不被支持时（InvalidSort 被客户端吞成空结果）回退无序拉取
    result = await client.search_records(
        sort=[{"field_name": src.date_field, "desc": True}],
        page_size=50,
    )
    rows = result.get("items", []) if isinstance(result, dict) else []
    if not rows:
        result = await client.search_records(page_size=100)
        rows = result.get("items", []) if isinstance(result, dict) else []
    today_rows, mine_rows = [], []
    for r in rows:
        f = r.get("fields", {})
        ms = _ms(f.get(src.date_field))
        if ms is None or not (lo <= ms < hi):
            continue
        today_rows.append(r)
        if any(name in _plain(f.get(af)) for af in anchor_fields):
            mine_rows.append(r)
    sample_fields = _SAMPLE_FIELDS.get((src.domain, src.kind), ())
    samples = tuple(
        "·".join(_plain(rf.get(sf)) for sf in sample_fields if _plain(rf.get(sf)))[:60]
        for rf in (mine_rows or today_rows)[:3]
    )
    return SourceFacts(
        source=label, extracts=src.extracts,
        total_today=len(today_rows), mine_today=len(mine_rows),
        samples=tuple(s for s in samples if s),
    )


async def collect_facts(name: str, date_key: str) -> list[SourceFacts]:
    """按画像拉该人全部系统源的当日事实（并行）。"""
    profile = profiles.profile_for(name)
    if profile is None:
        return []
    results = await asyncio.gather(
        *(_collect_one(src, name, date_key) for src in profile.system_sources),
        return_exceptions=True,
    )
    facts: list[SourceFacts] = []
    for src, res in zip(profile.system_sources, results, strict=True):
        if isinstance(res, BaseException):
            logger.warning("预览拉源失败 %s: %s", src.domain or src.module, res)
            continue
        facts.append(res)
    return facts


def facts_markdown(facts: list[SourceFacts], name: str) -> str:
    """事实清单（卡片底部溯源区）。"""
    lines = []
    for f in facts:
        if f.total_today or f.note:
            if f.note:
                head = f"- **{f.source}**：{f.note}"
            else:
                head = f"- **{f.source}**：{f.total_today} 条，本人相关 {f.mine_today}"
            lines.append(head)
            for s in f.samples[:2]:
                lines.append(f"  - {s}")
    if not lines:
        lines.append("- 今日各系统源均无新留痕（模块级源未接入）")
    return "\n".join(lines)


def build_preview_skeleton(date_key: str, profile: profiles.PersonProfile,
                           facts: list[SourceFacts]) -> dict[str, Any]:
    """无留痕者的确定性骨架卡（不调 LLM）。"""
    content = (
        f"**{profile.name}｜{profile.direction}**\n\n"
        f"今日系统留痕中未检索到与画像相关的记录，以下为空栏骨架——"
        "请以本人实际工作为准填写正式日报（画像仅为参考）。\n\n"
        "**一、今日重点工作**\n（待本人确认）\n\n"
        "**二、完成情况**\n（待本人确认）\n\n"
        "**三、需要协调事项**\n（待本人确认）\n\n"
        "**四、风险/问题报备**\n（待本人确认）\n\n"
        "**五、明日重点工作计划**\n（待本人确认）"
    )
    return cards.build_card_dict(
        f"🤖 日报预览·{profile.name}（AI·待本人确认）",
        content, header_template="orange",
    )


def _preview_messages(profile: profiles.PersonProfile, date_key: str,
                      facts: list[SourceFacts]) -> list[dict[str, str]]:
    facts_text = facts_markdown(facts, profile.name)
    system = (
        "你是安全部门日报预览助手。输入=员工画像、当日系统留痕事实清单、日期。"
        "请生成该员工的五段式工作日报**预览版**（仅供本人核对确认，不是正式提交）。\n"
        "段头必须逐字使用：一、今日重点工作／二、完成情况／三、需要协调事项／"
        "四、风险/问题报备／五、明日重点工作计划。\n"
        "规则：\n"
        "1. 只使用事实清单中出现的数字与状态，禁止编造或外推。**归属红线：清单中"
        "「本人相关 0」的源，其条数只是部门当日业务量，绝不能写成该员工的完成成果**——"
        "只能在段内以「部门当日共X条（本人无归属记录，待本人确认）」作背景，或整段"
        "写（今日系统无本人归属留痕，待本人确认）。\n"
        "2. 清单没有的板块写「（今日系统无留痕，待本人确认）」，不得写「无」。\n"
        "3. 明日计划=清单中未关闭/进行中事项的可执行条目；没有证据的写「待本人确认」。\n"
        "4. 数字后可用中文括注来源（如（特殊作业日报3条）），不得出现任何英文或代码式标识。\n"
        "5. 文字具体简洁：对象、数量、状态、结果；禁用「推进/尽快/持续跟进」。\n"
        "输出 JSON：{\"report_markdown\": \"<五段式 markdown，段头为一、二、三、四、五、>\"}"
    )
    user = (
        f"日期：{date_key}\n员工：{profile.name}（{profile.direction}）\n"
        f"常见工作：{profile.common_works}\n"
        + (f"周期规则：{profile.periodic}\n" if profile.periodic else "")
        + f"\n当日系统留痕事实清单：\n{facts_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def validate_preview_output(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    markdown = raw.get("report_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        return None
    for header in ("一、今日重点工作", "二、完成情况", "三、需要协调事项",
                   "四、风险/问题报备", "五、明日重点工作计划"):
        if header not in markdown:
            return None
    # 英文源标识零容忍（用户拍板：卡片不出现英文/代码式标识）
    for key in CN_LABELS:
        if key in markdown:
            return None
    return {"report_markdown": markdown.strip()}


async def generate_preview(name: str, date_key: str) -> dict[str, Any]:
    """单人预览：拉事实 →（有留痕）LLM 五段预览 /（无留痕）骨架卡。"""
    profile = profiles.profile_for(name)
    if profile is None:
        return {"ok": False, "error": "无画像"}
    facts = await collect_facts(name, date_key)
    has_facts = any(f.total_today for f in facts)
    if not has_facts:
        return {"ok": True, "card": build_preview_skeleton(date_key, profile, facts),
                "facts_count": 0}

    service = create_ai_service("text")
    try:
        with ai_audit_scope(scenario="daily_report_preview", channel="system"):
            raw = await asyncio.wait_for(
                service.chat_parsed(
                    _preview_messages(profile, date_key, facts),
                    expected_keys=["report_markdown"],
                    temperature=0.2,
                ),
                timeout=PREVIEW_TIMEOUT_SECONDS,
            )
    except Exception as exc:  # noqa: BLE001 — 预览失败降级骨架
        logger.warning("预览 LLM 失败(%s)：%s", name, exc)
        return {"ok": True, "card": build_preview_skeleton(date_key, profile, facts),
                "facts_count": sum(f.total_today for f in facts),
                "degraded": True}
    finally:
        await service.close()

    parsed = validate_preview_output(raw)
    if parsed is None:
        return {"ok": True, "card": build_preview_skeleton(date_key, profile, facts),
                "facts_count": sum(f.total_today for f in facts), "degraded": True}
    content = (
        f"**{profile.name}｜{profile.direction}**\n\n{parsed['report_markdown']}"
        "\n\n> 本卡为 AI 预览·待本人确认；正式日报以本人提交为准。"
    )
    card = cards.build_card_dict(
        f"🤖 日报预览·{profile.name}（AI·待本人确认）",
        content, header_template="blue",
    )
    return {"ok": True, "card": card, "facts_count": sum(f.total_today for f in facts)}

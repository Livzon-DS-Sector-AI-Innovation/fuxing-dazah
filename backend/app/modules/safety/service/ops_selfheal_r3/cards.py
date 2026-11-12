"""R3 汇报卡文案 —— 四形态（§4.6），纯文本构造（先存后发走 dm_admin 通道）。

卡片内容只来自结构化 stage_facts/处方/结果（证据摘要截断展示）；
「事件时间」而非「发现时间」防同机盲区误读（§13）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.ops_selfheal_r3 import signals

_RC_LABELS = {
    "upstream_outage": "上游依赖断连", "quota_exhausted": "配额/余额耗尽",
    "network": "本机网络瞬断", "config_error": "配置错误",
    "data_issue": "数据问题", "code_bug": "代码缺陷", "unknown": "未能归因",
}


def rc_label(rc: str | None) -> str:
    return _RC_LABELS.get(str(rc or "unknown"), str(rc or "unknown"))


def _evidence_brief(evidence: dict[str, Any] | None, limit: int = 6) -> str:
    """证据摘要行（首错原文/计数/探针结果，供人快速核对）。"""
    if not evidence:
        return "（无证据快照）"
    lines: list[str] = []
    for err in (evidence.get("errors") or [])[:2]:
        if err.get("error"):
            lines.append(f"- 错误原文：{str(err['error'])[:160]}")
    if evidence.get("detail"):
        lines.append(f"- 探活详情：{str(evidence['detail'])[:160]}")
    if evidence.get("count") is not None:
        lines.append(f"- 积压计数：{evidence['count']}")
    rag = evidence.get("rag") or {}
    if rag:
        lines.append(
            f"- RAG 探针：embedding {'✅' if rag.get('embedding_ok') else '❌'}"
            f"｜检索 {'➖' if rag.get('ragplus') is None else ('✅' if rag['ragplus']['ok'] else '❌')}"
        )
    feishu = evidence.get("feishu") or {}
    if feishu:
        lines.append(f"- 飞书连通：{'✅' if feishu.get('ok') else '❌'}")
    for ep in (evidence.get("dep_endpoints") or [])[:3]:
        lines.append(f"- 依赖端点：{ep}")
    return "\n".join(lines[:limit]) or "（无关键证据）"


def _signal_title(signal: str, subject: str | None = None) -> str:
    names = {
        signals.SIGNAL_JOB_FAILED: f"定时任务「{subject or '?'}」连续失败",
        signals.SIGNAL_JOB_RECOVERED: f"定时任务「{subject or '?'}」已恢复",
        signals.SIGNAL_RAG_DEGRADED: "RAG 知识层故障",
        signals.SIGNAL_RAG_RECOVERED: "RAG 知识层已恢复",
        signals.SIGNAL_PARKED: f"副作用队列卡死（{subject or '?'}）",
        signals.SIGNAL_DEADLETTER: "隐患 AI 死信积压",
        signals.SIGNAL_DEP_RECOVERED: f"上游依赖恢复（{subject or ''}）",
        signals.SIGNAL_BATCH: "多组件故障（防风暴聚合）",
    }
    return names.get(signal, signal)


def build_diagnosis_card(
    r3: dict[str, Any], evidence: dict[str, Any] | None, *, repair_mode: str,
) -> str:
    """诊断卡：事件/根因+置信度/证据/已执行或将执行/建议/是否需人。"""
    signal = str(r3.get("signal") or "")
    subject = r3.get("job_name") or r3.get("component")
    executed = list(r3.get("executed") or [])
    planned = list(r3.get("planned") or [])
    mode_line = (
        f"已执行（auto）：{'、'.join(executed)}" if executed and repair_mode == "auto"
        else f"将执行（{repair_mode} 观察模式，不真正执行）：{'、'.join(planned) or '无'}"
        if planned else "无自动修复动作"
    )
    suggestions = [
        str(x) for x in (r3.get("suggestions") or [])
    ][:5]
    lines = [
        f"【R3 诊断】{_signal_title(signal, subject)}",
        f"事件时间：{r3.get('first_seen_at') or r3.get('diag_at') or '-'}",
        f"根因判断：{rc_label(r3.get('root_cause_class'))}"
        f"（置信度 {r3.get('confidence', 0):.2f}｜{r3.get('source', 'rules')}）",
        f"归因说明：{str(r3.get('reasoning') or '-')[:160]}",
        "证据摘要：", _evidence_brief(evidence),
        f"修复动作：{mode_line}",
    ]
    if r3.get("dep_endpoints"):
        lines.append(f"监控端点：{'、'.join(r3['dep_endpoints'])}（恢复后自动补跑漏审日）")
    if suggestions:
        lines.append("建议：" + "；".join(suggestions))
    if r3.get("stage") == signals.R3_STAGE_NEEDS_HUMAN:
        lines.append("⚠️ 需人工处理（本地不可自愈）")
    return "\n".join(lines)


def build_repair_result_card(
    action: str, results: list[dict[str, Any]], *, observe: bool = False,
) -> str:
    """修复结果卡：动作 × 逐项 ✅/❌；失败带错误原文与下一步。

    observe=True 版当前无调用方（「将执行」由诊断卡承担），保留作
    人工一键转正展示的预留形态（§4.6 修复结果卡 observe 变体）。
    """
    if observe:
        return "\n".join([
            f"【R3 修复结果】{action}（观察模式·未执行）",
            *[f"- 将执行：{r.get('label') or r}" for r in results[:10]],
        ])
    lines = [f"【R3 修复结果】{action}"]
    for r in results[:20]:
        ok = bool(r.get("ok"))
        mark = "✅" if ok else "❌"
        detail = str(r.get("detail") or "")
        if not ok:
            detail = f"{detail}｜下一步：{'重试中' if r.get('will_retry') else '已升级人工'}"
        lines.append(f"- {mark} {r.get('label') or '?'}：{detail[:200]}")
    ok_n = sum(1 for r in results if r.get("ok"))
    lines.append(f"合计：✅ {ok_n} ｜ ❌ {len(results) - ok_n}")
    return "\n".join(lines)


def build_closure_card(r3: dict[str, Any], extra: str = "") -> str:
    """收口卡 🟢：已自愈（根因/持续/动作/补跑/验证/关闭）。"""
    signal = str(r3.get("signal") or "")
    subject = r3.get("job_name") or r3.get("component")
    lines = [
        f"【R3 收口 🟢】{_signal_title(signal, subject)} 已自愈",
        f"事件时间：{r3.get('first_seen_at') or '-'}",
        f"根因：{rc_label(r3.get('root_cause_class'))}",
        f"动作清单：{'、'.join(r3.get('executed') or []) or '（无需修复动作）'}",
    ]
    backfill = r3.get("backfill_summary")
    if backfill:
        lines.append(f"补跑结果：{str(backfill)[:300]}")
    lines.append("验证通过（信号恢复 ∧ 本通知送达），工单关闭")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def build_escalation_card(r3: dict[str, Any], guidance: str = "") -> str:
    """升级卡 🔴：已试动作×轮×结果+根因判断+具体指引（人按指引决策，不从日志查起）。"""
    signal = str(r3.get("signal") or "")
    subject = r3.get("job_name") or r3.get("component")
    lines = [
        f"【R3 升级 🔴】{_signal_title(signal, subject)} 自愈未收口",
        f"事件时间：{r3.get('first_seen_at') or '-'}",
        f"根因判断：{rc_label(r3.get('root_cause_class'))}"
        f"（置信度 {r3.get('confidence', 0):.2f}）",
        f"已试动作：{len(r3.get('executed') or [])} 项 × "
        f"{r3.get('repair_rounds', 0)} 轮"
        f"（{'、'.join(r3.get('executed') or []) or '无 L1 动作'}）",
        f"当前阶段：{signals.R3_STAGE_LABELS.get(str(r3.get('stage')), str(r3.get('stage')))}",
        f"需人工：{guidance or '请人工排查处置（处置后工单将随恢复信号自动收口）'}",
    ]
    return "\n".join(lines)

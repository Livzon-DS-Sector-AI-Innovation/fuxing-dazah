"""域 Agent 委派元工具（2-D 试点：URS 域）。

orchestrator 恒定持有确认门（PendingAction）/权限（ROLE_TOOL_POLICY）/
审计（ai_audit scope），delegate 只做「程序化运行域 Agent + 结果回传」，
零新框架（pydantic-ai 2.8 无内建 delegation，取仓储 Runner 同款模式）。

挂起传播（方案 Y，最小侵入）：域子 Agent 以 DeferredToolRequests 终局
（请求写工具）时，delegate **绝不代为执行**（那会绕过 orchestrator 确认门），
而是返回待确认结构；executor 检测到后合成挂起动作，走既有
pending action → 用户确认 → resume 链路执行（权限/审计管道零变动）。

开关：SAFETY_AGENT_URS_DELEGATION（app_config feature_flag，默认关 =
挂载式整域工具集，一键回退）。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import DeferredToolRequests, RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

# 当前可委派域（试点仅 URS；扩大与否由 2-D 试点对比数据决定）
DELEGATABLE_DOMAINS: tuple[str, ...] = ("urs",)

# 挂起透传标记的键契约（executor._extract_delegated_deferral 同源引用，
# 防跨模块字符串漂移）
DELEGATED_KEY = "deferred"
DELEGATED_DEFERRED_SUMMARY = "URS 域子流程请求执行写操作 {tool_name}（参数以复述为准）"


async def delegate(
    ctx: RunContext[SafetyDeps], domain: str, query: str
) -> dict[str, Any]:
    """将任务委派给域专家 Agent 处理（当前支持 URS 设备采购审核域）。

    当用户任务属于 URS（用户需求规格书）域——查询 URS 记录/审核详情、
    发起 URS 审核、解析 URS 文档、跑适用性评估/风险画像、更新条目、
    确认评估、申诉、导出报告——调用本工具，由域 Agent 完成多步流程后
    回传结果；你再汇总作答。query 用用户的原始诉求（可补充必要上下文）。
    """
    from app.modules.safety.business_agent.agent import get_domain_agent

    if domain not in DELEGATABLE_DOMAINS:
        return {
            "error": f"未知域 {domain!r}，可委派域: {', '.join(DELEGATABLE_DOMAINS)}"
        }

    sub_agent = get_domain_agent(domain)
    logger.info("delegate: domain=%s query=%r", domain, query[:80])
    result = await sub_agent.run(query, deps=ctx.deps, message_history=[])
    output = result.output

    if isinstance(output, DeferredToolRequests):
        # 子 Agent 请求写工具 → 透传为待确认结构（不代为执行，确认门在
        # orchestrator；executor 合成挂起动作走既有确认/resume 链路）
        approvals = output.approvals or output.calls
        if not approvals:
            return {"error": "子流程挂起但无待确认调用"}
        call = approvals[0]  # 试点口径：一次透传一个写请求
        extra = len(approvals) - 1
        try:
            args = call.args_as_dict() if call.args else {}
        except Exception:
            args = {}
        summary = DELEGATED_DEFERRED_SUMMARY.format(tool_name=call.tool_name)
        if extra:
            summary += f"（另有 {extra} 个写请求，本轮确认后再继续发起）"
        return {
            DELEGATED_KEY: True,
            "tool_name": call.tool_name,
            "arguments": dict(args) if isinstance(args, dict) else {},
            "summary": summary,
            "message": (
                "子流程已规划完毕并请求上述写操作。请向用户完整复述该方案"
                "（工具名与参数），请求用户确认；本轮不要调用其它工具。"
                "用户确认后系统会执行并回传结果。"
            ),
        }

    return {
        "deferred": False,
        "reply": output if isinstance(output, str) else str(output),
    }

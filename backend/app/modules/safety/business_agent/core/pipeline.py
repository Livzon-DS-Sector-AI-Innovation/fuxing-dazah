"""统一工具执行管道（S2）。

所有工具调用（含只读）统一走「pre-execute 权限 → guard 审批挂起 → execute → post 审计+禁语 → result」管道：

- pre-execute：``perm_check(role, tool_name)``，deny-by-default。只读工具也强制（US1：匿名会话调
  敏感只读工具被拒）。
- guard：写工具（``TOOL_KIND[name]=True``）的审批挂起由 Pydantic AI ``DeferredToolRequests`` 处理，
  管道不重复（只做权限 + 执行 + 审计，审批机制不变）。
- execute：调真实工具函数。
- post-execute：单点写 ``safety.ai_call_audits``（每工具调用一行）+ 禁语检查（rules.check_output）。
- result：统一 ``ToolResult`` 结构，兼容现有工具散落的 dict 返回。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.core.permissions import check as perm_check
from app.modules.safety.business_agent.rules import check_output
from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

# 1-B：单条工具结果给模型的内容上限（对齐仓储 agent 的 4KB 截断）。
# 只截「给模型看的内容」；审计（_post_audit）与业务落库不受影响。
_TOOL_RESULT_MAX_BYTES = 4096
# 截断提示文案占位的冗余预算（notice 字段本体不计入上限判定）
_TOOL_RESULT_NOTICE_SLACK = 512


@dataclass
class ToolResult:
    """统一工具结果结构（替代各工具散落的 dict）。

    Attributes:
        ok: 工具执行是否成功（假的「权限拒绝」业务不存在，denied 单独标记）
        data: 成功时的返回数据（业务 dict）
        error: 失败/拒绝时的错误描述
        denied: 权限拒绝（区别于业务错误）
        banned_hits: 禁语检测命中的短语（仅对返回文本中检测出禁语时非空）
    """

    ok: bool
    data: dict | None = None
    error: str | None = None
    denied: bool = False
    banned_hits: list[str] = field(default_factory=list)

    @staticmethod
    def deny(reason: str) -> ToolResult:
        return ToolResult(ok=False, error=reason, denied=True)

    @staticmethod
    def ok_(data: dict) -> ToolResult:
        return ToolResult(ok=True, data=data)

    def to_dict(self) -> dict:
        """转换为兼容现有工具的 dict 返回（denied/失败走 ``{"error": ...}``）。"""
        if not self.ok:
            return {"error": self.error or "工具执行失败"}
        return self.data if self.data is not None else {}


async def execute_tool(
    ctx: RunContext[SafetyDeps],
    tool_name: str,
    args: dict[str, Any],
    real_func: Callable[..., Awaitable[Any]],
) -> Any:
    """统一工具执行管道：pre → guard → execute → post → result。

    被 wrap 后的工具函数调用；返回值兼容现有工具的 dict 返回
    （denied 时返回 ``{"error": ...}``），避免 Pydantic AI tool schema 校验失败。
    """
    deps = ctx.deps

    # 1. pre-execute：权限（所有工具含只读，deny-by-default）
    if not perm_check(deps.role, tool_name):
        await _post_audit(
            ctx,
            tool_name,
            args,
            denied=True,
            error=f"权限不足：角色 {deps.role!r} 无权调用 {tool_name!r}",
        )
        return {"error": f"权限不足：角色 {deps.role!r} 无权调用 {tool_name!r}"}

    # 2. guard：写工具（TOOL_KIND[name]=True）的审批挂起由 Pydantic AI
    #    DeferredToolRequests 处理，不在管道内重复（机制不变）。

    # 3. execute：调真实工具函数
    try:
        data = await real_func(ctx, **args)
        ok = True
        err = None
    except Exception as e:
        data = None
        ok = False
        err = f"{type(e).__name__}: {e}"

    # 4. post-execute：审计埋点（单点写 ai_call_audits）+ 禁语检查
    banned_hits = _check_banned_output(tool_name, data) if ok else []
    await _post_audit(
        ctx,
        tool_name,
        args,
        denied=False,
        ok=ok,
        data=data,
        error=err,
        banned_hits=banned_hits,
    )

    # 5. result：统一返回（成功结果超限时截断给模型的内容；错误/拒绝不截断）
    result = ToolResult(ok=ok, data=data, error=err, banned_hits=banned_hits)
    out = result.to_dict()
    if ok and isinstance(out, dict):
        return _truncate_tool_result(out)
    return out


def _serialized_len(obj: Any) -> int:
    """JSON 序列化字节数；失败返回超大值（交给上层兜底路径）。"""
    try:
        return len(json.dumps(obj, ensure_ascii=False, default=str).encode())
    except Exception:  # noqa: BLE001 - 不可序列化对象走整体预览兜底
        return _TOOL_RESULT_MAX_BYTES * 8


def _truncate_tool_result(data: dict) -> dict:
    """工具结果超 4KB 时截断给模型的内容。

    - 列表字段（取序列化后最大者）：二分保留前 M 条 + 「共 N 条，已显示前 M 条」提示，
      保持原有 dict 结构（模型可继续按字段消费）。
    - 无列表可截或单条仍超限：整体降级为截断预览（preview + 截断提示）。
    """
    if _serialized_len(data) <= _TOOL_RESULT_MAX_BYTES:
        return data

    list_fields = [
        (k, v) for k, v in data.items() if isinstance(v, list) and len(v) > 1
    ]
    if list_fields:
        key, values = max(list_fields, key=lambda kv: _serialized_len(kv[1]))
        total = len(values)
        lo, hi = 1, total  # 二分找满足预算的最大保留条数 M
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = {**data, key: values[:mid]}
            if _serialized_len(candidate) <= _TOOL_RESULT_MAX_BYTES:
                lo = mid
            else:
                hi = mid - 1
        trimmed = dict(data)
        trimmed[key] = values[:lo]
        trimmed["truncation_notice"] = (
            f"「{key}」共 {total} 条，已显示前 {lo} 条；"
            f"如需完整数据请缩小查询范围或分页查询"
        )
        if _serialized_len(trimmed) <= _TOOL_RESULT_MAX_BYTES + _TOOL_RESULT_NOTICE_SLACK:
            return trimmed

    payload = json.dumps(data, ensure_ascii=False, default=str)
    keep = max(0, _TOOL_RESULT_MAX_BYTES - 200)
    return {
        "truncated": True,
        "truncation_notice": "工具结果过长，已整体截断为预览",
        "preview": payload[:keep],
    }


def _check_banned_output(tool_name: str, data: Any) -> list[str]:
    """对工具返回的文本字段做禁语检查；命中返回短语列表。

    工具返回通常是 dict，仅对其中的字符串字段做禁语检测（rules.check_output 面向文本回复）。
    """
    if not isinstance(data, dict):
        return []
    hits: list[str] = []
    for value in data.values():
        if isinstance(value, str) and value:
            check = check_output(value)
            if not check.ok:
                # 合并去重，重复短语只记一次
                for p in check.banned_hits:
                    if p not in hits:
                        hits.append(p)
    return hits


async def _post_audit(
    ctx: RunContext[SafetyDeps],
    tool_name: str,
    args: dict[str, Any],
    *,
    denied: bool,
    ok: bool = True,
    data: Any = None,
    error: str | None = None,
    banned_hits: list[str] | None = None,
) -> None:
    """单点写 safety.ai_call_audits（每工具调用一行）。失败仅告警，不阻塞。"""
    try:
        from app.modules.safety.ai_audit.store import insert_audit

        deps = ctx.deps
        person = deps.person
        await insert_audit(
            scenario="agent_tool_call",
            session_id=deps.session_id or None,
            channel=deps.channel,
            user_name=person.name if person else None,
            # ai_call_audits.model 列非空约束；工具调用不涉模型，用占位标记（与 executor 的 _model_name 区分）
            model="tool_call",
            input_text=f"{tool_name}({list(args.keys())})",
            output_text=(str(data)[:500] if ok and data else None),
            status=("denied" if denied else ("success" if ok else "failed")),
            error=error,
            latency_ms=None,
            guard_hits=banned_hits or None,
            extra={"tool_name": tool_name, "args": args, "role": deps.role},
        )
    except Exception:
        logger.exception("pipeline 审计写入失败（不影响业务）")

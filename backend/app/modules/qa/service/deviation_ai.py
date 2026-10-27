"""偏差 AI 辅助服务：登记规范化与调查引导的建议生成。

只产建议不落库：登记辅助（描述规范化 5W1H + 涉及对象识别）与调查辅助
（M1E 问题清单 / 5Why 追问 / 假设性检验草案）的输出全部由前端审核采纳，
正式写入仍走 ``create_deviation`` / ``update_deviation`` 的既有审计路径。
涉及对象的主数据匹配复用知识库 AI 分析的目录与模糊匹配基建，保持
「AI 抽取 + 确定性匹配优先」的同一套纪律。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import (
    Deviation,
    DeviationItemCategory,
    MasterObject,
    MasterObjectType,
)
from app.modules.qa.schemas import DeviationAiAssistIn
from app.modules.qa.service._shared import _audit, normalize_text
from app.modules.qa.service.ai_analysis import _catalog, _fuzzy_match
from app.platform.identity.models import User
from app.platform.integrations.ai.client import AIOutputError, AIService

logger = logging.getLogger(__name__)

DEVIATION_AI_PROMPT_VERSION = "qa-deviation-assist-v1"

# 建议数量上限：prompt 约束 + 代码截断双保险。
MAX_SUGGESTED_ITEMS = 20
MAX_MISSING_ELEMENTS = 10
MAX_M1E_QUESTIONS = 3
MAX_WHY_STEPS = 10
MAX_HYPOTHESES = 5

_M1E_KEYS = ("personnel", "machine", "material", "method", "environment", "other")
_M1E_LABELS = {
    "personnel": "人员",
    "machine": "设备 / 仪器",
    "material": "物料",
    "method": "方法 / 程序",
    "environment": "环境",
    "other": "其他",
}
# 命中主数据后按对象类型校正涉及对象类别；SUPPLIER/REGION 没有对应的
# 涉及对象类别，保留模型给出的类别由人工判断。键用存储值字符串，避免
# 脏数据触发枚举构造异常。
_MASTER_CATEGORY_MAP: dict[str, DeviationItemCategory] = {
    MasterObjectType.PRODUCT.value: DeviationItemCategory.FINISHED,
    MasterObjectType.MATERIAL.value: DeviationItemCategory.MATERIAL,
    MasterObjectType.EQUIPMENT.value: DeviationItemCategory.EQUIPMENT,
}
_VALID_ITEM_CATEGORIES = {member.value for member in DeviationItemCategory}


def _require_ai() -> None:
    settings = get_settings()
    if not settings.QA_AI_ENABLED or not settings.QA_AI_API_KEY:
        raise AppException(status_code=503, message="AI 服务未配置，请联系管理员启用")


async def _model_json(prompt: str, expected_keys: list[str]) -> dict[str, Any]:
    """调用 LLM 并解析 JSON；429/5xx/网络错误按配置退避重试。

    独立成模块级函数便于测试打桩，不需要真实模型即可覆盖装配逻辑。
    """
    settings = get_settings()
    last_error: Exception | None = None
    for attempt in range(max(1, int(settings.QA_AI_MAX_RETRIES) + 1)):
        client = AIService(
            api_key=settings.QA_AI_API_KEY,
            base_url=settings.QA_AI_BASE_URL,
            model=settings.QA_AI_MODEL,
            timeout=settings.QA_AI_TIMEOUT_SECONDS,
        )
        try:
            return await client.chat_parsed(
                messages=[
                    {
                        "role": "system",
                        "content": "你是制药企业 GMP 质量保证专家。只输出合法 JSON，不输出 Markdown。",
                    },
                    {"role": "user", "content": prompt},
                ],
                expected_keys=expected_keys,
                temperature=0.2,
            )
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.TransportError,
            AIOutputError,
        ) as exc:
            last_error = exc
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code not in {429, 500, 502, 503, 504}
            ):
                break
            if attempt < int(settings.QA_AI_MAX_RETRIES):
                await asyncio.sleep(min(2**attempt, 4))
        finally:
            await client.close()
    raise AppException(
        status_code=502, message=f"AI 服务暂时不可用，请稍后重试（{last_error}）"
    )


def _context_block(payload: DeviationAiAssistIn) -> str:
    """把表单快照组装成 prompt 的上下文段；空字段不出现。"""
    lines = [f"偏差描述：{payload.description}"]
    if payload.department_name:
        lines.append(f"发生部门：{payload.department_name}")
    if payload.group_name:
        lines.append(f"组别：{payload.group_name}")
    if payload.reporter_name:
        lines.append(f"发现人：{payload.reporter_name}")
    if payload.emergency_measures:
        lines.append(f"应急处理措施：{payload.emergency_measures}")
    if payload.items:
        rows = "；".join(
            f"{item.name}（批号 {item.batch_no}）" if item.batch_no else item.name
            for item in payload.items
        )
        lines.append(f"已登记涉及对象：{rows}")
    m1e_parts = [
        f"{_M1E_LABELS[key]}调查：{value}"
        for key in _M1E_KEYS
        if (value := getattr(payload, f"m1e_{key}"))
    ]
    lines.extend(m1e_parts)
    if payload.direct_cause:
        lines.append(f"直接原因：{payload.direct_cause}")
    if payload.root_cause:
        lines.append(f"根本原因：{payload.root_cause}")
    if payload.why_chain:
        chain = " → ".join(
            f"{step.question}：{step.answer}" for step in payload.why_chain if step.answer
        )
        if chain:
            lines.append(f"已有 5Why：{chain}")
    if payload.hypothesis_tests:
        done = "；".join(
            f"{test.hypothesis}（结果：{test.result}）"
            for test in payload.hypothesis_tests
            if test.result
        )
        if done:
            lines.append(f"已完成的假设检验：{done}")
    return "\n".join(lines)


def _coerce_category(value: Any) -> DeviationItemCategory:
    text = str(value or "").strip().lower()
    if text in _VALID_ITEM_CATEGORIES:
        return DeviationItemCategory(text)
    return DeviationItemCategory.OTHER


def _match_master(
    name: str,
    masters: list[MasterObject],
    aliases: dict[uuid.UUID, list[str]],
) -> dict[str, Any] | None:
    """三级匹配：归一化全等 > 归一化包含 > 模糊（复用知识库 0.82 阈值）。"""
    target = normalize_text(name)
    if len(target) < 2:
        return None
    best: tuple[float, int, str, MasterObject] | None = None
    for master in masters:
        terms: list[tuple[str, str]] = [
            ("exact_code", master.code),
            ("exact_name", master.name),
        ]
        terms.extend(("exact_alias", alias) for alias in aliases.get(master.id, []))
        for match_type, term in terms:
            normalized = normalize_text(term)
            if len(normalized) < 2:
                continue
            if normalized == target:
                score = 1.0
            elif normalized in target or target in normalized:
                score = 0.9
            else:
                continue
            if best is None or (score, len(normalized)) > (best[0], best[1]):
                best = (score, len(normalized), match_type, master)
    if best is None:
        fuzzy = _fuzzy_match(name, masters, aliases)
        if fuzzy:
            master, _term, score = fuzzy[0]
            return {
                "master_id": str(master.id),
                "code": master.code,
                "name": master.name,
                "object_type": master.object_type,
                "match_type": "fuzzy",
                "confidence": round(float(score), 3),
            }
        return None
    score, _length, match_type, master = best
    return {
        "master_id": str(master.id),
        "code": master.code,
        "name": master.name,
        "object_type": master.object_type,
        "match_type": match_type,
        "confidence": score,
    }


async def _assist_describe(db: AsyncSession, payload: DeviationAiAssistIn) -> dict[str, Any]:
    prompt = (
        "请帮助整理下面的偏差登记内容，完成三件事：\n"
        "1. description：把偏差描述重组为规范的 5W1H 段落式描述——何时发现、何时发生、何地、"
        "谁发现、发生了什么、如何发现的、为何构成偏差（正确做法是什么）、已采取的应急措施。"
        "只能重组和明确已有事实，禁止编造、推测或遗漏原始信息。\n"
        "2. missing_elements：按固定要素清单检查缺项：发生日期、涉及批号、发现人、发现方式、"
        "偏差发生的具体位置/工序、应急处理措施、涉及设备或物料编号。只列出确实缺失的要素名。\n"
        "3. items：抽取涉及的物料/中间体/成品/中控样品/设备/文件，每条含 name（原文中的名称）、"
        "category（material|intermediate|finished|in_process|equipment|document|other）、"
        "batch_no（原文批号，没有则留空）、evidence（原文中包含该名称的短片段）。\n"
        '返回 JSON：{"description": "...", "missing_elements": ["..."], '
        '"items": [{"name": "...", "category": "...", "batch_no": "", "evidence": "..."}]}\n\n'
        f"登记内容：\n{_context_block(payload)}"
    )
    raw = await _model_json(prompt, ["description", "missing_elements", "items"])
    description = str(raw.get("description") or "").strip()
    if not description:
        raise AppException(status_code=502, message="AI 返回内容为空，请重试")
    missing = [
        str(element).strip()
        for element in (raw.get("missing_elements") or [])
        if str(element or "").strip()
    ][:MAX_MISSING_ELEMENTS]

    masters, aliases, _ = await _catalog(db)
    description_folded = payload.description.casefold()
    suggested: list[dict[str, Any]] = []
    seen = {(item.category.value, normalize_text(item.name)) for item in payload.items}
    for entry in raw.get("items") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:255]
        if not name:
            continue
        category = _coerce_category(entry.get("category"))
        batch_no = str(entry.get("batch_no") or "").strip()[:128] or None
        # 防幻觉纪律：证据必须在原描述中命中，命中不了就丢证据不丢行。
        evidence = str(entry.get("evidence") or "").strip()[:200] or None
        if evidence and evidence.casefold() not in description_folded:
            evidence = None
        # 先按主数据校正类别，再按「最终类别 + 名称」去重：模型类别与已登记
        # 类别不一致时，校正后命中已登记对象应整条丢弃，而不是换个类别再提一次。
        match = _match_master(name, masters, aliases)
        if match is not None:
            mapped = _MASTER_CATEGORY_MAP.get(str(match["object_type"]))
            if mapped is not None:
                category = mapped
        key = (category.value, normalize_text(name))
        if key in seen:
            continue
        seen.add(key)
        suggested.append(
            {
                "category": category.value,
                "name": name,
                "batch_no": batch_no,
                "evidence": evidence,
                "match": match,
            }
        )
        if len(suggested) >= MAX_SUGGESTED_ITEMS:
            break
    return {"description": description, "missing_elements": missing, "items": suggested}


async def _assist_m1e(db: AsyncSession, payload: DeviationAiAssistIn) -> dict[str, Any]:
    prompt = (
        "请针对下面的偏差，为人机料法环（5M1E）调查生成针对性的调查问题清单。\n"
        "每个方面 2-3 个问题，全部合计不超过 12 个，优先覆盖与本偏差最相关的方面；"
        "每个问题只问一件事、一句话、不超过 60 字。问题必须结合该偏差的具体情境"
        "（涉及对象、发生环节、现有调查发现），不要泛泛而谈的通用问题；"
        "目的是引导调查人员收集事实，而不是给出结论。\n"
        '返回 JSON：{"checklists": {"personnel": ["问题", ...], "machine": [...], '
        '"material": [...], "method": [...], "environment": [...], "other": [...]}}\n\n'
        f"偏差上下文：\n{_context_block(payload)}"
    )
    raw = await _model_json(prompt, ["checklists"])
    checklists_raw = raw.get("checklists")
    checklists: dict[str, list[str]] = {}
    if isinstance(checklists_raw, dict):
        for key in _M1E_KEYS:
            questions = [
                str(question).strip()
                for question in (checklists_raw.get(key) or [])
                if str(question or "").strip()
            ][:MAX_M1E_QUESTIONS]
            if questions:
                checklists[key] = questions
    return {"checklists": checklists}


async def _assist_why(db: AsyncSession, payload: DeviationAiAssistIn) -> dict[str, Any]:
    prompt = (
        "请协助下面偏差的 5Why 根本原因分析：基于偏差描述和已有的直接原因（若给出），"
        "生成一条 3-5 步的追问链建议——从直接原因出发连续追问「为什么」，"
        "逐步深入到系统性/管理体系层面的根本原因（培训、SOP 设计、防错机制、资源安排等），"
        "不要停留在「人员失误」层面。\n"
        "每步含 question（追问问题）和 answer（基于现有信息的最可能回答提示；"
        "信息不足时给出待调查的假设并注明「需现场核实」）。禁止编造描述中没有的事实。\n"
        '返回 JSON：{"steps": [{"question": "为什么…？", "answer": "…"}, ...]}\n\n'
        f"偏差上下文：\n{_context_block(payload)}"
    )
    raw = await _model_json(prompt, ["steps"])
    steps: list[dict[str, str]] = []
    for entry in raw.get("steps") or []:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()[:500]
        if not question:
            continue
        answer = str(entry.get("answer") or "").strip()[:4000]
        steps.append({"question": question, "answer": answer})
        if len(steps) >= MAX_WHY_STEPS:
            break
    return {"steps": steps}


async def _assist_hypothesis(
    db: AsyncSession, payload: DeviationAiAssistIn
) -> dict[str, Any]:
    prompt = (
        "下面的偏差经常规调查暂时无法确认根本原因，需要设计假设性检验实验。"
        "请提出 2-4 个最值得优先验证的候选假设：\n"
        "hypothesis（假设原因，一句可被实验证实或排除的陈述）、sample（需要检验的样品/对象）、"
        "protocol（简明的检验方案）、expected（判定标准/预期结果）。\n"
        "假设必须与偏差现象有因果逻辑，优先可快速排除的假设。\n"
        '返回 JSON：{"hypotheses": [{"hypothesis": "...", "sample": "...", '
        '"protocol": "...", "expected": "..."}]}\n\n'
        f"偏差上下文：\n{_context_block(payload)}"
    )
    raw = await _model_json(prompt, ["hypotheses"])
    hypotheses: list[dict[str, str | None]] = []
    for entry in raw.get("hypotheses") or []:
        if not isinstance(entry, dict):
            continue
        hypothesis = str(entry.get("hypothesis") or "").strip()[:4000]
        if not hypothesis:
            continue
        hypotheses.append(
            {
                "hypothesis": hypothesis,
                "sample": str(entry.get("sample") or "").strip()[:4000] or None,
                "protocol": str(entry.get("protocol") or "").strip()[:4000] or None,
                "expected": str(entry.get("expected") or "").strip()[:4000] or None,
            }
        )
        if len(hypotheses) >= MAX_HYPOTHESES:
            break
    return {"hypotheses": hypotheses}


_HANDLERS = {
    "describe": _assist_describe,
    "m1e": _assist_m1e,
    "why": _assist_why,
    "hypothesis": _assist_hypothesis,
}


async def ai_assist(
    db: AsyncSession,
    payload: DeviationAiAssistIn,
    user: User | None = None,
) -> dict[str, Any]:
    """按 kind 生成建议；不写任何业务表，仅记一条不含原文的审计。"""
    _require_ai()
    settings = get_settings()
    if payload.deviation_id is not None:
        # 审计归属校验：指向不存在的偏差会污染审计线索。
        result = await db.execute(
            select(Deviation).where(
                Deviation.id == payload.deviation_id,
                Deviation.is_deleted.is_(False),
            )
        )
        if result.scalar_one_or_none() is None:
            raise NotFoundException("偏差", str(payload.deviation_id))
    handler = _HANDLERS[payload.kind]
    result = await handler(db, payload)
    await _audit(
        db,
        action="deviation.ai_assist",
        user=user,
        resource_type="deviation",
        resource_id=payload.deviation_id,
        extra={
            "kind": payload.kind,
            "model": settings.QA_AI_MODEL,
            "prompt_version": DEVIATION_AI_PROMPT_VERSION,
        },
    )
    return {
        "kind": payload.kind,
        "prompt_version": DEVIATION_AI_PROMPT_VERSION,
        "model": settings.QA_AI_MODEL,
        **result,
    }

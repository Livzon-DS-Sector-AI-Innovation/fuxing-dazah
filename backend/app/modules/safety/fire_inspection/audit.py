"""点检记录 AI 审核轮询：手写签字完备性 + 设备编号照片比对，结果写回 Bitable。

轮询口径：审核「审核结果」字段为空的记录（未审 = 待审队列）；已写
「通过/不通过」的记录不再重复审核。基础设施失败（照片下载/模型调用/
输出解析）不写结果，下轮自然重试——绝不把 infra 故障误判成「不通过」。

审核两项（2026-11-05 需求）：
1. 手写签字——「签字」字段有附件即过（点检责任到人）；
2. 设备编号——整体照片送视觉模型识别编号，与登记「设备编号」比对，
   拍错设备/照片不匹配在此拦截。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.safety.fire_inspection.models import (
    FIELD_AUDIT_NOTE,
    FIELD_AUDIT_RESULT,
    DeviceSpec,
    EXTINGUISHER_SPEC,
    InspectionRecord,
    parse_record,
)
from app.modules.safety.fire_inspection.pdf import _normalize_for_embed
from app.modules.safety.fire_inspection.service import default_repo

logger = logging.getLogger(__name__)

AUDIT_PASS = "通过"
AUDIT_FAIL = "不通过"

# 视觉模型调用注入点：(text_prompt, image_data_uris) -> 模型原始输出
VisionChat = Callable[[str, list[str]], Awaitable[str]]

_TRUE = {"1", "true", "yes", "on", "y"}


def audit_enabled() -> bool:
    """审核轮询总开关（默认关闭；SAFETY_FIRE_INSPECTION_AUDIT_ENABLED 置真启用）。"""
    from app.modules.safety.app_config.store import store as _app_config_store

    raw = (_app_config_store.get_raw("SAFETY_FIRE_INSPECTION_AUDIT_ENABLED") or "").strip().lower()
    return raw in _TRUE


class AuditParseError(RuntimeError):
    """模型输出无法解析为预期 JSON（基础设施级，跳过重试，不写结果）。"""


# ── 纯函数：编号归一 / 比对 / prompt / 解析 / 判定 ──────────────────

_NOISE_RE = re.compile(r"[\s\-_—－·.。:：,，/\\]")


def normalize_equipment_no(value: str | None) -> str:
    """编号归一：去空白/分隔符/全角标点，统一大写，供宽松比对。"""
    return _NOISE_RE.sub("", value or "").upper()


def compare_equipment_no(
    expected: str | None, recognized: str | None
) -> tuple[bool, str]:
    """登记编号 vs 照片识别编号。返回 (是否核验通过, 说明)。"""
    if not expected:
        return False, "记录未填写设备编号，无法比对"
    if not recognized:
        return False, "整体照片中未识别到设备编号，无法核验是否拍对设备"
    e, r = normalize_equipment_no(expected), normalize_equipment_no(recognized)
    # 识别串可能带标牌前缀等杂字符，归一后期望串被完整包含即视为一致
    if e == r or e in r:
        return True, f"照片识别编号 {recognized} 与登记编号一致"
    return False, f"照片识别编号 {recognized} 与登记编号 {expected} 不一致，疑似拍错设备或照片与设备不匹配"


def build_audit_prompt(spec: DeviceSpec = EXTINGUISHER_SPEC) -> str:
    # 2026-11-05 真机试验：先逐字转录标牌再抽编号，对 21 条不一致样本纠正
    # 6 条（T2→TZ 类前缀读错）；显式提示形近字符（2/Z、0/O、T/F、1/I）。
    # 2026-11-10 双表化：设备名词与编号示例按 spec 注入（灭火器 MF / 消火栓 XHS）。
    example = "T2-1F-MF-005 / T2-3F-XHS-001" if spec.kind == "hydrant" else "T2-1F-MF-005 / FJ-3F-MF-012"
    return (
        f"你是消防设施点检照片审核助手。照片中有一个红色点检标牌和{spec.label}。\n"
        "请分两步：\n"
        "第1步：逐字符转录红色标牌上「设备编号」方框内的全部文字，注意区分易混字符："
        "数字2与字母Z、数字0与字母O、字母T与字母F、数字1与字母I。\n"
        f"第2步：从转录文字中提取设备编号（形如 {example}，"
        "结构为 楼栋-楼层-类型-序号）。\n"
        '只输出 JSON：{"设备编号": "提取的编号"}；找不到编号输出 {"设备编号": null}。'
    )


def parse_recognized_no(text: str) -> str | None:
    """解析模型输出：JSON 的「设备编号」值；null → None。

    容忍 markdown 围栏；解析不出 JSON 结构抛 AuditParseError（infra 级重试），
    JSON 合法但编号为 null 返回 None（照片确实没有 → 判不通过）。
    """
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise AuditParseError(f"模型输出无 JSON 结构: {text[:120]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise AuditParseError(f"模型输出 JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict) or "设备编号" not in data:
        raise AuditParseError(f"模型输出缺少「设备编号」键: {text[:120]!r}")
    value = data["设备编号"]
    if value is None:
        return None
    recognized = str(value).strip()
    return recognized or None


def to_data_uri(data: bytes) -> str:
    """照片字节 → 视觉模型 data URI（复用归档链路降采样防 MPO/超大图）。"""
    normalized = _normalize_for_embed(data)
    if normalized[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif normalized[:4] == b"\x89PNG":
        mime = "image/png"
    else:
        mime = "image/jpeg"  # 兜底：归一化后基本是 JPEG
    encoded = base64.b64encode(normalized).decode("ascii")
    return f"data:{mime};base64,{encoded}"


@dataclass(frozen=True)
class AuditDecision:
    """两项检查合成后的写回内容。"""

    result: str  # AUDIT_PASS / AUDIT_FAIL
    note: str    # 不通过原因（通过时为空）


def decide_audit(has_signature: bool, eq_ok: bool, eq_note: str) -> AuditDecision:
    reasons: list[str] = []
    if not has_signature:
        reasons.append("未上传手写签字，点检责任无法落实到人")
    if not eq_ok:
        reasons.append(eq_note)
    if not reasons:
        return AuditDecision(result=AUDIT_PASS, note="")
    return AuditDecision(result=AUDIT_FAIL, note="；".join(reasons))


def build_writeback(decision: AuditDecision) -> dict[str, str]:
    return {FIELD_AUDIT_RESULT: decision.result, FIELD_AUDIT_NOTE: decision.note}


# ── 编排：单轮审核 ──────────────────────────────────────────────


@dataclass
class AuditRoundResult:
    """一轮审核的结局。"""

    audited: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    failed_audit: list[str] = field(default_factory=list)
    # infra 失败（下载/模型/解析）：不写结果，下轮重试
    infra_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def failures(self) -> list[dict[str, str]]:
        return [{"record_id": rid, "reason": reason} for rid, reason in self.infra_failed]

    @property
    def failed(self) -> int:
        return len(self.infra_failed)


class AuditRepoPort(Protocol):
    """审核所需数据端口（BitableRepo 满足；测试注入内存桩）。"""

    async def list_records(self) -> list[dict[str, object]]: ...

    async def download(self, file_token: str, extra: str | None = None) -> bytes: ...

    async def attachment_extra_map(
        self, record_ids: list[str]
    ) -> dict[str, dict[str, str]]: ...

    async def update_fields(self, record_id: str, field_values: dict[str, str]) -> None: ...

    async def aclose(self) -> None: ...


def _default_vision_chat() -> VisionChat:
    """生产视觉链路：ai_config vision profile（deepseek-flash 多模态直传）。"""
    from app.modules.safety.service.config import get_ai_service

    service = get_ai_service("vision")

    async def _chat(prompt: str, image_uris: list[str]) -> str:
        return await service.chat_vision(prompt, image_uris, temperature=0.1, max_tokens=512)

    return _chat


async def _audit_one(
    repo: AuditRepoPort,
    record: InspectionRecord,
    extras: dict[str, str],
    vision_chat: VisionChat,
    spec: DeviceSpec = EXTINGUISHER_SPEC,
) -> AuditDecision | None:
    """审核单条记录；返回写回判定，infra 失败抛异常由调用方计失败。"""
    # 1) 手写签字（纯规则）
    has_signature = bool(record.signatures)
    # 2) 设备编号比对（视觉）
    eq_ok, eq_note = False, ""
    if not record.overall_photos:
        eq_ok, eq_note = False, "未上传整体照片，无法核验设备编号"
    elif not record.equipment_no:
        eq_ok, eq_note = False, "记录未填写设备编号，无法比对"
    else:
        att = record.overall_photos[0]
        data = await repo.download(att.file_token, extras.get(att.file_token))
        uri = to_data_uri(data)
        raw = await vision_chat(build_audit_prompt(spec), [uri])
        recognized = parse_recognized_no(raw)
        eq_ok, eq_note = compare_equipment_no(record.equipment_no, recognized)
    return decide_audit(has_signature, eq_ok, eq_note)


async def run_audit_round(
    record_ids: list[str] | None = None,
    *,
    repo: AuditRepoPort | None = None,
    vision_chat: VisionChat | None = None,
    spec: DeviceSpec = EXTINGUISHER_SPEC,
) -> AuditRoundResult:
    """扫描待审记录（审核结果为空），逐条审核并写回。

    record_ids 给定时只在该范围内审（仍只审未审过的）；spec 决定表坐标与
    点检项清单（灭火器/消火栓）。
    """
    own_repo = repo is None
    repo = repo or default_repo(spec)
    vision_chat = vision_chat or _default_vision_chat()
    result = AuditRoundResult()
    try:
        raw_records = await repo.list_records()
        records = [parse_record(raw, spec) for raw in raw_records]
        if record_ids:
            id_set = set(record_ids)
            records = [r for r in records if r.record_id in id_set]
        pending = [r for r in records if not r.audit_result]
        logger.info(
            "点检AI审核[%s]: 待审 %d 条（范围 %d 条）", spec.label, len(pending), len(records)
        )
        extras_by_record = await repo.attachment_extra_map([r.record_id for r in pending])
        for record in pending:
            try:
                decision = await _audit_one(
                    repo, record, extras_by_record.get(record.record_id, {}), vision_chat, spec
                )
                if decision is None:
                    continue
                await repo.update_fields(record.record_id, build_writeback(decision))
                result.audited.append(record.record_id)
                (result.passed if decision.result == AUDIT_PASS else result.failed_audit).append(
                    record.record_id
                )
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}".rstrip(": ")
                logger.warning(
                    "点检AI审核 infra 失败 record=%s: %s", record.record_id, reason
                )
                result.infra_failed.append((record.record_id, reason))
        return result
    finally:
        if own_repo:
            await repo.aclose()


__all__ = [
    "AUDIT_FAIL",
    "AUDIT_PASS",
    "AuditDecision",
    "AuditParseError",
    "AuditRoundResult",
    "audit_enabled",
    "build_audit_prompt",
    "build_writeback",
    "compare_equipment_no",
    "decide_audit",
    "normalize_equipment_no",
    "parse_recognized_no",
    "run_audit_round",
    "to_data_uri",
]

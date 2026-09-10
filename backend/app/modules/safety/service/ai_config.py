"""安全模块 AI 配置只读视图（脱敏 + 场景清单 + 生效来源标识）。

供 HTTP API ``GET /scheduler-config/ai-config`` 与 Agent 只读工具
``query_ai_config`` 复用，保证 API / Agent 侧返回同构数据，
且不泄露完整 API Key（只输出 ``api_key_masked``，绝无明文 api_key）。

数据源：AI 配置中心 store（``ai_config.resolver.get_profile``），
每字段来源（``sources``）与生效状态（``source``）直接透出
（db/env/default/disabled/missing 字符串，未做映射）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.ai_config.resolver import get_profile
from app.modules.safety.ai_config.scenario_registry import (  # noqa: F401  re-export 契约
    _AI_SCENARIO_FUNCTIONS,
    iter_scenarios,
)
from app.modules.safety.ai_config.scenario_store import scenario_store
from app.modules.safety.ai_config.store import ProfileView

# 场景事实源（scenario -> (label, description, model_type, channel)）已迁至
# ai_config/scenario_registry.py（唯一事实源，防双向 import）；本行 import 为该名字的
# re-export —— 外部 `from app.modules.safety.service.ai_config import _AI_SCENARIO_FUNCTIONS`
# 兼容（backend-design §2.1）；_build_functions_view 已直接遍历注册表
# （iter_scenarios，27 场景为事实源），不再依赖 ai_audit 常量交集。


def _mask_api_key(api_key: str | None) -> str:
    """脱敏 API Key：仅显示「已配置 · **** + 后 4 位」，未配置显示「未配置」。"""
    if not api_key:
        return "未配置"
    if len(api_key) > 8:
        return f"已配置 · ****{api_key[-4:]}"
    return "已配置 · ****"


def _build_model_view(
    view: ProfileView,
    backup_view: ProfileView | None,
    *,
    has_backup: bool = False,
) -> dict[str, Any]:
    """把某 profile 的合并视图转成只读模型视图（脱敏 + 来源标识）。

    configured 按**本组自身** api_key 判定（WARN3 修复：不再用顶层「text 与 vision
    都就绪」的联合值——单缺另一组 key 时本组不得误报未配置）。
    """
    model: dict[str, Any] = {
        "configured": bool(view.config.get("api_key")),
        "base_url": view.config.get("base_url") or None,
        "model": view.config.get("model") or None,
        "temperature": view.config.get("temperature"),
        "timeout": view.config.get("timeout"),
        "api_key_masked": _mask_api_key(view.config.get("api_key")),
        "source": view.status,
        "sources": dict(view.sources),
    }
    if has_backup:
        backup = backup_view
        # 备用组 configured 按自身 api_key 或 model 判定（与顶层无关，对齐 design §4.5）
        model["backup"] = {
            "configured": bool(backup) and bool(
                backup.config.get("api_key") or backup.config.get("model")
            ),
            "model": (backup.config.get("model") if backup else None) or None,
            "api_key_masked": (
                _mask_api_key(backup.config.get("api_key")) if backup else "未配置"
            ),
        }
    else:
        model["backup"] = None
    return model


def _build_text_backup_view(view: ProfileView) -> dict[str, Any]:
    """文本备用模型卡（顶层扁平化，与其它 4 组同构；无 backup/dims/temperature 字段）。

    configured = api_key 非空 或 model 非空（design §4.5：备用组仅配 model 也算已配置）。
    """
    return {
        "configured": bool(view.config.get("api_key") or view.config.get("model")),
        "base_url": view.config.get("base_url") or None,
        "model": view.config.get("model") or None,
        "timeout": view.config.get("timeout"),
        "api_key_masked": _mask_api_key(view.config.get("api_key")),
        "source": view.status,
        "sources": dict(view.sources),
    }


def _build_embedding_view(view: ProfileView) -> dict[str, Any]:
    """向量模型卡（与 text_model 同构，无 backup，含 dims）。"""
    return {
        "configured": bool(view.config.get("api_key")),
        "base_url": view.config.get("base_url") or None,
        "model": view.config.get("model") or None,
        "dims": view.config.get("dims"),
        "api_key_masked": _mask_api_key(view.config.get("api_key")),
        "source": view.status,
        "sources": dict(view.sources),
    }


def _build_rerank_view(view: ProfileView) -> dict[str, Any]:
    """重排模型卡（与 text_model 同构，无 backup/temperature/timeout/dims）。"""
    return {
        "configured": bool(view.config.get("api_key")),
        "base_url": view.config.get("base_url") or None,
        "model": view.config.get("model") or None,
        "api_key_masked": _mask_api_key(view.config.get("api_key")),
        "source": view.status,
        "sources": dict(view.sources),
    }


def _build_functions_view() -> list[dict[str, Any]]:
    """遍历场景注册表（iter_scenarios，27 场景为单一事实源），输出 AI 调用功能清单。

    WARN3 修复：不再以 ai_audit/models.py 的 SCENARIO_* 常量 ∩ 注册表为迭代源
    （常量含未注册的 chemical_inventory_risk_scan、注册表含 vision 的
    regulation_ocr，交集会漏掉视觉场景行）；直接遍历注册表，保证每个可配场景
    都在 functions 中出现（含 regulation_ocr，前端据此对视觉场景做熔断开关）。

    每项在 {id,label,description,model_type,channel} 基础上追加场景配置状态
    （enabled/model_profile/effective_profile/source/status，与 GET ai-scenarios
    同源合并，前端零重复请求）；旧字段保持不动（向后兼容一期/二期契约）。
    """
    functions: list[dict[str, Any]] = []
    for info in iter_scenarios():
        view = scenario_store.get_scenario_view(info.scenario)
        functions.append({
            "id": info.scenario,
            "label": info.label,
            "description": info.description,
            "model_type": info.model_type,
            "channel": info.channel,
            "enabled": view.enabled,
            "model_profile": view.model_profile,
            "effective_profile": view.effective_profile,
            "source": view.source,
            "status": view.status,
        })
    return functions


def build_ai_config_view() -> dict[str, Any]:
    """返回 AI 配置只读视图：脱敏模型配置（5 组）+ AI 调用功能清单。

    与 API ``GET /scheduler-config/ai-config`` 的结构完全一致。
    env/DB 均无 text/vision key 时，返回 configured=False 与 error 说明
    （原 RuntimeError 降级语义），不抛 500，也不泄露完整密钥
    （api_key 只以 api_key_masked 形式输出）。
    """
    text_view = get_profile("text")
    vision_view = get_profile("vision")
    backup_view = get_profile("text_backup")
    embedding_view = get_profile("embedding")
    rerank_view = get_profile("rerank")

    configured = True
    error: str | None = None
    if not text_view.config.get("api_key"):
        configured = False
        error = (
            "环境变量 SAFETY_AI_TEXT_API_KEY 未配置，无法初始化 AI 文本模型。"
            "请在 .env 文件或 AI 配置中心（text profile）设置该值。"
        )
    elif not vision_view.config.get("api_key"):
        configured = False
        error = (
            "环境变量 SAFETY_AI_VISION_API_KEY 未配置，无法初始化 AI 视觉模型。"
            "请在 .env 文件或 AI 配置中心（vision profile）设置该值。"
        )

    return {
        # 顶层 configured 语义保持「text 与 vision 都就绪」（现有调用方语义不下沉）；
        # 各 model 视图的 configured 独立按本组自身 key 判定（WARN3 修复）
        "configured": configured,
        "error": error,
        "text_model": _build_model_view(
            text_view, backup_view, has_backup=True
        ),
        # text_backup 顶层扁平化（WARN1 修复）：与其它组同构，携带 base_url/timeout/
        # source/sources；text_model.backup 嵌套结构保留（前端双源兼容）
        "text_backup_model": _build_text_backup_view(backup_view),
        "vision_model": _build_model_view(
            vision_view, None, has_backup=False
        ),
        "embedding_model": _build_embedding_view(embedding_view),
        "rerank_model": _build_rerank_view(rerank_view),
        "functions": _build_functions_view(),
    }

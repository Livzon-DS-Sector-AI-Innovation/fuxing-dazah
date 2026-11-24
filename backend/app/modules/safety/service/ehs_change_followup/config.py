"""开关（app_config KV：env > DB 活行 > 代码默认）。

三道闸（DESIGN §8）——**总闸默认关**是安全红线：本机 dev 后端连真实飞书租户，
uvicorn --reload 会把当天到点未跑的任务立刻补跑；开发全程不开总闸，
真机验收走灰度收件人（所有 DM 只发此人，内容不变）。
"""

from __future__ import annotations

from app.modules.safety.app_config.store import store as _app_config_store

TOGGLE_KEY = "SAFETY_EHS_CHANGE_FOLLOWUP_ENABLED"
GRAY_KEY = "SAFETY_EHS_CHANGE_FOLLOWUP_GRAY_RECIPIENT"
EXCLUDED_KEY = "SAFETY_EHS_CHANGE_FOLLOWUP_EXCLUDED"
WRITEBACK_DRY_RUN_KEY = "SAFETY_EHS_CHANGE_FOLLOWUP_WRITEBACK_DRY_RUN"

# 排除清单预置（DESIGN §2.5 七项，2026-11-24 拍板）：状态填了已验收但无
# 已通过验收单，待业务确认。确认后的出路都不改代码——补挂验收单关联自动判
# 关闭，或改对状态列后从清单移除。比较按归一化编号（records.normalize_change_no）。
DEFAULT_EXCLUDED = (
    "FSAS-2025-003,FXAS-2025-005,FX-D4-2026-002,FX-T5-20260424,"
    "FXD1-2026-07-01,FXSC-2026001,FXQA-20260728"
)


def enabled() -> bool:
    """EHS 变更周度督办总闸（默认关）。"""
    return _app_config_store.get_bool(TOGGLE_KEY, False)


def gray_recipient() -> str:
    """灰度收件人（非空时所有 DM 卡只发此人，内容不变）。"""
    return _app_config_store.get_str(GRAY_KEY, "")


def excluded_raw() -> str:
    """排除清单原文（逗号分隔变更编号）。"""
    return _app_config_store.get_str(EXCLUDED_KEY, DEFAULT_EXCLUDED)


def writeback_dry_run() -> bool:
    """回写演练模式（默认关）。

    开 = 提交进展时**不真写**变更表「变更最新具体进展」，但按成功返回，
    只验「回调→写库→改卡」链路。实机点名/交互演练用，避免污染生产表；
    正式验收「回写」一项与上线必须关。
    """
    return _app_config_store.get_bool(WRITEBACK_DRY_RUN_KEY, False)

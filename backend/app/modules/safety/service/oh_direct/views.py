"""oh 直读视图对象（Ticket 01）。

照 msds_direct/views.py 模式，字段与 OhPosition / OhHazardFactor ORM 完全同名：

1. id = feishu_record_id = recXXX（legacy 为镜像 UUID——工具体 id 仅信息性，
   双态落档 spec D6）；
2. 直读常量列（spec D6）：
   - job_title 恒 None：Bitable 岗位信息表无「职务」列（survey_oh 探针
     2026-09-23 坐实：3 fields）→ 直读取不到；镜像因历史迁移保有职务值
     （verify 盘点 439/440 非空——映射只在非空时写键，事件不会清掉旧值），
     这是 positions 维持镜像的佐证之一（spec §0.1/§0.3）；列恢复后
     ``bd_fields.text`` 天然取到，无需改代码；
   - notes 恒 None（两表均无备注列映射）；source 恒 "bitable"（handler upsert 恒置）；
   - created_at/updated_at：PG 审计时间不可直读 → 恒 None；
   - is_deleted 恒 False：Bitable 行删除即物理消失，直读天然不含已删行。
3. hazard_factors_status 系 handler 映射时派生（"filled" if hazard_factors else
   "empty"，oh_bitable_handler.map_position_fields），非独立数据源——直读同规则派生；
4. 危害因素多选去重保序（handler `_clean_hazard_factors` 同款，spec D8）；
5. 映射用底座 fields.*（text/multi 双形态解析），不复用 handler `_rich/_multi_list`：
   handler 走 get_record 纯字符串形态故无恙，直读 search 富文本段形态必须底座
   双形态解析（msds handler `_text` 形态陷阱同款教训）；
6. 跳行规则复刻（spec D7）：position 部门岗位均空、hazard_factor 名称空 →
   ``view_from_record`` 返回 None（reader 侧丢弃），与镜像种群口径一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields

__all__ = [
    "OhHazardFactorView",
    "OhPositionView",
    "hazard_factor_view_from_record",
    "position_view_from_record",
]


@dataclass
class OhPositionView:
    """岗位信息表行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    feishu_record_id: str | None = None

    # 业务字段（与 ORM 完全同名）
    department: str | None = None
    position: str | None = None
    job_title: str | None = None
    hazard_factors: list[str] | None = None
    hazard_factors_status: str | None = None

    # 状态/审计列（镜像口径；直读常量，见模块 docstring）
    source: str = "bitable"
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False


@dataclass
class OhHazardFactorView:
    """危害因素 PPE 表行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    feishu_record_id: str | None = None

    # 业务字段（与 ORM 完全同名）
    factor_name: str | None = None
    ppe_respiratory: str | None = None

    # 状态/审计列（镜像口径；直读常量，见模块 docstring）
    source: str = "bitable"
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_deleted: bool = False


def _clean_multi(value: Any) -> list[str] | None:
    """多选 → 去重保序标准名列表；空返回 None（handler `_clean_hazard_factors` 同款）。"""
    items = bd_fields.select_values(value)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out or None


def position_view_from_record(
    record_id: str, fields: dict[str, Any]
) -> OhPositionView | None:
    """岗位信息表原始 fields → 视图对象（纯函数；部门岗位均空 → None 跳行）。"""
    department = bd_fields.text(fields, "部门")
    position = bd_fields.text(fields, "岗位")
    if not department and not position:
        return None

    hazard_factors = _clean_multi(fields.get("危害因素"))
    return OhPositionView(
        id=record_id,
        feishu_record_id=record_id,
        department=department,
        position=position,
        # 「职务」死列：Bitable 无此列，恒 None（列恢复后天然取到）
        job_title=bd_fields.text(fields, "职务"),
        hazard_factors=hazard_factors,
        hazard_factors_status="filled" if hazard_factors else "empty",
    )


def hazard_factor_view_from_record(
    record_id: str, fields: dict[str, Any]
) -> OhHazardFactorView | None:
    """危害因素 PPE 表原始 fields → 视图对象（纯函数；名称空 → None 跳行）。"""
    factor_name = bd_fields.text(fields, "危害因素名称")
    if not factor_name:
        return None
    return OhHazardFactorView(
        id=record_id,
        feishu_record_id=record_id,
        factor_name=factor_name,
        ppe_respiratory=bd_fields.text(fields, "呼吸防护用品"),
    )

"""职业健康危害因素 PPE 字典 Service — 查询 / 42 项标准字典 / PPE 对照表。

对齐 backend-design.md §5.5：
- get_enums 返回标准危害因素字典（42 项，本 ticket 权威清单）；
- get_ppe_map 供工作流②（OhTransferService），因子 → 呼吸防护用品（取表值，禁止 AI 编造）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import OhHazardFactor
from app.modules.safety.repository import SafetyRepository

# 危害因素标准字典（42 项）— 与 Bitable 多选字段预设一致
OH_HAZARD_FACTORS_STANDARD: tuple[str, ...] = (
    "噪声", "氨", "高温", "甲醇", "甲醛", "苯", "甲苯", "甲酸", "乙酸", "磷酸",
    "乙腈", "丙酮", "氰及腈类化合物", "盐酸及氯化氢", "二甲基甲酰胺", "谷物粉尘",
    "锰及其无机化合物", "氮氧化物", "铝尘", "炭黑粉尘", "酸雾或酸酐", "二甲苯",
    "有机粉尘", "压力容器", "矽尘", "硅藻土粉尘", "珍珠岩粉尘", "活性炭粉尘",
    "无机粉尘", "电焊烟尘", "电焊弧光", "二氧化硫", "一氧化碳", "三氯甲烷", "三乙胺",
    "正己烷", "正庚烷", "二氯甲烷", "乙酸乙酯", "硫酸及三氧化硫", "高处作业", "其他粉尘",
)


class OhHazardFactorService:
    """危害因素 PPE 字典服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    async def get_factors(
        self, *, skip: int = 0, limit: int = 50
    ) -> tuple[list[OhHazardFactor], int]:
        """危害因素 PPE 台账列表（分页）"""
        return await self.repo.get_oh_hazard_factors(skip, limit)

    async def get_factor(self, factor_id: uuid.UUID) -> OhHazardFactor | None:
        """字典项详情"""
        return await self.repo.get_oh_hazard_factor_by_id(factor_id)

    async def get_enums(self) -> list[str]:
        """危害因素标准字典（42 项）"""
        return list(OH_HAZARD_FACTORS_STANDARD)

    async def get_ppe_map(self) -> dict[str, str]:
        """因子 → 呼吸防护用品对照表（供工作流②，取 oh_hazard_factors 表值）"""
        rows = await self.repo.get_all_oh_hazard_factors()
        return {r.factor_name: r.ppe_respiratory or "" for r in rows}

    # ── Bitable 同步（ticket 03 handler 复用）──

    async def upsert_from_bitable(
        self, data: dict[str, Any], feishu_record_id: str
    ) -> OhHazardFactor:
        existing = await self.repo.get_oh_hazard_factor_by_feishu_id(feishu_record_id)
        if existing:
            data.pop("feishu_record_id", None)
            updated = await self.repo.update_oh_hazard_factor(existing.id, data)
            if updated:
                return updated
            return existing
        return await self.repo.create_oh_hazard_factor(
            {**data, "feishu_record_id": feishu_record_id}
        )

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        existing = await self.repo.get_oh_hazard_factor_by_feishu_id(feishu_record_id)
        if not existing:
            return False
        return await self.repo.delete_oh_hazard_factor(existing.id)

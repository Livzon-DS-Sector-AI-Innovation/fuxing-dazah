"""危化品库存管理 Service — 单表固定行台账 + 规则直回风险标记/风险说明。

对齐 docs/chemical-inventory-design.md（精简版）：
- 只有一张「危化品库存总表」（固定行，每天原地更新）；
- 库存变化时触发规则分析，把 风险标记(正常/预警) 与 风险说明(预警类型多选) 回填到该行；
- 纯规则、无 AI、无汇总表/预警表、无通知。
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.chemical_inventory.rules import (
    ChemicalRiskRuleEngine,
    compute_risk,
)
from app.modules.safety.models import ChemicalInventoryRecord, MsdsDocument
from app.modules.safety.repository import SafetyRepository

logger = logging.getLogger(__name__)


class ChemicalInventoryService:
    """危化品库存管理主服务。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SafetyRepository(db)

    # ══════════════════════════ 查询/写入 ══════════════════════════

    async def get_records(
        self,
        skip: int,
        limit: int,
        *,
        department: str | None = None,
        material_name: str | None = None,
    ) -> tuple[list[ChemicalInventoryRecord], int]:
        return await self.repo.list_inventory_records(
            skip, limit, department=department, material_name=material_name,
        )

    async def create_record(self, data: dict[str, Any]) -> ChemicalInventoryRecord:
        """手工补录/更新一条（固定行：同 部门+存放部位+物料名称 只一条，原地更新）。"""
        data = dict(data)
        for key in ("quantity", "total_quantity_t", "max_limit"):
            if data.get(key) is not None:
                data[key] = Decimal(str(data[key]))
        if data.get("hazard_classes") is not None:
            data["hazard_classes"] = [str(v) for v in data["hazard_classes"]]

        existing = await self.repo.get_inventory_record_by_key(
            data.get("department", ""),
            data.get("storage_location"),
            data.get("material_name", ""),
        )
        if existing is not None:
            await self.repo.update_inventory_record(existing.id, data)
            await self.db.flush()
            refreshed = await self.repo.get_inventory_record_by_id(existing.id)
            return refreshed if refreshed is not None else existing

        return await self.repo.create_inventory_record(data)

    # ══════════════════════════ 风险分析（规则回填）══════════════════════════

    async def analyze_changed_record(self, feishu_record_id: str) -> dict[str, Any]:
        """库存变化触发：分析该记录，回填风险标记/风险说明。"""
        record = await self.repo.get_inventory_record_by_feishu_id(feishu_record_id)
        if record is None:
            return {"changed": 0, "reason": "record not found"}
        return await self.analyze_records([record])

    async def run_full_scan(self) -> dict[str, Any]:
        """手动全量兜底：分析当前全部记录。"""
        records = await self.repo.list_all_inventory_records()
        return await self.analyze_records(records)

    async def analyze_records(self, records: list[ChemicalInventoryRecord]) -> dict[str, Any]:
        """对一批记录跑规则，逐行回填 风险标记 + 风险说明。"""
        if not records:
            return {"changed": 0, "warn_count": 0, "normal_count": 0}

        engine = ChemicalRiskRuleEngine(
            msds_names=await self._load_msds_names(),
        )
        rule_alerts = engine.scan(records)

        # 记录 id → 命中的预警类型列表
        hits: dict[Any, list[str]] = {}
        for alert in rule_alerts:
            for rid in alert.record_ids:
                if rid is not None:
                    hits.setdefault(rid, []).append(alert.alert_type)

        changed_records: list[ChemicalInventoryRecord] = []
        warn_count = 0
        normal_count = 0
        for record in records:
            flag, note = compute_risk(hits.get(record.id, []))
            if flag == "warn":
                warn_count += 1
            else:
                normal_count += 1
            if record.risk_flag != flag or (record.risk_note or []) != note:
                await self.repo.update_inventory_record(record.id, {
                    "risk_flag": flag, "risk_note": note,
                })
                record.risk_flag = flag
                record.risk_note = note
                changed_records.append(record)

        await self.db.flush()

        # 系统写回飞书总表：风险标记/风险说明（未配置时优雅降级）
        try:
            from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
                sync_record_flags_to_bitable,
            )

            if changed_records:
                await sync_record_flags_to_bitable(changed_records)
        except Exception:  # noqa: BLE001
            logger.exception("危化品库存风险标记飞书写回失败")

        return {
            "changed": len(changed_records),
            "warn_count": warn_count,
            "normal_count": normal_count,
        }

    # ══════════════════════════ 统计 ══════════════════════════

    async def get_stats(self) -> dict[str, Any]:
        """当前库存风险统计。"""
        records = await self.repo.list_all_inventory_records()
        by_flag = await self.repo.count_inventory_records_by_flag()

        over_limit = 0
        for record in records:
            if (
                record.total_quantity_t is not None
                and record.max_limit is not None
                and record.max_limit > 0
                and record.total_quantity_t > record.max_limit
            ):
                over_limit += 1

        return {
            "total_records": len(records),
            "over_limit": over_limit,
            "warn_count": by_flag.get("warn", 0),
            "normal_count": by_flag.get("normal", 0),
            "by_flag": by_flag,
        }

    # ══════════════════════════ Bitable 同步 ══════════════════════════

    async def sync_from_bitable(self) -> dict[str, Any]:
        from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
            sync_inventory_records_from_bitable,
        )
        return await sync_inventory_records_from_bitable()

    # ══════════════════════════ 只读风险分析（Agent 工具）══════════════════════════

    async def analyze_risk(self, department: str | None = None) -> dict[str, Any]:
        """只读分析当前库存风险（不落库），供 Agent 工具使用。"""
        records = await self.repo.list_all_inventory_records()
        if department:
            records = [r for r in records if r.department == department]

        engine = ChemicalRiskRuleEngine(
            msds_names=await self._load_msds_names(),
        )
        rule_alerts = engine.scan(records)
        hits: dict[Any, list[str]] = {}
        for alert in rule_alerts:
            for rid in alert.record_ids:
                if rid is not None:
                    hits.setdefault(rid, []).append(alert.alert_type)

        items: list[dict[str, Any]] = []
        for record in records:
            flag, note = compute_risk(hits.get(record.id, []))
            items.append({
                "department": record.department,
                "storage_location": record.storage_location,
                "material_name": record.material_name,
                "risk_flag": flag,
                "risk_note": note,
            })
        return {"alert_count": sum(1 for i in items if i["risk_flag"] == "warn"), "items": items}

    # ══════════════════════════ 内部工具 ══════════════════════════

    async def _load_msds_names(self) -> set[str]:
        try:
            stmt = (
                select(MsdsDocument.name, MsdsDocument.cas_no)
                .where(MsdsDocument.is_deleted == False)  # noqa: E712
            )
            rows = (await self.db.execute(stmt)).all()
            names: set[str] = set()
            for name, cas_no in rows:
                if name:
                    names.add(str(name).strip().lower())
                if cas_no:
                    names.add(str(cas_no).strip())
            return names
        except Exception:  # noqa: BLE001
            logger.exception("加载 MSDS 名称集合失败")
            return set()

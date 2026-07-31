"""Quality 业务逻辑编排。"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.excel_parser import LcReportData, parse_lc_excel
from app.modules.quality.repository import (
    create_impurities,
    create_inspection_record,
    get_impurities_by_record,
    get_inspection_by_batch,
    get_inspection_record,
)
from app.modules.quality.schemas import (
    CalculatedResultOut,
    ImpurityDetailOut,
    ImpurityPeakAreaOut,
    ImpurityResultOut,
    InspectionRecordDetail,
    LcReportOut,
    QualityStandardOut,
    UploadLcResponse,
)


@dataclass(frozen=True)
class ParserEntry:
    """解析器注册条目。"""

    name: str  # 产品名称（如"盐酸万古霉素"）
    description: str  # 简介


# 解析器注册表：后续新增产品在此注册
# 当前只有盐酸万古霉素，使用默认解析器
PARSER_REGISTRY: dict[str, ParserEntry] = {
    "盐酸万古霉素": ParserEntry(
        name="盐酸万古霉素",
        description="USP 标准（EX-HA-5246-001），支持 EP/CP 扩展",
    ),
}


class LcReportService:
    """液相报告单解析、判定与持久化服务。"""

    @staticmethod
    async def parse_and_validate(
        file_bytes: bytes,
        filename: str,
        db: AsyncSession | None = None,
    ) -> UploadLcResponse:
        """解析液相计算表，可选持久化到数据库。"""
        raw: LcReportData = parse_lc_excel(file_bytes, filename)
        report = LcReportService._build_report(raw)
        record_id: uuid.UUID | None = None

        if db:
            record_id = await LcReportService._save_inspection(db, raw, report, filename)

        return UploadLcResponse(filename=filename, report=report, record_id=record_id)

    @staticmethod
    async def get_record_detail(
        db: AsyncSession, record_id: uuid.UUID
    ) -> InspectionRecordDetail | None:
        """获取检验记录详情（含杂质明细）。"""
        record = await get_inspection_record(db, record_id)
        if not record:
            return None

        impurities = await get_impurities_by_record(db, record_id)

        # 从 raw_data 重建 LcReportOut
        report = None
        if record.raw_data:
            report = LcReportOut.model_validate(record.raw_data)

        return InspectionRecordDetail(
            id=record.id,
            product_name=record.product_name,
            batch_number=record.batch_number,
            form_id=record.form_id,
            standard_type=record.standard_type,
            all_pass=record.all_pass,
            has_oot=record.has_oot,
            excel_filename=record.excel_filename,
            created_at=record.created_at,
            report=report or LcReportOut(),
            impurities=[
                ImpurityDetailOut(
                    id=imp.id,
                    name=imp.name,
                    first_percent=imp.first_percent,
                    second_percent=imp.second_percent,
                    limit_value=imp.limit_value,
                    oot_haf=imp.oot_haf,
                    oot_haa=imp.oot_haa,
                    is_pass=imp.is_pass,
                    is_oot=imp.is_oot,
                )
                for imp in impurities
            ],
        )

    @staticmethod
    async def _save_inspection(
        db: AsyncSession,
        raw: LcReportData,
        report: LcReportOut,
        filename: str,
    ) -> uuid.UUID:
        """将解析结果持久化到数据库。"""
        # 检查是否已有同产品+批号的记录，有则更新
        existing = await get_inspection_by_batch(db, raw.product_name, raw.batch_number)
        if existing:
            existing.form_id = raw.form_id or None
            existing.standard_type = raw.standard_type or None
            existing.total_peak_area_a_first = raw.total_peak_area_a_first or None
            existing.total_peak_area_a_second = raw.total_peak_area_a_second or None
            existing.main_peak_area_a_first = raw.main_peak_area_a_first or None
            existing.main_peak_area_a_second = raw.main_peak_area_a_second or None
            existing.total_impurity_area_first = raw.total_impurity_area_first or None
            existing.total_impurity_area_second = raw.total_impurity_area_second or None
            existing.any_unknown_impurity_first = raw.any_unknown_impurity_first or None
            existing.any_unknown_impurity_second = raw.any_unknown_impurity_second or None
            existing.main_peak_area_b_first = raw.main_peak_area_b_first or None
            existing.main_peak_area_b_second = raw.main_peak_area_b_second or None
            existing.all_pass = report.all_pass
            existing.has_oot = report.has_oot
            existing.raw_data = report.model_dump(mode="json")
            existing.excel_filename = filename
            await db.flush()
            # 软删除旧杂质 + 写入新杂质
            old_impurities = await get_impurities_by_record(db, existing.id)
            for imp in old_impurities:
                imp.is_deleted = True
            await db.flush()
            record_id = existing.id
            # 保存新杂质明细
            impurity_data = []
            for imp in raw.impurity_results:
                impurity_data.append({
                    "name": imp.name,
                    "first_percent": imp.first_percent,
                    "second_percent": imp.second_percent,
                    "limit": imp.limit,
                    "oot_haf": imp.oot_haf,
                    "oot_haa": imp.oot_haa,
                    "is_pass": imp.is_pass,
                    "is_oot": imp.is_oot,
                })
            if impurity_data:
                await create_impurities(db, record_id, impurity_data)
            return record_id

        record = await create_inspection_record(
            db=db,
            product_name=raw.product_name,
            batch_number=raw.batch_number,
            form_id=raw.form_id or None,
            standard_type=raw.standard_type or None,
            total_peak_area_a_first=raw.total_peak_area_a_first or None,
            total_peak_area_a_second=raw.total_peak_area_a_second or None,
            main_peak_area_a_first=raw.main_peak_area_a_first or None,
            main_peak_area_a_second=raw.main_peak_area_a_second or None,
            total_impurity_area_first=raw.total_impurity_area_first or None,
            total_impurity_area_second=raw.total_impurity_area_second or None,
            any_unknown_impurity_first=raw.any_unknown_impurity_first or None,
            any_unknown_impurity_second=raw.any_unknown_impurity_second or None,
            main_peak_area_b_first=raw.main_peak_area_b_first or None,
            main_peak_area_b_second=raw.main_peak_area_b_second or None,
            all_pass=report.all_pass,
            has_oot=report.has_oot,
            raw_data=report.model_dump(mode="json"),
            excel_filename=filename,
        )

        # 保存杂质明细
        impurity_data = []
        for imp in raw.impurity_results:
            impurity_data.append({
                "name": imp.name,
                "first_percent": imp.first_percent,
                "second_percent": imp.second_percent,
                "limit": imp.limit,
                "oot_haf": imp.oot_haf,
                "oot_haa": imp.oot_haa,
                "is_pass": imp.is_pass,
                "is_oot": imp.is_oot,
            })
        if impurity_data:
            await create_impurities(db, record.id, impurity_data)

        return record.id

    @staticmethod
    def _build_report(raw: LcReportData) -> LcReportOut:
        all_pass = True
        has_oot = False
        standards = [
            QualityStandardOut(
                name=s.name,
                limit=s.limit,
                oot_haf=s.oot_haf,
                oot_haa=s.oot_haa,
                operator=s.operator,
            )
            for s in raw.standards
        ]
        peaks = [
            ImpurityPeakAreaOut(name=p.name, first=p.first, second=p.second)
            for p in raw.impurity_peaks
        ]

        def judge(val, op, limit, oh, oa):
            ok = True
            if limit and limit > 0:
                ok = val >= limit if op == "≥" else val <= limit
            oot = (oh and val > oh) or (oa and val > oa)
            return ok, oot

        vb = None
        if raw.vancomycin_b:
            v = raw.vancomycin_b
            vb_ok, vb_oot = judge(v.rounded_first, "≥", v.limit, v.oot_haf, v.oot_haa)
            if not vb_ok:
                all_pass = False
            if vb_oot:
                has_oot = True
            vb = CalculatedResultOut(
                name=v.name,
                first_percent=v.first_percent,
                second_percent=v.second_percent,
                rounded_first=v.rounded_first,
                rounded_second=v.rounded_second,
                limit=v.limit,
                oot_haf=v.oot_haf,
                oot_haa=v.oot_haa,
                is_pass=vb_ok,
                is_oot=vb_oot,
            )

        ti = None
        if raw.total_impurities:
            t = raw.total_impurities
            ti_ok, ti_oot = judge(t.rounded_first, "≤", t.limit, t.oot_haf, t.oot_haa)
            if not ti_ok:
                all_pass = False
            if ti_oot:
                has_oot = True
            ti = CalculatedResultOut(
                name=t.name,
                first_percent=t.first_percent,
                second_percent=t.second_percent,
                rounded_first=t.rounded_first,
                rounded_second=t.rounded_second,
                limit=t.limit,
                oot_haf=t.oot_haf,
                oot_haa=t.oot_haa,
                is_pass=ti_ok,
                is_oot=ti_oot,
            )

        imps = []
        for imp in raw.impurity_results:
            ok, oot = judge(
                imp.second_percent or imp.first_percent,
                "≤",
                imp.limit,
                imp.oot_haf,
                imp.oot_haa,
            )
            if not ok:
                all_pass = False
            if oot:
                has_oot = True
            imps.append(
                ImpurityResultOut(
                    name=imp.name,
                    first_percent=imp.first_percent,
                    second_percent=imp.second_percent,
                    limit=imp.limit,
                    oot_haf=imp.oot_haf,
                    oot_haa=imp.oot_haa,
                    is_pass=ok,
                    is_oot=oot,
                )
            )

        return LcReportOut(
            product_name=raw.product_name,
            batch_number=raw.batch_number,
            form_id=raw.form_id,
            standard_type=raw.standard_type,
            total_peak_area_a_first=raw.total_peak_area_a_first,
            total_peak_area_a_second=raw.total_peak_area_a_second,
            main_peak_area_a_first=raw.main_peak_area_a_first,
            main_peak_area_a_second=raw.main_peak_area_a_second,
            total_impurity_area_first=raw.total_impurity_area_first,
            total_impurity_area_second=raw.total_impurity_area_second,
            any_unknown_impurity_first=raw.any_unknown_impurity_first,
            any_unknown_impurity_second=raw.any_unknown_impurity_second,
            main_peak_area_b_first=raw.main_peak_area_b_first,
            main_peak_area_b_second=raw.main_peak_area_b_second,
            impurity_peaks=peaks,
            vancomycin_b=vb,
            total_impurities=ti,
            impurity_results=imps,
            standards=standards,
            all_pass=all_pass,
            has_oot=has_oot,
        )

    @staticmethod
    def build_report_data(report: LcReportOut) -> dict:
        """将 LcReportOut 转为模板填充所需的字段字典。

        字段名与模板占位符对应，数值转换为显示格式（百分比等）。
        """
        data: dict = {
            "产品名称": report.product_name,
            "批号": report.batch_number,
            "标准类型": report.standard_type,
            "表号": report.form_id,
            "判定结果": "合格" if report.all_pass else "不合格",
        }

        # 万古霉素B
        if report.vancomycin_b:
            vb = report.vancomycin_b
            # 百分比显示（模板占位符通常期望百分比字符串）
            data["万古霉素B"] = f"{vb.rounded_first * 100:.1f}%"
            data["万古霉素B_判定"] = "合格" if vb.is_pass else "不合格"

        # 总杂质
        if report.total_impurities:
            ti = report.total_impurities
            data["总杂质"] = f"{ti.rounded_first * 100:.1f}%"
            data["总杂质_判定"] = "合格" if ti.is_pass else "不合格"

        # 各杂质
        for imp in report.impurity_results:
            suffix = imp.name.replace("杂质", "").strip()
            pct = (imp.second_percent or imp.first_percent) * 100
            data[f"杂质{suffix}"] = f"{pct:.3f}%"
            data[f"杂质{suffix}_判定"] = "合格" if imp.is_pass else "不合格"

        return data


lc_report_service = LcReportService()

"""Quality 业务逻辑编排。"""

from app.modules.quality.excel_parser import LcReportData, parse_lc_excel
from app.modules.quality.schemas import (
    CalculatedResultOut, ImpurityPeakAreaOut, ImpurityResultOut, LcReportOut, QualityStandardOut, UploadLcResponse
)


class LcReportService:
    """液相报告单解析与判定服务。"""

    @staticmethod
    def parse_and_validate(file_bytes: bytes, filename: str) -> UploadLcResponse:
        raw: LcReportData = parse_lc_excel(file_bytes, filename)
        report = LcReportService._build_report(raw)
        return UploadLcResponse(filename=filename, report=report)

    @staticmethod
    def _build_report(raw: LcReportData) -> LcReportOut:
        all_pass = True; has_oot = False
        standards = [QualityStandardOut(name=s.name, limit=s.limit, oot_haf=s.oot_haf, oot_haa=s.oot_haa, operator=s.operator) for s in raw.standards]
        peaks = [ImpurityPeakAreaOut(name=p.name, first=p.first, second=p.second) for p in raw.impurity_peaks]

        def judge(val, op, l, oh, oa):
            ok = True
            if l and l > 0: ok = val >= l if op == "≥" else val <= l
            oot = (oh and val > oh) or (oa and val > oa)
            return ok, oot

        vb = None
        if raw.vancomycin_b:
            v = raw.vancomycin_b; vb_ok, vb_oot = judge(v.rounded_first, "≥", v.limit, v.oot_haf, v.oot_haa)
            if not vb_ok: all_pass = False
            if vb_oot: has_oot = True
            vb = CalculatedResultOut(name=v.name, first_percent=v.first_percent, second_percent=v.second_percent,
                rounded_first=v.rounded_first, rounded_second=v.rounded_second, limit=v.limit, oot_haf=v.oot_haf, oot_haa=v.oot_haa, is_pass=vb_ok, is_oot=vb_oot)

        ti = None
        if raw.total_impurities:
            t = raw.total_impurities; ti_ok, ti_oot = judge(t.rounded_first, "≤", t.limit, t.oot_haf, t.oot_haa)
            if not ti_ok: all_pass = False
            if ti_oot: has_oot = True
            ti = CalculatedResultOut(name=t.name, first_percent=t.first_percent, second_percent=t.second_percent,
                rounded_first=t.rounded_first, rounded_second=t.rounded_second, limit=t.limit, oot_haf=t.oot_haf, oot_haa=t.oot_haa, is_pass=ti_ok, is_oot=ti_oot)

        imps = []
        for imp in raw.impurity_results:
            ok, oot = judge(imp.second_percent or imp.first_percent, "≤", imp.limit, imp.oot_haf, imp.oot_haa)
            if not ok: all_pass = False
            if oot: has_oot = True
            imps.append(ImpurityResultOut(name=imp.name, first_percent=imp.first_percent, second_percent=imp.second_percent,
                limit=imp.limit, oot_haf=imp.oot_haf, oot_haa=imp.oot_haa, is_pass=ok, is_oot=oot))

        return LcReportOut(product_name=raw.product_name, batch_number=raw.batch_number, form_id=raw.form_id, standard_type=raw.standard_type,
            total_peak_area_a_first=raw.total_peak_area_a_first, total_peak_area_a_second=raw.total_peak_area_a_second,
            main_peak_area_a_first=raw.main_peak_area_a_first, main_peak_area_a_second=raw.main_peak_area_a_second,
            total_impurity_area_first=raw.total_impurity_area_first, total_impurity_area_second=raw.total_impurity_area_second,
            any_unknown_impurity_first=raw.any_unknown_impurity_first, any_unknown_impurity_second=raw.any_unknown_impurity_second,
            main_peak_area_b_first=raw.main_peak_area_b_first, main_peak_area_b_second=raw.main_peak_area_b_second,
            impurity_peaks=peaks, vancomycin_b=vb, total_impurities=ti, impurity_results=imps, standards=standards, all_pass=all_pass, has_oot=has_oot)


lc_report_service = LcReportService()

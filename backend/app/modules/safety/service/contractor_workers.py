"""承包商在册人员副台账（3.x 平台台账，F1）。

数据权威在 3.x 平台（tiji-master-data 承包商人员台账），dazah 只读不镜像：
不建 PG 表、不做定时同步，页面/Agent 共用本模块的进程内短 TTL 缓存。

三组交叉核验（纯规则，2026-10-26 拍板口径，见
.scratch/f1-contractor-workers/spec.md 附录 A）：
- X1 保险：人员姓名 × 外来人员预报备审批表（按申请单/单位维度的保险有效期至）。
  人名出现在其单位（单位名精确 > 包含两级匹配）已通过报备单的人名串中即视为
  报备覆盖，取该单位最近一份有保险日期的报备单：>30 天=covered、≤30 天=
  expiring、≤今日=expired；命中报备但保险未填=unfiled；人/单位未命中=uncovered。
- X2 特种持证：特种工种集合=workTypeName 命中关键词{焊,电,架子工}；按姓名
  精确匹配 cert 域 special_op 台账（台账无身份证/单位列，name 级即上限）。
  未命中状态为 missing，展示文案统一「未见持证记录」——台账主体是内部员工
  证书，不能断言无证。
- X3 超龄：age ≥60 红（red）、≥55 黄（yellow）。

文案统一「在册」不称「在场」（平台 bind/定位字段全空，无法验在场）。
身份证/手机沿用 personnel_screening.mask_secret 打码（前 3 后 2），全量值
只在内存交叉用，不出现在任何输出行里。
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from app.modules.safety.service.bitable_direct import gates
from app.modules.safety.service.cert_direct.reader import CertWarningView
from app.modules.safety.service.visitor_insurance.reader import (
    STATUS_APPROVED,
    VisitorNoticeView,
)
from app.modules.safety.workticket_review.personnel_screening import mask_secret

logger = logging.getLogger(__name__)

__all__ = [
    "ContractorWorkersService",
    "build_rows",
    "build_stats",
    "cache_ttl_seconds",
    "is_special_work_type",
    "match_notice_company",
    "open_service",
    "split_name_pool",
]

# X2 特种工种关键词（2026-10-26 平台 workTypeName 实测值域：普工/焊工/驾驶员/
# 电工/架子工/电工,焊工/空——焊·电·架子工为特种，驾驶员与普工不计）
_SPECIAL_WORK_TYPE_KEYWORDS: tuple[str, ...] = ("焊", "电", "架子工")

# X1 保险临期窗口（天）：保险有效期至落在 (今日, 今日+30] 内为 expiring
_INSURANCE_EXPIRING_DAYS = 30

# 人名串分隔符（预报备表实测混用：，,、空白）
_NAME_SPLIT_RE = re.compile(r"[，,、\s]+")

# 三态信封
STATUS_LIVE = "live"
STATUS_DEGRADED = "degraded"
STATUS_EMPTY = "empty"


def split_name_pool(text: str | None) -> set[str]:
    """报备单人名串 → 姓名集合（容错分隔符：，,、空白）。"""
    return {part.strip() for part in _NAME_SPLIT_RE.split(text or "") if part.strip()}


def match_notice_company(
    contractor_name: str | None, companies: set[str]
) -> str | None:
    """平台承包商单位名 × 报备表单位名匹配：精确等值 > 互相包含。"""
    name = (contractor_name or "").strip()
    if not name:
        return None
    for company in sorted(companies):
        if company == name:
            return company
    for company in sorted(companies, key=len, reverse=True):
        if name in company or company in name:
            return company
    return None


def is_special_work_type(work_type_name: str | None) -> bool:
    """工种是否属于特种作业集合（关键词匹配，见模块头 X2 口径）。"""
    name = (work_type_name or "").strip()
    return bool(name) and any(kw in name for kw in _SPECIAL_WORK_TYPE_KEYWORDS)


def _assess_insurance(
    name: str,
    contractor_name: str,
    notices_by_company: dict[str, list[tuple[VisitorNoticeView, set[str]]]],
    today: date,
) -> dict[str, Any]:
    """X1：单人保险状态（人名×单位名 × 报备单保险有效期至）。"""
    company = match_notice_company(
        contractor_name, set(notices_by_company.keys())
    )
    if company is None:
        return {
            "status": "uncovered",
            "expire_date": None,
            "days_left": None,
            "source_company": None,
        }
    matched = [
        notice
        for notice, pool in notices_by_company[company]
        if name in pool
    ]
    with_expiry = [n for n in matched if n.insurance_end is not None]
    if not with_expiry:
        return {
            "status": "unfiled" if matched else "uncovered",
            "expire_date": None,
            "days_left": None,
            "source_company": company,
        }
    best = max(with_expiry, key=lambda n: n.insurance_end or today)
    expire = best.insurance_end
    assert expire is not None  # with_expiry 已过滤
    # 边界口径对齐 visitor_insurance 预警：已过期=有效期至<今日（当天仍有效，
    # 两端含边界日）；临期=今日 ≤ 有效期至 ≤ 今日+30
    if expire < today:
        status = "expired"
        days_left = 0
    else:
        days_left = (expire - today).days
        status = "expiring" if days_left <= _INSURANCE_EXPIRING_DAYS else "covered"
    return {
        "status": status,
        "expire_date": expire,
        "days_left": days_left,
        "source_company": company,
    }


def _assess_cert(
    name: str,
    work_type_name: str | None,
    certs_by_name: dict[str, list[CertWarningView]],
) -> dict[str, Any]:
    """X2：单人特种持证状态（特种工种按姓名精确匹配 special_op 台账）。"""
    if not is_special_work_type(work_type_name):
        return {"status": "nonspecial", "project": None, "next_review_date": None}
    hits = certs_by_name.get(name, [])
    if not hits:
        return {"status": "missing", "project": None, "next_review_date": None}
    projects = [c.project for c in hits if c.project]
    reviews = [c.next_review_date for c in hits if c.next_review_date]
    return {
        "status": "hit",
        "project": "、".join(projects) if projects else None,
        # 多证时取最近的再复审日期（最早到期优先暴露）
        "next_review_date": min(reviews) if reviews else None,
    }


def _age_flag(age: int | float | None) -> str:
    """X3：超龄档位——≥60 红，≥55 黄。"""
    if age is None:
        return "none"
    if age >= 60:
        return "red"
    if age >= 55:
        return "yellow"
    return "none"


def build_rows(
    workers: list[dict[str, Any]],
    notices: list[VisitorNoticeView],
    certs: list[CertWarningView],
    today: date,
) -> list[dict[str, Any]]:
    """三源内存数据 → 副台账全量行（打码后，供信封/Agent 直接输出）。"""
    approved = [
        n for n in notices if n.status == STATUS_APPROVED and n.company
    ]
    notices_by_company: dict[str, list[tuple[VisitorNoticeView, set[str]]]] = defaultdict(list)
    for notice in approved:
        notices_by_company[notice.company].append(
            (notice, split_name_pool(notice.names))
        )
    certs_by_name: dict[str, list[CertWarningView]] = defaultdict(list)
    for cert_view in certs:
        if cert_view.cert_category == "special_op" and cert_view.person_name:
            certs_by_name[cert_view.person_name].append(cert_view)

    rows: list[dict[str, Any]] = []
    for w in workers:
        name = str(w.get("name") or "").strip()
        contractor = str(w.get("contractorName") or "").strip()
        raw_work_type = str(w.get("workTypeName") or "").strip() or None
        age = w.get("age") if isinstance(w.get("age"), (int, float)) else None

        insurance = _assess_insurance(name, contractor, notices_by_company, today)
        cert = _assess_cert(name, raw_work_type, certs_by_name)
        flag = _age_flag(age)

        anomalies: list[str] = []
        if flag == "red":
            anomalies.append("超龄")
        elif flag == "yellow":
            anomalies.append("超龄预警")
        insurance_status = insurance["status"]
        if insurance_status == "uncovered":
            anomalies.append("保险未覆盖")
        elif insurance_status == "unfiled":
            anomalies.append("保险未填报")
        elif insurance_status == "expired":
            anomalies.append("保险已过期")
        elif insurance_status == "expiring":
            anomalies.append("保险临期")
        if cert["status"] == "missing":
            anomalies.append("未见持证记录")

        expire = insurance["expire_date"]
        review = cert["next_review_date"]
        rows.append(
            {
                "id": str(w.get("id") or ""),
                "name": name,
                "before_name": str(w.get("beforeName") or ""),
                "contractor_id": w.get("contractorId"),
                "contractor_name": contractor,
                "work_type": raw_work_type or "未填",
                "age": age,
                "sex": w.get("sex"),
                "birth_date": w.get("birthDate"),
                "join_job_date": w.get("joinJobDate"),
                "card_no_masked": mask_secret(str(w.get("cardNo") or "")),
                "phone_masked": mask_secret(str(w.get("telphone") or "")),
                "health": w.get("health"),
                "education": w.get("education"),
                "major": w.get("major"),
                "insurance_status": insurance_status,
                "insurance_expire_date": expire.isoformat() if expire else None,
                "insurance_days_left": insurance["days_left"],
                "insurance_source_company": insurance["source_company"],
                "cert_status": cert["status"],
                "cert_project": cert["project"],
                "cert_next_review_date": review.isoformat() if review else None,
                "age_flag": flag,
                "anomalies": anomalies,
            }
        )
    return rows


def build_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """副台账 5 卡统计（保险覆盖=covered+expiring；持证率分母=特种在册）。"""
    total = len(rows)
    contractors = len({r["contractor_name"] for r in rows if r["contractor_name"]})
    covered = sum(
        1
        for r in rows
        if r["insurance_status"] in ("covered", "expiring")
    )
    special = [r for r in rows if r["cert_status"] != "nonspecial"]
    hits = sum(1 for r in special if r["cert_status"] == "hit")
    return {
        "total": total,
        "contractors": contractors,
        "insurance_covered_pct": round(covered * 100 / total) if total else 0,
        "special_total": len(special),
        "cert_covered_pct": round(hits * 100 / len(special)) if special else None,
        "overage_count": sum(1 for r in rows if r["age_flag"] == "red"),
        "overage_warn_count": sum(1 for r in rows if r["age_flag"] == "yellow"),
    }


def cache_ttl_seconds() -> int:
    """人员视图进程内 TTL 缓存秒数（默认 600；0=关）。

    平台台账变动低频，10 分钟窗口内页面刷新/Agent 查询共用缓存实例，
    避免全量 400+ 人重复打平台接口。
    """
    return gates.int_env(
        "SAFETY_CONTRACTOR_WORKERS_CACHE_TTL_SECONDS", 600, minimum=0
    )


@dataclass
class _Entry:
    at: float
    rows: list[dict[str, Any]]
    stats: dict[str, Any]
    fetched_at: str


class ContractorWorkersService:
    """三源组装 + 短 TTL 缓存 + 三态信封（读取器全部可构造注入）。

    信封语义：live=本次（或 TTL 窗口内缓存）拉取成功；degraded=拉取失败
    回退旧缓存并保留缓存时点；empty=首次失败且无缓存。任何一源失败都按
    整包降级处理——部分源成功不出半真数据。
    """

    def __init__(
        self,
        *,
        platform_client: Any = None,
        notice_reader: Any = None,
        cert_reader: Any = None,
        ttl_seconds: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        now_fn: Callable[[], datetime] | None = None,
        today_fn: Callable[[], date] | None = None,
    ) -> None:
        self._platform_client = platform_client
        self._notice_reader = notice_reader
        self._cert_reader = cert_reader
        self._ttl = int(ttl_seconds if ttl_seconds is not None else cache_ttl_seconds())
        self._clock = clock
        self._now_fn = now_fn or (lambda: datetime.now().astimezone())
        self._today_fn = today_fn or date.today
        self._entry: _Entry | None = None

    async def get_payload(self) -> dict[str, Any]:
        now = self._clock()
        if self._ttl > 0 and self._entry and now - self._entry.at < self._ttl:
            return _live_envelope(self._entry)
        try:
            workers, notices, certs = await self._fetch_sources()
        except Exception:
            logger.exception("承包商在册人员数据源拉取失败")
            if self._entry is not None:
                entry = self._entry
                return {
                    "status": STATUS_DEGRADED,
                    "fetched_at": entry.fetched_at,
                    "message": (
                        "数据源拉取失败，当前展示缓存数据"
                        f"（缓存时点 {entry.fetched_at}）"
                    ),
                    "stats": entry.stats,
                    "workers": list(entry.rows),
                }
            return {
                "status": STATUS_EMPTY,
                "fetched_at": None,
                "message": (
                    "承包商在册人员数据拉取失败且无缓存："
                    "3.x 平台接口或飞书数据源暂不可用，请稍后重试"
                ),
                "stats": None,
                "workers": [],
            }

        rows = build_rows(workers, notices, certs, self._today_fn())
        stats = build_stats(rows)
        fetched_at = self._now_fn().isoformat()
        self._entry = _Entry(at=now, rows=rows, stats=stats, fetched_at=fetched_at)
        return _live_envelope(self._entry)

    async def _fetch_sources(
        self,
    ) -> tuple[
        list[dict[str, Any]], list[VisitorNoticeView], list[CertWarningView]
    ]:
        platform = self._platform_client or self._real_platform_client()
        notice_reader = self._notice_reader or self._real_notice_reader()
        cert_reader = self._cert_reader or self._real_cert_reader()
        workers = await platform.list_contractor_users()
        notices = await notice_reader.fetch_all()
        certs = await cert_reader.get_all_active(strict=False)
        logger.info(
            "承包商在册人员三源拉取完成: workers=%d notices=%d certs=%d",
            len(workers), len(notices), len(certs),
        )
        return workers, notices, certs

    # 真实读取器惰性装配（避免模块导入期建连；测试注入替身则不触发）

    def _real_platform_client(self) -> Any:
        from app.modules.safety.workticket_review.client import (
            WorkTicketPlatformClient,
        )

        return WorkTicketPlatformClient()

    def _real_notice_reader(self) -> Any:
        from app.modules.safety.service.visitor_insurance.reader import (
            open_reader,
        )

        return open_reader()

    def _real_cert_reader(self) -> Any:
        from app.modules.safety.service.cert_direct.reader import open_reader

        return open_reader()


def _live_envelope(entry: _Entry) -> dict[str, Any]:
    return {
        "status": STATUS_LIVE,
        "fetched_at": entry.fetched_at,
        "message": None,
        "stats": entry.stats,
        "workers": list(entry.rows),
    }


_service: ContractorWorkersService | None = None


def open_service() -> ContractorWorkersService:
    """进程内单例（页面端点与 Agent 工具共用同一缓存实例）。"""
    global _service
    if _service is None:
        _service = ContractorWorkersService()
    return _service

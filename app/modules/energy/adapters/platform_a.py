"""智恒（Zhiheng）水耗平台适配器。

从智恒平台获取指定水表（EMTRNUM）在目标小时的累计流量数据。
``platform_device_code`` 支持单水表ID和公式表达式（+/- 组合多水表）。

API 地址优先使用设备配置中的 ``api_endpoint``，为空时回退到默认地址。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.modules.energy.adapters.base import BasePlatformAdapter, CollectResult
from app.modules.energy.adapters.formula_utils import (
    eval_formula,
    has_formula,
    parse_formula_ids,
    resolve_api_url,
)

logger = logging.getLogger(__name__)

# 默认 API 地址（设备配置中 api_endpoint 为空时使用）
DEFAULT_API_URL = (
    "http://cxc.qhzl.net:8090"
    "/WebServices/YiChunWebServer.asmx/GetSiteDataByTime"
)
UNIT_CODE = "lzfxyy"
PAGE_SIZE = 20000
MAX_PAGES = 50
# 中国标准时间 UTC+8
CST = timezone(timedelta(hours=8))


class ZhihengWaterAdapter(BasePlatformAdapter):
    """智恒水耗平台适配器。"""

    platform_code = "zhiheng"
    platform_name = "智恒水耗平台"

    async def fetch_energy_data(
        self,
        device_codes: list[str],
        target_hour: datetime,
        api_endpoint: str,
        is_daily: bool = False,
    ) -> list[CollectResult]:
        # 1. 收集所有独立的水表ID
        all_meter_ids: set[str] = set()
        for code in device_codes:
            all_meter_ids.update(parse_formula_ids(code))

        # 2. 构造日期参数：智恒 API 的 endDate 不包含当天（半开区间），需 +1 天
        beg_date = (target_hour - timedelta(days=2)).strftime("%Y-%m-%d")
        end_date = (target_hour + timedelta(days=1)).strftime("%Y-%m-%d")

        # 3. 确定 API 地址：优先使用设备配置的 api_endpoint
        api_url = resolve_api_url(api_endpoint, DEFAULT_API_URL)

        # 4. 逐个水表请求 API：日汇总模式不过滤小时，直接求全天和
        meter_values: dict[str, float] = {}
        meter_errors: set[str] = set()
        async with httpx.AsyncClient(timeout=30.0) as client:
            for meter_id in sorted(all_meter_ids):
                try:
                    meter_values[meter_id] = await _fetch_meter_data(
                        client, meter_id, beg_date, end_date,
                        target_hour=None if is_daily else target_hour,
                        api_url=api_url,
                    )
                except Exception:
                    logger.exception(
                        "获取水表 %s 数据失败，默认值 0", meter_id
                    )
                    meter_values[meter_id] = 0.0
                    meter_errors.add(meter_id)

        # 所有水表均失败 → 抛出异常，避免将无效零值写入数据库
        if meter_errors and meter_errors == all_meter_ids:
            raise RuntimeError(
                f"智恒 API 所有水表均请求失败，"
                f"跳过本次采集以免写入无效零值。"
                f"失败的水表: {sorted(meter_errors)}"
            )

        # 5. 按公式求值，生成采集结果
        results: list[CollectResult] = []
        for code in device_codes:
            if has_formula(code):
                value = eval_formula(code, meter_values)
            else:
                value = meter_values.get(code, 0.0)

            results.append(
                CollectResult(
                    device_code=code,
                    timestamp=target_hour,
                    value=round(value, 4),
                    raw_data={"meter_values": meter_values},
                )
            )

        return results


async def _fetch_meter_data(
    client: httpx.AsyncClient,
    emtrnum: str,
    beg_date: str,
    end_date: str,
    target_hour: datetime | None,
    api_url: str,
) -> float:
    """分页获取指定水表数据，对 AANALOGFLOW 求和。

    target_hour 为 None 时求全天总和（日汇总模式）；
    否则仅筛选匹配 target_hour 的记录（小时模式）。
    单页请求失败时记录 warning 并继续下一页，不因个别网络抖动丢失已累计数据。
    """
    total_value = 0.0
    page = 1
    fetched = 0
    matched_count = 0

    while True:
        try:
            response = await client.post(
                api_url,
                data={
                    "unitCode": UNIT_CODE,
                    "nRow": str(PAGE_SIZE),
                    "nPage": str(page),
                    "begDate": beg_date,
                    "endDate": end_date,
                    "whereEmtrm": emtrnum,
                },
            )
            response.raise_for_status()

            payload = _extract_json(response.text)
            records = payload.get("syncData") or []  # API 可能返回 null
            total_count = int(payload.get("nCount", 0))

            for record in records:
                try:
                    if target_hour is None or _record_matches_hour(record, target_hour):
                        raw_flow = record.get("AANALOGFLOW")
                        flow_value = float(raw_flow) if raw_flow is not None else 0.0
                        total_value += flow_value
                        matched_count += 1
                        if target_hour is not None:
                            logger.debug(
                                "水表 %s 匹配记录[%d] RecordDate=%s AANALOGFLOW=%s → %.4f",
                                emtrnum,
                                matched_count,
                                record.get("RecordDate") or record.get("RecordTime"),
                                raw_flow,
                                flow_value,
                            )
                except (ValueError, TypeError) as e:
                    logger.warning(
                        "水表 %s AANALOGFLOW 解析异常: %s, record=%s",
                        emtrnum,
                        e,
                        record,
                    )
                    continue

            fetched += len(records)
            if fetched >= total_count:
                break
            page += 1
            if page > MAX_PAGES:
                logger.warning("水表 %s 分页超过 %d 页，强制停止", emtrnum, MAX_PAGES)
                break

        except httpx.HTTPStatusError:
            logger.exception(
                "智恒 API HTTP 错误: emtrnum=%s, page=%d", emtrnum, page
            )
            page += 1
            if page > MAX_PAGES:
                logger.warning(
                    "水表 %s 分页请求连续失败已达上限 %d 页，停止", emtrnum, MAX_PAGES
                )
                break
            continue
        except (json.JSONDecodeError, RuntimeError) as e:
            logger.warning(
                "智恒 API 响应解析错误: emtrnum=%s, page=%d, error=%s",
                emtrnum,
                page,
                e,
            )
            page += 1
            if page > MAX_PAGES:
                break
            continue

    mode = "全天" if target_hour is None else f"小时 {target_hour.isoformat()}"
    logger.debug(
        "水表 %s [%s]: %d 条记录, 匹配 %d 条, 合计=%.4f",
        emtrnum, mode, fetched, matched_count, total_value,
    )

    # 水务零值采集告警
    if total_value == 0.0 and matched_count > 0:
        logger.warning(
            "水表 %s [%s] 采集值为 0（匹配 %d 条记录但 AANALOGFLOW 全部为 0），"
            "请确认水表读数是否正常。",
            emtrnum, mode, matched_count,
        )
    elif total_value == 0.0:
        logger.warning(
            "水表 %s [%s] 采集值为 0（%d 条记录中无匹配记录），"
            "请检查 API 数据时间是否对齐。",
            emtrnum, mode, fetched,
        )

    return total_value


def _extract_json(text: str) -> dict[str, Any]:
    """从 XML 包裹的响应中提取 JSON。"""
    match = re.search(r"<string[^>]*>(.+)</string>", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"无法从智恒 API 响应中提取 JSON 数据: {text[:200]}")
    return json.loads(match.group(1))


def _record_matches_hour(record: dict[str, Any], target_hour: datetime) -> bool:
    """判断记录是否属于目标小时。

    智恒 API 时间字段为 POSTDATE，格式为 "2026/6/25 12:00:00"（斜杠分隔，无前导零）。
    兼容多种可能的时间字段和格式。
    解析失败时返回 False 并记录 debug 日志，便于排查 API 数据格式变更。
    """
    # 智恒 API 主时间字段：POSTDATE，备选 RecordDate / RecordTime
    time_str = record.get("POSTDATE") or record.get("RecordDate") or record.get("RecordTime")
    if not time_str:
        return False
    for fmt in (
        "%Y/%m/%d %H:%M:%S",   # 智恒格式: 2026/6/25 12:00:00
        "%Y-%m-%d %H:%M:%S",   # 标准格式: 2026-06-25 12:00:00
        "%Y/%m/%d",            # 仅日期（斜杠）
        "%Y-%m-%d",            # 仅日期（横杠）
    ):
        try:
            record_time = datetime.strptime(time_str, fmt)
            break
        except ValueError:
            continue
    else:
        logger.debug(
            "无法解析水表记录时间字段: POSTDATE=%s, RecordDate=%s, RecordTime=%s",
            record.get("POSTDATE"),
            record.get("RecordDate"),
            record.get("RecordTime"),
        )
        return False
    return (
        record_time.year == target_hour.year
        and record_time.month == target_hour.month
        and record_time.day == target_hour.day
        and record_time.hour == target_hour.hour
    )

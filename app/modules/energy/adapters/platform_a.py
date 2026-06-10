"""智恒（Zhiheng）水耗平台适配器。

从智恒平台获取指定水表（EMTRNUM）在目标小时的累计流量数据。
``platform_device_code`` 支持单水表ID和公式表达式（+/- 组合多水表）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.modules.energy.adapters.base import BasePlatformAdapter, CollectResult

logger = logging.getLogger(__name__)

API_URL = (
    "http://cxc.qhzl.net:8090"
    "/WebServices/YiChunWebServer.asmx/GetSiteDataByTime"
)
UNIT_CODE = "lzfxyy"
PAGE_SIZE = 20000
MAX_PAGES = 50
# 中国标准时间 UTC+8
CST = timezone(__import__("datetime").timedelta(hours=8))

# 公式分隔符：按 + 或 - 拆分
_FORMULA_SPLIT_RE = re.compile(r"([+-])")


def _parse_meter_ids(device_code: str) -> list[str]:
    """从单个设备编码中提取所有独立的水表ID（EMTRNUM）。

    如果 ``device_code`` 是公式（含 + 或 -），则拆分提取每个操作数；
    否则视为单水表ID返回。
    """
    tokens = _FORMULA_SPLIT_RE.split(device_code.strip())
    ids: list[str] = []
    for token in tokens:
        t = token.strip()
        if t and t not in ("+", "-"):
            ids.append(t)
    return ids


def _has_formula(device_code: str) -> bool:
    return "+" in device_code or "-" in device_code


def _eval_formula(formula: str, meter_values: dict[str, float]) -> float:
    """根据已聚合的水表值计算公式结果。"""
    tokens = _FORMULA_SPLIT_RE.split(formula.strip())
    result = 0.0
    operator = "+"
    for token in tokens:
        t = token.strip()
        if t == "+":
            operator = "+"
        elif t == "-":
            operator = "-"
        elif t:
            value = meter_values.get(t, 0.0)
            if operator == "+":
                result += value
            else:
                result -= value
    return result


class ZhihengWaterAdapter(BasePlatformAdapter):
    """智恒水耗平台适配器。"""

    platform_code = "zhiheng"
    platform_name = "智恒水耗平台"

    async def fetch_energy_data(
        self,
        device_codes: list[str],
        target_hour: datetime,
        api_endpoint: str,
    ) -> list[CollectResult]:
        # 1. 收集所有独立的水表ID
        all_meter_ids: set[str] = set()
        for code in device_codes:
            all_meter_ids.update(_parse_meter_ids(code))

        # 2. 构造日期参数（目标小时所在日期）
        beg_date = target_hour.strftime("%Y-%m-%d")
        end_date = target_hour.strftime("%Y-%m-%d")

        # 3. 逐个水表请求 API，按目标小时聚合
        meter_values: dict[str, float] = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            for meter_id in sorted(all_meter_ids):
                try:
                    meter_values[meter_id] = await _fetch_meter_hourly(
                        client, meter_id, beg_date, end_date, target_hour
                    )
                except Exception:
                    logger.exception(
                        "获取水表 %s 数据失败，默认值 0", meter_id
                    )
                    meter_values[meter_id] = 0.0

        # 4. 按公式求值，生成采集结果
        results: list[CollectResult] = []
        for code in device_codes:
            if _has_formula(code):
                value = _eval_formula(code, meter_values)
            else:
                value = meter_values.get(code, 0.0)

            results.append(
                CollectResult(
                    device_code=code,
                    timestamp=target_hour,
                    value=round(value, 4),
                    unit="m³",
                    raw_data={"meter_values": meter_values},
                )
            )

        return results


async def _fetch_meter_hourly(
    client: httpx.AsyncClient,
    emtrnum: str,
    beg_date: str,
    end_date: str,
    target_hour: datetime,
) -> float:
    """分页获取指定水表数据，筛选目标小时记录并求和 AANALOGFLOW。"""
    total_value = 0.0
    page = 1
    fetched = 0

    while True:
        response = await client.post(
            API_URL,
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
        records = payload.get("syncData", [])
        total_count = int(payload.get("nCount", 0))

        # 筛选目标小时的数据
        for record in records:
            if _record_matches_hour(record, target_hour):
                total_value += float(record.get("AANALOGFLOW", 0))

        fetched += len(records)
        if fetched >= total_count:
            break
        page += 1
        if page > MAX_PAGES:
            logger.warning("水表 %s 分页超过 %d 页，强制停止", emtrnum, MAX_PAGES)
            break

    logger.debug("水表 %s: %d 条记录, 目标小时合计=%.4f", emtrnum, fetched, total_value)
    return total_value


def _extract_json(text: str) -> dict[str, Any]:
    """从 XML 包裹的响应中提取 JSON。"""
    match = re.search(r"<string[^>]*>(.+)</string>", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"无法从智恒 API 响应中提取 JSON 数据: {text[:200]}")
    return json.loads(match.group(1))


def _record_matches_hour(record: dict[str, Any], target_hour: datetime) -> bool:
    """判断记录是否属于目标小时。

    尝试从 record 中提取时间字段（优先 RecordDate，其次 RecordTime）。
    """
    time_str = record.get("RecordDate") or record.get("RecordTime")
    if time_str:
        try:
            # 常见格式: "2026-06-08 09:00:00"
            record_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                # 也可能只有日期 "2026-06-08"
                record_time = datetime.strptime(time_str, "%Y-%m-%d")
            except ValueError:
                return False
        return (
            record_time.year == target_hour.year
            and record_time.month == target_hour.month
            and record_time.day == target_hour.day
            and record_time.hour == target_hour.hour
        )
    return False

"""智能电气系统平台适配器。

从智能电气系统 API 获取指定电气采集点（formulaId）在目标小时的能耗数据。
``platform_device_code`` 支持单个 formulaId 和公式表达式（+/- 组合多采集点）。

API 地址优先使用设备配置中的 ``api_endpoint``，为空时回退到默认地址。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
DEFAULT_API_URL = "http://120.25.153.226:2189/api/calculate"
API_PASSWORD = "cs123456"

# API 要求的时间格式
TIME_FMT = "%Y-%m-%d %H:%M:%S"


class PlatformBAdapter(BasePlatformAdapter):
    """智能电气系统平台适配器。"""

    platform_code = "platform_b"
    platform_name = "智能电气系统"

    async def fetch_energy_data(
        self,
        device_codes: list[str],
        target_hour: datetime,
        api_endpoint: str,
        is_daily: bool = False,
    ) -> list[CollectResult]:
        # 1. 收集所有独立的 formulaId
        all_formula_ids: set[str] = set()
        for code in device_codes:
            all_formula_ids.update(parse_formula_ids(code))

        # 2. 构造时间范围
        if is_daily:
            start_time = target_hour.strftime(TIME_FMT)
            end_time = (target_hour + timedelta(days=1)).strftime(TIME_FMT)
        else:
            start_time = target_hour.strftime(TIME_FMT)
            end_time = (target_hour + timedelta(hours=1)).strftime(TIME_FMT)

        # 3. 确定 API 地址：优先使用设备配置的 api_endpoint
        api_url = resolve_api_url(api_endpoint, DEFAULT_API_URL)

        # 4. 逐个 formulaId 请求 API
        formula_values: dict[str, float] = {}
        formula_errors: set[str] = set()
        async with httpx.AsyncClient(timeout=30.0) as client:
            for fid_str in sorted(all_formula_ids):
                try:
                    formula_values[fid_str] = await _fetch_formula_hourly(
                        client, int(fid_str), start_time, end_time, api_url
                    )
                except Exception:
                    logger.exception(
                        "获取 formulaId %s 数据失败，默认值 0", fid_str
                    )
                    formula_values[fid_str] = 0.0
                    formula_errors.add(fid_str)

        # 所有 formulaId 均失败 → 抛出异常，避免将无效零值写入数据库
        if formula_errors and formula_errors == all_formula_ids:
            raise RuntimeError(
                f"智能电气 API 所有 formulaId 均请求失败，"
                f"跳过本次采集以免写入无效零值。"
                f"失败的 formulaId: {sorted(formula_errors)}"
            )

        # 5. 按公式求值，生成采集结果
        results: list[CollectResult] = []
        for code in device_codes:
            if has_formula(code):
                value = eval_formula(code, formula_values)
            else:
                value = formula_values.get(code, 0.0)

            results.append(
                CollectResult(
                    device_code=code,
                    timestamp=target_hour,
                    value=round(value, 4),
                    raw_data={"formula_values": formula_values},
                )
            )

        return results


async def _fetch_formula_hourly(
    client: httpx.AsyncClient,
    formula_id: int,
    start_time: str,
    end_time: str,
    api_url: str,
) -> float:
    """调用智能电气系统 API 获取指定 formulaId 在时间范围内的能耗值。

    API 返回格式：``{"code": 0, "data": {"data": <float>}}``。
    任何异常均向上抛出，由调用方统一处理（记录日志 + 标记为采集失败）。
    """
    payload = {
        "formulaId": formula_id,
        "startTime": start_time,
        "endTime": end_time,
        "pwd": API_PASSWORD,
    }

    response = await client.post(api_url, json=payload)
    response.raise_for_status()
    body = response.json()

    code = body.get("code")
    if code != 0:
        raise RuntimeError(
            f"智能电气 API 返回异常状态码: formulaId={formula_id}, "
            f"code={code}, msg={body.get('msg', 'N/A')}"
        )

    data = body.get("data", {})
    value = float(data.get("data", 0))
    logger.debug(
        "formulaId %d: %s ~ %s → %.4f",
        formula_id,
        start_time,
        end_time,
        value,
    )
    return value

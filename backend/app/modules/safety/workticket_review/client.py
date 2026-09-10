"""工业互联网安全生产数智化平台工作流客户端（WorkTicketPlatformClient）。

封装「密码登录 → 平台 token → LCP token → 工作流 all-list/detail」的全部 HTTP 调用，
隔离平台接口演变对上层（Parser / Service）的影响。本客户端为只读读取，不修改平台数据。

鉴权流程（参照 .scratch/workticket-review/backend-design.md 第 3 节）：
  1. POST /api/tiji-auth/oauth/token           -> 平台 access_token
  2. GET  /api/tiji-system/wf-api/get-token    -> LCP access_token
  3. 工作流接口统一携带 Blade-Auth(bearer LCP)/Authorization(X-Token 平台token)/Tenant-Id
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── 环境变量加载（与 app/modules/safety/feishu/client.py 完全一致） ──
_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

# ── 平台配置：全部从环境变量读取，禁止在代码中硬编码真实凭据 ──
# 敏感项（USERNAME / PASSWORD_MD5 / AUTH_BASIC）缺失时启动即失败（fail-fast），
# 避免把真实账号/密码/认证头当作默认值写死。
# 非敏感项：BASE_URL 可回退到本机开发地址（不含任何 secret）；TENANT_ID / ORG_CODE 不设回退。
BASE_URL = os.getenv("SAFETY_PLATFORM_BASE_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "http://192.168.5.7:9550"
    logger.warning(
        "SAFETY_PLATFORM_BASE_URL 未设置，使用本机开发地址 %s（仅地址，不含凭据）",
        BASE_URL,
    )

USERNAME = os.getenv("SAFETY_PLATFORM_USERNAME", "")
PASSWORD_MD5 = os.getenv("SAFETY_PLATFORM_PASSWORD_MD5", "")
AUTH_BASIC = os.getenv("SAFETY_PLATFORM_AUTH_BASIC", "")

TENANT_ID = os.getenv("SAFETY_PLATFORM_TENANT_ID", "")
ORG_CODE = os.getenv("SAFETY_PLATFORM_ORG_CODE", "")

def _require_platform_credentials() -> None:
    """敏感凭据缺失时 fail-fast，并给出清晰配置提示。"""
    missing = [
        name
        for name, val in (
            ("SAFETY_PLATFORM_USERNAME", USERNAME),
            ("SAFETY_PLATFORM_PASSWORD_MD5", PASSWORD_MD5),
            ("SAFETY_PLATFORM_AUTH_BASIC", AUTH_BASIC),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            "作业票审核平台敏感凭据未配置，请在环境变量中设置以下一项或多项："
            + "、".join(missing)
            + "。示例：SAFETY_PLATFORM_USERNAME=<用户名>、"
            "SAFETY_PLATFORM_PASSWORD_MD5=<密码MD5>、"
            "SAFETY_PLATFORM_AUTH_BASIC=<Basic认证头（Base64(用户名:密钥)）>。"
        )

# 若 AUTH_BASIC 配置为原始 username:secret（而非 base64），则自动编码
if AUTH_BASIC and ":" in AUTH_BASIC:
    AUTH_BASIC = base64.b64encode(AUTH_BASIC.encode("utf-8")).decode("ascii")

if not TENANT_ID:
    logger.debug("SAFETY_PLATFORM_TENANT_ID 未设置（非敏感项，允许留空）")
if not ORG_CODE:
    logger.debug("SAFETY_PLATFORM_ORG_CODE 未设置（非敏感项，允许留空）")

# ── 8 类标准作业票：ticket_type -> processDefinitionKey（来自 作业票字段映射.md） ──
TICKET_TYPE_KEYS: dict[str, str] = {
    "hot_work": "process_fBEAziWfaLrFGrtAbdFmaCkNTZY8N8yz",
    "confined_space": "process_S3chZ3frZh8AXNbs5aS7gCAzkBg6LCEF",
    "height_work": "process_hxcEeLcyXyhxPGHeTXFJLSrrTpGFBKhP",
    "lifting": "process_2SJxGs5Lb83cntAFCiB4JMrhAbGjzJdr",
    "temporary_electricity": "process_pCQkxX37ntkwsFPzr6MJWBT84ZXXkSt8",
    "excavation": "process_anh48SaGtAKr76e2wwb4c5ttwE8ENsT4",
    "road_breaking": "process_wS8HtBQGJ8cCnmLBTKit35bdsLX8tWEp",
    "blind_plate": "process_mjkwy66WYB3Jk8xYZi2HAST6WYc8pMR2",
}

# 保持稳定顺序的 (type, key) 列表
STANDARD_TICKET_TYPES: list[tuple[str, str]] = list(TICKET_TYPE_KEYS.items())

_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_MAX_RETRIES = 3
_RETRY_STATUS = {500, 502, 503, 504}


def _to_asia_date(value: Any) -> date | None:
    """把 createTime（str / datetime / 时间戳）转为 Asia/Shanghai 日期。"""
    if value is None:
        return None
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1_000_000_000_000:  # 毫秒
            ts = ts / 1000.0
        dt = datetime.fromtimestamp(ts, tz=ZoneInfo("Asia/Shanghai"))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(text, fmt)
                except ValueError:
                    continue
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    if dt is None:
        return None
    return dt.astimezone(ZoneInfo("Asia/Shanghai")).date()


def _pick_list(value: Any) -> list[Any]:
    """从 all-list 响应中尽力抽取记录列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("records", "list", "rows", "content", "data"):
            got = value.get(key)
            if isinstance(got, list):
                return got
            if isinstance(got, dict):
                nested = _pick_list(got)
                if nested:
                    return nested
        # data 可能是 dict 里再包一层
        inner = value.get("data")
        if isinstance(inner, dict):
            return _pick_list(inner)
        if isinstance(inner, list):
            return inner
    return []


def _record_entry(ticket_type: str, record: dict[str, Any]) -> dict[str, Any]:
    """把 all-list 原始记录归一化为统一结构化 dict（与 list_tickets_for_date 一致）。"""
    pid = (
        record.get("processInstanceId")
        or record.get("processInstanceID")
        or record.get("id")
    )
    variables = record.get("variables") or record.get("formVariables") or {}
    serial_number = str(
        record.get("serialNumber")
        or record.get("serialNo")
        or record.get("businessKey")
        or record.get("ticketNo")
        or record.get("processInstanceCode")
        or (
            variables.get("serialNumber")
            if isinstance(variables, dict)
            else None
        )
        or ""
    )
    return {
        "type": ticket_type,
        "processInstanceId": pid,
        "serialNumber": serial_number,
        "createTime": record.get("createTime"),
        "endTime": record.get("endTime") or record.get("finishTime"),
        "status": record.get("status"),
        "variables": variables,
        "raw": record,
    }


def _serial_contains_window_date(
    serial_number: str,
    start_date: date,
    end_date: date,
) -> bool:
    """serialNumber 是否含窗口内任一日期（iso 如 2026-08-26，或紧凑如 20260826）。"""
    day = start_date
    while day <= end_date:
        if day.isoformat() in serial_number or day.strftime("%Y%m%d") in serial_number:
            return True
        day += timedelta(days=1)
    return False


def _extract_access_token(body: Any) -> str:
    """从 token 响应中抽取 access_token。"""
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            token = data.get("access_token") or data.get("token")
            if token:
                return str(token)
        tok = body.get("access_token") or body.get("token")
        if tok:
            return str(tok)
        if isinstance(data, str):
            return data
    raise RuntimeError(f"平台 token 响应缺少 access_token: {body!r}")


class WorkTicketPlatformClient:
    """工业互联网安全生产数智化平台工作流客户端（只读）。"""

    def __init__(
        self,
        session: httpx.AsyncClient | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        _require_platform_credentials()
        self._client = session
        self._owns_client = session is None
        self._timeout = timeout or _HTTP_TIMEOUT
        self._platform_token: str | None = None
        self._lcp_token: str | None = None

    async def __aenter__(self) -> WorkTicketPlatformClient:
        await self._get_client()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """关闭自建的连接；外部注入的 session 由调用方负责关闭。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    json=json_body,
                )
                if resp.status_code in _RETRY_STATUS and attempt < _MAX_RETRIES:
                    wait = 0.5 * attempt
                    logger.warning(
                        "平台接口 %s 返回 %s，%s 后重试 (%s/%s)",
                        url,
                        resp.status_code,
                        wait,
                        attempt,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue
                # 非 2xx：抛清晰异常
                if resp.status_code >= 400:
                    body_snippet = resp.text[:500]
                    raise RuntimeError(
                        f"平台接口调用失败 {method} {url} -> HTTP {resp.status_code}: "
                        f"{body_snippet}"
                    )
                return cast(dict[str, Any], resp.json())
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning("平台接口超时 %s，%s 秒后重试 (%s/%s)", url, attempt, attempt, _MAX_RETRIES)
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"平台接口超时 {method} {url}: {exc}") from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning("平台接口网络错误 %s (%s)，重试 (%s/%s)", url, exc, attempt, _MAX_RETRIES)
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"平台接口网络错误 {method} {url}: {exc}") from exc
        raise RuntimeError(f"平台接口请求失败 {method} {url}: {last_exc!r}")

    async def get_platform_token(self) -> str:
        """密码登录获取平台 access_token。"""
        url = f"{BASE_URL}/api/tiji-auth/oauth/token"
        headers = {
            "Tenant-Id": TENANT_ID,
            "Authorization": f"Basic {AUTH_BASIC}",
        }
        form = {
            "tenantId": TENANT_ID,
            "username": USERNAME,
            "password": PASSWORD_MD5,
            "grant_type": "password",
            "scope": "all",
            "type": "account",
            "hideErrorMsg": "true",
        }
        if ORG_CODE:
            form["org_code"] = ORG_CODE
        body = await self._request_json("POST", url, headers=headers, data=form)
        token = _extract_access_token(body)
        logger.info("平台 access_token 获取成功（len=%d）", len(token))
        return token

    async def get_lcp_token(self, platform_token: str) -> str:
        """用平台 access_token 换取 LCP token（工作流引擎 token）。"""
        url = f"{BASE_URL}/api/tiji-system/wf-api/get-token"
        headers = {
            "Authorization": f"bearer {platform_token}",
            "Blade-Auth": f"bearer {platform_token}",
            "X-Token": f"bearer {platform_token}",
            "Tenant-Id": TENANT_ID,
        }
        body = await self._request_json("GET", url, headers=headers)
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            token = data.get("access_token") or data.get("token")
        else:
            token = data
        if not token:
            raise RuntimeError(f"LCP token 响应缺少 access_token: {body!r}")
        logger.info("LCP token 获取成功（len=%d）", len(str(token)))
        return str(token)

    async def _ensure_tokens(self) -> tuple[str, str]:
        """获取（并缓存）平台 token + LCP token。"""
        if self._lcp_token and self._platform_token:
            return self._platform_token, self._lcp_token
        pt = self._platform_token or await self.get_platform_token()
        self._platform_token = pt
        lcp = self._lcp_token or await self.get_lcp_token(pt)
        self._lcp_token = lcp
        return pt, lcp

    def _workflow_headers(self, platform_token: str, lcp_token: str) -> dict[str, str]:
        """工作流接口统一请求头（兼容设计文档与实测两种写法）。"""
        return {
            "Blade-Auth": f"bearer {lcp_token}",
            "Authorization": f"X-Token {platform_token}",
            "X-Token": platform_token,
            "Tenant-Id": TENANT_ID,
        }

    async def detail(self, process_instance_id: str) -> Any:
        """拉取单个流程实例详情（containForm=true）。返回平台 data 字段。"""
        pt, lcp = await self._ensure_tokens()
        url = f"{BASE_URL}/api/tiji-workflow/process-inst-ext/detail"
        headers = self._workflow_headers(pt, lcp)
        params = {"processInstanceId": process_instance_id, "containForm": "true"}
        body = await self._request_json("GET", url, headers=headers, params=params)
        if isinstance(body, dict):
            data = body.get("data")
            if data is not None:
                return data
        return body

    async def _enrich_records_with_detail(
        self,
        records: list[dict[str, Any]],
        *,
        concurrency: int = 5,
    ) -> None:
        """为命中记录补全 detail 接口的 process.variables。

        detail 返回的 data.process.variables 含审批/开始/结束/完工验收/气体分析等
        all-list 顶层未暴露的字段（实测 74 键）。每条记录仅在 detail 成功后合并，
        detail 失败时保留原 variables（该票后续走数据不足）。并发受 semaphore 限制。
        """
        sem = asyncio.Semaphore(concurrency)

        async def enrich(record: dict[str, Any]) -> None:
            pid = (
                record.get("processInstanceId")
                or record.get("processInstanceID")
                or record.get("id")
            )
            if not pid:
                logger.warning(
                    "跳过 detail：记录缺少 processInstanceId: %s",
                    record.get("serialNumber") or record.get("serialNo") or "",
                )
                return
            try:
                detail_data = await self.detail(str(pid))
            except Exception as exc:
                logger.warning(
                    "detail 拉取失败 processInstanceId=%s: %s",
                    pid,
                    exc,
                )
                return

            detail_vars: dict[str, Any] | None = None
            if isinstance(detail_data, dict):
                process = detail_data.get("process")
                if isinstance(process, dict):
                    candidate = process.get("variables")
                    if isinstance(candidate, dict):
                        detail_vars = candidate
                if detail_vars is None:
                    # 兜底：data 本身即含扁平 variables（兼容不同返回结构）
                    candidate = detail_data.get("variables")
                    if isinstance(candidate, dict):
                        detail_vars = candidate
            if not detail_vars:
                logger.warning(
                    "detail 未找到 process.variables processInstanceId=%s",
                    pid,
                )
                return

            current = record.get("variables")
            if not isinstance(current, dict):
                current = {}
            record["variables"] = {**current, **detail_vars}

            # 保留 detail 原始返回（含 process.variables）便于溯源。
            raw = record.get("raw")
            if isinstance(raw, dict):
                raw["detail"] = detail_data
            else:
                record["raw"] = record

        async def guarded(record: dict[str, Any]) -> None:
            async with sem:
                await enrich(record)

        if records:
            await asyncio.gather(*(guarded(r) for r in records))

    async def list_tickets_for_date(self, target_date: date) -> list[dict[str, Any]]:
        """按日期拉取 8 类标准作业票原始记录。

        返回 list[dict]，每个 dict 含：
          type / processInstanceId / serialNumber / createTime / endTime / status / variables / raw
        过滤规则：createTime（Asia/Shanghai）日期 == target_date，或 serialNumber 含目标日期。
        """
        pt, lcp = await self._ensure_tokens()
        headers = self._workflow_headers(pt, lcp)
        date_str = target_date.isoformat()          # 2026-08-26
        compact_date = target_date.strftime("%Y%m%d")  # 20260826

        results: list[dict[str, Any]] = []
        for ticket_type, process_key in STANDARD_TICKET_TYPES:
            url = f"{BASE_URL}/api/tiji-workflow/process-inst-ext/all-list"
            params = {
                "processDefinitionKey": process_key,
                "current": 1,
                "size": 1000,
            }
            try:
                body = await self._request_json("GET", url, headers=headers, params=params)
            except Exception as exc:
                raise RuntimeError(
                    f"拉取 {ticket_type}（{process_key}）作业票列表失败: {exc}"
                ) from exc

            data = body.get("data") if isinstance(body, dict) else body
            for record in _pick_list(data):
                pid = (
                    record.get("processInstanceId")
                    or record.get("processInstanceID")
                    or record.get("id")
                )
                variables = record.get("variables") or record.get("formVariables") or {}
                serial_number = str(
                    record.get("serialNumber")
                    or record.get("serialNo")
                    or record.get("businessKey")
                    or record.get("ticketNo")
                    or record.get("processInstanceCode")
                    or (
                        variables.get("serialNumber")
                        if isinstance(variables, dict)
                        else None
                    )
                    or ""
                )
                create_time = record.get("createTime")
                create_date = _to_asia_date(create_time)

                # 命中条件：创建日期匹配 或 票号含日期
                if create_date != target_date and not (
                    date_str in serial_number or compact_date in serial_number
                ):
                    continue

                results.append(
                    {
                        "type": ticket_type,
                        "processInstanceId": pid,
                        "serialNumber": serial_number,
                        "createTime": create_time,
                        "endTime": record.get("endTime") or record.get("finishTime"),
                        "status": record.get("status"),
                        "variables": variables,
                        "raw": record,
                    }
                )
        await self._enrich_records_with_detail(results)

        logger.info(
            "按日期 %s 拉取标准作业票共 %d 条",
            date_str,
            len(results),
        )
        return results

    async def list_tickets_for_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """按日期范围拉取 8 类标准作业票原始记录（含 detail 富化）。

        返回 list[dict]，每个 dict 含：
          type / processInstanceId / serialNumber / createTime / endTime / status / variables / raw
        过滤规则：createTime（Asia/Shanghai）日期 ∈ [start_date, end_date]，
        或 serialNumber 含窗口内任一日期（iso 或紧凑格式）；窗口内记录按
        processInstanceId 去重（保留首次出现）；最后统一做一次 detail 富化
        （复用 _enrich_records_with_detail，避免逐类重复请求）。
        """
        if end_date < start_date:
            logger.info(
                "日期范围无效（end < start），返回空列表：%s ~ %s",
                start_date,
                end_date,
            )
            return []

        pt, lcp = await self._ensure_tokens()
        headers = self._workflow_headers(pt, lcp)

        results: list[dict[str, Any]] = []
        seen_pids: set[str] = set()
        for ticket_type, process_key in STANDARD_TICKET_TYPES:
            url = f"{BASE_URL}/api/tiji-workflow/process-inst-ext/all-list"
            params = {
                "processDefinitionKey": process_key,
                "current": 1,
                "size": 1000,
            }
            try:
                body = await self._request_json("GET", url, headers=headers, params=params)
            except Exception as exc:
                raise RuntimeError(
                    f"拉取 {ticket_type}（{process_key}）作业票列表失败: {exc}"
                ) from exc

            data = body.get("data") if isinstance(body, dict) else body
            for record in _pick_list(data):
                entry = _record_entry(ticket_type, record)
                create_date = _to_asia_date(record.get("createTime"))
                if not (
                    create_date is not None
                    and start_date <= create_date <= end_date
                ) and not _serial_contains_window_date(
                    entry["serialNumber"], start_date, end_date
                ):
                    continue
                pid = entry["processInstanceId"]
                if pid is not None:
                    pid_key = str(pid)
                    if pid_key in seen_pids:
                        logger.info(
                            "范围拉取去重：processInstanceId=%s 已存在",
                            pid_key,
                        )
                        continue
                    seen_pids.add(pid_key)
                results.append(entry)

        await self._enrich_records_with_detail(results)

        logger.info(
            "按日期范围 %s ~ %s 拉取标准作业票共 %d 条",
            start_date.isoformat(),
            end_date.isoformat(),
            len(results),
        )
        return results


__all__ = [
    "BASE_URL",
    "USERNAME",
    "PASSWORD_MD5",
    "TENANT_ID",
    "ORG_CODE",
    "AUTH_BASIC",
    "TICKET_TYPE_KEYS",
    "STANDARD_TICKET_TYPES",
    "WorkTicketPlatformClient",
]

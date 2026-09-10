"""人员持证台账 Bitable 镜像 — 纯映射 + 配置中心 store 连接。

监听三个飞书 Bitable 表的变更，实时镜像到平台 safety.person_certificates：

- 特种作业证表（wiki 文档 app_token）：cert/special_op
- 监护人 A 证表（base 文档 app_token）：cert/guardian_a
- 监护人 B 证表（同 base 文档）：cert/guardian_b

监护人 A/B 证分表（不在同一表，由 table_id 区分），cert_category 由 table_id 决定。
连接配置从配置中心 store 读取（延迟读取 + 同步缓存，改表 ID → 新事件进新表）。

本模块只负责：
  - (app_token, table_id) → kind 反查（table_kind_by_id）
  - 字段映射纯函数（map_special_op_cert_fields / map_guardian_cert_fields）

纯数据映射，无副作用（不触发 AI / 通知 / 状态流转）。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu import bitable_handler as bh  # _ms_to_datetime
from app.modules.safety.feishu import oh_bitable_handler as oh  # _rich / _text

logger = logging.getLogger(__name__)


def cert_tables() -> dict[str, tuple[str, str]]:
    """kind → (app_token, table_id)（special_op/guardian_a/guardian_b），仅启用连接。"""
    return {
        v.kind: (v.app_token, v.table_id)
        for v in store.get_connections("cert")
        if v.app_token and v.table_id
    }


def table_kind_by_id(table_id: str) -> str | None:
    """按 table_id 反查 kind（special_op / guardian_a / guardian_b）。

    注：监护人 A/B 证分表，table_id 全局唯一，可直接按 table_id 区分；
    特种作业证 wiki 文档的 table_id 与 base 文档不冲突。
    """
    for kind, (_app, tid) in cert_tables().items():
        if table_id and table_id == tid:
            return kind
    return None


def app_token_for_kind(kind: str) -> str:
    """返回 kind 对应的 app_token（事件回源拉记录用）。"""
    pair = cert_tables().get(kind)
    return pair[0] if pair else ""


# ── 值提取辅助（复用 feishu/bitable_handler.py / oh_bitable_handler.py 已有函数）──


def _rich(value: Any) -> str:
    """富文本 / 公式包装 / 普通字符串统一提取纯文本。"""
    return oh._rich(value)


def _text(value: Any) -> str:
    """文本 / 单选 / 字符串数组统一提取。"""
    return oh._text(value)


def _ms(value: Any) -> date | None:
    """DateTime 字段（毫秒时间戳）→ date。"""
    dt = bh._ms_to_datetime(value)
    return dt.date() if dt else None


def _person_name(value: Any) -> str:
    """从 Bitable 人员字段提取姓名（list[{'name': ...}] 或新格式 {'users': [...]}）。"""
    info = bh._extract_person_info(value)
    return info.get("name", "")


def _select(value: Any) -> str:
    """单选字段 → 纯文本。"""
    return bh._extract_select_values(value)


# ── 字段映射 ──


def map_special_op_cert_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """特种作业证表（wiki 文档）→ PersonCertificate dict。

    真实字段（2026-08-21 实测 214 条记录）：
      姓名(list[rich]) / 姓名(人员)(person) / 部门(list[rich]) / 作业类别(single) /
      项目(single) / 证件编号(list[rich]) / 再复审时间(date ms) / 取证日期(date ms) /
      复审频次(single)
    """
    # 姓名：优先用人员字段的姓名（带 open_id 可后续通知），fallback 富文本姓名
    name = _person_name(fields.get("姓名 (人员 )")) or _rich(fields.get("姓名"))
    if not name:
        logger.warning(
            "持证(特种作业证)记录无姓名，跳过: fields=%s", list(fields.keys())[:8]
        )
        return None
    mapped: dict[str, Any] = {
        "cert_category": "special_op",
        "person_name": name,
        "department": _rich(fields.get("部门")) or None,
        "operation_type": _select(fields.get("作业类别")) or None,
        "project": _select(fields.get("项目")) or None,
        "certificate_no": _rich(fields.get("证件编号")) or None,
        "issue_date": _ms(fields.get("取证日期")),
        "next_review_date": _ms(fields.get("再复审时间")),
        "review_frequency": _select(fields.get("复审频次")) or None,
    }
    return mapped


def map_guardian_cert_fields(fields: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """监护人 A/B 证表（base 文档，分表）→ PersonCertificate dict。

    kind 决定 cert_category（guardian_a / guardian_b）。
    真实字段（2026-08-21 实测 A 证 188 条 / B 证 154 条）：
      姓名(person) / 部门(list[str]) / 证件类型(single: A证/B证) /
      取证日期(date ms) / 第一次复审截止日期(date ms) /
      第二次复审截止日期(date ms) / 应换证日期(date ms) / 已换证日期(date ms)
    """
    name = _person_name(fields.get("姓名"))
    if not name:
        logger.warning(
            "持证(%s)记录无姓名，跳过: fields=%s", kind, list(fields.keys())[:8]
        )
        return None
    # 部门是 list[str]，取第一项
    dept_raw = fields.get("部门")
    if isinstance(dept_raw, list) and dept_raw:
        dept = str(dept_raw[0]) if dept_raw[0] else None
    else:
        dept = _text(dept_raw) or None
    mapped: dict[str, Any] = {
        "cert_category": kind,  # guardian_a / guardian_b
        "person_name": name,
        "department": dept,
        "issue_date": _ms(fields.get("取证日期")),
        "first_review_deadline": _ms(fields.get("第一次复审截止日期")),
        "second_review_deadline": _ms(fields.get("第二次复审截止日期")),
        "should_renew_date": _ms(fields.get("应换证日期")),
        "renewed_date": _ms(fields.get("已换证日期")),
        # 证件类型字段值（A证/B证）与 kind 一致，冗余但保留以便核对
        "notes": _select(fields.get("证件类型")) or None,
    }
    return mapped


# ── 文档事件订阅（飞书要求必须先调用 subscribe，Bitable 事件才会推送）──


async def ensure_cert_bitable_subscribed() -> bool:
    """订阅持证台账 2 个唯一 app_token 的文档事件。

    cert 域 3 张表共享 2 个文档：
      - special_op 特种作业证：独立 wiki app_token（VyYmwLlZsi2sXDkkIa6cEISsnpg）
      - guardian_a / guardian_b 监护人 A/B 证：共用 base app_token
        （QNKibNfd2aIxSEsvWaJc13G6nCb），按 table_id 分表
    app_token 从配置中心 store 读取（``store.get_connection("cert", kind)``），
    启用且非空才订阅，去重后最多 2 次调用。全部成功返回 True。
    """
    from app.modules.safety.bitable_config.store import store

    app_tokens: list[str] = []
    for kind in ("special_op", "guardian_a", "guardian_b"):
        conn = store.get_connection("cert", kind)
        if conn is None or not conn.enabled:
            continue
        if conn.app_token and conn.app_token not in app_tokens:
            app_tokens.append(conn.app_token)

    if not app_tokens:
        logger.info("持证台账 Bitable app_token 未配置，跳过文档事件订阅")
        return False

    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        all_ok = True
        async with httpx.AsyncClient(timeout=15) as http:
            for app_token in app_tokens:
                resp = await http.post(
                    f"https://open.feishu.cn/open-apis/drive/v1/files/{app_token}/subscribe",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"file_type": "bitable"},
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(
                        "持证台账 Bitable 文档事件订阅成功: file_token=%s", app_token
                    )
                else:
                    all_ok = False
                    logger.error(
                        "持证台账 Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                        data.get("code"), data.get("msg"), app_token,
                    )
        return all_ok
    except Exception:
        logger.exception("持证台账 Bitable 文档事件订阅异常")
        return False

"""HR 模块暴露给 AI Agent 的 MCP Tools：员工本人证件查询（配合 dazah-agent 机器人）。

一线工人无平台账号，身份以飞书 open_id 为准（hr.employees.feishu_open_id，
由员工信息表「员工账号」列同步）。证件号码输出脱敏；原件按归属校验后
以 base64 返回（机器人侧转文件/图片发送）。
"""

from __future__ import annotations

import base64

from fastmcp.tools.base import ToolResult
from sqlalchemy import select

from app.core.file_storage import read_object
from app.modules.hr.employee_certificate_service import (
    RESOURCE_TYPE,
    _serialize,
    mask_certificate_no,
)
from app.modules.hr.models import Employee, EmployeeCertificate
from app.platform.mcp.deps import get_db
from app.platform.mcp.server import get_module_mcp

mcp = get_module_mcp("hr")

_MODULE = "hr"


async def _resolve_employee_by_open_id(open_id: str) -> Employee:
    """open_id → 员工档案（员工账号列同步的 feishu_open_id）。"""
    db = get_db()
    employee = (await db.execute(
        select(Employee).where(
            Employee.feishu_open_id == open_id,
            Employee.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("未在员工档案中找到该飞书账号对应的员工（需员工信息表「员工账号」列已同步）")
    return employee


@mcp.tool()
async def list_my_certificates(open_id: str) -> ToolResult:
    """
    查询本人已归档的电子证件清单（当前版本）。

    一线员工查自己有哪些证件已归档、缺哪些待补交（按应交清单配置）。
    证件号码部分隐藏；原件内容请用 get_my_certificate_file 获取。

    Args:
        open_id: 员工本人飞书 open_id（机器人从消息上下文获得）
    """
    try:
        db = get_db()
        employee = await _resolve_employee_by_open_id(open_id)
        certs = (await db.execute(
            select(EmployeeCertificate).where(
                EmployeeCertificate.employee_id == employee.id,
                EmployeeCertificate.is_current.is_(True),
                EmployeeCertificate.is_deleted.is_(False),
            ).order_by(EmployeeCertificate.category)
        )).scalars().all()

        from app.modules.hr.employee_certificate_service import _required_categories

        required = await _required_categories(db, employee.is_key_position)
        has = {c.category for c in certs}
        missing = [cat for cat in sorted(required - has)]

        lines = [f"{employee.name} 的证件档案（共 {len(certs)} 份在档）："]
        for c in certs:
            label = EmployeeCertificate.CATEGORY_LABELS.get(c.category, c.category)
            expiry = "长期有效" if c.is_permanent else (
                f"有效期至 {c.expiry_date}" if c.expiry_date else "未登记有效期"
            )
            lines.append(
                f"  - {label}：{c.certificate_name or '—'}（{expiry}，证号 {mask_certificate_no(c.certificate_no) or '—'}）"
            )
        if missing:
            labels = "、".join(EmployeeCertificate.CATEGORY_LABELS.get(c, c) for c in missing)
            lines.append(f"待补交（应交未交）：{labels}")
        else:
            lines.append("应交证件已齐全。")

        return ToolResult(
            content="\n".join(lines),
            structured_content={
                "employee_name": employee.name,
                "certificates": [_serialize(c) for c in certs],
                "missing_categories": missing,
            },
        )
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)


@mcp.tool()
async def get_my_certificate_file(open_id: str, certificate_id: str) -> ToolResult:
    """
    获取本人某份证件的原件文件（base64，机器人侧转为图片/文件发送）。

    仅可获取本人名下的证件；调阅会记录审计日志。

    Args:
        open_id: 员工本人飞书 open_id
        certificate_id: 证件记录 ID（来自 list_my_certificates 的结果）
    """
    import uuid as uuid_mod

    try:
        employee = await _resolve_employee_by_open_id(open_id)
        db = get_db()
        cert = (await db.execute(
            select(EmployeeCertificate).where(
                EmployeeCertificate.id == uuid_mod.UUID(certificate_id),
                EmployeeCertificate.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if cert is None or cert.employee_id != employee.id:
            return ToolResult(
                content="证件不存在或不属于本人，无法获取。",
                structured_content={"error": "not_found_or_forbidden"},
                is_error=True,
            )

        obj = read_object(_MODULE, cert.storage_key)
        if obj is None:
            return ToolResult(
                content="证件原件文件缺失，请联系人事重新上传。",
                structured_content={"error": "file_missing"},
                is_error=True,
            )
        data, _ = obj
        # 本人调阅留审计（user_id 为空 = Agent 通道，extra 记录员工身份）
        from app.platform.audit.service import record_audit_log

        await record_audit_log(
            db, action="certificate_view_self", resource_type=RESOURCE_TYPE,
            resource_id=cert.id,
            extra={
                "employee_id": str(employee.id),
                "employee_name": employee.name,
                "category": cert.category,
                "version_no": cert.version_no,
                "channel": "mcp_self",
            },
        )
        await db.commit()

        label = EmployeeCertificate.CATEGORY_LABELS.get(cert.category, cert.category)
        return ToolResult(
            content=f"{employee.name} 的{label}原件（{cert.filename}，{cert.content_type}）。",
            structured_content={
                "certificate_id": str(cert.id),
                "filename": cert.filename,
                "content_type": cert.content_type,
                "size": cert.size,
                "data_base64": base64.b64encode(data).decode("ascii"),
            },
        )
    except ValueError as e:
        return ToolResult(content=str(e), structured_content={"error": str(e)}, is_error=True)

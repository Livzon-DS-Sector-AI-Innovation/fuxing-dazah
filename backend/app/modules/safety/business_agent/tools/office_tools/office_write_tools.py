"""办公写入工具（创建/生成/上传/权限/回滚）。"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.business_agent.tools.office_tools._common import (
    _result_to_dict,
)
from app.modules.safety.business_agent.tools.office_tools.office_scenarios import (
    _generate_docx,
    _generate_pdf,
    build_report_docx_blocks,
)
from app.modules.safety.feishu.office_client import OfficeResult, get_office_client

logger = logging.getLogger(__name__)


def _join_message(*parts: str | None) -> str | None:
    """合并多条面向用户的提示信息，空值跳过。"""
    text = "；".join(p for p in parts if p)
    return text or None


def _attach_rollback_handle(
    result: OfficeResult,
    handle: dict[str, Any],
) -> OfficeResult:
    """把回滚句柄挂到结果 meta，供 rollback_office_file 读取。"""
    if result.kind == "error":
        return result
    result.meta = dict(result.meta or {})
    result.meta["rollback"] = handle
    if handle.get("rollback_type") == "no_rollback":
        result.meta["no_rollback"] = True
    return result


async def _grant_creator_manage(
    ctx: RunContext[SafetyDeps],
    result: OfficeResult,
) -> OfficeResult:
    """创建/上传成功后，把文件管理权限授予发起人（deps.person）。

    - person 为空（Web 端匿名）→ 跳过授权并降级告警；
    - set_permission 失败不改变整体 result.kind，只补充 message 提示。
    """
    if result.kind != "link" or not result.file_token:
        return result

    person = ctx.deps.person
    open_id = getattr(person, "open_id", None)
    if not open_id:
        logger.warning(
            "office 工具跳过发起人管理权限授予：person=%r 无 open_id",
            person,
        )
        result.message = _join_message(
            result.message, "无法授权发起人（Web 端匿名）",
        )
        return result

    client = get_office_client(ctx)
    try:
        grant = await client.set_permission(result.file_token, [open_id], "manage")
        if grant.kind == "error":
            result.message = _join_message(
                result.message,
                f"发起人管理权限授予失败：{grant.error}",
            )
        else:
            result.message = _join_message(
                result.message,
                f"已将管理权限授予发起人 {getattr(person, 'name', '')}",
            )
    except NotImplementedError:
        result.message = _join_message(
            result.message, "发起人管理权限授予暂未实现",
        )
    except Exception as exc:
        logger.warning("office 工具授予发起人管理权限失败: %s", exc)
        result.message = _join_message(
            result.message,
            f"发起人管理权限授予失败：{type(exc).__name__}: {exc}",
        )
    return result


async def office_create_docx(
    ctx: RunContext[SafetyDeps],
    title: str,
    folder_token: str | None = None,
    blocks: list[dict] | None = None,
    markdown_report: str | None = None,
) -> dict:
    """在飞书新建一篇云文档，并返回可编辑链接。

    创建成功后自动把当前发起人（飞书端真实身份）授予该文档的管理权限；
    Web 端匿名用户会跳过授权并提示。

    场景模板「日报 → 飞书云文档 → 推群」：把日报/报表工具返回的
    markdown_report 直接作为 markdown_report 传入，工具会先用
    build_report_docx_blocks 转成 docx blocks 再创建云文档。
    若同时传 blocks 与 markdown_report，markdown_report 优先（会覆盖 blocks）。

    Args:
        title: 云文档标题（必填）
        folder_token: 目标云空间文件夹 token（可选，不传放应用根目录）
        blocks: 飞书 docx 内容块列表（可选；不传且无 markdown_report 时建空文档）
        markdown_report: Markdown 日报/报表正文（可选；自动转 blocks）

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    if markdown_report is not None:
        blocks = build_report_docx_blocks(title, markdown_report)

    client = get_office_client(ctx)
    result = await client.create_docx(
        title, folder_token=folder_token, blocks=blocks,
    )
    result = await _grant_creator_manage(ctx, result)
    result = _attach_rollback_handle(
        result,
        {"rollback_type": "delete", "token": result.file_token},
    )
    return _result_to_dict(result, "创建云文档")


async def office_create_sheet(
    ctx: RunContext[SafetyDeps],
    title: str,
    folder_token: str | None = None,
    rows: list[list] | None = None,
) -> dict:
    """在飞书新建电子表格，可选写入初始数据，并返回可编辑链接。

    创建成功后自动把当前发起人授予该表格的管理权限；Web 端匿名用户跳过授权。
    rows 为二维数组，第一行通常是表头。

    Args:
        title: 电子表格标题（必填）
        folder_token: 目标云空间文件夹 token（可选）
        rows: 二维数组数据（可选，如 [["姓名","部门"],["张三","生产部"]]）

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    client = get_office_client(ctx)
    result = await client.create_sheet(
        title, folder_token=folder_token, rows=rows,
    )
    result = await _grant_creator_manage(ctx, result)
    result = _attach_rollback_handle(
        result,
        {"rollback_type": "delete", "token": result.file_token},
    )
    return _result_to_dict(result, "创建电子表格")


async def office_write_sheet(
    ctx: RunContext[SafetyDeps],
    spreadsheet_token: str,
    sheet_range: str,
    values: list[list],
) -> dict:
    """向既有飞书电子表格指定区域写入值。

    修改既有文件属高风险写操作，会走人审确认；工具会原样覆盖目标区域，
    请先确认 range 与 values 行列匹配。

    Args:
        spreadsheet_token: 电子表格 token（sheets 链接路径中的 token）
        sheet_range: 写入区域（如 "Sheet1!A1:D10"）
        values: 二维数组，与 range 行列一致

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    client = get_office_client(ctx)
    snapshot_rows = len(values) or 1
    snapshot_cols = max((len(row) for row in values), default=1)
    snapshot_result = await client.read_sheet(
        spreadsheet_token,
        sheet_range,
        max_rows=snapshot_rows,
        max_cols=snapshot_cols,
    )
    result = await client.write_sheet(
        spreadsheet_token, sheet_range, values,
    )

    if snapshot_result.kind == "error":
        rollback = {
            "rollback_type": "no_rollback",
            "token": spreadsheet_token,
            "reason": f"原值快照读取失败：{snapshot_result.error}",
        }
    else:
        rollback = {
            "rollback_type": "write_sheet",
            "token": spreadsheet_token,
            "range": sheet_range,
            "values": snapshot_result.content,
        }
    result = _attach_rollback_handle(result, rollback)
    return _result_to_dict(result, "写入电子表格")


async def office_create_base(
    ctx: RunContext[SafetyDeps],
    title: str,
    folder_token: str | None = None,
    tables: list[dict] | None = None,
) -> dict:
    """在飞书新建多维表格（Bitable），可选建表/字段，并返回可编辑链接。

    创建成功后自动把当前发起人授予该多维表格的管理权限；Web 端匿名用户跳过授权。
    tables 可传入 [{name, fields: [{field_name, type}]}]，字段 type 使用飞书
    Bitable 字段类型枚举（1=多行文本）。

    Args:
        title: 多维表格标题（必填）
        folder_token: 目标云空间文件夹 token（可选）
        tables: 数据表定义（可选，不传建空多维表格）

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    client = get_office_client(ctx)
    result = await client.create_base(
        title, folder_token=folder_token, tables=tables,
    )
    result = await _grant_creator_manage(ctx, result)
    result = _attach_rollback_handle(
        result,
        {"rollback_type": "delete", "token": result.file_token},
    )
    return _result_to_dict(result, "创建多维表格")


async def office_create_slides(
    ctx: RunContext[SafetyDeps],
    title: str,
    folder_token: str | None = None,
    content: list[dict] | str | None = None,
    template: str | None = None,
) -> dict:
    """在飞书新建幻灯片（PPT），生成含页内容的幻灯片并返回可编辑链接。

    content 支持 list[dict]（每页 {title, body?}，body 可为多行字符串或列表）
    或 markdown 字符串；不传 content 时创建空白幻灯片。创建成功后自动把当前
    发起人授予该幻灯片的管理权限。

    Args:
        title: 幻灯片标题（必填）
        folder_token: 目标云空间文件夹 token（可选）
        content: 幻灯片内容定义（可选，list[dict] 或 markdown）
        template: 幻灯片模板 token（可选，本期预留，未展开模板导入）

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    client = get_office_client(ctx)
    result = await client.create_slides(
        title,
        folder_token=folder_token,
        content=content,
        template=template,
    )
    result = await _grant_creator_manage(ctx, result)
    result = _attach_rollback_handle(
        result,
        {"rollback_type": "delete", "token": result.file_token},
    )
    return _result_to_dict(result, "创建幻灯片")


async def office_generate_docx_pdf(
    ctx: RunContext[SafetyDeps],
    title: str,
    content: str,
    file_type: str = "docx",
    sections: list[dict] | None = None,
) -> dict:
    """在本地生成 .docx 或 .pdf 文件，返回文件内容（base64）与文件名。

    不调用飞书 API，生成产物以 base64 返回给 Agent，可后续发回聊天。
    file_type 仅支持 docx / pdf。sections 可选结构化章节
    （[{heading, body}]），不传时按 content 的换行分段。

    Args:
        title: 文档标题（必填）
        content: 正文内容（纯文本，多段用换行分隔）
        file_type: 生成类型（docx / pdf，默认 docx）
        sections: 结构化章节（可选）

    Returns:
        dict: {"kind": "file", "file_name", "size", "content_base64"}
    """
    del ctx  # 本地生成不依赖 ctx.deps.office_client
    normalized_type = (file_type or "docx").strip().lower()
    if normalized_type not in {"docx", "pdf"}:
        return {
            "kind": "error",
            "error": f"file_type 仅支持 docx / pdf，当前为 {file_type!r}",
        }

    try:
        if normalized_type == "docx":
            data = _generate_docx(title, content, sections)
            file_name = f"{title or 'document'}.docx"
        else:
            data = _generate_pdf(title, content, sections)
            file_name = f"{title or 'document'}.pdf"

        result = OfficeResult.file(bytes=data, file_name=file_name, size=len(data))
        result = _attach_rollback_handle(
            result,
            {
                "rollback_type": "no_rollback",
                "reason": "本地生成文件不涉及飞书云空间，无法回滚",
            },
        )
        return _result_to_dict(result, "生成 docx/pdf")
    except Exception as exc:
        logger.exception("office_generate_docx_pdf 生成失败")
        return {
            "kind": "error",
            "error": f"生成文件失败：{type(exc).__name__}: {exc}",
        }


async def office_upload_file(
    ctx: RunContext[SafetyDeps],
    file_path: str,
    parent_token: str | None = None,
    file_name: str | None = None,
) -> dict:
    """上传本地文件到飞书云空间，返回可访问链接。

    上传成功后自动把当前发起人授予该文件的管理权限；Web 端匿名用户跳过授权。
    文件路径必须是 Agent 可访问的本地绝对路径或相对路径。

    Args:
        file_path: 本地文件路径（必填）
        parent_token: 目标文件夹 token（可选，不传上传到应用根目录）
        file_name: 上传后的文件名（可选，默认取原文件名）

    Returns:
        dict: {"kind": "link", "url", "file_token", "message"}
    """
    client = get_office_client(ctx)
    result = await client.upload_drive_file(
        file_path, parent_token=parent_token, file_name=file_name,
    )
    result = await _grant_creator_manage(ctx, result)
    result = _attach_rollback_handle(
        result,
        {"rollback_type": "delete", "token": result.file_token},
    )
    return _result_to_dict(result, "上传云空间文件")


async def office_set_permission(
    ctx: RunContext[SafetyDeps],
    file_token: str | None = None,
    document_id: str | None = None,
    spreadsheet_token: str | None = None,
    base_token: str | None = None,
    target_type: str = "user",
    open_ids: list[str] | None = None,
    emails: list[str] | None = None,
    permission: str = "read",
) -> dict:
    """设置飞书文件/文档的协作者权限（高危写，仅 safety_admin 可调）。

    执行前会先读取目标对象的原权限快照，写入后把快照随 rollback 句柄返回；
    需要撤销时把返回的 rollback 字典交给 rollback_office_file 即可还原。

    Args:
        file_token: 通用文件 token（与 document_id / spreadsheet_token / base_token 四选一）
        document_id: 云文档 token（docx 链接路径最后一段，如 doxcnXXXX）
        spreadsheet_token: 电子表格 token（sheets 链接路径中的 token）
        base_token: 多维表格应用 token（base 链接中的 app_token）
        target_type: 授权对象类型，user=飞书用户（open_ids），member=邮箱（emails）
        open_ids: 飞书用户 open_id 列表（target_type=user 时使用）
        emails: 邮箱列表（target_type=member 时使用）
        permission: 权限级别，可选 manage / full_access / edit / read

    Returns:
        dict: {"kind": "link", "url", "token", "message", "rollback"}
    """
    client = get_office_client(ctx)

    token = file_token or document_id or spreadsheet_token or base_token
    if not token:
        return {
            "kind": "error",
            "error": (
                "至少需要提供 file_token / document_id / spreadsheet_token / "
                "base_token 中的一个"
            ),
        }

    member_type = "openid" if (target_type or "user").strip().lower() != "member" else "email"
    targets = open_ids if member_type == "openid" else emails
    if not targets:
        return {
            "kind": "error",
            "error": (
                f"target_type={target_type} 需要 "
                f"{'open_ids' if member_type == 'openid' else 'emails'} 列表"
            ),
        }

    # 执行前快照：只保留本次授权对象的原权限；列表里没有则视为「原本无权限」。
    snapshot_result = await client.list_permission_members(token)
    if snapshot_result.kind == "error":
        rollback = {
            "rollback_type": "no_rollback",
            "token": token,
            "reason": f"权限快照读取失败：{snapshot_result.error}",
        }
    else:
        current = [
            member
            for member in (snapshot_result.content or [])
            if member.get("member_type") == member_type
            and member.get("member_id") in set(targets)
        ]
        permissions = [
            {
                "member_type": member_type,
                "member_id": member.get("member_id"),
                "perm": member.get("perm"),
            }
            for member in current
        ]
        for target in targets:
            if not any(item["member_id"] == target for item in permissions):
                permissions.append({
                    "member_type": member_type,
                    "member_id": target,
                    "perm": None,
                })
        rollback = {
            "rollback_type": "set_permission",
            "token": token,
            "permissions": permissions,
        }

    result = await client.set_permission(
        token, targets, permission, member_type=member_type,
    )
    if result.kind == "error":
        out = _result_to_dict(result, "设置文件/文档权限")
        out["rollback"] = rollback
        if rollback.get("rollback_type") == "no_rollback":
            out["no_rollback"] = True
        return out

    out: dict[str, Any] = {
        "kind": "link",
        "url": client.file_url(token),
        "token": token,
        "file_token": token,
        "message": f"已为 {len(targets)} 个对象设置权限 {permission}",
        "rollback": rollback,
    }
    if isinstance(result.content, dict):
        out["granted"] = result.content.get("granted")
        out["perm"] = result.content.get("perm")
    if rollback.get("rollback_type") == "no_rollback":
        out["no_rollback"] = True
    return out


async def rollback_office_file(
    ctx: RunContext[SafetyDeps],
    file_token: str | None = None,
    *,
    rollback: dict[str, Any] | None = None,
) -> dict:
    """回滚钩子：删除新建文件，或按快照还原写表/权限。

    写工具返回的「rollback」字段可直接作为 rollback 参数传入：
    - {"rollback_type": "delete", "token": ...} 表示删除新建文件
    - {"rollback_type": "write_sheet", "token": ..., "range": ..., "values": ...}
      表示用执行前快照还原被覆盖区域
    - {"rollback_type": "set_permission", "token": ..., "permissions": [...]}
      表示还原原权限；原本无权限的成员会被移除
    未传 rollback 时保留旧语义：按 file_token 删除文件。

    Args:
        file_token: 待删除文件的飞书 token（rollback 未提供时使用）
        rollback: 写工具返回的回滚句柄（可选，优先使用）

    Returns:
        dict: {"kind": "link", "token"/"file_token", "message", "rollback_type"}
        或 {"kind": "no_rollback", "no_rollback": true} 或 {"kind": "error", "error"}
    """
    client = get_office_client(ctx)
    handle = rollback or {}
    rollback_type = handle.get("rollback_type") or "delete"
    token = handle.get("token") or file_token

    if not token:
        return {"kind": "error", "error": "缺少回滚目标 token"}

    if rollback_type == "no_rollback":
        return {
            "kind": "no_rollback",
            "token": token,
            "no_rollback": True,
            "message": handle.get("reason") or "该操作不支持回滚",
        }

    if rollback_type == "write_sheet":
        sheet_range = handle.get("range") or handle.get("sheet_range")
        values = handle.get("values")
        if sheet_range is None or values is None:
            return {
                "kind": "error",
                "error": "write_sheet 回滚缺少 range/values 快照",
            }
        result = await client.write_sheet(token, sheet_range, values)
        if result.kind == "error":
            return _result_to_dict(result, "回滚写入电子表格")
        out = _result_to_dict(result, "回滚写入电子表格")
        out["rollback_type"] = "write_sheet"
        out["message"] = f"已还原电子表格区域 {sheet_range}"
        return out

    if rollback_type == "set_permission":
        permissions = handle.get("permissions") or handle.get("snapshot") or []
        restored = 0
        errors: list[str] = []
        for item in permissions:
            if not isinstance(item, dict):
                continue
            member_type = item.get("member_type") or "openid"
            member_id = item.get("member_id") or item.get("open_id")
            perm = item.get("perm")
            if not member_id:
                continue
            if perm is None:
                res = await client.remove_permission_member(
                    token, member_id, member_type=member_type,
                )
            else:
                res = await client.set_permission(
                    token, [member_id], perm, member_type=member_type,
                )
            if res.kind == "error":
                errors.append(f"{member_id}: {res.error}")
            else:
                restored += 1

        if errors:
            return {
                "kind": "error",
                "error": "权限回滚部分失败：" + "；".join(errors),
            }
        return {
            "kind": "link",
            "token": token,
            "file_token": token,
            "rollback_type": "set_permission",
            "message": f"已还原 {restored} 个协作者的权限",
        }

    result = await client.delete_file(token)
    out = _result_to_dict(result, "删除/回滚办公文件")
    out.setdefault("rollback_type", "delete")
    return out

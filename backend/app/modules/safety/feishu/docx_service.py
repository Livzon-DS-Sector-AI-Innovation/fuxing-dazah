"""飞书云文档创建与权限管理服务。

为演练方案 AI 生成结果创建飞书云文档，并设置可编辑的分享链接。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.modules.safety.feishu.client import (
    get_safety_feishu_client,
    get_safety_tenant_token,
)
from app.modules.safety.feishu.docx_blocks import drill_plan_to_blocks

logger = logging.getLogger(__name__)

# 分批写入的每批 block 数量
_CHUNK_SIZE = 50


class FeishuDocxService:
    """飞书云文档创建服务。

    使用安全模块独立的飞书应用（SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET）。
    """

    async def create_document(self, title: str) -> tuple[str, str]:
        """创建空白飞书云文档。

        Returns:
            (document_id, doc_url)
        """
        from lark_oapi.api.docx.v1 import (
            CreateDocumentRequest,
            CreateDocumentRequestBody,
        )

        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        create_req = (
            CreateDocumentRequest.builder()
            .request_body(
                CreateDocumentRequestBody.builder()
                .title(title)
                .build()
            )
            .build()
        )
        create_req.headers = {"Authorization": f"Bearer {token}"}
        create_resp = await client.docx.v1.document.acreate(create_req)

        if not create_resp.success():
            raise RuntimeError(
                f"创建飞书文档失败: code={create_resp.code}, msg={create_resp.msg}"
            )

        document_id: str = create_resp.data.document.document_id
        doc_url = f"https://bytedance.feishu.cn/docx/{document_id}"

        logger.info("Feishu doc created: id=%s", document_id)
        return document_id, doc_url

    async def write_blocks(self, document_id: str, blocks: list[dict]) -> bool:
        """分批写入 blocks 到文档。

        使用 docx children API，每批最多 50 个 block，
        自动查询当前子节点数量以确定插入位置。
        """
        if not blocks:
            return True

        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        children_url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents"
            f"/{document_id}/blocks/{document_id}/children"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        total_ok = 0

        for chunk_start in range(0, len(blocks), _CHUNK_SIZE):
            chunk = blocks[chunk_start : chunk_start + _CHUNK_SIZE]

            # 计算插入位置：非首批时查询已有子节点数量
            index = 0
            if chunk_start > 0:
                try:
                    async with httpx.AsyncClient(timeout=15) as http:
                        get_resp = await http.get(children_url, headers=headers)
                        get_data = get_resp.json()
                        if get_data.get("code") == 0:
                            existing = get_data.get("data", {}).get("children", [])
                            index = len(existing)
                        else:
                            logger.warning(
                                "获取子节点数量失败: %s, 使用估算位置",
                                get_data.get("msg"),
                            )
                            index = chunk_start  # fallback 估算
                except Exception:
                    logger.warning("获取子节点数量异常, 使用估算位置")
                    index = chunk_start

            body: dict[str, Any] = {"children": chunk, "index": index}

            try:
                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.post(children_url, headers=headers, json=body)
                    data = resp.json()

                if data.get("code") == 0:
                    total_ok += len(chunk)
                else:
                    logger.error(
                        "写入 block 失败 [%d-%d]: code=%s, msg=%s",
                        chunk_start + 1,
                        chunk_start + len(chunk),
                        data.get("code"),
                        data.get("msg"),
                    )
            except Exception:
                logger.exception(
                    "写入 block 异常 [%d-%d]",
                    chunk_start + 1,
                    chunk_start + len(chunk),
                )

        success = total_ok == len(blocks)
        logger.info(
            "Feishu doc blocks written: %d/%d blocks (success=%s)",
            total_ok,
            len(blocks),
            success,
        )
        return success

    async def set_permission(self, document_id: str) -> str | None:
        """设置文档为「组织内可编辑」。

        通过 Feishu Drive Permission API（v1），所有租户成员可直接编辑文档。
        权限设置失败时降级返回文档 URL。

        对应 SDK: lark_oapi.api.drive.v1.PatchPermissionPublicRequest
        请求体: PermissionPublicRequest

        Returns:
            文档 URL，失败时返回 None。
        """
        client = await get_safety_feishu_client()
        token = await get_safety_tenant_token(client)

        doc_url = f"https://bytedance.feishu.cn/docx/{document_id}"

        # type=docx 是 URL query 参数（值取文档类型：doc/sheet/file/wiki/bitable/docx/mindnote）
        perm_url = (
            f"https://open.feishu.cn/open-apis/drive/v1/permissions"
            f"/{document_id}/public?type=docx"
        )

        # 对应 PermissionPublicRequest 字段：
        #   security_entity: anyone_can_view | anyone_can_edit | only_full_access
        #   link_share_entity: tenant_readable | tenant_editable | anyone_readable | anyone_editable
        perm_body = {
            "external_access": True,
            "security_entity": "anyone_can_edit",
            "link_share_entity": "tenant_editable",
            "invite_external": True,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.patch(
                    perm_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=perm_body,
                )
                data = resp.json()
                if data.get("code") == 0:
                    logger.info(
                        "Feishu doc permission set (tenant_editable): id=%s", document_id
                    )
                else:
                    logger.warning(
                        "设置飞书文档权限失败 (code=%s msg=%s)，"
                        "文档可能需在飞书内手动设置权限: id=%s",
                        data.get("code"),
                        data.get("msg"),
                        document_id,
                    )
        except Exception:
            logger.exception(
                "设置飞书文档权限异常，需手动设置权限: id=%s url=%s",
                document_id,
                doc_url,
            )

        return doc_url

    async def create_drill_document(
        self,
        content_json: dict,
        title: str,
    ) -> tuple[str, str] | None:
        """一站式：创建文档 → 写入内容 → 创建分享链接。

        Args:
            content_json: AI 生成的演练方案 JSON（含 title/summary/sections/cited_regulations）
            title: 文档标题

        Returns:
            (document_id, share_url) 或 None（失败时）
        """
        # 1. 创建空白文档
        document_id, _doc_url = await self.create_document(title)

        # 2. 转换为 blocks 并写入
        blocks = drill_plan_to_blocks(content_json)
        if not blocks:
            logger.warning("No blocks generated for drill plan: title=%s", title)
            return None

        write_ok = await self.write_blocks(document_id, blocks)
        if not write_ok:
            logger.error("Failed to write all blocks to Feishu doc: id=%s", document_id)
            # 继续 —— 部分成功的文档仍然有用

        # 3. 创建分享链接（可编辑）
        share_url = await self.set_permission(document_id)
        if share_url is None:
            share_url = f"https://bytedance.feishu.cn/docx/{document_id}"

        logger.info(
            "Drill plan Feishu doc complete: id=%s, blocks=%d, url=%s",
            document_id,
            len(blocks),
            share_url,
        )
        return document_id, share_url

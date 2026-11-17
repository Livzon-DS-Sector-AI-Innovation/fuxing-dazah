"""五金库对话式 Excel 入库链（2026-11-13：私聊机器人发 Excel → 草稿确认卡）。

复用 Web 端同一解析内核（excel_io.parse_receipt_excel + matcher 四级匹配）
与两段式确认门（draft_flow scene=hardware_receipt + hardware 确认卡）——
对话入口只多两步：IM 文件消息下载（media.download_im_file）与模板回发
（media.send_file_to_chat）。

流程：用户私聊发 xlsx → gateway file 路由（无五金意图文本也按 Excel 入库
试探）→ 本模块 process_hardware_excel → 解析+匹配 → 确认卡（核对修正→
确认入账，与图片 OCR 链同门）。
用户说「五金入库/模板」→ 意图回卡：发模板文件 + 指引文本。
"""

from __future__ import annotations

import logging
import time

from app.modules.warehouse.feishu import media

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = (".xlsx", ".xlsm", ".xls", ".csv")  # .xls=ERP原生导出（HTML伪xls，内容嗅探区分真二进制）
TEMPLATE_FILENAME = "五金库入库登记模板.xlsx"


def sniff_excel_filename(filename: str) -> bool:
    """按扩展名判断是否 Excel/CSV（gateway file 路由预判用）。"""
    return (filename or "").lower().endswith(SUPPORTED_EXTS)


async def send_receipt_template(chat_id: str) -> bool:
    """回发入库登记模板文件（用户说「五金入库/模板」时）。"""
    from app.modules.warehouse.hardware.excel_io import build_receipt_template

    return await media.send_file_to_chat(
        chat_id, build_receipt_template(), TEMPLATE_FILENAME
    )


async def process_hardware_excel(
    *,
    chat_id: str,
    chat_type: str,
    open_id: str,
    message_id: str,
    file_key: str,
    file_name: str,
    started: float | None = None,
) -> None:
    """五金 Excel 文件处理（gateway 派发，独立 DB 会话自管提交）。

    交互节奏对齐安全模块 URS 对话上传（2026-11-13）：收文即回「受理卡」
    （解析中）→ 解析+匹配 → 建草稿 → 确认卡接管；失败回结构化话术
    （模板指引/格式错误/系统异常三分类）。
    """
    started = started or time.monotonic()
    from app.core.database import async_session_factory
    from app.modules.warehouse.feishu import notification
    from app.modules.warehouse.hardware.excel_io import ExcelParseError

    async def _reply_card(title: str, template: str, md: str) -> None:
        card = {
            "config": {"wide_screen": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": md}}],
        }
        await notification.send_card(chat_id, card)

    try:
        # ① 收文受理回执（URS 同款：先告诉用户"收到了在处理"）
        await _reply_card(
            "🔩 五金库 Excel 入库 · 解析中", "blue",
            f"已收到 **{file_name}**，正在解析物料明细并匹配主数据……\n"
            f"解析完成后将回确认卡片，核对无误后点击确认即可入账。",
        )

        async with async_session_factory() as db:
            # ① 下载 + 扩展名守门
            file_bytes = await media.download_im_file(message_id, file_key)
            if not sniff_excel_filename(file_name):
                raise ValueError(
                    f"文件 {file_name} 不是 Excel/CSV（仅支持 xlsx/xlsm/xls/csv），"
                    f"请先回复「五金模板」下载标准模板填写后上传"
                )

            # ② 解析 → source=excel 草稿（红线：只产 draft 不动账）
            from app.modules.warehouse.hardware import matcher as hw_matcher
            from app.modules.warehouse.hardware.excel_io import (
                ExcelParseError,
                parse_receipt_excel,
            )
            from app.modules.warehouse.hardware.receipt_pipeline import (
                load_active_materials,
            )
            from app.modules.warehouse.hardware.schemas import (
                ReceiptCreate,
                ReceiptItemIn,
            )
            from app.modules.warehouse.hardware import service as hw_service

            parsed = parse_receipt_excel(file_bytes, file_name)
            materials = await load_active_materials(db)
            items: list[ReceiptItemIn] = []
            match_rows: list[dict] = []
            excluded_rows: list[dict] = []  # 入库范围外（清单外物料）：剔除不建单
            matched_stocked = matched_direct = 0
            for row in parsed["items"]:
                result = hw_matcher.match_one(
                    name=row["name"], spec=row.get("spec"), materials=materials
                )
                if result.material is None:
                    # 入库范围判定（2026-11-13 用户拍板）：清单外物料自动剔除，
                    # 不进草稿（492 项清单=入库范围的业务边界；剔除行回执告知）
                    excluded_rows.append(
                        {
                            "ocr_name": row["name"],
                            "ocr_spec": row.get("spec") or "",
                            "quantity": row["quantity"],
                        }
                    )
                    continue
                items.append(
                    ReceiptItemIn(
                        material_id=str(result.material.id),
                        name=result.material.name,
                        spec=result.material.spec,
                        unit=result.material.unit,
                        quantity=row["quantity"],
                        match_confidence=result.method,
                        match_score=result.score,
                    )
                )
                if result.material.managed_class == "stocked":
                    matched_stocked += 1
                else:
                    matched_direct += 1
                match_rows.append(
                    {
                        # 键名对齐图片 OCR 链（确认卡渲染读 ocr_name/ocr_spec）
                        "ocr_name": row["name"],
                        "ocr_spec": row.get("spec") or "",
                        "quantity": row["quantity"],
                        "matched": result.material.name,
                        "low_confidence": result.low_confidence,
                    }
                )
            if not items:
                raise ExcelParseError(
                    f"全部 {len(excluded_rows)} 行均不在五金库入库范围（物资清单外）；"
                    f"系统仅收录清单内五金物料——如需新增清单请联系管理员"
                )

            # 单头取首个入库行的供应商/单号（ERP 大文件多供应商多单号，取首行会串）
            ingested_names = {r["ocr_name"] for r in match_rows}
            first_item = next(
                (r for r in parsed["items"] if r["name"] in ingested_names),
                {},
            )
            header = {
                "supplier_name": first_item.get("supplier") or (parsed["header"] or {}).get("supplier_name"),
                "delivery_note_no": first_item.get("delivery_note_no") or (parsed["header"] or {}).get("delivery_note_no"),
            }
            mode = "direct" if (matched_stocked == 0 and matched_direct > 0) else "stocked"
            payload = ReceiptCreate(
                source="excel",
                mode=mode,  # type: ignore[arg-type]
                supplier_name=header.get("supplier_name"),
                delivery_note_no=header.get("delivery_note_no"),
                excel_result={**parsed, "excluded_rows": excluded_rows},
                items=items,
            )
            receipt = await hw_service.create_receipt(db, payload)

            # ③ AgentDraft（scene=hardware_receipt，aligned=入库草稿引用）
            from app.modules.warehouse.agent.pipeline import draft_flow

            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.HARDWARE_RECEIPT_SCENE,
                fields={
                    "receipt_id": str(receipt.id),
                    "receipt_no": receipt.receipt_no,
                    "supplier": receipt.supplier_name,
                    "mode": receipt.mode,
                    "target_dept": receipt.target_dept,
                    "source": "excel",
                    "errors": parsed["errors"],
                    "excluded_count": len(excluded_rows),
                    "rows": match_rows,
                },
                open_id=open_id,
                chat_id=chat_id,
            )
            await db.commit()

            # ④ 确认卡（两段式确认门；TTL/防重复点击/PATCH 机制全继承）
            await draft_flow.send_confirm_card(db, draft, chat_id=chat_id, open_id=open_id)
            await db.commit()
            # ⑤ 剔除行回执（入库范围外告知；静默总闸 dry_run 下只落日志）
            if excluded_rows:
                sample = "\n".join(
                    f"· {r['ocr_name']} {r['ocr_spec']} × {r['quantity']}"
                    for r in excluded_rows[:5]
                )
                more = f"\n…等共 {len(excluded_rows)} 行" if len(excluded_rows) > 5 else ""
                await _reply_card(
                    "📋 入库范围外物料已自动剔除", "grey",
                    f"文件中 {len(excluded_rows)} 行不在五金库物资清单内，未纳入本次入库"
                    f"（如办公/劳保/化玻等非五金域物料或清单外五金）：\n{sample}{more}\n\n"
                    f"如需新增入库范围请联系管理员维护物资清单。",
                )
            logger.info(
                "五金Excel入库草稿已回显: draft=%s receipt=%s rows=%d "
                "matched=%d excluded=%d errors=%d cost=%.1fs",
                draft.draft_no, receipt.receipt_no, len(items),
                matched_stocked + matched_direct, len(excluded_rows),
                len(parsed["errors"]), time.monotonic() - started,
            )
    except ExcelParseError as exc:
        logger.warning("五金Excel解析失败: chat_id=%s file=%s: %s", chat_id, file_name, exc)
        await _reply_card(
            "❌ 五金库 Excel 入库 · 解析失败", "red",
            f"文件 **{file_name}** 解析失败：{exc}\n\n"
            f"📩 回复「**五金入库**」可重新获取标准模板；"
            f"或到 Web 端「五金出入库」手动登记。",
        )
    except ValueError as exc:
        # 扩展名守门等业务性拒绝（非 Excel 文件类）
        await _reply_card(
            "❌ 五金库 Excel 入库 · 文件类型不符", "orange",
            f"{exc}\n\n📩 回复「**五金入库**」可获取标准模板。",
        )
    except Exception as exc:  # noqa: BLE001 — 对话链兜底话术
        logger.exception("五金Excel入库处理失败")
        await _reply_card(
            "❌ 五金库 Excel 入库 · 处理异常", "red",
            f"文件 **{file_name}** 处理失败（{type(exc).__name__}），请稍后重试。\n\n"
            f"📩 回复「**五金入库**」获取模板；或到 Web 端「五金出入库」手动登记。",
        )

"""五金库对话式 Excel 入库链（2026-11-19 改版：ERP 导出直传口径）。

复用 Web 端同一解析内核（excel_io.parse_receipt_excel + matcher 四级匹配，
HTML 伪 xls / ERP 列名归一已兼容）与两段式确认门（draft_flow
scene=hardware_receipt + hardware 确认卡）。

流程：用户私聊发 ERP 导出的入库流水 Excel → gateway file 路由 →
process_hardware_excel → 解析+匹配 → **按「入库单号」分组，每张 ERP 单
一张草稿** → 逐单确认卡（多单时先回汇总卡；核对修正→确认入账）。
用户说「五金入库/模板」→ 意图回**指引卡**（双方式：ERP 流水 Excel 直传 +
送货单照片 OCR，均无人工模板——2026-11-19 用户拍板）。
"""

from __future__ import annotations

import logging
import time

from app.modules.warehouse.feishu import media

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = (".xlsx", ".xlsm", ".xls", ".csv")  # .xls=ERP原生导出（HTML伪xls，内容嗅探区分真二进制）

INBOUND_GUIDE_MD = (
    "五金库入库有**两种方式**，任选其一，把文件/照片直接发到本会话即可：\n\n"
    "**方式一 · ERP 流水 Excel**（批量入库）\n"
    "发送 ERP 导出的入库流水 Excel（.xls/.xlsx/.csv，无需填写模板）。"
    "系统自动筛五金物料、剔除清单外行、按「**入库单号**」分单、匹配主数据，"
    "逐单回复确认卡。\n\n"
    "**方式二 · 送货单照片**（拍照入库）\n"
    "发送送货单**照片**即可（获取过本指引的会话内可直接发；隔了较久请在照片"
    "配文「五金」，否则会按原辅料收货处理）。OCR 解析后回**与方式一相同格式**"
    "的确认卡。\n\n"
    "两种方式都在确认卡上核对匹配结果（绿色=已匹配/黄色=低置信），"
    "点「**确认入账**」完成登记；清单外物料自动剔除并回执。\n\n"
    "> 方式一需含「物料名称+数量」列（ERP 标准导出即满足）；"
    "个别手工补录可到 Web 端「五金出入库 → 手动登记」。"
)


def sniff_excel_filename(filename: str) -> bool:
    """按扩展名判断是否 Excel/CSV（gateway file 路由预判用）。"""
    return (filename or "").lower().endswith(SUPPORTED_EXTS)


async def send_inbound_guide(chat_id: str) -> bool:
    """回入库指引卡（用户说「五金入库/模板」时；ERP 导出直传口径，无模板文件）。"""
    from app.modules.warehouse.feishu import notification

    card = {
        "config": {"wide_screen": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🔩 五金库入库 · 双方式指引"},
            "template": "blue",
        },
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": INBOUND_GUIDE_MD}}],
    }
    return await notification.send_card(chat_id, card)


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
                    f"请发送 ERP 导出的入库流水文件"
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
            src_rows: list[dict] = []  # 源行（取入库单号/供应商做分组）
            row_classes: list[str] = []  # 行级 managed_class（分组定 mode）
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
                src_rows.append(row)
                row_classes.append(result.material.managed_class or "stocked")
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

            # ③ 按「入库单号」分组，每张 ERP 单一张草稿（2026-11-19 拍板：
            # ERP 导出文件天然多单，拍平成一张草稿会串单号/供应商；
            # 无单号行归入同一张无名草稿）
            groups: dict[str, dict[str, Any]] = {}
            for src, item, mrow, mclass in zip(src_rows, items, match_rows, row_classes):
                doc_no = (src.get("delivery_note_no") or "").strip()
                g = groups.setdefault(
                    doc_no,
                    {"items": [], "rows": [], "supplier": src.get("supplier"),
                     "stocked": 0, "direct": 0},
                )
                g["items"].append(item)
                g["rows"].append(mrow)
                g["stocked" if mclass == "stocked" else "direct"] += 1

            from app.modules.warehouse.agent.pipeline import draft_flow

            if len(groups) > 1:
                summary = "\n".join(
                    f"· 单号 **{doc_no or '（无单号）'}**：{len(g['items'])} 行"
                    for doc_no, g in groups.items()
                )
                await _reply_card(
                    "📦 已按入库单号分单", "blue",
                    f"文件共识别 **{len(groups)}** 张入库单（{len(items)} 行五金物资），"
                    f"将逐单生成草稿并回复确认卡，请逐张核对入账：\n{summary}",
                )

            created: list[str] = []
            for doc_no, g in groups.items():
                mode = "direct" if (g["stocked"] == 0 and g["direct"] > 0) else "stocked"
                payload = ReceiptCreate(
                    source="excel",
                    mode=mode,  # type: ignore[arg-type]
                    supplier_name=g["supplier"] or (parsed["header"] or {}).get("supplier_name"),
                    delivery_note_no=doc_no or None,
                    excel_result={**parsed, "excluded_rows": excluded_rows},
                    items=g["items"],
                )
                receipt = await hw_service.create_receipt(db, payload)
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
                        "erp_doc_no": doc_no or None,
                        "errors": parsed["errors"],
                        "excluded_count": len(excluded_rows),
                        "rows": g["rows"],
                    },
                    open_id=open_id,
                    chat_id=chat_id,
                )
                await db.commit()
                # ④ 确认卡（两段式确认门；TTL/防重复点击/PATCH 机制全继承）
                await draft_flow.send_confirm_card(db, draft, chat_id=chat_id, open_id=open_id)
                await db.commit()
                created.append(receipt.receipt_no)

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
                "五金Excel入库草稿已回显: receipts=%s rows=%d "
                "matched=%d excluded=%d errors=%d cost=%.1fs",
                created, len(items),
                matched_stocked + matched_direct, len(excluded_rows),
                len(parsed["errors"]), time.monotonic() - started,
            )
    except ExcelParseError as exc:
        logger.warning("五金Excel解析失败: chat_id=%s file=%s: %s", chat_id, file_name, exc)
        await _reply_card(
            "❌ 五金库 Excel 入库 · 解析失败", "red",
            f"文件 **{file_name}** 解析失败：{exc}\n\n"
            f"📩 请发送 **ERP 导出的入库流水 Excel**（需含「物料名称/数量」列）；"
            f"回复「**五金入库**」可查看入库指引。",
        )
    except ValueError as exc:
        # 扩展名守门等业务性拒绝（非 Excel 文件类）
        await _reply_card(
            "❌ 五金库 Excel 入库 · 文件类型不符", "orange",
            f"{exc}\n\n📩 请发送 ERP 导出的入库流水文件（.xls/.xlsx/.csv）。",
        )
    except Exception as exc:  # noqa: BLE001 — 对话链兜底话术
        logger.exception("五金Excel入库处理失败")
        await _reply_card(
            "❌ 五金库 Excel 入库 · 处理异常", "red",
            f"文件 **{file_name}** 处理失败（{type(exc).__name__}），请稍后重试。\n\n"
            f"📩 回复「**五金入库**」查看入库指引；或到 Web 端「五金出入库」手动登记。",
        )

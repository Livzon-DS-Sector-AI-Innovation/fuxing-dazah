"""入库/GMP 出库/成品出库提交（S2 ticket 04 + S3 ticket 01/02，spec
Implementation Decisions 1/2/3/6）。

scene=receipt 确认回调真身（draft_flow 注册薄包装，票03 桩退役）：
confirmed 草稿 → aligned/recognized 值组装 material_receipt 写入字段 →
validate_write_fields（S0 写契约最后防线）→ 原图附件下载+上传（feishu/media）
→ create_record 写入测试版物料入库总账 → get_record 读回核对（数量/批号/
单位/供应商）→ draft=submitted + target_record_id 回填 + audit（tool_name=
"submit_receipt"）→ 回执卡片发送（发起人私聊，dry-run 可捕获）→ 返回回执
note（confirm.handle_action 的用户可见消息）。

scene=gmp_outbound 同款链路（S3 ticket 01）：submit_gmp 写 gmp_outbound
（GMP 物料出库总账）——对话收集字段（aligned，canonical 键）→ 字段映射
（日期=当天毫秒时间戳、单据类型默认出库）→ validate → create_record →
读回核对（批号/数量/单位）→ submitted + audit（tool_name="submit_gmp"）；
物料名称为 lookup 拒写（仅确认卡片展示）。

scene=finished_outbound 同款链路（S3 ticket 02）：submit_outbound 写
finished_outbound（成品出库台账）——读回核对（批号/出库量/单位/客户）+
audit（tool_name="submit_outbound"）；快递号写入 API 专用文本字段
「快递号(API)」（原字段为附件类型 type 17 无法写文本）；
登记了快递号时回执 note 附加推送引导（用户回复 group:/user: 目标后经
send_card 确认门发送发货通知，spec 决策 3）。

**物料批号写入 API 专用文本字段「物料批号(API)」**（原单选字段被 Base 侧：测试版 Base 对
该字段存在编辑限制（任何合法选项值均 1254062），submit 跳过批号写入，
回执卡片与 audit 标注「需人工在 Base 补填」；Base 放开后置 True 恢复
自动写入。

**物料名称降级**（spec 决策 6，``SUBMIT_MATERIAL_NAME_ENABLED`` 开关注释）：
测试版「物料名称」单选字段选项重复未治理，按名写入必失败（业务方暂缓
治理）——submit 跳过该字段，回执卡片与 audit 标注「需人工在 Base 补选」；
Base 治理完成后置 True 即恢复自动写入（代码无其他改动）。

单选字段适配（读写不对称 + 选项集硬约束）：识别/对齐值与 Base 选项集
（bitable_schema 静态快照）先做大小写归一匹配（如识别 kg → 选项 Kg），
命中选项集原值写入；未命中跳过并记入 degraded（避免 1254062 使整单
失败），回执卡片提示人工补填。validate_write_fields 本地拦截为最后防线。

读回核对值形态规范化（实测契约，与 tools/query.py _cell_list 同口径）：
单选读回数组取首段、文本读回富文本段取 text、数字整值去 .0；规范化后
字符串比对，不一致 → 回执 ⚠ + audit error_code="mismatch"。

模块依赖说明：cards 经 render_receipt_result_card 渲染回执——cards →
runner → tools.query → tools.draft_update → draft_flow 存在模块环（见
draft_flow 模块注释），故 cards 在 submit_receipt 函数内延迟 import；
draft_flow 反向 import submit 同样走注册处薄包装延迟 import（双向解环）。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.agent import repository
from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    TABLES,
    FieldMeta,
    WarehouseBitableError,
    get_table_fields,
    validate_write_fields,
)
from app.modules.warehouse.feishu import media, notification
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# 目标表（spec：识别入库写测试版物料入库总账）
RECEIPT_TABLE = "material_receipt"

# 附件列字段名（原图写入，spec Implementation Decisions 3）
ATTACHMENT_FIELD = "外包装/厂家报告单/送货单照片"

# 到货情况固定写入值（合法选项，spec 决策 6 场景 A）
ARRIVAL_STATUS_VALUE = "到货物料"

# 物料名称降级开关（spec 决策 6：测试版选项重复未治理 → False 跳过写入；
# Base 治理后置 True 恢复自动写入）
SUBMIT_MATERIAL_NAME_ENABLED = False

# 读回核对关键字段（spec 决策 6：数量/批号/单位/供应商）
CHECK_FIELDS: tuple[str, ...] = ("入库数量", "厂家批号", "单位", "供应商")

# canonical 键 → (Base 字段名, 是否单选)；material_name 降级单独处理，
# produced_at 为 datetime 单独处理（日期字符串 → 毫秒时间戳）
_FIELD_MAP: tuple[tuple[str, str, bool], ...] = (
    ("vendor_batch_no", "厂家批号", False),
    ("quantity", "入库数量", False),
    ("unit", "单位", True),
    ("supplier", "供应商", True),
    ("manufacturer", "生产商", True),
    ("plate_no", "车牌", False),
    ("contract_no", "合同编号或订单号", False),
    ("package_spec", "包装规格", True),
)

# adapter 进程级单例（凭证/连接复用；测试经 monkeypatch get_adapter 注入假件）
_adapter: WarehouseBitableAdapter | None = None


def get_adapter() -> WarehouseBitableAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# ── 值形态规范化（读回核对；实测契约，tools/query.py _cell_list 同口径）──


def _normalize_cell(value: Any) -> str:
    """读回单元格 → 单段规范文本：数组取首、富文本段取 text、数字整值去 .0。"""
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            part = _normalize_cell(item)
            if part:
                return part
        return ""
    if isinstance(value, dict):
        if "text" in value:  # 富文本分段
            return _normalize_cell(value.get("text"))
        if "value" in value:  # 类型包裹（formula/lookup）
            return _normalize_cell(value.get("value"))
        name = value.get("name")  # user/附件
        return str(name).strip() if name else ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


# ── 写入字段组装（纯函数，降级/单选适配集中在此便于单测）──


def _to_number(value: Any) -> int | float | None:
    """quantity 值 → 数字（整值 int 化）；解析失败 None（跳过并标注）。"""
    try:
        num = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return int(num) if num.is_integer() else num


def _parse_date_ms(text: str) -> int | None:
    """生产日期字符串 → 毫秒时间戳（飞书 datetime 字段写入契约）；失败 None。"""
    stripped = text.strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(stripped, fmt).replace(tzinfo=UTC)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _select_or_skip(
    table_fields: dict[str, FieldMeta], field_name: str, text: str, degraded: list[str]
) -> str | None:
    """单选值适配：大小写归一匹配选项集（截断到合法值）；未命中 None + 标注。

    未收录字段/非单选/空选项集放行原值（bitable_schema 契约：避免常量
    滞后误杀；validate_write_fields 为最后防线）。
    """
    meta = table_fields.get(field_name)
    if meta is None or meta.type != FIELD_TYPE_SELECT:
        return text
    options: tuple[str, ...] = meta.options
    if not options:
        return text
    if text in options:
        return text
    lowered = text.lower()
    for opt in options:
        if opt.lower() == lowered:
            return opt
    degraded.append(field_name)
    return None


def build_receipt_fields(
    draft: WarehouseAgentDraft,
) -> tuple[dict[str, Any], list[str]]:
    """draft（aligned 覆盖优先，recognized 兜底）→ material_receipt 写入字段。

    返回 (fields, degraded)：degraded 为未写入字段名（物料名称降级 / 数量
    非数字 / 日期不可解析 / 单选值不在选项集），回执卡片与 audit 标注用。
    到货情况恒写「到货物料」（合法选项）。
    """
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    table_fields = get_table_fields(RECEIPT_TABLE)
    fields: dict[str, Any] = {}
    degraded: list[str] = []

    def value_of(key: str) -> Any:
        # aligned 优先（对话修改后的最新值），空则回落识别值
        if key in aligned:
            v = aligned[key]
            if v is not None and str(v).strip():
                return v
        item = recognized.get(key)
        if isinstance(item, dict):
            v = item.get("value")
            if v is not None and str(v).strip():
                return v
        return None

    # 物料名称（spec 决策 6 降级：跳过写入，标注人工补选；开关见模块注释）
    name = value_of("material_name")
    if name and SUBMIT_MATERIAL_NAME_ENABLED:
        adapted = _select_or_skip(table_fields, "物料名称", str(name).strip(), degraded)
        if adapted:
            fields["物料名称"] = adapted
    elif name:
        degraded.append("物料名称")

    for key, field_name, is_select in _FIELD_MAP:
        value = value_of(key)
        if value is None:
            continue
        if key == "quantity":
            num = _to_number(value)
            if num is None:
                degraded.append(field_name)
                continue
            fields[field_name] = num
            continue
        text = str(value).strip()
        if is_select:
            adapted = _select_or_skip(table_fields, field_name, text, degraded)
            if not adapted:
                continue
            text = adapted
        fields[field_name] = text

    produced_at = value_of("produced_at")
    if produced_at is not None:
        ms = _parse_date_ms(str(produced_at))
        if ms is None:
            degraded.append("生产日期")
        else:
            fields["生产日期"] = ms

    fields["到货情况"] = ARRIVAL_STATUS_VALUE
    return fields, degraded


# ── 读回核对 ──


async def _verify_record(
    adapter: WarehouseBitableAdapter,
    record_id: str,
    written_fields: dict[str, Any],
    *,
    table_key: str = RECEIPT_TABLE,
    check_fields: tuple[str, ...] = CHECK_FIELDS,
) -> dict[str, Any]:
    """get_record 读回核对（仅实际写入的 check_fields 字段参与）。

    返回 {"consistent": bool, "mismatches": [{field, written, read_back}]}
    （值经 _normalize_cell 规范化后字符串比对）。
    """
    record = await adapter.get_record(table_key, record_id)
    read_fields = record.get("fields") or {}
    mismatches: list[dict[str, Any]] = []
    for field_name in check_fields:
        if field_name not in written_fields:
            continue  # 未写入（空值/降级跳过）不参与核对
        written = _normalize_cell(written_fields[field_name])
        read_back = _normalize_cell(read_fields.get(field_name))
        if written != read_back:
            mismatches.append(
                {"field": field_name, "written": written, "read_back": read_back}
            )
    return {"consistent": not mismatches, "mismatches": mismatches}


def get_table_meta(table_key: str = RECEIPT_TABLE) -> dict[str, str]:
    """目标表坐标（target_base/target_table 回填用）：app_token + table_id。"""
    meta = TABLES[table_key]
    return {
        "base_token": str(getattr(get_settings(), meta.base_token_setting, "") or ""),
        "table_id": meta.table_id,
    }


# ── 确认回调真身（draft_flow 注册薄包装转发到这里）──


async def submit_receipt(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
    """入库提交：写契约 → 附件 → create_record → 读回核对 → submitted + 回执。

    状态前置：confirm.handle_action 已先置 confirmed（S1 防重复点击语义）；
    非 confirmed / 重复提交（submitted 终态）抛 :class:`DraftFlowError`。
    写入/附件异常向上抛（confirm 统一置 failed + audit callback_error；
    failed 为终态无法重试——用户需重新拍照发起新识别，见 cards 回执话术）；mismatch 不算失败——draft 仍 submitted，
    audit error_code="mismatch" + 回执 ⚠。
    """
    started = time.monotonic()
    if draft.status != "confirmed":
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {draft.status}，仅 confirmed 可提交"
        )

    adapter = get_adapter()
    fields, degraded = build_receipt_fields(draft)

    # 原图附件（spec 决策 3）：drafts.source_image（Base 附件 file token）
    # → 下载字节 → upload_all 上传 → 附件列 [{file_token}]。
    # 票05 实测（im 链路）：gateway 先行 upload_all 的原图尚未挂到任何
    # 记录，drive download 端点会 404（media 写入记录后才可下载）——此时
    # 直接把 source token 写入附件列（media 上传时 parent_node 即本 Base，
    # 同 Base 引用合法，票05 探针验证）；票04 原路径（源 token 来自已有
    # 记录，可下载）仍走下载重传。
    attachment_token: str | None = None
    source_image = (draft.source_image or "").strip()
    if source_image:
        try:
            content = await media.download_attachment(source_image)
            attachment_token = await media.upload_image(
                content, f"{draft.draft_no}.jpg"
            )
            fields[ATTACHMENT_FIELD] = [{"file_token": attachment_token}]
        except WarehouseBitableError:
            logger.warning(
                "原图下载失败，直接引用 source token 写附件列: draft_no=%s token=%s…",
                draft.draft_no,
                source_image[:20],
            )
            fields[ATTACHMENT_FIELD] = [{"file_token": source_image}]

    validate_write_fields(RECEIPT_TABLE, fields)  # S0 写契约最后防线（本地拦截）

    created = await adapter.create_record(RECEIPT_TABLE, fields)
    record_id = str(created.get("record_id") or "")
    if not record_id:
        raise WarehouseBitableError(
            "create_record 未返回 record_id", code="no_record_id"
        )

    check_result = await _verify_record(adapter, record_id, fields)
    check_result["written"] = dict(fields)
    check_result["record_id"] = record_id
    check_result["degraded"] = degraded

    # draft → submitted + target 回填（状态机迁移表已含 confirmed → submitted）
    from_status = draft.status
    draft.status = "submitted"
    meta = get_table_meta()
    draft.target_base = meta["base_token"]
    draft.target_table = meta["table_id"]
    draft.target_record_id = record_id
    await db.flush()

    await repository.insert_agent_audit(
        db,
        tool_name="submit_receipt",
        args_summary={
            "draft_no": draft.draft_no,
            "record_id": record_id,
            "fields": sorted(fields.keys()),
            "attachment": ATTACHMENT_FIELD in fields,
            "degraded": degraded,
            "from": from_status,
            "to": "submitted",
        },
        result_status="ok",
        error_code=None if check_result["consistent"] else "mismatch",
        duration_ms=_elapsed_ms(started),
        draft_id=draft.id,
    )

    # 回执卡片发送（发起人私聊；cards 延迟 import 解模块环，draft_flow 同理）
    from app.modules.warehouse.agent.cards import render_receipt_result_card

    card = render_receipt_result_card(draft, check_result)
    await _send_result_card(draft, card)

    logger.info(
        "入库提交完成: draft_no=%s record_id=%s consistent=%s degraded=%s",
        draft.draft_no,
        record_id,
        check_result["consistent"],
        degraded,
    )
    if check_result["consistent"]:
        return f"✅ 入库已登记：{draft.draft_no}（Base 记录 {record_id}）"
    count = len(check_result["mismatches"])
    return (
        f"⚠ 入库已登记：{draft.draft_no}（Base 记录 {record_id}），"
        f"{count} 个字段读回不一致，请到 Base 核对"
    )


# ── GMP 出库提交（S3 ticket 01，spec Implementation Decisions 1）──
# scene=gmp_outbound 确认回调真身（draft_flow._gmp_submit_callback 薄包装）：
# aligned（对话收集字段，canonical 键）→ 组装 gmp_outbound 写入字段 →
# validate → create_record → 读回核对（批号/数量/单位）→ submitted + 回执。
# 日期=当天（毫秒时间戳）；物料名称是 lookup 拒写（仅确认卡片展示，不在
# 映射表）；领用品种/部门为单选（空选项集快照放行原值，刷新后严格匹配）。

GMP_OUTBOUND_TABLE = "gmp_outbound"

# 读回核对关键字段（spec 决策 1：批号/数量/单位）
GMP_CHECK_FIELDS: tuple[str, ...] = ("物料批号(API)", "领用数量", "单位")

# canonical 键 → (Base 字段名, 是否单选)；material_name（lookup 拒写）与
# 日期（恒写当天）单独处理
_GMP_FIELD_MAP: tuple[tuple[str, str, bool], ...] = (
    # 物料批号写入 API 专用文本字段（原「物料批号」单选被 Base 侧字段级
    # 编辑限制拒写 1254062，2026-09-07 新建文本字段绕开，见 spec/记忆）
    ("material_batch_no", "物料批号(API)", False),
    ("doc_type", "单据类型", True),
    ("category", "领用品种", True),
    ("department", "领用部门", True),
    ("unit", "单位", True),
    ("quantity", "领用数量", False),
    ("production_batch_no", "生产批号", False),
)

async def _send_result_card(draft: WarehouseAgentDraft, card: dict[str, Any]) -> None:
    """回执按发起渠道发送：chat_id（群/私聊原渠道）优先，缺失回落发起人私聊。

    发送失败只记日志（回执不回滚已完成的写入）。
    """

    chat_id = (draft.chat_id or "").strip()
    sent: bool | str | None = None
    try:
        if chat_id:
            sent = await notification.send_card(chat_id, card)
        else:
            open_id = (draft.created_by_open_id or "").strip()
            sent = await notification.send_card_to_user(open_id, card) if open_id else False
    except Exception:  # noqa: BLE001 — 回执发送失败不回滚已完成的写入
        logger.exception("回执卡片发送异常: draft_no=%s", draft.draft_no)
        return
    if not sent:
        logger.warning("回执卡片发送失败: draft_no=%s chat_id=%r", draft.draft_no, chat_id[:24])


def _today_ms(today: date | None = None) -> int:
    """当天日期 → 毫秒时间戳（飞书 datetime 写入契约；UTC 零点即北京当天
    08:00，日期显示不受时区影响）。"""
    day = today or date.today()
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


async def _gmp_table_fields() -> dict[str, FieldMeta]:
    """gmp_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    静态快照批号选项仅 50 条而 Base 实测 1700+（快照滞后会误杀合法批号）——
    先 refresh_table_fields 拉最新选项集（bitable_schema TTL 缓存内直用），
    刷新失败回落静态快照（create_record 阶段仍会因网络失败暴露，不静默）。
    """
    try:
        await get_adapter().refresh_table_fields(GMP_OUTBOUND_TABLE)
    except Exception:  # noqa: BLE001 — 选项集刷新失败不阻断（回落静态快照）
        logger.warning("gmp_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(GMP_OUTBOUND_TABLE)


def build_gmp_fields(
    draft: WarehouseAgentDraft,
    *,
    table_fields: dict[str, FieldMeta] | None = None,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """draft.aligned（对话收集 working set）→ gmp_outbound 写入字段。

    返回 (fields, degraded)：degraded 为未写入字段名（物料批号降级 / 单选
    值不在选项集 / 数量非数字）。日期恒写当天毫秒时间戳；material_name 是
    lookup 拒写，不进入映射（仅确认卡片展示）。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    fields: dict[str, Any] = {}
    degraded: list[str] = []

    for key, field_name, is_select in _GMP_FIELD_MAP:
        value = aligned.get(key)
        if value is None or not str(value).strip():
            continue
        if key == "quantity":
            num = _to_number(value)
            if num is None:
                degraded.append(field_name)
                continue
            fields[field_name] = num
            continue
        text = str(value).strip()
        if is_select:
            adapted = _select_or_skip(
                table_fields or get_table_fields(GMP_OUTBOUND_TABLE),
                field_name,
                text,
                degraded,
            )
            if not adapted:
                continue
            text = adapted
        fields[field_name] = text

    fields["日期"] = _today_ms(today)
    return fields, degraded


async def submit_gmp(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
    """GMP 出库提交：写契约 → create_record → 读回核对 → submitted + 回执。

    状态前置/异常语义与 submit_receipt 完全同款：非 confirmed 抛
    :class:`DraftFlowError`；写入异常向上抛（confirm 置 failed）；mismatch
    不算失败——draft 仍 submitted + audit error_code="mismatch" + 回执 ⚠。
    """
    started = time.monotonic()
    if draft.status != "confirmed":
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {draft.status}，仅 confirmed 可提交"
        )

    adapter = get_adapter()
    fields, degraded = await _build_and_validate_gmp(draft)

    created = await adapter.create_record(GMP_OUTBOUND_TABLE, fields)
    record_id = str(created.get("record_id") or "")
    if not record_id:
        raise WarehouseBitableError(
            "create_record 未返回 record_id", code="no_record_id"
        )

    check_result = await _verify_record(
        adapter,
        record_id,
        fields,
        table_key=GMP_OUTBOUND_TABLE,
        check_fields=GMP_CHECK_FIELDS,
    )
    check_result["written"] = dict(fields)
    check_result["record_id"] = record_id
    check_result["degraded"] = degraded

    # draft → submitted + target 回填（状态机迁移表已含 confirmed → submitted）
    from_status = draft.status
    draft.status = "submitted"
    meta = get_table_meta(GMP_OUTBOUND_TABLE)
    draft.target_base = meta["base_token"]
    draft.target_table = meta["table_id"]
    draft.target_record_id = record_id
    await db.flush()

    await repository.insert_agent_audit(
        db,
        tool_name="submit_gmp",
        args_summary={
            "draft_no": draft.draft_no,
            "record_id": record_id,
            "fields": sorted(fields.keys()),
            "degraded": degraded,
            "from": from_status,
            "to": "submitted",
        },
        result_status="ok",
        error_code=None if check_result["consistent"] else "mismatch",
        duration_ms=_elapsed_ms(started),
        draft_id=draft.id,
    )

    # 回执卡片（scene 分支渲染 GMP 标题；cards 延迟 import 解模块环，同上）
    from app.modules.warehouse.agent.cards import render_receipt_result_card

    card = render_receipt_result_card(draft, check_result)
    await _send_result_card(draft, card)

    logger.info(
        "GMP 出库提交完成: draft_no=%s record_id=%s consistent=%s degraded=%s",
        draft.draft_no,
        record_id,
        check_result["consistent"],
        degraded,
    )
    if check_result["consistent"]:
        return f"✅ GMP 出库已登记：{draft.draft_no}（Base 记录 {record_id}）"
    count = len(check_result["mismatches"])
    return (
        f"⚠ GMP 出库已登记：{draft.draft_no}（Base 记录 {record_id}），"
        f"{count} 个字段读回不一致，请到 Base 核对"
    )


async def _build_and_validate_gmp(
    draft: WarehouseAgentDraft,
) -> tuple[dict[str, Any], list[str]]:
    """组装 GMP 写入字段并跑写契约校验（刷新选项集后本地拦截）。"""
    fields, degraded = build_gmp_fields(draft, table_fields=await _gmp_table_fields())
    validate_write_fields(GMP_OUTBOUND_TABLE, fields)
    return fields, degraded


# ── 成品出库提交（S3 ticket 02，spec Implementation Decisions 2/3）──
# scene=finished_outbound 确认回调真身（draft_flow._finished_submit_callback
# 薄包装）：aligned（对话收集字段，canonical 键）→ 组装 finished_outbound
# 写入字段 → validate → create_record → 读回核对（批号/出库量/单位/客户）→
# submitted + 回执。出库日期=当天（毫秒时间戳）；品规/各品种库存/质量状态/
# 库存数量/出库人 等为公式/lookup/created_user 拒写（不在映射表）；快递号
# 为附件字段（type 17），文本单号无法写入——降级开关跳过（见下）。

FINISHED_OUTBOUND_TABLE = "finished_outbound"

# 读回核对关键字段（票02 验收：批号/出库量/单位/客户）
FINISHED_CHECK_FIELDS: tuple[str, ...] = (
    "产品批号",
    "出库量",
    "单位",
    "销售客户",
    "快递号(API)",
)

# canonical 键 → (Base 字段名, 是否单选)；quantity 数字化单独分支，出库日期
# 恒写当天单独处理；express_no（快递号，附件字段）走降级开关
_FINISHED_FIELD_MAP: tuple[tuple[str, str, bool], ...] = (
    ("product_name", "产品名称", True),
    ("product_batch_no", "产品批号", False),
    ("unit", "单位", True),
    ("customer", "销售客户", False),
    ("purpose", "用途", True),
    ("thermometer", "温度计", True),
    # 快递号写入 API 专用文本字段（原「快递号」为附件类型 type 17，
    # 文本单号无法写入，2026-09-07 新建文本字段绕开）
    ("express_no", "快递号(API)", False),
    ("remark", "备注", False),
    ("quantity", "出库量", False),
)

async def _finished_table_fields() -> dict[str, FieldMeta]:
    """finished_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    产品名称/单位/用途/温度计均单选且 Base 侧可能调整选项——先
    refresh_table_fields 拉最新选项集（bitable_schema TTL 缓存内直用），
    刷新失败回落静态快照（登记主链路不因选项集刷新抖动中断）。
    """
    try:
        await get_adapter().refresh_table_fields(FINISHED_OUTBOUND_TABLE)
    except Exception:  # noqa: BLE001 — 选项集刷新失败不阻断（回落静态快照）
        logger.warning("finished_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(FINISHED_OUTBOUND_TABLE)


def build_finished_fields(
    draft: WarehouseAgentDraft,
    *,
    table_fields: dict[str, FieldMeta] | None = None,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """draft.aligned（对话收集 working set）→ finished_outbound 写入字段。

    返回 (fields, degraded)：degraded 为未写入字段名（快递号降级 / 单选值
    不在选项集 / 出库量非数字）。出库日期恒写当天毫秒时间戳；品规/各品种
    库存/质量状态/库存数量/出库人 等只读类型不进入映射（validate_write_fields
    为最后防线）。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    fields: dict[str, Any] = {}
    degraded: list[str] = []

    for key, field_name, is_select in _FINISHED_FIELD_MAP:
        value = aligned.get(key)
        if value is None or not str(value).strip():
            continue
        if key == "quantity":
            num = _to_number(value)
            if num is None:
                degraded.append(field_name)
                continue
            fields[field_name] = num
            continue
        text = str(value).strip()
        if is_select:
            adapted = _select_or_skip(
                table_fields or get_table_fields(FINISHED_OUTBOUND_TABLE),
                field_name,
                text,
                degraded,
            )
            if not adapted:
                continue
            text = adapted
        fields[field_name] = text

    fields["出库日期"] = _today_ms(today)
    return fields, degraded


async def _build_and_validate_finished(
    draft: WarehouseAgentDraft,
) -> tuple[dict[str, Any], list[str]]:
    """组装成品出库写入字段并跑写契约校验（刷新选项集后本地拦截）。"""
    fields, degraded = build_finished_fields(
        draft, table_fields=await _finished_table_fields()
    )
    validate_write_fields(FINISHED_OUTBOUND_TABLE, fields)
    return fields, degraded


async def submit_outbound(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
    """成品出库提交：写契约 → create_record → 读回核对 → submitted + 回执。

    状态前置/异常语义与 submit_gmp 完全同款：非 confirmed 抛
    :class:`DraftFlowError`；写入异常向上抛（confirm 置 failed）；mismatch
    不算失败——draft 仍 submitted + audit error_code="mismatch" + 回执 ⚠。
    返回回执 note（confirm.handle_action 用户可见消息）：登记了快递号时
    附加推送引导（spec 决策 3——用户回复 group:/user: 目标后 LLM 经
    send_card 确认门发送发货通知，见 prompts 规则）。
    """
    started = time.monotonic()
    if draft.status != "confirmed":
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {draft.status}，仅 confirmed 可提交"
        )

    adapter = get_adapter()
    fields, degraded = await _build_and_validate_finished(draft)

    created = await adapter.create_record(FINISHED_OUTBOUND_TABLE, fields)
    record_id = str(created.get("record_id") or "")
    if not record_id:
        raise WarehouseBitableError(
            "create_record 未返回 record_id", code="no_record_id"
        )

    check_result = await _verify_record(
        adapter,
        record_id,
        fields,
        table_key=FINISHED_OUTBOUND_TABLE,
        check_fields=FINISHED_CHECK_FIELDS,
    )
    check_result["written"] = dict(fields)
    check_result["record_id"] = record_id
    check_result["degraded"] = degraded

    # draft → submitted + target 回填（状态机迁移表已含 confirmed → submitted）
    from_status = draft.status
    draft.status = "submitted"
    meta = get_table_meta(FINISHED_OUTBOUND_TABLE)
    draft.target_base = meta["base_token"]
    draft.target_table = meta["table_id"]
    draft.target_record_id = record_id
    await db.flush()

    await repository.insert_agent_audit(
        db,
        tool_name="submit_outbound",
        args_summary={
            "draft_no": draft.draft_no,
            "record_id": record_id,
            "fields": sorted(fields.keys()),
            "degraded": degraded,
            "from": from_status,
            "to": "submitted",
        },
        result_status="ok",
        error_code=None if check_result["consistent"] else "mismatch",
        duration_ms=_elapsed_ms(started),
        draft_id=draft.id,
    )

    # 回执卡片（scene 分支渲染成品标题；cards 延迟 import 解模块环，同上）
    from app.modules.warehouse.agent.cards import render_receipt_result_card

    card = render_receipt_result_card(draft, check_result)
    await _send_result_card(draft, card)

    logger.info(
        "成品出库提交完成: draft_no=%s record_id=%s consistent=%s degraded=%s",
        draft.draft_no,
        record_id,
        check_result["consistent"],
        degraded,
    )
    if check_result["consistent"]:
        note = f"✅ 成品出库已登记：{draft.draft_no}（Base 记录 {record_id}）"
    else:
        count = len(check_result["mismatches"])
        note = (
            f"⚠ 成品出库已登记：{draft.draft_no}（Base 记录 {record_id}），"
            f"{count} 个字段读回不一致，请到 Base 核对"
        )
    # 快递推送引导（spec 决策 3）：登记了快递号 → 回执附「要推送给谁？」
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    express_no = str(aligned.get("express_no") or "").strip()
    if express_no:
        note += (
            f"\n📦 已登记快递号 {express_no}，要推送给谁？"
            "回复 group:群ID 或 user:open_id 可发送发货通知"
        )
    return note

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

**物料名称**写入 API 专用文本字段「物料名称(API)」（原「物料名称」单选
被 Base 侧字段级编辑限制拒写 1254062——2026-09-09 新建文本字段绕开，
人工补选列保留但不再使用）。

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
from difflib import SequenceMatcher
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
    # 供应商等长文本字段：选项集模糊容差（ratio≥0.85，处理公司名小差异
    # 如括号/后缀/空格）——数字/枚举类字段（短选项集）不受影响（ratio 低）
    if len(text) >= 6:
        best_opt, best_ratio = "", 0.0
        for opt in options:
            ratio = SequenceMatcher(None, lowered, opt.lower()).ratio()
            if ratio > best_ratio:
                best_opt, best_ratio = opt, ratio
        if best_ratio >= 0.85:
            return best_opt
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
    if name:
        # 物料名称写入 API 专用文本字段「物料名称(API)」（原单选被 Base 侧
        # 字段级编辑限制拒写，2026-09-09 新建绕开，不再降级）
        fields["物料名称(API)"] = str(name).strip()

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

    # ── 对齐产物直填（级别/型号、物料大类）：主数据对齐已有值，单选适配 ──
    for aligned_key, field_name in (
        ("level", "级别/型号(API)"),
        ("material_category", "物料大类"),
    ):
        v = str(aligned.get(aligned_key) or "").strip()
        if v:
            adapted = _select_or_skip(table_fields, field_name, v, degraded)
            if adapted:
                fields[field_name] = adapted

    # ── 物料批号（内部批号）规则生成：{代码}-{YYMMDD}（人工记录同款格式，
    # 如 10123-260902）；卡片确认后可改。代码缺失时不生成（降级人工）。
    if "物料批号" not in fields:
        gen_code = str(aligned.get("code") or "").strip()
        if gen_code:
            today = date.today()
            fields["物料批号"] = (
                f"{gen_code}-{today.strftime('%y%m%d')}"
            )

    # ── 是否加急检测：选项集只有「加急检测」一个值（默认态=留空）——
    # 非加急时不写该字段（空即默认），加急时由人工/识别标注。

    # ── 件数（送货单「总数量/件数」的件数部分，如 1404/14桶 的 14） ──
    pkg_count = value_of("package_count")
    if pkg_count is not None:
        fields["件数"] = str(pkg_count).strip()

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
        # 请验单附件列：识别原图即请验单/送货单照片本身（与外包装列同源，
        # 人工流程两张附件列挂同一张照片的形态）
        if attachment_token:
            fields["请验单"] = [{"file_token": attachment_token}]

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

    # 到货请验（V3.0 分期B 链路1）：登记成功自动推 QC 群；失败不影响登记
    await _fire_arrival_inspection(db, fields, record_id, meta)

    # 供应商不一致提醒（V3.0 分期C §4.3，AI 辅助核对口径）：失败不影响登记
    await _fire_supplier_mismatch(db, draft, fields, record_id, meta)

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
    # 快递推送（V3.0 分期A Ticket 08）：登记了快递号 → 自动推发货通知到
    # 事件型推送任务（express_notify）目标；任务停用/目标未配置时回落
    # 既有 group:/user: 交互指令（保留兼容）。
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    express_no = str(aligned.get("express_no") or "").strip()
    if express_no:
        pushed = await _fire_express_notify(db, aligned, express_no)
        if pushed:
            note += f"\n📦 发货通知已自动推送给配置目标（快递号 {express_no}）"
        else:
            note += (
                f"\n📦 已登记快递号 {express_no}，要推送给谁？"
                "回复 group:群ID 或 user:open_id 可发送发货通知"
            )
    return note


# ── 领料出库提交（V3.0 分期C Ticket 02，设计 §4.2）──
# scene=picking_outbound 确认回调真身（draft_flow._picking_submit_callback
# 薄包装）：aligned（含 FIFO picking_plan 快照，改批号后由工具侧重算）→
# 组装 material_outbound 写入字段 → validate → create_record → 读回核对
# （批号/数量/部门）→ submitted + 回执。领用日期=当天（毫秒时间戳）；
# 领用类型缺省生产使用；物料名称/单位等为 lookup/公式拒写（不在映射表）。

PICKING_OUTBOUND_TABLE = "material_outbound"

# 读回核对关键字段（spec：批号/数量/部门；批号写 API 专用文本字段）
PICKING_CHECK_FIELDS: tuple[str, ...] = ("物料批号(API)", "出库数量", "领用部门")

# canonical 键 → (Base 字段名, 是否单选)；quantity 数字化与批号/名称（API 文本
# 列）单独分支，领用日期恒写当天单独处理；picking_plan（结构化建议快照）不进映射
_PICKING_FIELD_MAP: tuple[tuple[str, str, bool], ...] = (
    ("use_type", "领用类型", True),
    ("department", "领用部门", True),
    ("remark", "备注", False),
)


async def _picking_table_fields() -> dict[str, FieldMeta]:
    """material_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    物料批号/领用类型/领用部门均为单选且 Base 侧持续追加选项——先
    refresh_table_fields 拉最新选项集（bitable_schema TTL 缓存内直用），
    刷新失败回落静态快照（登记主链路不因选项集刷新抖动中断）。
    """
    try:
        await get_adapter().refresh_table_fields(PICKING_OUTBOUND_TABLE)
    except Exception:  # noqa: BLE001 — 选项集刷新失败不阻断（回落静态快照）
        logger.warning("material_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(PICKING_OUTBOUND_TABLE)


def build_picking_fields(
    draft: WarehouseAgentDraft,
    *,
    table_fields: dict[str, FieldMeta] | None = None,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """draft.aligned（含 picking_plan）→ material_outbound 写入字段。

    返回 (fields, degraded)：degraded 为未写入字段名（单选值不在选项集 /
    数量非数字）。物料批号/物料名称写 API 专用文本字段（2026-09-21 新建——
    原单选列选项集不含新批次/部分物料，领料提交实测 degraded，GMP/入库
    「(API)」同款先例）；批号取用户指定批号或 FIFO 建议首批（跨批拆分的
    多批无法一行写完——写首批并把完整建议放回执，多批余量人工在 Base 拆
    行；2B 台账权威，本地不做拆行镜像）；领用日期恒写当天毫秒时间戳。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    fields: dict[str, Any] = {}
    degraded: list[str] = []

    # 领用类型默认生产使用（工具层为卡片展示同款默认；提交侧兜底，单一
    # 常量源在 tools/picking）。只读兜底、不回写 aligned（草稿 JSONB 保持
    # 工具/对话修改路径的唯一写入口）。
    from app.modules.warehouse.agent.tools.picking import PICKING_DEFAULT_USE_TYPE

    use_type = str(aligned.get("use_type") or "").strip() or PICKING_DEFAULT_USE_TYPE

    # 领用数量（picking_plan 首批承担量优先，与写入批号行严格一致）
    plan = aligned.get("picking_plan") if isinstance(aligned.get("picking_plan"), list) else []
    if plan:
        qty_value = plan[0].get("pick_qty")
    else:
        qty_value = aligned.get("quantity")
    num = _to_number(qty_value)
    if num is None:
        degraded.append("出库数量")
    else:
        fields["出库数量"] = num

    # 物料批号/物料名称：API 专用文本字段（纯文本直写，无选项集约束）
    batch = str(aligned.get("designated_batch") or "").strip()
    if not batch and plan:
        batch = str(plan[0].get("batch_no") or "").strip()
    if batch:
        fields["物料批号(API)"] = batch
    material_name = str(aligned.get("material_name") or "").strip()
    if material_name:
        fields["物料名称(API)"] = material_name

    for key, field_name, is_select in _PICKING_FIELD_MAP:
        if key == "use_type":
            value: Any = use_type  # 默认生产使用（局部兜底，不回写 aligned）
        else:
            value = aligned.get(key)
        if value is None or not str(value).strip():
            continue
        text = str(value).strip()
        if is_select:
            adapted = _select_or_skip(
                table_fields or get_table_fields(PICKING_OUTBOUND_TABLE),
                field_name,
                text,
                degraded,
            )
            if not adapted:
                continue
            text = adapted
        fields[field_name] = text

    fields["领用日期"] = _today_ms(today)
    return fields, degraded


async def _build_and_validate_picking(
    draft: WarehouseAgentDraft,
) -> tuple[dict[str, Any], list[str]]:
    """组装领料写入字段并跑写契约校验（刷新选项集后本地拦截）。

    校验与组装用同一份运行时刷新后的字段元数据（静态快照批号选项仅
    50 条而 Base 实测 1700+，直接按快照校验会误杀合法批号）。
    """
    table_fields = await _picking_table_fields()
    fields, degraded = build_picking_fields(draft, table_fields=table_fields)
    validate_write_fields(PICKING_OUTBOUND_TABLE, fields, table_fields=table_fields)
    return fields, degraded


async def submit_picking(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
    """领料提交：写契约 → create_record → 读回核对 → submitted + 回执。

    状态前置/异常语义与 submit_gmp 完全同款：非 confirmed 抛
    :class:`DraftFlowError`；写入异常向上抛（confirm 置 failed）；mismatch
    不算失败——draft 仍 submitted + audit error_code="mismatch" + 回执 ⚠。
    跨批拆分建议在回执中提示人工拆行（首批自动写入，2B 台账权威）。
    """
    started = time.monotonic()
    if draft.status != "confirmed":
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {draft.status}，仅 confirmed 可提交"
        )

    adapter = get_adapter()
    fields, degraded = await _build_and_validate_picking(draft)

    created = await adapter.create_record(PICKING_OUTBOUND_TABLE, fields)
    record_id = str(created.get("record_id") or "")
    if not record_id:
        raise WarehouseBitableError(
            "create_record 未返回 record_id", code="no_record_id"
        )

    check_result = await _verify_record(
        adapter,
        record_id,
        fields,
        table_key=PICKING_OUTBOUND_TABLE,
        check_fields=PICKING_CHECK_FIELDS,
    )
    check_result["written"] = dict(fields)
    check_result["record_id"] = record_id
    check_result["degraded"] = degraded

    # draft → submitted + target 回填（状态机迁移表已含 confirmed → submitted）
    from_status = draft.status
    draft.status = "submitted"
    meta = get_table_meta(PICKING_OUTBOUND_TABLE)
    draft.target_base = meta["base_token"]
    draft.target_table = meta["table_id"]
    draft.target_record_id = record_id
    await db.flush()

    await repository.insert_agent_audit(
        db,
        tool_name="submit_picking",
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

    # 回执卡片（scene 分支渲染领料标题；cards 延迟 import 解模块环，同上）
    from app.modules.warehouse.agent.cards import render_receipt_result_card

    card = render_receipt_result_card(draft, check_result)
    await _send_result_card(draft, card)

    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    plan: list[Any] = (
        list(aligned["picking_plan"])
        if isinstance(aligned.get("picking_plan"), list)
        else []
    )
    split_note = ""
    if len(plan) > 1:
        rest = "、".join(
            f"{item.get('batch_no')} x{item.get('pick_qty')}" for item in plan[1:]
        )
        split_note = f"\n📦 跨批拆分：首批已写入，余量（{rest}）请在 Base 拆行登记"

    logger.info(
        "领料提交完成: draft_no=%s record_id=%s consistent=%s degraded=%s",
        draft.draft_no,
        record_id,
        check_result["consistent"],
        degraded,
    )
    if check_result["consistent"]:
        note = f"✅ 领料已登记：{draft.draft_no}（Base 记录 {record_id}）{split_note}"
    else:
        count = len(check_result["mismatches"])
        note = (
            f"⚠ 领料已登记：{draft.draft_no}（Base 记录 {record_id}），"
            f"{count} 个字段读回不一致，请到 Base 核对{split_note}"
        )
    return note


def _express_payload(aligned: dict[str, Any], express_no: str) -> dict[str, Any]:
    """快递通知 payload（canonical 键对齐 FINISHED_FIELD_LABELS）。"""
    payload = {
        "product_name": aligned.get("product_name"),
        "product_batch_no": aligned.get("product_batch_no"),
        "quantity": aligned.get("quantity"),
        "unit": aligned.get("unit"),
        "customer": aligned.get("customer"),
        "express_no": express_no,
        "remark": aligned.get("remark"),
        "outbound_date": date.today().isoformat(),
    }
    return {k: v for k, v in payload.items() if v not in (None, "")}


async def _fire_express_notify(
    db: AsyncSession, aligned: dict[str, Any], express_no: str
) -> bool:
    """自动推送发货通知；返回是否送达（至少一个目标执行成功）。"""
    from app.modules.warehouse.push_center.events import fire_push_event

    try:
        results = await fire_push_event(
            db, "express_notify", _express_payload(aligned, express_no)
        )
    except Exception:  # noqa: BLE001 — 通知失败不影响出库登记结果
        logger.exception("快递发货通知自动推送异常（express_no=%s）", express_no)
        return False
    return any(r.status == "executed" for r in results)


# ── 到货请验（V3.0 分期B 链路1，设计 §4.1）：入库登记成功 → 自动推 QC 群 ──


def _receipt_record_url(meta: dict[str, str], record_id: str) -> str:
    """material_receipt 记录链接（手机一键打开台账行填取样/出报）。

    域名与安全模块一致走 env FEISHU_BASE_URL（默认 livzon 租户域）。
    """
    import os

    base_url = os.getenv("FEISHU_BASE_URL", "https://livzon.feishu.cn").rstrip("/")
    app_token = meta.get("base_token") or ""
    table_id = meta.get("table_id") or ""
    return f"{base_url}/base/{app_token}?table={table_id}&record={record_id}"


def _arrival_payload(
    fields: dict[str, Any], record_id: str, meta: dict[str, str]
) -> dict[str, Any]:
    """到货请验事件 payload：登记写入字段取业务五项 + 记录链接（空值剔除）。"""
    payload: dict[str, Any] = {}
    for key, field_name in (
        ("material_name", "物料名称(API)"),
        ("batch_no", "物料批号"),
        ("supplier", "供应商"),
        ("quantity", "入库数量"),
        ("unit", "单位"),
    ):
        value = fields.get(field_name)
        if value is not None and str(value).strip():
            payload[key] = value
    payload["record_url"] = _receipt_record_url(meta, record_id)
    return payload


async def _fire_arrival_inspection(
    db: AsyncSession,
    fields: dict[str, Any],
    record_id: str,
    meta: dict[str, str],
) -> bool:
    """自动推到货请验卡；返回是否送达（至少一个目标执行成功）。"""
    from app.modules.warehouse.push_center.events import fire_push_event

    try:
        results = await fire_push_event(
            db, "arrival_inspection", _arrival_payload(fields, record_id, meta)
        )
    except Exception:  # noqa: BLE001 — 通知失败不影响入库登记结果
        logger.exception("到货请验通知自动推送异常（record_id=%s）", record_id)
        return False
    return any(r.status == "executed" for r in results)


# ── 供应商不一致提醒（V3.0 分期C §4.3，AI 辅助核对口径）──


def _mismatch_payload(
    draft: WarehouseAgentDraft,
    fields: dict[str, Any],
    record_id: str,
    meta: dict[str, str],
) -> dict[str, Any] | None:
    """不一致提醒 payload（识别/主数据供应商两方对照；空值剔除，无识别供应商返回 None）。

    master_supplier 来自对齐 match_detail（mark_aligned 已并入 aligned）。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    supp = recognized.get("supplier")
    supplier_text = (
        str(supp.get("value") or "").strip() if isinstance(supp, dict) else ""
    )
    if not supplier_text:
        return None
    match_detail_raw = aligned.get("match_detail")
    match_detail: dict[str, Any] = (
        match_detail_raw if isinstance(match_detail_raw, dict) else {}
    )
    payload: dict[str, Any] = {
        "supplier": supplier_text,
        "master_supplier": str(match_detail.get("master_supplier") or "").strip(),
        "material_name": str(
            fields.get("物料名称(API)") or aligned.get("material_name") or ""
        ).strip(),
        "batch_no": str(fields.get("物料批号") or "").strip(),
        "record_url": _receipt_record_url(meta, record_id),
    }
    return payload


async def _fire_supplier_mismatch(
    db: AsyncSession,
    draft: WarehouseAgentDraft,
    fields: dict[str, Any],
    record_id: str,
    meta: dict[str, str],
) -> bool:
    """识别供应商与主数据对齐不一致 → 推提醒卡；返回是否送达。

    仅 supplier_matched 显式为 False（对齐器判定）且识别供应商非空时触发；
    推送失败只记日志不影响登记（同到货请验钩子语义）。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    if aligned.get("supplier_matched") is not False:
        return False
    payload = _mismatch_payload(draft, fields, record_id, meta)
    if payload is None:
        return False
    from app.modules.warehouse.push_center.events import fire_push_event

    try:
        results = await fire_push_event(db, "supplier_mismatch_alert", payload)
    except Exception:  # noqa: BLE001 — 通知失败不影响入库登记结果
        logger.exception("供应商不一致提醒推送异常（record_id=%s）", record_id)
        return False
    return any(r.status == "executed" for r in results)


# ── 成品入库提交（V3.0 §4.6：识别+对话双入口 → 写成品入库台账）──
# scene=finished_receipt 确认回调真身（draft_flow._finished_receipt_submit_callback
# 薄包装）：aligned（对话收集/修改，识别值经 value_of 回落 recognized）→ 组装
# finished_receipt 写入字段 → validate（运行时选项集注入）→ create_record →
# 读回核对（产品/批号/数量/单位）→ submitted + 回执。口径（grilling 拍板）：
# 质量状态恒写「待检」；入库日期识别值缺失默认今天（毫秒时间戳）；生产日期/
# 有效期为该表文本列（type 1）原样写；「入库车间」lookup 只读——车间写备注
# 前缀「入库车间：X」；件数/库存数量/包装规格不写。

FINISHED_RECEIPT_TABLE = "finished_receipt"

# 读回核对关键字段（spec：产品/批号/数量/单位）
FINISHED_RECEIPT_CHECK_FIELDS: tuple[str, ...] = ("产品名称", "产品批号", "入库数量", "单位")

# 质量状态默认（成品入库必经 QC；须在选项集内——快照含 待检）
FINISHED_RECEIPT_QUALITY_DEFAULT = "待检"

# canonical 键 → (Base 字段名, 是否单选)；quantity 数字化与入库日期（毫秒
# 时间戳、默认今天）单独分支；workshop 写备注前缀单独处理；生产日期/有效期
# 该表为文本列（type 1）原样写（不复用原辅料毫秒时间戳转换）
_FINISHED_RECEIPT_FIELD_MAP: tuple[tuple[str, str, bool], ...] = (
    ("product_name", "产品名称", True),
    ("product_batch_no", "产品批号", False),
    ("quantity", "入库数量", False),
    ("spec", "品规", True),
    ("unit", "单位", True),
    ("storage_location", "库区位置", False),
    ("produced_at", "生产日期", False),
    ("expiry", "有效期", False),
)


async def _finished_receipt_table_fields() -> dict[str, FieldMeta]:
    """finished_receipt 字段元数据（运行时选项集优先，静态快照兜底）。

    产品名称/品规/单位均为单选且 D 期快照未收录选项（options 为空）——
    必须 refresh_table_fields 拉真实选项集，否则收集期空集放行的值要到
    Base 侧 1254062 才暴露；刷新失败回落静态快照（登记主链路不中断）。
    """
    try:
        await get_adapter().refresh_table_fields(FINISHED_RECEIPT_TABLE)
    except Exception:  # noqa: BLE001 — 选项集刷新失败不阻断（回落静态快照）
        logger.warning("finished_receipt 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(FINISHED_RECEIPT_TABLE)


def build_finished_receipt_fields(
    draft: WarehouseAgentDraft,
    *,
    table_fields: dict[str, FieldMeta] | None = None,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """draft → finished_receipt 写入字段（aligned 优先，recognized 兜底）。

    返回 (fields, degraded)：degraded 为未写入字段名（单选值不在选项集 /
    数量非数字 / 入库日期不可解析）。识别路径 recognized 携带置信度、
    对话路径 aligned 即收集值——取值口径与 build_receipt_fields 同款
    （aligned 覆盖优先）。
    """
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    table_fields_snapshot = table_fields or get_table_fields(FINISHED_RECEIPT_TABLE)
    fields: dict[str, Any] = {}
    degraded: list[str] = []

    def value_of(key: str) -> Any:
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

    for key, field_name, is_select in _FINISHED_RECEIPT_FIELD_MAP:
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
            adapted = _select_or_skip(table_fields_snapshot, field_name, text, degraded)
            if not adapted:
                continue
            text = adapted
        fields[field_name] = text

    # 入库日期：识别/对话值 → 毫秒时间戳；缺失默认今天；不可解析降级默认今天
    receipt_date = value_of("receipt_date")
    receipt_ms: int | None = None
    if receipt_date is not None:
        receipt_ms = _parse_date_ms(str(receipt_date))
        if receipt_ms is None:
            degraded.append("入库日期")
    fields["入库日期"] = receipt_ms if receipt_ms is not None else _today_ms(today)

    # 质量状态恒写「待检」（成品入库必经 QC；grilling 拍板 2）
    fields["质量状态"] = FINISHED_RECEIPT_QUALITY_DEFAULT

    # 备注 = 车间前缀 + remark 拼接（「入库车间」列 lookup 只读，grilling 拍板 1）
    workshop = str(value_of("workshop") or "").strip()
    remark = str(value_of("remark") or "").strip()
    remark_parts = []
    if workshop:
        remark_parts.append(f"入库车间：{workshop}")
    if remark:
        remark_parts.append(remark)
    if remark_parts:
        fields["备注"] = "；".join(remark_parts)
    return fields, degraded


async def _build_and_validate_finished_receipt(
    draft: WarehouseAgentDraft,
) -> tuple[dict[str, Any], list[str]]:
    """组装成品入库写入字段并跑写契约校验（运行时选项集注入，picking 先例）。

    校验与组装用同一份刷新后字段元数据——D 期快照产品名称/品规/单位选项集
    为空，直接按静态快照校验等于不校验，非法值会拖到 Base 侧 1254062。
    """
    table_fields = await _finished_receipt_table_fields()
    fields, degraded = build_finished_receipt_fields(draft, table_fields=table_fields)
    validate_write_fields(FINISHED_RECEIPT_TABLE, fields, table_fields=table_fields)
    return fields, degraded


async def submit_finished_receipt(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
    """成品入库提交：写契约 → create_record → 读回核对 → submitted + 回执。

    状态前置/异常语义与 submit_picking 完全同款：非 confirmed 抛
    :class:`DraftFlowError`；写入异常向上抛（confirm 置 failed）；mismatch
    不算失败——draft 仍 submitted + audit error_code="mismatch" + 回执 ⚠。
    """
    started = time.monotonic()
    if draft.status != "confirmed":
        raise DraftFlowError(
            f"草稿 {draft.draft_no} 状态为 {draft.status}，仅 confirmed 可提交"
        )

    adapter = get_adapter()
    fields, degraded = await _build_and_validate_finished_receipt(draft)

    created = await adapter.create_record(FINISHED_RECEIPT_TABLE, fields)
    record_id = str(created.get("record_id") or "")
    if not record_id:
        raise WarehouseBitableError(
            "create_record 未返回 record_id", code="no_record_id"
        )

    check_result = await _verify_record(
        adapter,
        record_id,
        fields,
        table_key=FINISHED_RECEIPT_TABLE,
        check_fields=FINISHED_RECEIPT_CHECK_FIELDS,
    )
    check_result["written"] = dict(fields)
    check_result["record_id"] = record_id
    check_result["degraded"] = degraded

    # draft → submitted + target 回填（状态机迁移表已含 confirmed → submitted）
    from_status = draft.status
    draft.status = "submitted"
    meta = get_table_meta(FINISHED_RECEIPT_TABLE)
    draft.target_base = meta["base_token"]
    draft.target_table = meta["table_id"]
    draft.target_record_id = record_id
    await db.flush()

    await repository.insert_agent_audit(
        db,
        tool_name="submit_finished_receipt",
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

    # 回执卡片（scene 分支渲染成品入库标题；cards 延迟 import 解模块环，同上）
    from app.modules.warehouse.agent.cards import render_receipt_result_card

    card = render_receipt_result_card(draft, check_result)
    await _send_result_card(draft, card)

    logger.info(
        "成品入库提交完成: draft_no=%s record_id=%s consistent=%s degraded=%s",
        draft.draft_no,
        record_id,
        check_result["consistent"],
        degraded,
    )
    if check_result["consistent"]:
        note = f"✅ 成品入库已登记：{draft.draft_no}（Base 记录 {record_id}）"
    else:
        count = len(check_result["mismatches"])
        note = (
            f"⚠ 成品入库已登记：{draft.draft_no}（Base 记录 {record_id}），"
            f"{count} 个字段读回不一致，请到 Base 核对"
        )
    return note

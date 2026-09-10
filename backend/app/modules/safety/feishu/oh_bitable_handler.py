"""职业健康（OH）多维表格 6 表实时镜像事件处理器。

监听 OH 文档（单 app_token）6 张业务表：
人员汇总 / 体检记录 / 岗位信息 / 危害因素 PPE / 转岗离岗申请 / 新员工登记，
created / changed / deleted 三事件实时镜像到平台 oh_* 表。

- 事件按 table_id → table_kind 分发（oh_tables() 反查）
- 防循环四件套：_set_sync_ignore（平台回写前必调）/ Redis 60s 去重 /
  INSERT 互斥锁（redis lock）/ PG advisory lock（并发创建兜底）
- exam_registry 镜像时按 姓名+身份证 关联 oh_persons（platform 侧查询，不回源 Bitable）
- 体检报告附件三级下载：URL（预签名）→ file_token（Drive）→ extra（bitablePerm）
- 活行 upsert（WHERE is_deleted=false）；软删清唯一键
- 来源表联动（D7）：new_employee / exam_application created → create_from_source
  自动建体检记录（流程状态=未体检，source_table+source_record_id 溯源，uq_oh_exams_source 幂等）；
  exam_application 申请状态=已通过 → 差异分析更新已建登记（不新建）；
  已拒绝/已取消/已终止/已撤回 → 软删关联体检记录
- AI 触发钩子（ticket 04）+ 总表回填钩子（ticket 08：体检记录变更 → 人员汇总表回填），
  本文件只做数据对齐，不触发 AI / 通知

字段映射见 backend-design.md §三.5；危害因素多选 Bitable 已是标准名，直接落 JSON 列表。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import select, text, update

from app.core.database import async_session_factory
from app.modules.safety.attachment_store import store_bytes
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu import bitable_handler as bh
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import (
    OhExamApplication,
    OhHazardFactor,
    OhHealthExam,
    OhPerson,
    OhPosition,
)

logger = logging.getLogger(__name__)

# ── 连接配置（配置中心 store：DB 行 → registry 默认，backend-design §5.1）──
# 单 app_token 单文档 6 表；kind→table_id 映射函数内读 store 现场构建（改表 ID 即生效）


def oh_tables() -> dict[str, str]:
    """kind → table_id（启用连接；事件过滤与同步分派）。"""
    return {v.kind: v.table_id for v in store.get_connections("oh") if v.enabled}


def _oh_conn(kind: str) -> ConnectionView | None:
    """单 kind 连接视图（store：DB 活行 → registry 默认；missing 返回 None）。"""
    return store.get_connection("oh", kind)


def _get_oh_app_token() -> str:
    """OH 文档 app_token（6 表共用同一文档，取任一启用连接；未配置返回空串）。"""
    for v in store.get_connections("oh"):
        if v.app_token:
            return v.app_token
    return ""


def _get_oh_table_id(kind: str) -> str:
    """单 kind table_id；未配置/停用返回空串（handler 走现有降级分支）。"""
    conn = _oh_conn(kind)
    return conn.table_id if conn and conn.status != "disabled" else ""


# table_id → kind 反查（用于 bitable.record.* 事件，事件里通常不含 app token）
def table_kind_by_id(table_id: str) -> str | None:
    for kind, tid in oh_tables().items():
        if table_id and table_id == tid:
            return kind
    return None


# ── 枚举映射 ──

# 体检类别脏值（12 种）→ 5 标准枚举；未匹配 → None（设计 §三.5）
_EXAM_TYPE_MAP: dict[str, str] = {
    "岗前": "pre_employment",
    "新员工": "pre_employment",
    "在岗": "periodic",
    "在岗期间": "periodic",
    "在职": "periodic",
    "年度": "periodic",
    "离岗": "post_employment",
    "离职": "post_employment",
    "转岗": "transfer",
    "调岗": "transfer",
    "应急": "emergency",
    "特殊情况": "emergency",
}

# 在岗状态（原「最后体检状态」更名）→ work_status
_WORK_STATUS_MAP: dict[str, str] = {
    "在岗": "on_post",
    "离岗": "off_post",
    "岗前": "pre_employment",
    "转岗": "transfer",
}

# 体检记录表 流程状态 → status（机器状态，兼容旧前端）
_REGISTRY_FLOW_STATUS_MAP: dict[str, str] = {
    "未体检": "pending",
    "已体检": "completed",
}

_PAPER_KEPT_MAP: dict[str, str] = {"是": "yes", "否": "no"}

# 申请表申请状态「已删除」→ 软删除该镜像记录
_APPLY_STATUS_DELETED = "已删除"

# 申请表申请状态 ∈ 拒绝集 → 软删关联体检记录（D7：来源联动反向）
_APPLY_STATUS_REJECT: set[str] = {"已拒绝", "已取消", "已终止", "已撤回"}

# 申请表脏字段（备案残留等，镜像忽略主字段后兜底进 bt_extra）
_APPLY_DIRTY_FIELDS: tuple[str, ...] = (
    "备案证号", "品名", "备案数量", "单位（1）", "有效期",
    "核准次数", "供货商", "合同编号", "备案证状态", "SourceID",
)


# ── 值提取辅助 ──


def _rich(value: Any) -> str:
    """富文本 / 公式包装 / 普通字符串统一提取纯文本。

    兼容 Bitable 富文本 [{"type":"text","text":"..."}]、
    公式包装 {"type":1,"value":[{"text":"19"}]}、
    年龄 {"type":2,"value":[21]} 与纯字符串。
    """
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "") or ""))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _text(value: Any) -> str:
    """文本 / 单选 / 字符串数组统一提取（多选逗号拼接，兼容 `_extract_select_values`）。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return _rich(value)
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return ""


def _multi_list(value: Any) -> list[str]:
    """多选字段 → 字符串列表（Bitable 值形如 ["噪声","氨"]）。"""
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text_val = str(item.get("text", "") or "").strip()
        else:
            text_val = str(item).strip()
        if text_val:
            out.append(text_val)
    return out


def _clean_hazard_factors(value: Any) -> list[str] | None:
    """危害因素多选 → 去重后的标准名列表；空返回 None（不覆盖平台已有值）。"""
    items = _multi_list(value)
    if not items:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _formula_float(value: Any) -> float | None:
    """公式数字字段（如 总工龄（年）{"type":1,"value":[{"text":"19"}]}）→ float。"""
    text_val = _rich(value)
    if not text_val:
        return None
    try:
        return float(text_val)
    except (ValueError, TypeError):
        return None


def _work_years(value: Any) -> float | None:
    """解析 'X年Y月'（体检记录表 总工龄/接害工龄）→ 年.月折算 float。"""
    text_val = _rich(value)
    if not text_val:
        return None
    m = re.search(r"(\d+)\s*年", text_val)
    n = re.search(r"(\d+)\s*月", text_val)
    if not m and not n:
        return None
    years = int(m.group(1)) if m else 0
    months = int(n.group(1)) if n else 0
    return round(years + months / 12.0, 2)


def _person(value: Any) -> dict[str, str]:
    """Bitable person 字段 → {"name","id","email"}（复用 bitable_handler）。"""
    return bh._extract_person_info(value)


def _ms(value: Any) -> Any:
    """DateTime 字段 → datetime（复用 bitable_handler._ms_to_datetime）。"""
    return bh._ms_to_datetime(value)


def _url_text(value: Any) -> str:
    """Url 字段（如 申请编号 {"text":..,"link":..}）→ 纯文本。"""
    if isinstance(value, dict):
        return (value.get("text") or "").strip()
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return (value[0].get("text") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _yes_no(value: Any) -> bool | None:
    """是否已同步汇总表（是/否）→ bool。"""
    text_val = _text(value)
    if text_val == "是":
        return True
    if text_val == "否":
        return False
    return None


def _paper_kept(value: Any) -> str | None:
    """纸质报告留存（是/否）→ yes/no。"""
    return _PAPER_KEPT_MAP.get(_text(value))


def _attachment_meta(value: Any) -> list[dict] | None:
    """附件字段 → [{name,file_token,size,type}]（不落 url/tmp_url，避免敏感链接持久化）。"""
    if not isinstance(value, list):
        return None
    metas: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            metas.append({
                "name": item.get("name", ""),
                "file_token": item.get("file_token", ""),
                "size": item.get("size"),
                "type": item.get("type"),
            })
    return metas or None


def _link_record_ids(value: Any) -> list[str]:
    """link 字段 {"link_record_ids": ["rec..."]} → record_id 列表。"""
    if isinstance(value, dict):
        ids = value.get("link_record_ids") or []
        if isinstance(ids, list):
            return [str(i) for i in ids if i]
    return []


# ── 5 表字段映射（纯函数，无副作用）──


def map_person_master_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """人员汇总表 → OhPerson dict。

    Returns:
        dict — 可直接用于创建/更新 OhPerson；
        None — 无姓名（脏数据），调用方跳过（不软删）。
    """
    person = _person(fields.get("姓名"))
    name = person["name"] or _rich(fields.get("姓名（文本）"))
    if not name:
        logger.warning("OH 人员汇总记录无姓名，跳过: fields=%s", list(fields.keys())[:8])
        return None

    mapped: dict[str, Any] = {"name": name}
    if person["id"]:
        mapped["open_id"] = person["id"]

    employee_no = _rich(fields.get("姓名.工号"))
    if employee_no:
        mapped["employee_no"] = employee_no

    id_card_no = _rich(fields.get("身份证号码"))
    if id_card_no:
        mapped["id_card_no"] = id_card_no

    department = _text(fields.get("姓名.部门"))
    if department:
        mapped["department"] = department

    position = _rich(fields.get("岗位"))
    if position:
        mapped["position"] = position

    gender = _rich(fields.get("性别"))
    if gender:
        mapped["gender"] = gender

    marital_status = _text(fields.get("婚姻状况"))
    if marital_status:
        mapped["marital_status"] = marital_status

    phone = _rich(fields.get("手机号码"))
    if phone:
        mapped["phone"] = phone

    # 总工龄 / 接害工龄：年 + 月 公式合并折算
    years = _formula_float(fields.get("总工龄（年）"))
    months = _formula_float(fields.get("总工龄（月）"))
    if years is not None or months is not None:
        mapped["total_work_years"] = round((years or 0) + (months or 0) / 12.0, 2)
    years = _formula_float(fields.get("接害工龄（年）"))
    months = _formula_float(fields.get("接害工龄（月）"))
    if years is not None or months is not None:
        mapped["hazard_exposure_years"] = round((years or 0) + (months or 0) / 12.0, 2)

    # 体检类别脏值 → 标准枚举（未匹配 → None）
    last_exam_type = _EXAM_TYPE_MAP.get(_rich(fields.get("体检类别")))
    if last_exam_type:
        mapped["last_exam_type"] = last_exam_type

    work_status = _WORK_STATUS_MAP.get(_text(fields.get("在岗状态")))
    if work_status:
        mapped["work_status"] = work_status

    last_exam_at = _ms(fields.get("最后一次体检时间"))
    if last_exam_at:
        mapped["last_exam_at"] = last_exam_at

    hazard_factors = _clean_hazard_factors(fields.get("接触危害因素"))
    if hazard_factors:
        mapped["hazard_factors"] = hazard_factors

    safety_officer = _person(fields.get("安全员"))["name"]
    if safety_officer:
        mapped["safety_officer"] = safety_officer

    # 体检记录 link（P0 新增）→ exam_record_ids：handler 内按 platform 侧反查后回填
    return mapped


def map_exam_registry_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """体检记录表 → OhHealthExam dict。

    Returns:
        dict — 可直接用于创建/更新 OhHealthExam；
        None — 无姓名，调用方跳过。
    """
    name = _rich(fields.get("姓名"))
    if not name:
        logger.warning("OH 体检记录无姓名，跳过: fields=%s", list(fields.keys())[:8])
        return None

    mapped: dict[str, Any] = {"employee_name": name}

    exam_no = _rich(fields.get("体检号"))
    if exam_no:
        mapped["exam_no"] = exam_no

    id_card_no = _rich(fields.get("身份证号码"))
    if id_card_no:
        mapped["id_card_no"] = id_card_no

    # 体检类型（E4 回填）→ 5 标准枚举；未知/空 → periodic 兜底（模型 NOT NULL）
    exam_type = _EXAM_TYPE_MAP.get(_text(fields.get("体检类型")))
    if not exam_type:
        source_table = _rich(fields.get("Source Table"))
        exam_type = _EXAM_TYPE_MAP.get(source_table, "periodic")
    mapped["exam_type"] = exam_type

    # 流程状态（未体检→pending / 已体检→completed），空 → 不覆盖（默认 pending）
    status = _REGISTRY_FLOW_STATUS_MAP.get(_text(fields.get("流程状态")))
    if status:
        mapped["status"] = status

    gender = _text(fields.get("性别"))
    if gender:
        mapped["gender"] = gender

    marital_status = _text(fields.get("婚姻状况"))
    if marital_status:
        mapped["marital_status"] = marital_status

    age = _formula_float(fields.get("年龄"))
    if age is not None:
        mapped["age"] = int(age)

    phone = _text(fields.get("电话"))
    if phone:
        mapped["phone"] = phone

    department = _text(fields.get("部门"))
    if department:
        mapped["department"] = department

    position = _rich(fields.get("岗位"))
    if position:
        mapped["position"] = position

    scheduled_date = _ms(fields.get("登记时间"))
    if scheduled_date:
        mapped["scheduled_date"] = scheduled_date

    exam_date = _ms(fields.get("体检时间"))
    if exam_date:
        mapped["exam_date"] = exam_date

    report_date = _ms(fields.get("报告日期"))
    if report_date:
        mapped["report_date"] = report_date

    total_work_years = _work_years(fields.get("总工龄"))
    if total_work_years is not None:
        mapped["total_work_years"] = total_work_years

    hazard_exposure_years = _work_years(fields.get("接害工龄"))
    if hazard_exposure_years is not None:
        mapped["hazard_exposure_years"] = hazard_exposure_years

    hazard_factors = _clean_hazard_factors(fields.get("危害因素"))
    if hazard_factors:
        mapped["hazard_factors"] = hazard_factors

    protection_measures = _rich(fields.get("防护措施"))
    if protection_measures:
        mapped["protection_measures"] = protection_measures

    attachments = _attachment_meta(fields.get("体检报告附件"))
    if attachments:
        mapped["attachments"] = attachments

    exam_result = _rich(fields.get("体检结果"))
    if exam_result:
        mapped["exam_result"] = exam_result

    exam_conclusion = _rich(fields.get("检查结论"))
    if exam_conclusion:
        mapped["exam_conclusion"] = exam_conclusion

    treatment_advice_raw = _rich(fields.get("处理意见"))
    if treatment_advice_raw:
        mapped["treatment_advice_raw"] = treatment_advice_raw

    paper_report_kept = _paper_kept(fields.get("纸质报告留存"))
    if paper_report_kept:
        mapped["paper_report_kept"] = paper_report_kept

    synced_to_summary = _yes_no(fields.get("是否已同步汇总表"))
    if synced_to_summary is not None:
        mapped["synced_to_summary"] = synced_to_summary

    source_table = _rich(fields.get("Source Table"))
    if source_table:
        mapped["source_table"] = source_table

    source_record_id = _rich(fields.get("Source Record ID"))
    if source_record_id:
        mapped["source_record_id"] = source_record_id

    ai_interpretation = _rich(fields.get("AI智能解读"))
    if ai_interpretation:
        mapped["ai_interpretation"] = ai_interpretation

    exam_agency = _text(fields.get("体检机构"))
    if exam_agency:
        mapped["exam_agency"] = exam_agency

    return mapped


def map_position_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """岗位信息表 → OhPosition dict。部门/岗位均空 → None（跳过）。"""
    department = _rich(fields.get("部门"))
    position = _rich(fields.get("岗位"))
    if not department and not position:
        logger.warning("OH 岗位记录部门/岗位均空，跳过: fields=%s", list(fields.keys())[:8])
        return None

    mapped: dict[str, Any] = {}
    if department:
        mapped["department"] = department
    if position:
        mapped["position"] = position

    job_title = _rich(fields.get("职务"))
    if job_title:
        mapped["job_title"] = job_title

    hazard_factors = _clean_hazard_factors(fields.get("危害因素"))
    if hazard_factors:
        mapped["hazard_factors"] = hazard_factors
    mapped["hazard_factors_status"] = "filled" if hazard_factors else "empty"

    return mapped


def map_hazard_factor_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """危害因素 PPE 表 → OhHazardFactor dict。无标准名 → None（跳过）。"""
    factor_name = _rich(fields.get("危害因素名称"))
    if not factor_name:
        logger.warning("OH 危害因素记录无名称，跳过: fields=%s", list(fields.keys())[:8])
        return None

    mapped: dict[str, Any] = {"factor_name": factor_name.strip()}
    ppe_respiratory = _rich(fields.get("呼吸防护用品"))
    if ppe_respiratory:
        mapped["ppe_respiratory"] = ppe_respiratory
    return mapped


def _clean_gender(value: Any) -> str | None:
    """性别脏值清洗：男/女 → 标准；「未婚」等无法判断 → None（设计 §2.3 D12）。"""
    text_val = _text(value)
    if text_val in ("男", "女"):
        return text_val
    if text_val:
        logger.info("OH 性别脏值清洗（无法判断置空）: %r", text_val)
    return None


def _clean_id_card(value: Any) -> str:
    """身份证号码清洗：脏值形如 'xxx,xxx'（逗号/顿号拼接）→ 取首 token（设计 D3）。"""
    text_val = _rich(value)
    if not text_val:
        return ""
    return re.split(r"[,，、;；\s]+", text_val, maxsplit=1)[0].strip()[:32]


def map_new_employee_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """新员工登记表（来源表①）→ 联动 payload（不建平台表，仅提取字段供 create_from_source）。

    Returns:
        dict — 含 employee_name/id_card_no/部门/工种/登记时间/体检时间/检查结论/处理意见等；
        None — 无姓名（脏数据），调用方跳过。
    """
    name = _rich(fields.get("姓名"))
    if not name:
        logger.warning("OH 新员工登记无姓名，跳过: fields=%s", list(fields.keys())[:8])
        return None

    mapped: dict[str, Any] = {"employee_name": name}

    id_card_no = _clean_id_card(fields.get("身份证号码"))
    if id_card_no:
        mapped["id_card_no"] = id_card_no

    phone = _text(fields.get("电话"))
    if phone:
        mapped["phone"] = phone

    gender = _clean_gender(fields.get("性别"))
    if gender:
        mapped["gender"] = gender

    marital_status = _text(fields.get("婚姻状况"))
    if marital_status:
        mapped["marital_status"] = marital_status

    department = _text(fields.get("部门"))
    if department:
        mapped["department"] = department

    position = _text(fields.get("工种"))
    if position:
        mapped["position"] = position

    scheduled_date = _ms(fields.get("登记时间"))
    if scheduled_date:
        mapped["scheduled_date"] = scheduled_date

    exam_date = _ms(fields.get("体检时间"))
    if exam_date:
        mapped["exam_date"] = exam_date

    exam_conclusion = _rich(fields.get("检查结论"))
    if exam_conclusion:
        mapped["exam_conclusion"] = exam_conclusion

    treatment_advice_raw = _rich(fields.get("处理意见"))
    if treatment_advice_raw:
        mapped["treatment_advice_raw"] = treatment_advice_raw

    notes = _rich(fields.get("备注"))
    if notes:
        mapped["notes"] = notes

    # 入职时间（Q2 用户决策：changed 事件触发 work_status 岗前→在岗）。
    # 「入职时间」优先，「工作年限（第一份工作入职时间）」兜底（均为日期字段）；
    # OhPerson 无对应日期列，建档时忽略日期，仅作事件触发条件。
    hire_date = _ms(fields.get("入职时间"))
    if hire_date:
        mapped["hire_date"] = hire_date
    first_job_date = _ms(fields.get("工作年限（第一份工作入职时间）"))
    if first_job_date:
        mapped["first_job_date"] = first_job_date

    # 总工龄（公式 "X年Y月"）→ total_work_years（建档带入）
    total_work_years = _work_years(fields.get("总工龄"))
    if total_work_years is not None:
        mapped["total_work_years"] = total_work_years

    flow_status = _text(fields.get("流程状态"))
    if flow_status:
        mapped["flow_status"] = flow_status

    return mapped


def map_exam_application_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """转岗离岗申请表 → OhExamApplication dict。

    Returns:
        dict — 可直接用于创建/更新 OhExamApplication；
        None — 申请状态为「已删除」，调用方应软删除/跳过该记录。
    """
    apply_status = _text(fields.get("申请状态"))
    if apply_status == _APPLY_STATUS_DELETED:
        return None

    mapped: dict[str, Any] = {}
    if apply_status:
        mapped["apply_status"] = apply_status

    application_no = _url_text(fields.get("申请编号"))
    if application_no:
        mapped["application_no"] = application_no

    approval_flow = _text(fields.get("审批流程"))
    if approval_flow:
        mapped["approval_flow"] = approval_flow

    approval_node = _rich(fields.get("审批节点"))
    if approval_node:
        mapped["approval_node"] = approval_node

    current_handler = _person(fields.get("当前处理人"))["name"]
    if current_handler:
        mapped["current_handler"] = current_handler

    initiator_name = _person(fields.get("发起人"))["name"]
    if initiator_name:
        mapped["initiator_name"] = initiator_name

    submitted_at = _ms(fields.get("发起时间"))
    if submitted_at:
        mapped["submitted_at"] = submitted_at

    completed_at = _ms(fields.get("完成时间"))
    if completed_at:
        mapped["completed_at"] = completed_at

    # 体检类型（离岗体检/转岗体检）→ exam_type + transfer_type
    exam_type = _text(fields.get("体检类型"))
    if exam_type:
        mapped["exam_type"] = exam_type
        if "离岗" in exam_type:
            mapped["transfer_type"] = "post_employment"
        elif "转岗" in exam_type:
            mapped["transfer_type"] = "transfer"

    employee_name = _person(fields.get("姓名"))["name"] or _rich(fields.get("姓名"))
    if employee_name:
        mapped["employee_name"] = employee_name

    id_card_no = _rich(fields.get("身份证号码"))
    if id_card_no:
        mapped["id_card_no"] = id_card_no

    department = _text(fields.get("部门"))
    if department:
        mapped["department"] = department

    position = _text(fields.get("工种"))
    if position:
        mapped["position"] = position

    new_department = _text(fields.get("转入部门"))
    if new_department:
        mapped["new_department"] = new_department

    new_position = _text(fields.get("转入岗位"))
    if new_position:
        mapped["new_position"] = new_position

    transfer_date = _ms(fields.get("转岗日期"))
    if transfer_date:
        mapped["transfer_date"] = transfer_date

    leave_date = _ms(fields.get("离岗日期"))
    if leave_date:
        mapped["leave_date"] = leave_date

    dept_safety_officer = _person(fields.get("部门安全员"))["name"] or _text(fields.get("部门安全员"))
    if dept_safety_officer:
        mapped["dept_safety_officer"] = dept_safety_officer

    applicant_name = _person(fields.get("申请人"))["name"]
    if applicant_name:
        mapped["applicant_name"] = applicant_name

    apply_date = _ms(fields.get("申请日期"))
    if apply_date:
        mapped["apply_date"] = apply_date

    # 备案残留等脏字段 → bt_extra 兜底
    bt_extra: dict[str, Any] = {}
    for label in _APPLY_DIRTY_FIELDS:
        val = _rich(fields.get(label))
        if val:
            bt_extra[label] = val
    if bt_extra:
        mapped["bt_extra"] = bt_extra

    return mapped


_MAPPERS: dict[str, Any] = {
    "person_master": map_person_master_fields,
    "exam_registry": map_exam_registry_fields,
    "position": map_position_fields,
    "hazard_factor": map_hazard_factor_fields,
    "exam_application": map_exam_application_fields,
    "new_employee": map_new_employee_fields,
}

_MODEL_BY_KIND: dict[str, Any] = {
    "person_master": OhPerson,
    "exam_registry": OhHealthExam,
    "position": OhPosition,
    "hazard_factor": OhHazardFactor,
    "exam_application": OhExamApplication,
}


def get_mapper(table_kind: str | None):
    """按表类型返回映射函数。"""
    return _MAPPERS.get(table_kind)


# ── 订阅（飞书要求必须先调用 subscribe，Bitable 事件才会推送）──


async def ensure_oh_bitable_subscribed() -> bool:
    """订阅职业健康 OH 多维表格云文档事件（单文档订阅，6 表共用）。

    app_token 从配置中心 store 读取（``store.get_connection("oh", kind)``），
    启用且非空才订阅，去重后最多 1 次调用。
    """
    app_tokens: list[str] = []
    for kind in (
        "person_master", "exam_registry", "position",
        "hazard_factor", "exam_application", "new_employee",
    ):
        conn = store.get_connection("oh", kind)
        if conn is None or not conn.enabled:
            continue
        if conn.app_token and conn.app_token not in app_tokens:
            app_tokens.append(conn.app_token)

    if not app_tokens:
        logger.info("职业健康 Bitable app_token 未配置，跳过文档事件订阅")
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
                    logger.info("职业健康 Bitable 文档事件订阅成功: file_token=%s", app_token)
                else:
                    all_ok = False
                    logger.error(
                        "职业健康 Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                        data.get("code"), data.get("msg"), app_token,
                    )
        return all_ok
    except Exception:
        logger.exception("职业健康 Bitable 文档事件订阅异常")
        return False


# ── 平台侧 upsert / 软删 ──


def _apply_values(obj: Any, values: dict[str, Any]) -> None:
    """将映射字段应用到已有对象（None 跳过；AI智能解读平台已确认则不改写 D10）。"""
    for key, val in values.items():
        if val is None:
            continue
        # D10：存量 AI智能解读非空视为人工已确认，镜像不改写
        if key == "ai_interpretation" and getattr(obj, "ai_interpretation", None):
            continue
        setattr(obj, key, val)


async def _create_guarded(model: Any, values: dict[str, Any], record_id: str) -> Any | None:
    """INSERT 并发兜底：Redis 互斥锁 + PG advisory lock + 唯一索引冲突回退。"""
    from sqlalchemy.exc import IntegrityError

    from app.core.redis import redis_client

    # 1. Redis INSERT 互斥锁（120s）
    lock_key = f"bitable:lock:insert:{record_id}"
    try:
        if not await redis_client.set(lock_key, "1", ex=120, nx=True):
            logger.info("职业健康 INSERT 互斥锁已存在，跳过创建: record_id=%s", record_id)
            return None
    except Exception:
        pass  # Redis 不可用 → 降级，依赖 advisory lock + 唯一索引兜底

    # 2. PG advisory lock（显式事务保证同一连接；非阻塞尝试，失败则等待）
    lock_id = bh._compute_advisory_lock_id(record_id)
    guard_session = async_session_factory()
    try:
        trans = await guard_session.begin()
        try:
            acquired = (
                await guard_session.execute(
                    text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}
                )
            ).scalar()
            if not acquired:
                await guard_session.execute(
                    text("SET LOCAL lock_timeout = '120s'; SELECT pg_advisory_lock(:id)"),
                    {"id": lock_id},
                )
        except Exception:
            pass  # advisory lock 不可用 → 降级
        existing = await guard_session.scalar(
            select(model).where(
                model.feishu_record_id == record_id,
                model.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            await trans.rollback()
            await guard_session.close()
            return existing
        await trans.commit()
        await guard_session.close()
    except Exception:
        try:
            await guard_session.rollback()
        except Exception:
            pass
        await guard_session.close()

    # 3. INSERT（部分唯一索引 feishu_record_id 最终兜底）
    session = async_session_factory()
    try:
        obj = model(**values)
        session.add(obj)
        await session.flush()
        await session.commit()
        return obj
    except IntegrityError:
        await session.rollback()
        logger.warning(
            "职业健康 feishu_record_id 唯一约束冲突（并发创建），获取已有记录: %s", record_id
        )
        return await session.scalar(
            select(model).where(
                model.feishu_record_id == record_id,
                model.is_deleted == False,  # noqa: E712
            )
        )
    finally:
        await session.close()


async def _soft_delete(kind: str, record_id: str) -> None:
    """软删除 Bitable 来源记录，并清空唯一键（软删铁律：防重复添加→删除→添加隐形 bug）。

    hazard_factor 的 factor_name 为 NOT NULL，且部分唯一索引以 is_deleted=false 过滤，
    无需清键（也无键可清）。
    """
    model = _MODEL_BY_KIND.get(kind)
    if model is None:
        return
    clear_values: dict[str, Any] = {}
    if kind == "person_master":
        clear_values = {"id_card_no": None, "employee_no": None}
    elif kind == "exam_registry":
        clear_values = {"exam_no": None, "feishu_record_id": None}
    elif kind == "position":
        clear_values = {"department": None, "position": None}
    elif kind == "exam_application":
        clear_values = {"application_no": None, "feishu_record_id": None}

    async with async_session_factory() as session:
        result = await session.execute(
            update(model)
            .where(
                model.feishu_record_id == record_id,
                model.source == "bitable",
                model.is_deleted == False,  # noqa: E712
            )
            .values(is_deleted=True, **clear_values)
        )
        await session.commit()
        if result.rowcount:
            logger.info("职业健康已软删除: kind=%s record_id=%s", kind, record_id)


# ── 关联与附件 ──


async def _link_person(session, exam: OhHealthExam, fields: dict[str, Any]) -> None:
    """体检记录按 姓名+身份证 关联 oh_persons（platform 侧查询，勿重复调用 Bitable）。

    匹配策略：姓名+身份证 精确匹配（98% 覆盖）；身份证缺失时按姓名唯一匹配兜底。
    """
    if not exam.employee_name:
        return
    person = None
    if exam.id_card_no:
        person = await session.scalar(
            select(OhPerson).where(
                OhPerson.name == exam.employee_name,
                OhPerson.id_card_no == exam.id_card_no,
                OhPerson.is_deleted == False,  # noqa: E712
            )
        )
    if person is None:
        rows = (
            await session.execute(
                select(OhPerson).where(
                    OhPerson.name == exam.employee_name,
                    OhPerson.is_deleted == False,  # noqa: E712
                )
            )
        ).scalars().all()
        if len(rows) == 1:
            person = rows[0]
    if person is not None and exam.person_id != person.id:
        exam.person_id = person.id
        await session.commit()
        logger.info("体检记录 person 关联: exam=%s person=%s", exam.id, person.id)


async def _resolve_person_links(session, person: OhPerson, fields: dict[str, Any]) -> None:
    """人员汇总「体检记录」link → 平台 oh_health_exams.id 数组（platform 侧反查）。"""
    link_ids = _link_record_ids(fields.get("体检记录"))
    if not link_ids:
        return
    resolved: list[str] = []
    for record_id in link_ids:
        exam_id = await session.scalar(
            select(OhHealthExam.id).where(
                OhHealthExam.feishu_record_id == record_id,
                OhHealthExam.is_deleted == False,  # noqa: E712
            )
        )
        if exam_id:
            resolved.append(str(exam_id))
    if resolved and resolved != person.exam_record_ids:
        person.exam_record_ids = resolved
        await session.commit()
        logger.info("人员体检记录 link 回填: person=%s exams=%d", person.id, len(resolved))


async def _download_exam_attachments(
    session, exam: OhHealthExam, fields: dict[str, Any]
) -> None:
    """体检报告附件三级下载：URL（预签名）→ file_token（Drive）→ extra（bitablePerm）。

    下载成功后写入 attachment_paths（store_bytes 返回值：MinIO key / 本地相对路径）
    + attachments（元数据，仅 name/file_token/size/type，不含 url/tmp_url）。
    """
    # 下载需要原始附件 dict（含预签名 url/tmp_url），直接从 Bitable 字段提取；
    # 落库元数据用 _attachment_meta（已剔除 url/tmp_url）
    raw_attachments = fields.get("体检报告附件")
    if not isinstance(raw_attachments, list):
        return
    raw_list = [a for a in raw_attachments if isinstance(a, dict) and a.get("file_token")]
    if not raw_list:
        return

    conn = _oh_conn("exam_registry")
    if conn is None or not conn.enabled:
        return
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    field_id: str | None = None
    saved: list[str] = []
    for att in raw_list:
        file_token = att.get("file_token", "")
        file_name = att.get("name", "") or (file_token[:12] if file_token else "unknown")
        data: bytes | None = None

        # 1. Bitable API 预签名 url（含 extra，内部处理 auth/no-auth 重试）
        url = att.get("url") or att.get("tmp_url")
        if url:
            try:
                data = await client.download_attachment_from_url(url)
            except Exception:
                logger.exception("OH 附件 URL 下载异常: token=%s", file_token)

        # 2. file_token 直连 Drive media API
        if not data and file_token:
            try:
                data = await client.download_attachment(file_token)
            except Exception:
                logger.exception("OH 附件 Drive 下载异常: token=%s", file_token)

        # 3. file_token + extra（bitablePerm 位权限定，高级权限表附件必需）
        if not data and file_token:
            try:
                if field_id is None:
                    field_id = await client.get_field_id_by_name("体检报告附件")
                if field_id:
                    data = await client.download_bitable_attachment(
                        file_token, exam.feishu_record_id or "", field_id,
                    )
            except Exception:
                logger.exception("OH 附件 extra 下载异常: token=%s", file_token)

        if not data:
            logger.error(
                "OH 附件下载失败(全部策略耗尽): token=%s name=%s", file_token, file_name
            )
            continue

        try:
            filename = f"oh_{exam.feishu_record_id}_{file_token[:12]}_{file_name}"
            stored = store_bytes("oh", filename, data, att.get("type") or "application/octet-stream")
            saved.append(stored)
            logger.info("OH 附件已保存: %s (%d bytes)", stored, len(data))
        except Exception:
            logger.exception("OH 附件保存失败: name=%s", file_name)

    if saved:
        exam.attachment_paths = saved
        exam.attachments = _attachment_meta(raw_attachments)
        await session.commit()
        logger.info("OH 体检报告附件已下载: exam=%s count=%d", exam.id, len(saved))


# ── AI 触发（工作流①：体检报告智能解析，ticket 04 实现）──


def _attachments_changed(exam, prev_tokens: list[str]) -> bool:
    """Bitable 新附件与平台旧附件 file_token 是否不一致（附件替换 → 重置 pending）。"""
    new_tokens = [a.get("file_token", "") for a in (exam.attachments or [])]
    return bool(new_tokens) and new_tokens != prev_tokens


async def _run_exam_parse(exam_id, *, channel: str = "system") -> None:
    """后台任务：独立 session 执行 AI 解析（不阻塞事件回调，对标 msds_collection_handler）。"""
    try:
        async with async_session_factory() as session:
            from app.modules.safety.service.oh_health_exam import OhHealthExamService

            exam = await OhHealthExamService(session).run_ai_parse(exam_id, channel=channel)
            await session.commit()
            if exam:
                logger.info(
                    "职业健康 AI 解析完成: exam=%s status=%s conclusion=%s",
                    exam_id, exam.ai_parse_status, exam.ai_conclusion,
                )
    except Exception:
        logger.exception("职业健康 AI 解析后台任务异常: exam=%s", exam_id)


async def _run_person_sync(exam_id) -> None:
    """后台任务：独立 session 执行人员汇总表回填（ticket 08；只回填，不触发 AI/通知）。"""
    try:
        async with async_session_factory() as session:
            from app.modules.safety.service.oh_person import OhPersonService

            person = await OhPersonService(session).sync_from_exam(exam_id)
            await session.commit()
            if person:
                logger.info(
                    "职业健康人员汇总表已回填: exam=%s person=%s", exam_id, person.id
                )
    except Exception:
        logger.exception("职业健康人员汇总表回填后台任务异常: exam=%s", exam_id)


async def _maybe_trigger_ai_parse(exam_id, *, created: bool) -> None:
    """AI 解析触发钩子（ticket 04 实现）。

    触发条件（设计 §3.7/§4.4）：
      体检报告附件非空 OR 体检结果/检查结论/处理意见非空
      且 ai_parse_status ∈ {pending, failed}
    → asyncio.create_task(_run_exam_parse(exam_id, channel="system"))
    """
    try:
        async with async_session_factory() as session:
            exam = await session.scalar(
                select(OhHealthExam).where(
                    OhHealthExam.id == exam_id,
                    OhHealthExam.is_deleted == False,  # noqa: E712
                )
            )
            if exam is None:
                return
            has_input = any(
                (
                    exam.attachments,
                    exam.exam_result,
                    exam.exam_conclusion,
                    exam.treatment_advice_raw,
                )
            )
            if not has_input:
                logger.debug(
                    "体检记录无附件无结果文本，不触发 AI 解析: exam=%s", exam_id
                )
                return
            if exam.ai_parse_status in ("parsing", "parsed"):
                logger.debug(
                    "体检记录已解析/解析中，跳过触发: exam=%s status=%s",
                    exam_id, exam.ai_parse_status,
                )
                return
        try:
            asyncio.get_running_loop().create_task(_run_exam_parse(exam_id, channel="system"))
            logger.info("职业健康 AI 解析已调度: exam=%s created=%s", exam_id, created)
        except RuntimeError:
            logger.warning("无运行中的事件循环，AI 解析任务不调度: exam=%s", exam_id)
    except Exception:
        logger.exception("职业健康 AI 解析触发检查失败: exam=%s", exam_id)


async def _maybe_sync_person_master(exam_id, *, created: bool) -> None:
    """总表回填触发钩子（ticket 08）。

    触发条件（backend-design.md §3.7 step 4）：
      体检已完成（exam_date 非空）且平台侧 synced_to_summary != true
    → asyncio.create_task(_run_person_sync(exam_id))
    平台回写「是否已同步汇总表」触发的 changed 事件由 _is_sync_ignored 拦截；
    回填只做数据同步，不触发 AI / 通知。
    """
    try:
        async with async_session_factory() as session:
            exam = await session.scalar(
                select(OhHealthExam).where(
                    OhHealthExam.id == exam_id,
                    OhHealthExam.is_deleted == False,  # noqa: E712
                )
            )
            if exam is None:
                return
            if not exam.exam_date:
                logger.debug("体检记录未完成（无体检时间），暂不触发总表回填: exam=%s", exam_id)
                return
            if exam.synced_to_summary:
                logger.debug("体检记录已同步汇总表，跳过触发: exam=%s", exam_id)
                return
        try:
            asyncio.get_running_loop().create_task(_run_person_sync(exam_id))
            logger.info("职业健康总表回填已调度: exam=%s created=%s", exam_id, created)
        except RuntimeError:
            logger.warning("无运行中的事件循环，总表回填任务不调度: exam=%s", exam_id)
    except Exception:
        logger.exception("职业健康总表回填触发检查失败: exam=%s", exam_id)


# 申请状态「已通过」（Bitable 7 态原文值，schemas/oh_exam_applications.py 枚举同源）
_APPLY_STATUS_APPROVED = "已通过"


def _maybe_trigger_transfer_diff(item) -> None:
    """申请状态=已通过 且 未分析/失败 → 后台触发转岗差异分析（ticket 06 工作流②）。

    平台回写「差异分析结论」等字段触发的 changed 事件由 _is_sync_ignored 拦截，
    不会走到这里；parsing/analyzed 状态由 OhTransferService 内防重兜底。
    """
    if (
        getattr(item, "apply_status", None) == _APPLY_STATUS_APPROVED
        and getattr(item, "diff_analyze_status", None) in ("none", "failed")
    ):
        logger.info("职业健康申请已通过，触发转岗差异分析: application=%s", item.id)
        asyncio.create_task(_trigger_transfer_diff(item.id))


async def _trigger_transfer_diff(application_id) -> None:
    """后台执行转岗危害差异分析（独立 session，channel=system）。"""
    from app.modules.safety.service.oh_transfer import OhTransferService

    try:
        async with async_session_factory() as session:
            await OhTransferService(session).analyze_transfer_diff(
                application_id, channel="system"
            )
    except Exception:
        logger.exception(
            "职业健康转岗差异分析后台触发失败: application=%s", application_id
        )


# ── 来源表联动（D7：created 自动建体检登记 / 审批拒绝软删）──


async def _handle_new_employee_created(record_id: str, mapped: dict[str, Any]) -> None:
    """新员工登记 created → 自动建体检登记（exam_type=pre_employment，source_table=new_employee）。

    幂等由 create_from_source（source 键先查 + uq_oh_exams_source 唯一索引）保证。
    """
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    # 检查结论+处理意见合并（§3.5.2 拼接逻辑；payload 内分离字段在 create_from_source 优先）
    conclusion = mapped.get("exam_conclusion") or ""
    advice = mapped.get("treatment_advice_raw") or ""
    merged = "\n".join(p for p in (conclusion, advice) if p) or None
    try:
        async with async_session_factory() as session:
            exam = await OhHealthExamService(session).create_from_source(
                "new_employee", record_id,
                name=mapped.get("employee_name") or "未填写",
                id_card_no=mapped.get("id_card_no"),
                department=mapped.get("department"),
                job_position=mapped.get("position"),
                exam_type="pre_employment",
                registered_at=mapped.get("scheduled_date"),
                raw_conclusion_advice=merged,
                source_payload=mapped,
            )
            await session.commit()
            logger.info(
                "新员工登记联动建体检登记: record_id=%s exam=%s", record_id, exam.id
            )
    except Exception:
        logger.exception("新员工登记联动建体检登记失败: record_id=%s", record_id)


async def _sync_person_work_status_to_bitable(person) -> None:
    """人员档案 work_status 变更 → 回写 Bitable 人员汇总表「在岗状态」（Q2）。

    写回前 _set_sync_ignore(record_id, ttl=30) 防 created/changed 事件循环；
    env 未配置或无 feishu_record_id → 告警跳过；失败仅告警，不阻塞平台状态流转。
    """
    if not person.feishu_record_id:
        logger.warning(
            "人员汇总表「在岗状态」回写跳过（无 record_id）: person=%s", person.id
        )
        return
    conn = _oh_conn("person_master")
    if conn is None or not conn.enabled:
        logger.warning(
            "人员汇总表「在岗状态」回写跳过（Bitable 未配置）: person=%s", person.id
        )
        return
    try:
        await bh._set_sync_ignore(person.feishu_record_id, ttl=30)
        client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
        await client.update_record(
            record_id=person.feishu_record_id,
            fields={"在岗状态": "在岗"},
        )
        logger.info(
            "人员档案在岗状态已回写 Bitable 人员汇总表: person=%s record_id=%s",
            person.id, person.feishu_record_id,
        )
    except Exception:
        logger.exception("人员汇总表「在岗状态」回写失败（不阻塞）: person=%s", person.id)


async def _handle_new_employee_changed(record_id: str, mapped: dict[str, Any]) -> None:
    """新员工登记 changed → 入职时间监听（Q2 用户决策）。

    登记表更新「入职时间」（「入职时间」优先，「工作年限（第一份工作入职时间）」兜底）→
    该人员档案 work_status 岗前（pre_employment）→ 在岗（on_post），
    并回写 Bitable 人员汇总表「在岗状态」=在岗（_set_sync_ignore 防循环）。

    幂等：已是在岗直接跳过；查不到人员/无入职时间仅告警，不报错。
    """
    hire_date = mapped.get("hire_date") or mapped.get("first_job_date")
    if not hire_date:
        return
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    try:
        async with async_session_factory() as session:
            svc = OhHealthExamService(session)
            person = await svc.repo.get_oh_person_by_name_idcard(
                mapped.get("employee_name") or "", mapped.get("id_card_no")
            )
            if person is None:
                logger.warning(
                    "新员工入职时间更新但人员档案不存在，跳过状态流转: record_id=%s name=%s",
                    record_id, mapped.get("employee_name"),
                )
                return
            if person.work_status == "on_post":
                logger.debug(
                    "人员档案已是在岗，跳过流转: person=%s", person.id
                )
                return
            if person.work_status != "pre_employment":
                logger.info(
                    "人员档案在岗状态非岗前，不流转: person=%s work_status=%s",
                    person.id, person.work_status,
                )
                return
            person.work_status = "on_post"
            await session.flush()
            await _sync_person_work_status_to_bitable(person)
            await session.commit()
            logger.info(
                "新员工入职时间更新 → 人员档案岗前转在岗: record_id=%s person=%s",
                record_id, person.id,
            )
    except Exception:
        logger.exception("新员工入职时间监听失败: record_id=%s", record_id)


async def _handle_application_created(record_id: str, mapped: dict[str, Any]) -> None:
    """申请表 created → 自动建体检登记（Q1 用户决策映射）。

    转岗体检本质是岗位体检 → exam_type=periodic（在岗期间）；
    离岗体检 → post_employment；其他 → periodic 兜底。
    """
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    exam_type_label = mapped.get("exam_type") or ""
    if "离岗" in exam_type_label:
        exam_type = "post_employment"
    else:
        exam_type = "periodic"  # 转岗体检 → 岗位体检（periodic）；未知 → 兜底 periodic
    try:
        async with async_session_factory() as session:
            exam = await OhHealthExamService(session).create_from_source(
                "exam_application", record_id,
                name=mapped.get("employee_name") or "未填写",
                id_card_no=mapped.get("id_card_no"),
                department=mapped.get("department"),
                job_position=mapped.get("position"),
                exam_type=exam_type,
                registered_at=mapped.get("submitted_at"),
                transfer_date=mapped.get("transfer_date"),
                leave_date=mapped.get("leave_date"),
                source_payload=mapped,
            )
            await session.commit()
            logger.info(
                "申请表联动建体检登记: record_id=%s exam=%s exam_type=%s",
                record_id, exam.id, exam_type,
            )
    except Exception:
        logger.exception("申请表联动建体检登记失败: record_id=%s", record_id)


async def _soft_delete_exam_by_source(source_table: str, record_id: str) -> None:
    """审批拒绝/取消/终止/撤回 → 软删关联体检记录（按 source 键查，清唯一键）。"""
    from app.modules.safety.service.oh_health_exam import OhHealthExamService

    try:
        async with async_session_factory() as session:
            deleted = await OhHealthExamService(session).soft_delete_exam_by_source(
                source_table, record_id
            )
            await session.commit()
            if deleted:
                logger.info(
                    "申请拒绝联动软删体检登记: source_table=%s record_id=%s",
                    source_table, record_id,
                )
    except Exception:
        logger.exception(
            "申请拒绝联动软删体检登记失败: source_table=%s record_id=%s",
            source_table, record_id,
        )


# ── 事件处理 ──


async def _upsert(kind: str, record_id: str, *, created: bool = False) -> None:
    """回源拉取记录并 upsert 到平台 oh_* 表（活行 WHERE is_deleted=false）。"""
    table_id = oh_tables().get(kind)
    if not table_id:
        return
    conn = _oh_conn(kind)
    if conn is None or not conn.enabled or not conn.app_token:
        return

    # 1. 平台自身回写 Bitable 触发的 changed 事件 → 跳过（防死循环）
    try:
        if await bh._is_sync_ignored(record_id):
            logger.debug("职业健康 Bitable 同步忽略（平台回写）: record_id=%s", record_id)
            return
    except Exception:
        pass  # Redis 不可用 → 不拦截

    # 2. Redis 60s 去重（suffix 按 table_kind，避免跨表 record_id 碰撞误杀）
    try:
        if await bh._is_duplicate("oh_upsert", record_id, ttl=60, suffix=kind):
            logger.info("职业健康 Bitable 重复事件已忽略: kind=%s record_id=%s", kind, record_id)
            return
    except Exception:
        pass

    # 3. 回源拉全量
    client = SafetyBitableClient(app_token=conn.app_token, table_id=table_id)
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("职业健康 Bitable 记录读取为空: kind=%s record_id=%s", kind, record_id)
        return

    # 4. 字段映射
    mapper = get_mapper(kind)
    if mapper is None:
        return
    mapped = mapper(fields)
    if mapped is None:
        if kind == "exam_application":
            await _soft_delete(kind, record_id)
        else:
            logger.info("职业健康记录映射为空，跳过: kind=%s record_id=%s", kind, record_id)
        return

    # 4b. 来源表联动（D7+Q2）：新员工登记不建平台表，created → 自动建体检登记；
    #     changed → 入职时间监听（更新入职时间 → 人员档案岗前转在岗）
    if kind == "new_employee":
        if created:
            await _handle_new_employee_created(record_id, mapped)
        else:
            await _handle_new_employee_changed(record_id, mapped)
        return
    mapped["feishu_record_id"] = record_id
    mapped["source"] = "bitable"

    # 5. 活行 upsert
    model = _MODEL_BY_KIND[kind]
    # 附件变更检测基线（exam_registry：Bitable 新附件 token 与平台旧附件比对）
    prev_attachment_tokens: list[str] = []
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(model).where(
                model.feishu_record_id == record_id,
                model.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            if kind == "exam_registry":
                prev_attachment_tokens = [
                    a.get("file_token", "") for a in (existing.attachments or [])
                ]
            _apply_values(existing, mapped)
            await session.commit()
            item = await session.scalar(
                select(model).where(
                    model.id == existing.id,
                    model.is_deleted == False,  # noqa: E712
                )
            )
        else:
            item = await _create_guarded(model, mapped, record_id)
            if item is not None:
                item = await session.scalar(
                    select(model).where(
                        model.id == item.id,
                        model.is_deleted == False,  # noqa: E712
                    )
                )
            else:
                # INSERT 互斥锁被占用 → 回查已有记录
                item = await session.scalar(
                    select(model).where(
                        model.feishu_record_id == record_id,
                        model.is_deleted == False,  # noqa: E712
                    )
                )

        # 6. 关联回填 / 附件下载 / AI 钩子
        if item is not None:
            if kind == "exam_registry":
                await _link_person(session, item, fields)
                await _download_exam_attachments(session, item, fields)
                # 附件替换 → 重置 pending 重新解析（设计 §4.4 触发时机表）
                if _attachments_changed(item, prev_attachment_tokens):
                    item.ai_parse_status = "pending"
                    item.ai_parse_error = None
                    await session.commit()
                    logger.info(
                        "体检报告附件变更，重置解析状态: exam=%s", item.id
                    )
                await _maybe_trigger_ai_parse(item.id, created=created)
                await _maybe_sync_person_master(item.id, created=created)
            elif kind == "person_master":
                await _resolve_person_links(session, item, fields)
            elif kind == "exam_application":
                # D7 来源联动②：created → 自动建体检登记；审批状态流转
                if created:
                    await _handle_application_created(record_id, mapped)
                if getattr(item, "apply_status", None) in _APPLY_STATUS_REJECT:
                    # 已拒绝/已取消/已终止/已撤回 → 软删关联体检记录（不新建）
                    await _soft_delete_exam_by_source("exam_application", record_id)
                else:
                    # 已通过 → 差异分析更新已建登记（ensure_exam_for_application 不重复新建）
                    _maybe_trigger_transfer_diff(item)

        logger.info("职业健康已同步: kind=%s record_id=%s", kind, record_id)


async def _handle_record_event(event_data: dict, *, created: bool) -> None:
    """created/changed 统一入口：table_id → kind 分发 → 回源拉记录 → 映射 → upsert。"""
    record_id = event_data.get("record_id", "")
    table_id = event_data.get("table_id", "")
    kind = table_kind_by_id(table_id)
    if not kind or not record_id:
        return
    logger.info("职业健康 Bitable 记录事件: kind=%s record_id=%s", kind, record_id)
    try:
        await _upsert(kind, record_id, created=created)
    except Exception:
        logger.exception("职业健康 upsert 失败: kind=%s record_id=%s", kind, record_id)


async def _handle_deleted_event(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    table_id = event_data.get("table_id", "")
    kind = table_kind_by_id(table_id)
    if not kind or not record_id:
        return
    logger.info("职业健康 Bitable 删除事件: kind=%s record_id=%s", kind, record_id)
    try:
        await _soft_delete(kind, record_id)
    except Exception:
        logger.exception("职业健康软删除失败: kind=%s record_id=%s", kind, record_id)


# ── 事件注册 ──

# 飞书 long-connection 实际推送的 bitable 记录事件名为 v2
# 「drive.file.bitable_record_changed_v1」（payload 含 action_list：
# record_added/record_edited/record_deleted）。早期注册的 bitable.record.*_v1 旧名
# 收不到推送（2026-08-18 实测：OH 事件到 handler 计数为 0）。同一事件由
# bitable_handler.handle_bitable_record_changed（目标=隐患表）先行过滤并丢弃，
# 本处理器按 table_kind_by_id 二次过滤分发，互不干扰。


@on_event("drive.file.bitable_record_changed_v1")
async def _on_oh_record_changed(event_data: dict) -> None:
    """OH 6 表记录变更（v2 action_list 格式），created/edited/deleted 统一分发。

    v2 payload 顶层含 file_token/table_id，record_id 与 action 在 action_list 项内；
    兼容旧 flat 格式（record_id/action 顶层）兜底。
    """
    table_id = event_data.get("table_id", "")
    if table_kind_by_id(table_id) is None:
        return
    action_list = event_data.get("action_list") or []
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            if not record_id:
                continue
            if action == "record_deleted":
                await _handle_deleted_event({"record_id": record_id, "table_id": table_id})
            elif action in ("record_added", "record_edited"):
                await _handle_record_event(
                    {"record_id": record_id, "table_id": table_id},
                    created=(action == "record_added"),
                )
        return
    # flat 兜底（旧格式）
    await _handle_record_event(event_data, created=False)

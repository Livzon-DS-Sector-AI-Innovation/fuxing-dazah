"""职业健康 AI 工作流① — 体检报告智能解析（scenario=oh_exam_report_parsing）。

对齐 backend-design.md §四.2 工作流①：

  1. 取 exam（含 exam_result/exam_conclusion/treatment_advice_raw/hazard_factors/exam_type/position）
  2. 附件管线：attachment_paths → SafetyDocumentParser.extract_text（PDF/DOCX 文本抽取）
     → 文本失败且为图片 → VisionService.analyze_parsed 降级（expected_keys 同文本输出 schema）
     → 仍失败 → ai_parse_status=failed 人工
  3. ai_parse_status = parsing（先提交防重复触发）
  4. ai_audit_scope(scenario="oh_exam_report_parsing", channel=channel,
                    resource_type="oh_health_exam", resource_id=exam_id) 包住调用链
  5. create_ai_service("text")；chat_parsed(system 稳定 prompt + user 变量末尾, temperature=0.1)
  6. OhExamReportParseOutput.model_validate → 落库 ai_* 字段
  7. 生成「AI智能解读」文本（对齐存量 147 条格式，D10：存量非空不改写）
     → update_record 回写 Bitable（_set_sync_ignore 防循环）
  8. 异常指标 → OhFollowupService.create_from_exam（ticket 07，source='ai_parse'，幂等）
  9. 解析完成 → OhPersonService.sync_from_exam 联动人员汇总表（只回填，不触发 AI/通知）
 10. 成功 → parsed；失败 → failed + ai_parse_error
"""

from __future__ import annotations

import logging
import mimetypes
import os
import pathlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.models import OhHealthExam
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas.oh_ai import (
    CONCLUSION_CATEGORIES,
    CONCLUSION_CATEGORY_ABNORMAL_OTHER,
    CONCLUSION_CATEGORY_CONTRAINDICATED,
    FITNESS_UNFIT,
    FITNESS_VALUES,
    OhExamReportParseOutput,
)
from app.modules.safety.service.config import create_ai_service
from app.modules.safety.service.oh_hazard_factor import OH_HAZARD_FACTORS_STANDARD

logger = logging.getLogger(__name__)

# ── 场景常量（与 ai_audit/models.py::SCENARIO_OH_EXAM_REPORT_PARSING 对齐）──
SCENARIO_OH_EXAM_REPORT_PARSING = "oh_exam_report_parsing"

# 输出 schema 顶层键（chat_parsed expected_keys / vision expected_keys 共用）
_PARSE_EXPECTED_KEYS: tuple[str, ...] = (
    "abnormal_indicators",
    "conclusion_category",
    "contraindication_factors",
    "contraindication_statement",
    "has_contraindication",
    "fitness",
    "treatment_advice",
    "recommendations",
    "summary_text",
)

# 体检类型标准枚举 → 中文标签（user prompt 展示用）
_EXAM_TYPE_LABELS: dict[str, str] = {
    "pre_employment": "岗前体检",
    "periodic": "在岗期间体检",
    "post_employment": "离岗体检",
    "transfer": "转岗体检",
    "emergency": "应急体检",
}


# ═══════════════════════════════════════════════════════════════
# System Prompt（稳定内容，遵守前缀缓存铁律：system 固定、变量放 user 末尾）
# ═══════════════════════════════════════════════════════════════

# 危害因素标准字典（模块级常量，system prompt 构建时内联；字典变更 = prompt 变更 = 缓存失效，
# 属可接受的低频变更，与 msds_extraction 同一处理口径）
_HAZARD_LIST_TEXT = "、".join(OH_HAZARD_FACTORS_STANDARD)

OH_EXAM_PARSE_SYSTEM_PROMPT = f"""你是资深职业健康医师，依据《GBZ 188-2014 职业健康监护技术规范》对职业健康体检记录进行结构化解读，输出 JSON。

## 输入说明
用户将提供：体检类型、岗位、接触危害因素、接害工龄，以及体检结果 / 检查结论 / 处理意见原文，可能还包括体检报告附件抽取文本。

## 输出 JSON 结构（字段定义）
{{
  "abnormal_indicators": [
    {{
      "name": "异常指标名称（如：谷丙转氨酶）",
      "value": "检测值（保留原文数值、单位与 ↑↓ 标记，如 68U/L↑，不换算）",
      "reference_range": "参考范围（原文，无则 null）",
      "category": "lab/vision/hearing/physique/other",
      "severity": "mild/moderate/severe",
      "followup_suggestion": "建议随访动作（如：建议复查、建议专科就诊），无则 null"
    }}
  ],
  "conclusion_category": "normal/abnormal_other/contraindicated/suspected_od/od_diagnosed/re_examination",
  "contraindication_factors": ["涉及职业禁忌证的危害因素标准名（只能取自危害因素标准字典）"],
  "contraindication_statement": "与职业禁忌证判定直接相关的结论原文逐字引用（必须与原文完全一致，禁止改写、润色、编造；无禁忌证相关内容则 null）",
  "has_contraindication": true,
  "fitness": "fit/fit_with_restriction/unfit",
  "treatment_advice": ["follow_up/transfer_post/medical_referral/ppe_strengthen/regular_monitor"],
  "recommendations": ["面向员工的健康建议，逐条，中文"],
  "summary_text": "不超过 200 字的总体解读摘要"
}}

## 判定规则
1. 禁忌证判定必须逐字引用结论原文（contraindication_statement），不得改写、润色或编造；原文未提及禁忌证相关内容时 contraindication_statement 为 null。
2. 异常指标 value 保留原文数值、单位与 ↑↓ 标记（如"68U/L↑"），一律不换算、不归一、不改写。
3. 结论分类规则：
   - 结论明确"职业禁忌证"/"禁忌从事" → contraindicated；
   - 结论提及"疑似职业病" → suspected_od；提及"职业病诊断"/"职业病确诊" → od_diagnosed；
   - 结论建议"复查"/"复检" → re_examination；
   - 未见异常且无处理意见 → normal；
   - 其他异常情况 → abnormal_other。
4. 无法判定结论分类时 → conclusion_category="abnormal_other"，fitness="unfit"，并在 contraindication_statement 中标注"需人工复核"。
5. fitness 与结论联动：contraindicated → unfit；normal 且无异常 → fit；其他异常按严重程度给 fit_with_restriction 或 unfit。
6. contraindication_factors 只能从危害因素标准字典中选取（见下），禁止编造字典外的因素名；无禁忌证则为空数组。
7. treatment_advice 只从枚举中选取：follow_up/transfer_post/medical_referral/ppe_strengthen/regular_monitor。
8. 异常指标 category 只从枚举中选取：lab/vision/hearing/physique/other；severity：mild/moderate/severe。
9. recommendations 面向员工，具体可执行（如复查项目、防护建议、就诊科室），不编造体检机构结论之外的医学事实。

## 危害因素标准字典
{_HAZARD_LIST_TEXT}

只输出上述 JSON 对象，禁止输出任何其他文字。"""


# ═══════════════════════════════════════════════════════════════
# 输入组装（变量拼最后一条 user 消息，前缀缓存铁律）
# ═══════════════════════════════════════════════════════════════


def _build_exam_user_prompt(exam: OhHealthExam, document_text: str = "") -> str:
    """体检记录变量 → user prompt（变量全部在末尾，system 保持稳定）。"""
    parts: list[str] = []
    parts.append(f"体检类型：{_EXAM_TYPE_LABELS.get(exam.exam_type, exam.exam_type)}")
    parts.append(f"岗位：{exam.position or '未提供'}")
    if exam.hazard_factors:
        parts.append(f"接触危害因素：{'、'.join(exam.hazard_factors)}")
    else:
        parts.append("接触危害因素：未提供")
    if exam.hazard_exposure_years is not None:
        parts.append(f"接害工龄：{exam.hazard_exposure_years}年")
    else:
        parts.append("接害工龄：未提供")

    if exam.exam_result:
        parts.append(f"【体检结果】\n{exam.exam_result}")
    if exam.exam_conclusion:
        parts.append(f"【检查结论】\n{exam.exam_conclusion}")
    if exam.treatment_advice_raw:
        parts.append(f"【处理意见】\n{exam.treatment_advice_raw}")
    if document_text:
        parts.append(f"【体检报告附件文本】\n{document_text}")
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════════


class OhAIService:
    """职业健康 AI 工作流服务（工作流①：体检报告智能解析）。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SafetyRepository(db)

    # ── 工作流①：体检报告智能解析 ──

    async def parse_exam_report(
        self,
        exam_id: uuid.UUID,
        *,
        channel: str = "system",  # system（Bitable 事件）/ web（手动触发）
    ) -> OhHealthExam | None:
        """体检报告智能解析（scenario=oh_exam_report_parsing）。

        流程见文件头 docstring。返回更新后的 exam；失败时 ai_parse_status=failed + ai_parse_error。
        """
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if not exam:
            return None
        if exam.ai_parse_status in ("parsing", "parsed"):
            logger.info("体检 AI 解析跳过（当前状态 %s）: exam=%s", exam.ai_parse_status, exam_id)
            return exam

        # D10：存量 AI智能解读非空视为人工已确认 → 本次解析保留原文，不覆盖不写回
        existing_interpretation = exam.ai_interpretation

        # 状态置 parsing（先提交，防止事件/手动并发重复触发）
        exam.ai_parse_status = "parsing"
        exam.ai_parse_error = None
        await self.db.commit()
        exam = await self.repo.get_health_exam_by_id(exam_id)

        try:
            # ai_audit_scope 包住整条 AI 调用链（文本 + 图片降级共用 trace）
            with ai_audit_scope(
                scenario=SCENARIO_OH_EXAM_REPORT_PARSING,
                channel=channel,
                resource_type="oh_health_exam",
                resource_id=exam.id,
            ):
                document_text, vision_result = await self._collect_input(exam)

                if vision_result is not None:
                    # 图片降级：视觉模型直接产出结构化输出
                    parse_result = OhExamReportParseOutput.model_validate(vision_result)
                else:
                    if not document_text.strip():
                        raise RuntimeError("体检记录无有效输入文本（体检结果/检查结论/处理意见/附件文本均为空）")
                    ai = create_ai_service("text")
                    try:
                        result = await ai.chat_parsed(
                            messages=[
                                {"role": "system", "content": OH_EXAM_PARSE_SYSTEM_PROMPT},
                                # 变量数据拼 user 末尾（前缀缓存友好）
                                {"role": "user", "content": _build_exam_user_prompt(exam, document_text)},
                            ],
                            expected_keys=list(_PARSE_EXPECTED_KEYS),
                            temperature=0.1,
                        )
                    finally:
                        await ai.close()
                    parse_result = OhExamReportParseOutput.model_validate(result)

            # ── 结论归一（has_contraindication 优先；非法值兜底 abnormal_other / unfit）──
            conclusion = (
                CONCLUSION_CATEGORY_CONTRAINDICATED
                if parse_result.has_contraindication
                else (
                    parse_result.conclusion_category
                    if parse_result.conclusion_category in CONCLUSION_CATEGORIES
                    else CONCLUSION_CATEGORY_ABNORMAL_OTHER
                )
            )
            fitness = (
                parse_result.fitness if parse_result.fitness in FITNESS_VALUES else FITNESS_UNFIT
            )

            # ── 落库 ai_* 字段 ──
            update_data: dict = {
                "ai_parse_result": parse_result.model_dump(mode="json"),
                "ai_conclusion": conclusion,
                "ai_contraindication_factors": (
                    parse_result.contraindication_factors or None
                ),
                "ai_fitness": fitness,
                "ai_parse_status": "parsed",
                "ai_parse_error": None,
            }
            if existing_interpretation:
                logger.info("存量 AI智能解读非空，保留人工已确认内容（D10）: exam=%s", exam.id)
            else:
                update_data["ai_interpretation"] = self._build_interpretation_text(exam, parse_result)
            item = await self.repo.update_health_exam(exam.id, update_data)
            if item is None:
                raise RuntimeError("体检记录更新失败")
            await self.db.commit()

            # ── 异常指标 → oh_followups（ticket 07 OhFollowupService.create_from_exam，幂等）──
            try:
                from app.modules.safety.service.oh_followup import OhFollowupService

                await OhFollowupService(self.db).create_from_exam(item.id)
                await self.db.commit()
            except Exception:
                logger.exception("体检异常随访生成失败（不阻塞解析）: exam=%s", exam.id)
                await self.db.rollback()

            # ── 解析完成 → 联动人员汇总表（last_exam_* / exam_record_ids；只回填，不触发 AI/通知）──
            try:
                from app.modules.safety.service.oh_person import OhPersonService

                await OhPersonService(self.db).sync_from_exam(item.id)
                await self.db.commit()
            except Exception:
                logger.exception("体检解析后人员汇总表回填失败（不阻塞解析）: exam=%s", exam.id)
                await self.db.rollback()
            # 上两段独立保护可能 rollback（expire 全部实例），回写 Bitable 前 select re-fetch（async 铁律）
            item = await self.repo.get_health_exam_by_id(exam.id)
            if item is None:
                return None

            # ── 生成 AI智能解读文本回写 Bitable（_set_sync_ignore 防循环；失败不阻塞）──
            if not existing_interpretation:
                await self._write_back_interpretation(item)

            logger.info(
                "体检 AI 解析完成: exam=%s conclusion=%s indicators=%d",
                exam.id, conclusion, len(parse_result.abnormal_indicators),
            )
            return await self.repo.get_health_exam_by_id(exam.id)

        except Exception as e:
            logger.exception("体检 AI 解析失败: exam=%s", exam_id)
            try:
                failed = await self.repo.update_health_exam(
                    exam.id,
                    {"ai_parse_status": "failed", "ai_parse_error": str(e)[:2000]},
                )
                await self.db.commit()
                return failed
            except Exception:
                logger.exception("体检 AI 解析失败状态落库异常: exam=%s", exam_id)
                return await self.repo.get_health_exam_by_id(exam.id)

    # ── 附件管线：文本抽取 → 图片降级 ──

    async def _collect_input(
        self, exam: OhHealthExam
    ) -> tuple[str, dict | None]:
        """收集体检输入文本（Bitable 文本字段 + 附件抽取）。

        Returns:
            (text, vision_result)：vision_result 非 None 表示图片降级成功，
            已直接产出结构化输出，此时 text 为空串。
        """
        texts = [
            t.strip()
            for t in (exam.exam_result, exam.exam_conclusion, exam.treatment_advice_raw)
            if t and t.strip()
        ]

        document_text, vision_result = await self._extract_attachments(exam)
        if vision_result is not None:
            return "", vision_result
        if document_text:
            texts.append(document_text)
        return "\n\n".join(texts), None

    async def _extract_attachments(
        self, exam: OhHealthExam
    ) -> tuple[str, dict | None]:
        """附件 → 文本（SafetyDocumentParser）；文本失败且为图片 → VisionService 降级。

        Returns:
            (document_text, vision_result)：任一附件图片降级成功 → vision_result 非 None（整体取代文本解析）。
        """
        paths = list(exam.attachment_paths or [])
        if not paths and exam.attachments and exam.feishu_record_id:
            # 附件元数据已同步但本地未下载（如手工建单）→ 尝试下载首个附件
            paths = await self._download_attachments(exam)
            if paths and not exam.attachment_paths:
                exam.attachment_paths = paths
                await self.db.commit()

        pieces: list[str] = []
        for path in paths:
            file_path = str(path)
            tmp_path: pathlib.Path | None = None
            try:
                from app.modules.safety.attachment_store import (
                    cleanup_temp,
                    materialize,
                )
                from app.modules.safety.knowledge.document_parser import (
                    SafetyDocumentParser,
                )
                from app.modules.safety.vision.utils import resolve_local_path

                # 回读适配：本地未命中时按 MinIO object key 物化临时文件（保留扩展名）
                local = resolve_local_path(file_path)
                parse_target = local
                if parse_target is None:
                    tmp_path = materialize(file_path, suffix=os.path.splitext(file_path)[1])
                    if tmp_path is None:
                        logger.warning("体检附件回读失败（本地与 MinIO 均未命中）: %s", file_path)
                        continue
                    parse_target = str(tmp_path)

                text = SafetyDocumentParser.extract_text(parse_target, max_chars=100000)
                if text:
                    pieces.append(f"[附件 {os.path.basename(file_path)}]\n{text}")
                    continue
            except Exception:
                logger.warning("体检附件文本抽取失败: %s", file_path)
            finally:
                if tmp_path is not None:
                    cleanup_temp(tmp_path)

            # 文本抽取失败 → 图片降级（VisionService.analyze_parsed，expected_keys 同文本 schema）
            if pathlib.Path(file_path).suffix.lower() in _IMAGE_EXTENSIONS:
                vision_result = await self._vision_parse(file_path)
                if vision_result is not None:
                    return "", vision_result
            logger.warning("体检附件解析失败且非图片/视觉降级无效，跳过: %s", file_path)

        return "\n\n".join(pieces), None

    async def _vision_parse(self, image_path: str) -> dict | None:
        """图片体检报告 → 视觉模型结构化解析（返回 None 表示失败/不可用）。

        回读适配：``image_path`` 可能是 MinIO object key——经 attachment_store
        取字节（本地或 MinIO）后编码为 data URI 送视觉模型。
        """
        try:
            from app.modules.safety.attachment_store import read_bytes
            from app.modules.safety.vision.constants import IMAGE_MIME_MAP
            from app.modules.safety.vision.service import VisionService
            from app.modules.safety.vision.utils import encode_image_for_vision

            raw = read_bytes(image_path)
            if raw is None:
                logger.warning("体检报告图片回读失败（本地与 MinIO 均未命中）: %s", image_path)
                return None
            mime = IMAGE_MIME_MAP.get(os.path.splitext(image_path)[1].lower())
            if mime is None:
                logger.info("非图片扩展名，跳过视觉解析: %s", image_path)
                return None
            data_uri = encode_image_for_vision(raw, mime, image_path)
            if data_uri is None:
                return None

            vision: VisionService | None = None
            try:
                vision = VisionService(create_ai_service("vision"))
                result = await vision.analyze_parsed(
                    text_prompt=(
                        OH_EXAM_PARSE_SYSTEM_PROMPT
                        + "\n\n请根据体检报告图片中的全部内容，输出上述 JSON 结构。"
                    ),
                    image_urls=[data_uri],
                    expected_keys=list(_PARSE_EXPECTED_KEYS),
                    temperature=0.1,
                )
                if result:
                    logger.info("体检报告图片降级解析成功: %s", image_path)
                return result
            finally:
                if vision is not None:
                    await vision.close()
        except Exception:
            logger.exception("体检报告图片视觉解析失败: %s", image_path)
            return None

    async def _download_attachments(self, exam: OhHealthExam) -> list[str]:
        """附件元数据 → 本地下载（URL/file_token 两级，复用 SafetyBitableClient）。"""
        from app.modules.safety.attachment_store import store_bytes
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        attachments = exam.attachments or []
        if not attachments:
            return []
        client = SafetyBitableClient()
        saved: list[str] = []
        for att in attachments[:1]:  # 解析首个附件即可（报告全文）
            if not isinstance(att, dict):
                continue
            file_name = att.get("name", "attachment")
            file_token = att.get("file_token", "")
            url = att.get("url") or att.get("tmp_url")
            data: bytes | None = None
            if url:
                try:
                    data = await client.download_attachment_from_url(url)
                except Exception:
                    logger.warning("体检附件 URL 下载失败，回退 file_token: %s", file_name)
            if not data and file_token:
                try:
                    data = await client.download_attachment(file_token)
                except Exception:
                    logger.exception("体检附件 Drive 下载失败: %s", file_name)
            if not data:
                continue
            content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            saved.append(
                store_bytes(
                    "oh",
                    f"oh_{exam.id}_{file_token[:12]}_{file_name}",
                    data,
                    content_type,
                )
            )
        return saved

    # ── AI智能解读文本（对齐存量 147 条格式）──

    @staticmethod
    def _build_interpretation_text(exam: OhHealthExam, parse_result: OhExamReportParseOutput) -> str:
        """生成「AI智能解读」回写文本（backend-design.md §六.1 模板）。"""
        exam_date = exam.exam_date or exam.report_date or exam.scheduled_date
        date_str = exam_date.strftime("%Y-%m-%d") if exam_date else "未提供"

        lines = [
            "【AI智能解读】",
            f"员工：{exam.employee_name or '未知'} | 部门：{exam.department or '未知'} | 岗位：{exam.position or '未知'}",
            f"体检日期：{date_str}",
            "",
            "【异常指标】",
        ]
        indicators = parse_result.abnormal_indicators
        if indicators:
            for i, ind in enumerate(indicators, 1):
                value = f" {ind.value}" if ind.value else ""
                lines.append(f"{i}. {ind.name}{value}")
        else:
            lines.append("未发现异常指标")
        lines.append("")

        lines.append("【岗位关联分析】")
        if exam.hazard_factors:
            lines.append(f"该岗位接触危害因素：{'、'.join(exam.hazard_factors)}")
            if parse_result.contraindication_factors:
                lines.append(
                    f"AI 判定存在职业禁忌证相关危害因素：{'、'.join(parse_result.contraindication_factors)}"
                )
            elif parse_result.has_contraindication:
                lines.append("AI 判定存在职业禁忌证，涉及危害因素需人工复核")
            else:
                lines.append("未发现与该岗位危害因素直接相关的职业禁忌证")
        else:
            lines.append("未获取岗位危害因素信息")
        lines.append("")

        lines.append("【健康建议】")
        recommendations = [r.strip() for r in (parse_result.recommendations or []) if r and r.strip()]
        if recommendations:
            lines.extend(f"- {r}" for r in recommendations)
        elif parse_result.fitness == "fit" and exam.hazard_factors:
            lines.append(f"可以从事{'、'.join(exam.hazard_factors)}相关作业，建议按周期参加职业健康体检")
        elif parse_result.has_contraindication:
            lines.append("建议调离相关危害因素岗位，并咨询职业健康医师")
        else:
            lines.append("建议咨询职业健康医师，按医嘱复查")
        return "\n".join(lines)

    # ── Bitable 回写（_set_sync_ignore 防循环）──

    async def _write_back_interpretation(self, exam: OhHealthExam) -> None:
        """AI智能解读回写 Bitable「AI智能解读」字段（仅 Bitable 来源记录；失败不阻塞）。"""
        if not exam.feishu_record_id or not exam.ai_interpretation:
            return
        try:
            from app.modules.safety.bitable_config.store import store
            from app.modules.safety.feishu import bitable_handler as bh
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient

            conn = store.get_connection("oh", "exam_registry")
            if conn is None or conn.status == "disabled":
                logger.warning("OH Bitable 配置未配置，跳过 AI智能解读回写: exam=%s", exam.id)
                return
            # 防循环铁律：平台写回 Bitable 前必调
            await bh._set_sync_ignore(exam.feishu_record_id, ttl=30)
            client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
            await client.update_record(
                record_id=exam.feishu_record_id,
                fields={"AI智能解读": exam.ai_interpretation},
            )
            logger.info("体检 AI智能解读已回写 Bitable: exam=%s record=%s", exam.id, exam.feishu_record_id)
        except Exception:
            logger.exception("体检 AI智能解读回写 Bitable 失败（不影响平台落库）: exam=%s", exam.id)


# 图片扩展名（VisionService.IMAGE_MIME_MAP 同步）
_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

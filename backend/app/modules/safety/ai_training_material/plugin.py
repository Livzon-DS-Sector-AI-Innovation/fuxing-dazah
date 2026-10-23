"""AI 培训课件/试卷生成插件 — 核心引擎（链2）。

用法:
    from app.modules.safety.ai_training_material import LecturePlugin

    plugin = LecturePlugin(ai_service)  # create_ai_service("text")
    output = await plugin.generate(LectureInput(...))

场景键：training_material_generation（ai_config/scenario_registry 注册）。
产物是草案（docx 供讲师定稿），全部落附件列可审，不推送任何消息。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.ai_training_material.prompts import (
    EXAM_SYSTEM_PROMPT,
    LECTURE_SYSTEM_PROMPT,
    build_exam_user_prompt,
    build_lecture_user_prompt,
    resolve_exam_counts,
)
from app.modules.safety.ai_training_material.schemas import (
    ExamInput,
    ExamOutput,
    LectureInput,
    LectureOutput,
    LectureSection,
)

logger = logging.getLogger(__name__)

LECTURE_EXPECTED_KEYS = ["title", "objectives", "sections", "key_takeaways", "references"]

# 题型键契约对齐 HR ai_exam_service.EXAM_QUESTION_KEYS（JSON 键结构复用，代码自持）
EXAM_QUESTION_KEYS = (
    "choice_questions",
    "true_false_questions",
    "multi_choice_questions",
    "fill_blank_questions",
)


class TrainingMaterialError(Exception):
    """课件/试卷生成失败（AI 调用或输出解析）。"""


class LecturePlugin:
    """培训行 + 知识片段 → 讲义要点卡。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def generate(self, input_data: LectureInput) -> LectureOutput:
        prompt = build_lecture_user_prompt(
            topic=input_data.topic,
            category=input_data.category,
            hours=input_data.hours,
            position=input_data.position,
            knowledge_md=input_data.knowledge_md,
        )
        messages = [
            {"role": "system", "content": LECTURE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=LECTURE_EXPECTED_KEYS,
                temperature=0.2,
            )
        except Exception as e:
            logger.error("讲义要点卡 AI 调用失败: %s", e)
            raise TrainingMaterialError(f"AI 调用失败: {e}") from e
        return self._parse_output(raw)

    @staticmethod
    def _parse_output(raw: Any) -> LectureOutput:
        if not isinstance(raw, dict):
            raise TrainingMaterialError(f"AI 输出非 dict: {type(raw).__name__}")
        title = str(raw.get("title") or "").strip()
        if not title:
            raise TrainingMaterialError("AI 输出缺 title")

        def _str_list(value: Any) -> list[str]:
            if isinstance(value, str):
                value = [value]
            return [str(v).strip() for v in (value or []) if str(v).strip()]

        sections: list[LectureSection] = []
        for row in raw.get("sections") or []:
            if not isinstance(row, dict):
                continue
            heading = str(row.get("heading") or "").strip()
            points = _str_list(row.get("points"))
            if heading or points:
                sections.append(LectureSection(heading=heading, points=points))
        if not sections:
            raise TrainingMaterialError("AI 输出缺 sections")
        return LectureOutput(
            title=title,
            objectives=_str_list(raw.get("objectives")),
            sections=sections,
            key_takeaways=_str_list(raw.get("key_takeaways")),
            references=_str_list(raw.get("references")),
        )


def validate_exam(result: Any, config: dict | None = None) -> dict[str, list[dict]]:
    """校验 AI 试卷结构，不合格抛 ValueError（上层降级）——语义对齐 HR
    _validate_exam（选项结构/answer 合法性/数量、超出截断），safety 侧独立
    实现，另保留每题 source 字段（材料来源标注）。
    """
    if not isinstance(result, dict):
        raise ValueError("AI 返回结果不是合法的试卷结构")

    expected = resolve_exam_counts(config)
    validated: dict[str, list[dict]] = {}
    for key in EXAM_QUESTION_KEYS:
        want = expected[key]
        if want <= 0:
            validated[key] = []
            continue
        qs = result.get(key, [])
        if not isinstance(qs, list) or not qs:
            raise ValueError(f"AI 未生成任何{key}")
        clean: list[dict] = []
        for q in qs[:want]:  # 超出截断
            if not isinstance(q, dict) or not str(q.get("question", "")).strip():
                raise ValueError(f"AI 生成的{key}缺少题干")
            item: dict = {"question": str(q["question"]).strip()}
            source = str(q.get("source") or "").strip()
            if source:
                item["source"] = source
            answer = str(q.get("answer", "")).strip()
            if not answer:
                raise ValueError(f"AI 生成的{key}缺少答案")
            if key in ("choice_questions", "multi_choice_questions"):
                options = q.get("options")
                if not isinstance(options, list) or len(options) < 2:
                    raise ValueError(f"AI 生成的{key}选项不足")
                labels: list[str] = []
                clean_opts: list[dict[str, str]] = []
                for opt in options:
                    if not isinstance(opt, dict) or not str(opt.get("text", "")).strip():
                        raise ValueError(f"AI 生成的{key}选项不合法")
                    label = str(opt.get("label", "")).strip().upper() or chr(65 + len(labels))
                    labels.append(label)
                    clean_opts.append({"label": label, "text": str(opt["text"]).strip()})
                item["options"] = clean_opts
                answers = [a.strip().upper() for a in answer.replace("，", ",").split(",") if a.strip()]
                if not answers or any(a not in labels for a in answers):
                    raise ValueError(f"AI 生成的{key}答案与选项不匹配: {answer}")
                item["answer"] = ",".join(answers)
            elif key == "true_false_questions":
                if answer in ("对", "是", "√", "T", "true", "True"):
                    answer = "正确"
                elif answer in ("错", "否", "×", "F", "false", "False"):
                    answer = "错误"
                if answer not in ("正确", "错误"):
                    raise ValueError(f"AI 生成的判断题答案不合法: {answer}")
                item["answer"] = answer
            else:
                item["answer"] = answer
            clean.append(item)
        validated[key] = clean
    return validated


class ExamPlugin:
    """材料（讲义要点+检索片段）→ 试卷。

    expected_keys 只列数量>0 的题型键——chat_parsed 对缺失键直接抛错
    （platform/integrations/ai/client.py），把缺省题型列进去会让默认
    路径（多选/填空=0）必失败。

    Args:
        ai_service: AuditedAIService 实例（create_ai_service("text") 返回）
    """

    def __init__(self, ai_service: Any):
        self.ai_service = ai_service

    async def generate(self, input_data: ExamInput) -> ExamOutput:
        counts = resolve_exam_counts(input_data.config)
        expected_keys = [k for k in EXAM_QUESTION_KEYS if counts[k] > 0]
        prompt = build_exam_user_prompt(
            material=input_data.material, config=input_data.config
        )
        messages = [
            {"role": "system", "content": EXAM_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=expected_keys,
                temperature=0.1,
            )
        except Exception as e:
            logger.error("试卷 AI 调用失败: %s", e)
            raise TrainingMaterialError(f"AI 调用失败: {e}") from e
        try:
            validated = validate_exam(raw, input_data.config)
        except ValueError as e:
            raise TrainingMaterialError(f"试卷校验失败: {e}") from e
        return ExamOutput(questions=validated)


__all__ = [
    "EXAM_QUESTION_KEYS",
    "LECTURE_EXPECTED_KEYS",
    "ExamPlugin",
    "LecturePlugin",
    "TrainingMaterialError",
    "validate_exam",
]

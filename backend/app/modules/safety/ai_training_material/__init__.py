"""AI 培训课件/试卷生成插件（链2）。

对外：LecturePlugin / ExamPlugin / 输入输出结构 / TrainingMaterialError /
validate_exam / EXAM_QUESTION_KEYS（键契约对齐 HR）。
"""

from app.modules.safety.ai_training_material.plugin import (
    EXAM_QUESTION_KEYS,
    LECTURE_EXPECTED_KEYS,
    ExamPlugin,
    LecturePlugin,
    TrainingMaterialError,
    validate_exam,
)
from app.modules.safety.ai_training_material.schemas import (
    ExamInput,
    ExamOutput,
    LectureInput,
    LectureOutput,
    LectureSection,
)

__all__ = [
    "EXAM_QUESTION_KEYS",
    "LECTURE_EXPECTED_KEYS",
    "ExamInput",
    "ExamOutput",
    "ExamPlugin",
    "LecturePlugin",
    "LectureInput",
    "LectureOutput",
    "LectureSection",
    "TrainingMaterialError",
    "validate_exam",
]

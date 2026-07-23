"""AI exam schemas."""

from pydantic import BaseModel, Field


class ChoiceOption(BaseModel):
    label: str  # A/B/C/D
    text: str


class ChoiceQuestion(BaseModel):
    number: int = 0
    question: str
    options: list[ChoiceOption]
    answer: str = ""


class TrueFalseQuestion(BaseModel):
    number: int = 0
    question: str
    answer: str = ""


class ExamGenerateResponse(BaseModel):
    choice_questions: list[ChoiceQuestion] = []
    true_false_questions: list[TrueFalseQuestion] = []


class ExamExportRequest(BaseModel):
    title: str = "培训考试试卷"
    examiner: str = ""
    exam_date: str = ""
    assessment_date: str = ""
    choice_questions: list[ChoiceQuestion] = []
    true_false_questions: list[TrueFalseQuestion] = []
    multi_choice_questions: list[ChoiceQuestion] = []
    fill_blank_questions: list[TrueFalseQuestion] = []

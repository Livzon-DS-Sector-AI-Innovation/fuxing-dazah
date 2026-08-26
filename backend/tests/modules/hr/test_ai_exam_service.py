"""AI 出题服务单元测试：材料解析、本地规则出题、AI 结果校验、AI/本地降级。"""

import pytest

from app.modules.hr import ai_exam_service
from app.modules.hr import config as hr_config

SAMPLE_TEXT = (
    "操作人员必须经过培训合格后才能上岗操作设备。"
    "设备日常检查应当包括润滑油位、温度、振动情况。"
    "禁止在设备运行时进行维修作业，必须先停机断电。"
    "安全管理人员负责监督检查操作规程的执行情况。"
    "新员工入厂必须接受三级安全教育培训，培训合格后方可上岗。"
    "车间应当定期组织应急演练，提高员工应急处置能力。"
)

CONFIG = {"choice_count": 3, "true_false_count": 3, "multi_choice_count": 1, "fill_blank_count": 2}


def test_parse_txt_file() -> None:
    content = ai_exam_service._parse_file(SAMPLE_TEXT.encode(), "材料.txt")
    assert content["full_text"] == SAMPLE_TEXT
    assert content["bold_texts"] == []


def test_generate_local_counts_and_structure() -> None:
    content = ai_exam_service._parse_file(SAMPLE_TEXT.encode(), "材料.txt")
    result = ai_exam_service._generate_local(content, CONFIG)
    assert len(result["choice_questions"]) <= CONFIG["choice_count"]
    assert len(result["true_false_questions"]) <= CONFIG["true_false_count"]
    for q in result["choice_questions"]:
        assert q["question"] and "____" in q["question"]
        assert q["answer"] in {o["label"] for o in q["options"]}
    for q in result["true_false_questions"]:
        assert q["answer"] in ("正确", "错误")


def test_generate_local_empty_text() -> None:
    content = ai_exam_service._parse_file("短。短。".encode(), "材料.txt")
    result = ai_exam_service._generate_local(content, CONFIG)
    assert result["choice_questions"] == []


def _valid_ai_result() -> dict:
    return {
        "choice_questions": [
            {
                "question": "操作人员上岗前必须经过____",
                "options": [
                    {"label": "A", "text": "培训合格"},
                    {"label": "B", "text": "领导批准"},
                    {"label": "C", "text": "自我学习"},
                    {"label": "D", "text": "无需准备"},
                ],
                "answer": "A",
            },
        ],
        "true_false_questions": [
            {"question": "设备运行时可以进行维修作业", "answer": "错误"},
        ],
        "multi_choice_questions": [],
        "fill_blank_questions": [
            {"question": "新员工必须接受三级____教育培训", "answer": "安全"},
        ],
    }


def test_validate_exam_accepts_valid_result() -> None:
    config = {"choice_count": 1, "true_false_count": 1, "multi_choice_count": 0, "fill_blank_count": 1}
    validated = ai_exam_service._validate_exam(_valid_ai_result(), config)
    assert len(validated["choice_questions"]) == 1
    assert validated["true_false_questions"][0]["answer"] == "错误"
    assert validated["fill_blank_questions"][0]["answer"] == "安全"


def test_validate_exam_normalizes_tf_answer() -> None:
    config = {"choice_count": 0, "true_false_count": 1, "multi_choice_count": 0, "fill_blank_count": 0}
    result = {"true_false_questions": [{"question": "说法？", "answer": "对"}]}
    validated = ai_exam_service._validate_exam(result, config)
    assert validated["true_false_questions"][0]["answer"] == "正确"


def test_validate_exam_rejects_bad_answer() -> None:
    config = {"choice_count": 1, "true_false_count": 0, "multi_choice_count": 0, "fill_blank_count": 0}
    bad = _valid_ai_result()
    bad["choice_questions"][0]["answer"] = "Z"
    with pytest.raises(ValueError):
        ai_exam_service._validate_exam(bad, config)


def test_validate_exam_rejects_missing_questions() -> None:
    config = {"choice_count": 2, "true_false_count": 0, "multi_choice_count": 0, "fill_blank_count": 0}
    with pytest.raises(ValueError):
        ai_exam_service._validate_exam({"choice_questions": []}, config)


async def test_generate_exam_uses_local_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hr_config, "HR_AI_API_KEY", "")
    result = await ai_exam_service.generate_exam(SAMPLE_TEXT.encode(), "材料.txt", CONFIG)
    assert result["choice_questions"] or result["true_false_questions"]
    assert result["choice_questions"][0]["number"] == 1 if result["choice_questions"] else True


async def test_generate_exam_uses_ai_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hr_config, "HR_AI_API_KEY", "sk-test")

    async def fake_call_json(prompt: str, system_prompt: str | None = None,
                             model: str | None = None, api_key: str | None = None) -> dict:
        assert api_key == "sk-test"
        return _valid_ai_result()

    monkeypatch.setattr("app.modules.hr.ai_service.AiChatService.call_json", fake_call_json)
    config = {"choice_count": 1, "true_false_count": 1, "multi_choice_count": 0, "fill_blank_count": 1}
    result = await ai_exam_service.generate_exam(SAMPLE_TEXT.encode(), "材料.txt", config)
    assert result["choice_questions"][0]["question"].startswith("操作人员上岗前必须经过")
    assert result["fill_blank_questions"][0]["number"] == 1


async def test_generate_exam_falls_back_when_ai_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hr_config, "HR_AI_API_KEY", "sk-test")

    async def broken_call_json(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("app.modules.hr.ai_service.AiChatService.call_json", broken_call_json)
    result = await ai_exam_service.generate_exam(SAMPLE_TEXT.encode(), "材料.txt", CONFIG)
    # 降级到本地规则出题，仍有题目产出
    assert result["choice_questions"] or result["true_false_questions"]


async def test_generate_exam_empty_file_raises() -> None:
    with pytest.raises(ValueError, match="未检测到文本内容"):
        await ai_exam_service.generate_exam(b"", "材料.txt")

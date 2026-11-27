"""共享题库（/question-bank）：手工录入、检索、软删、培训记录 docx 导入。"""

from io import BytesIO
from uuid import uuid4

from docx import Document
from httpx import AsyncClient

from tests.modules.hr.conftest import _rand


async def test_add_search_and_soft_delete(client: AsyncClient):
    """添加题目 → 关键词/文件编号检索 → 软删后不可见；未知 ID 删除 404。"""
    keyword = _rand("题")
    file_no = _rand("SOP")
    question = f"{keyword}型设备的清洁规程是什么？"
    res = await client.post("/api/v1/hr/question-bank", json={
        "items": [
            {"file_no": file_no, "question": question, "answer": "按SOP执行清洁", "score": 10},
            # 无题目的行被跳过
            {"file_no": file_no, "answer": "没有题目"},
        ],
        "source": "手工录入",
    })
    assert res.status_code == 200, res.text
    assert res.json()["data"]["inserted"] == 1

    by_kw = await client.get("/api/v1/hr/question-bank", params={"keyword": keyword})
    assert by_kw.status_code == 200
    rows = by_kw.json()["data"]
    assert len(rows) == 1
    item = rows[0]
    assert item["file_no"] == file_no
    assert item["question"] == question
    assert item["answer"] == "按SOP执行清洁"
    assert by_kw.json()["meta"]["total"] == 1

    by_file = await client.get("/api/v1/hr/question-bank", params={"file_no": file_no})
    assert len(by_file.json()["data"]) == 1

    dele = await client.delete(f"/api/v1/hr/question-bank/{item['id']}")
    assert dele.status_code == 200
    after = await client.get("/api/v1/hr/question-bank", params={"keyword": keyword})
    assert after.json()["data"] == []

    assert (await client.delete(f"/api/v1/hr/question-bank/{uuid4()}")).status_code == 404


def _build_training_docx(subject: str, file_no: str, question: str) -> bytes:
    """构造带「培训内容」表 + 问答记录表的培训记录 docx。"""
    doc = Document()

    info = doc.add_table(rows=1, cols=2)
    info.rows[0].cells[0].text = "培训内容"
    info.rows[0].cells[1].text = f"Training content {subject}"

    qa = doc.add_table(rows=4, cols=5)
    qa.rows[0].cells[0].text = "文件编号"
    qa.rows[0].cells[1].text = "考题"
    qa.rows[0].cells[2].text = "答案"
    qa.rows[1].cells[0].text = "1"
    qa.rows[1].cells[1].text = file_no
    qa.rows[1].cells[2].text = question
    qa.rows[1].cells[3].text = "按SOP执行"
    qa.rows[1].cells[4].text = "10"
    qa.rows[2].cells[0].text = "2"
    qa.rows[2].cells[1].text = file_no
    qa.rows[2].cells[2].text = f"{question}（追问）"
    qa.rows[2].cells[3].text = "复述一遍"
    qa.rows[2].cells[4].text = "10"
    qa.rows[3].cells[0].text = "姓名"  # 数据区结束行

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def test_import_docx_extracts_questions(client: AsyncClient):
    """上传培训记录 docx：提取主题与问答题目入库；重复导入去重跳过。"""
    subject = _rand("主题")
    file_no = _rand("SOPQ")
    question = f"{subject}对应的首问检查要点有哪些？"
    content = _build_training_docx(subject, file_no, question)

    res = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": (f"{subject}.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res.status_code == 201, res.text
    data = res.json()["data"]
    assert data["subject"] == subject
    assert data["total"] == 2
    assert data["imported"] == 2
    assert data["skipped"] == 0

    by_kw = await client.get("/api/v1/hr/question-bank", params={"keyword": question})
    rows = by_kw.json()["data"]
    assert len(rows) >= 1
    assert rows[0]["source"] == "docx_import"
    assert rows[0]["file_no"] == file_no

    # 重复导入：同 file_no + question 全部跳过
    res2 = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": (f"{subject}.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res2.status_code == 201
    assert res2.json()["data"]["imported"] == 0
    assert res2.json()["data"]["skipped"] == 2


async def test_import_docx_rejects_bad_inputs(client: AsyncClient):
    """非 .docx 文件 → 400；无问答表的 docx → 400。"""
    res = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
    assert ".docx" in res.json()["message"]

    doc = Document()  # 空文档：没有问答记录表
    buf = BytesIO()
    doc.save(buf)
    empty = await client.post(
        "/api/v1/hr/question-bank/import-docx",
        files={"file": ("empty.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert empty.status_code == 400
    assert "未从文档中提取到问答题目" in empty.json()["message"]

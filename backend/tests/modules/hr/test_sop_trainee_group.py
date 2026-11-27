"""SOP 培训材料「培训对象」口径测试。

总表材料：培训对象 = 「发起部门」全体成员及相关一级培训师；
二级表生成材料：默认「该部门」全体成员（含全部门口径病产假附注）；
条目按标签选人时写「xx部门 标签名」（如「xx部门 班组长」，多标签「、」连接），
并省略病产假附注（标签人员已排除病产假，全部门口径不适用）。
"""

import io
import json
import zipfile
from datetime import date
from uuid import uuid4

import pytest
from docx import Document


def _rand() -> str:
    return uuid4().hex[:8]


def _docx_text(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


def _docx_xml_text(content: bytes) -> str:
    """document.xml 原文（覆盖文本框等 python-docx 遍历不到的位置）。"""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _zip_files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _notif_input(**kw) -> "object":
    from app.modules.hr.schemas import TrainingNotificationInput
    return TrainingNotificationInput(
        department="甲部门", training_date=date(2026, 1, 1), subject="主题",
        trainee_names=["张三", "李四"], sick_count=1, maternity_count=2, **kw,
    )


class TestTraineeTextUnit:
    def test_notification_default_all_members(self):
        """缺省群体词=全体成员，病产假附注保留（培训通知页等既有入口行为不变）。"""
        from app.modules.hr.notification_document_generator import _compute_trainee_text
        assert _compute_trainee_text(_notif_input()) == (
            "「甲部门」全体成员（2人）（病假1人、产假2人除外）"
        )

    def test_notification_master_group(self):
        """总表材料：全体成员及相关一级培训师。"""
        from app.modules.hr.notification_document_generator import _compute_trainee_text
        assert _compute_trainee_text(_notif_input(trainee_group="全体成员及相关一级培训师")) == (
            "「甲部门」全体成员及相关一级培训师（2人）（病假1人、产假2人除外）"
        )

    def test_notification_labeled_group_omits_leave_note(self):
        """标签选人：群体词=标签名，附注省略。"""
        from app.modules.hr.notification_document_generator import _compute_trainee_text
        data = _notif_input(trainee_group="班组长", omit_leave_note=True)
        assert _compute_trainee_text(data) == "「甲部门」班组长（2人）"

    def test_signin_same_rules(self):
        from app.modules.hr.schemas import TrainingSignInSheetInput
        from app.modules.hr.signin_document_generator import _compute_trainee_text

        base = dict(training_date=date(2026, 1, 1), department="甲部门", topic="内容")
        default = TrainingSignInSheetInput(**base, sick_count=1, maternity_count=2)
        assert _compute_trainee_text(default) == "「甲部门」全体成员（病假1人、产假2人除外）"
        labeled = TrainingSignInSheetInput(**base, trainee_group="班组长", omit_leave_note=True)
        assert _compute_trainee_text(labeled) == "「甲部门」班组长"

    async def test_evaluation_and_qa_record_group(self):
        """评估表/问答实操记录表与同套材料同口径。"""
        from app.modules.hr.evaluation_document_generator import (
            TrainingEvaluationInput,
            generate_training_evaluation,
        )
        from app.modules.hr.qa_record_generator import generate_qa_record

        ev = generate_training_evaluation(TrainingEvaluationInput(
            subject="主题", department="甲部门", trainee_names=["张三"],
            trainee_group="班组长",
        ))
        assert "「甲部门」班组长（1人）" in _docx_xml_text(ev.getvalue())

        qa = generate_qa_record(
            training_content="主题", training_department="甲部门",
            trainee_names=["张三"], trainee_group="班组长",
        )
        assert "「甲部门」班组长" in _docx_xml_text(qa.getvalue())

        # 缺省回落全体成员（历史行为）
        qa_default = generate_qa_record(
            training_content="主题", training_department="甲部门",
            trainee_names=["张三"],
        )
        assert "「甲部门」全体成员" in _docx_xml_text(qa_default.getvalue())


class TestBatchMaterialsTraineeGroup:
    async def _make_entry(self, db_session, classification: str | None):
        from app.modules.hr.models import SopTrainingEntry, SopTrainingRecord
        rec = SopTrainingRecord(
            year="2026", file_name=f"对象口径{_rand()}", file_no=f"SOP-TG-{_rand()}",
            method="T", assessment_method="问答",
            involved_departments=json.dumps(["甲部门"]), status="已提交",
            initiator_department="甲部门",
        )
        db_session.add(rec)
        await db_session.flush()
        entry = SopTrainingEntry(
            record_id=str(rec.id), department="甲部门", classification=classification,
            personnel=json.dumps([{"name": "张三", "employee_number": f"T{_rand()}"}]),
        )
        db_session.add(entry)
        await db_session.flush()
        return entry

    @pytest.mark.asyncio
    async def test_labeled_entry_writes_dept_tag(self, db_session, client):
        """条目按标签「班组长」选人：材料培训对象写「xx部门 班组长」，无病产假附注。"""
        entry = await self._make_entry(db_session, "班组长")
        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(entry.id)]},
        )
        assert res.status_code == 200, res.text
        files = _zip_files(res.content)
        notif_text = _docx_text(files["培训通知.docx"])
        assert "「甲部门」班组长" in notif_text
        assert "全体成员" not in notif_text
        assert "病假" not in notif_text
        # 同套问答实操记录表同口径
        assert "「甲部门」班组长" in _docx_text(files["问答实操记录表.docx"])

    @pytest.mark.asyncio
    async def test_unlabeled_entry_falls_back_all_members(self, db_session, client):
        """条目无标签（历史形态）：回落「全体成员」+ 病产假附注。"""
        entry = await self._make_entry(db_session, None)
        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(entry.id)]},
        )
        assert res.status_code == 200, res.text
        notif_text = _docx_text(_zip_files(res.content)["培训通知.docx"])
        assert "「甲部门」全体成员" in notif_text
        assert "病假" in notif_text

    @pytest.mark.asyncio
    async def test_mixed_labels_joined(self, db_session, client):
        """多条不同标签：「、」连接。"""
        e1 = await self._make_entry(db_session, "班组长")
        e2 = await self._make_entry(db_session, "操作工")
        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(e1.id), str(e2.id)]},
        )
        assert res.status_code == 200, res.text
        notif_text = _docx_text(_zip_files(res.content)["培训通知.docx"])
        assert "「甲部门」班组长、操作工" in notif_text


class TestMasterMaterialsTraineeGroup:
    @pytest.mark.asyncio
    async def test_master_writes_initiator_and_trainers(self, db_session, client):
        """总表材料：培训对象 = 「发起部门」全体成员及相关一级培训师。"""
        from app.modules.hr.models import SopTrainingRecord, TrainingRosterProfile

        dept = f"对象口径部{_rand()}"
        db_session.add(TrainingRosterProfile(
            name="在册甲", employee_number=f"N{_rand()}", department=dept,
            position="工程师", status="在职",
        ))
        await db_session.flush()
        rec = SopTrainingRecord(
            year="2026", file_name=f"总表对象{_rand()}", file_no=f"SOP-TG-{_rand()}",
            method="T", assessment_method="阅读并理解",
            involved_departments=json.dumps([dept]), status="已提交",
            initiator_department=dept,
        )
        db_session.add(rec)
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        notif_text = _docx_text(_zip_files(res.content)["培训通知.docx"])
        assert f"「{dept}」全体成员及相关一级培训师" in notif_text
        # 主办部门在册人员出现在签到表名单里
        sign_text = _docx_text(_zip_files(res.content)["培训签到表.docx"])
        assert "在册甲" in sign_text

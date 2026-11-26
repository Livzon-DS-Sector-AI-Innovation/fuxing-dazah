"""培训导出模板自维护：注册表一致性 / 上传校验 / 版本化加载 / 标记化生成器端到端。"""

from io import BytesIO

import pytest
from docx import Document

from app.core.exceptions import AppException
from app.modules.hr import training_template_store as store
from app.modules.hr.docx_markers import find_missing_markers
from app.modules.hr.template_utils import find_hr_template_bytes
from app.modules.hr.training_template_registry import TEMPLATES

# ───────────────────────── 注册表 ↔ 默认模板一致性 ─────────────────────────


class TestRegistryConsistency:
    def test_default_files_exist_with_required_markers(self):
        """每个注册模板的默认文件存在，且包含全部必填标记（防标记漂移）。

        用与上传校验同一份 find_missing_markers（兼容日期过滤器写法）。
        """
        for tdef in TEMPLATES:
            data = find_hr_template_bytes(tdef.key)
            assert data.startswith(b"PK"), f"{tdef.key} 默认文件不是 docx"
            missing = find_missing_markers(tdef.required_markers, data)
            assert not missing, f"{tdef.key} 默认模板缺少必填标记: {missing}"

    def test_keys_unique(self):
        keys = [t.key for t in TEMPLATES]
        assert len(keys) == len(set(keys))


# ───────────────────────── 上传校验 ─────────────────────────


def _default_bytes(key: str) -> bytes:
    return find_hr_template_bytes(key)


class TestUploadValidation:
    async def test_non_docx_rejected(self, db_session):
        with pytest.raises(AppException, match="仅支持"):
            await store.upload_training_template(db_session, "training_notification", "x.txt", b"hello")

    async def test_corrupt_docx_rejected(self, db_session):
        # PK 头都凑不齐：魔数校验直接拒绝（能过魔数但解析失败的路径由 validate_upload 拦截）
        with pytest.raises(AppException, match="损坏|无法解析"):
            await store.upload_training_template(
                db_session, "training_notification", "x.docx", b"PK\x03\x04 not a zip",
            )

    async def test_missing_required_marker_rejected(self, db_session):
        """删掉 {授课单位_培训师} 标记后上传必须被拒，且提示缺失标记名。"""
        from app.modules.hr.docx_markers import replace_markers

        doc = Document(BytesIO(_default_bytes("training_notification")))
        replace_markers(doc, {"{授课单位_培训师}": ""})
        buf = BytesIO()
        doc.save(buf)
        with pytest.raises(AppException, match="授课单位_培训师"):
            await store.upload_training_template(
                db_session, "training_notification", "坏模板.docx", buf.getvalue(),
            )

    async def test_unknown_key_404(self, db_session):
        data = _default_bytes("training_notification")
        with pytest.raises(AppException):
            await store.upload_training_template(db_session, "no_such_key", "x.docx", data)


# ───────────────────────── 版本化加载 ─────────────────────────


class TestLoaderAndVersions:
    async def test_fallback_to_default_without_custom(self, db_session):
        data, source = await store.load_training_template_bytes(db_session, "roster")
        assert source == "default"
        assert data == _default_bytes("roster")

    async def test_upload_creates_version_and_loader_prefers_custom(self, db_session):
        from app.core.file_storage import delete_object

        storage_keys: list[str] = []
        try:
            # 改造默认模板：插入自定义静态文案（保留全部标记）
            doc = Document(BytesIO(_default_bytes("roster")))
            first_para = doc.paragraphs[0] if doc.paragraphs else None
            if first_para is not None:
                first_para.add_run("自定义版本测试标记XYZ")
            buf = BytesIO()
            doc.save(buf)
            payload = buf.getvalue()

            row = await store.upload_training_template(
                db_session, "roster", "花名册自定义模板.docx", payload, remark="测试",
            )
            storage_keys.append(row.storage_key)
            assert row.version_no == 1 and row.is_current
            assert row.file_name == "花名册自定义模板.docx"

            data, source = await store.load_training_template_bytes(db_session, "roster")
            assert source == "custom" and data == payload

            # 再传一版：版本号递增、旧版转历史
            row2 = await store.upload_training_template(db_session, "roster", "v2.docx", payload)
            storage_keys.append(row2.storage_key)
            assert row2.version_no == 2 and row2.is_current
            await db_session.flush()
            versions = await store.list_versions(db_session, "roster")
            assert [v.version_no for v in versions] == [2, 1]
            assert versions[0].is_current and not versions[1].is_current

            # 回滚激活 v1
            await store.activate_version(db_session, "roster", row.id)
            current = await store.get_current_version(db_session, "roster")
            assert current is not None and current.version_no == 1

            # 恢复默认 → 无当前版，加载回退仓库模板
            await store.restore_default(db_session, "roster")
            assert await store.get_current_version(db_session, "roster") is None
            data, source = await store.load_training_template_bytes(db_session, "roster")
            assert source == "default" and data == _default_bytes("roster")
        finally:
            # DB 行随事务回滚；本地上传目录里的对象文件手动清理
            for key in storage_keys:
                delete_object(store.MODULE, key)


# ───────────────────────── 标记化生成器端到端 ─────────────────────────


class TestMarkerGeneratorsWithCustomTemplate:
    def _modified_notification(self, extra_text: str) -> bytes:
        doc = Document(BytesIO(_default_bytes("training_notification")))
        doc.paragraphs[0].add_run(extra_text)
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_notification_uses_custom_static_text(self):
        """自定义模板的静态文案出现在导出里（证明字节真正被采用）。"""
        from datetime import date

        from app.modules.hr.notification_document_generator import (
            TrainingNotificationInput,
            generate_training_notification,
        )

        payload = TrainingNotificationInput(
            department="发酵车间", training_date=date(2026, 12, 15), subject="GMP 培训",
            time_slots=[{"date": "2026-12-15", "start": "08:00", "end": "12:00"}],
        )
        custom_bytes = self._modified_notification("自定义文案XYZ")
        doc = Document(BytesIO(generate_training_notification(payload, template_bytes=custom_bytes).getvalue()))
        assert "自定义文案XYZ" in doc.paragraphs[0].text
        assert "GMP 培训" in doc.tables[0].rows[0].cells[1].text

        # 默认模板不含该文案
        doc2 = Document(BytesIO(generate_training_notification(payload).getvalue()))
        assert "自定义文案XYZ" not in doc2.paragraphs[0].text

    def test_evaluation_rate_sentence_hidden_when_both_rates_missing(self):
        from datetime import date

        from app.modules.hr.evaluation_document_generator import (
            TrainingEvaluationInput,
            generate_training_evaluation,
        )

        doc = Document(BytesIO(generate_training_evaluation(TrainingEvaluationInput(
            subject="GMP", training_date=date(2026, 12, 15),
        )).getvalue()))
        cell_text = doc.tables[0].rows[15].cells[1].text
        assert "参训人员参与率" not in cell_text  # 整句隐藏
        assert "{" not in cell_text  # 无残留标记

    def test_qa_record_with_questions_and_blank_rows(self):
        from app.modules.hr.qa_record_generator import generate_qa_record

        # 有题：逐题一行
        doc = Document(BytesIO(generate_qa_record(
            training_content="GMP", training_purpose="目的X", training_date=None,
            questions=[
                {"file_no": "SOP.1", "question": "Q1", "answer": "A1", "score": 5},
                {"file_no": "SOP.2", "question": "Q2", "answer": "A2", "score": 5},
            ],
            trainee_names=["张三"],
        ).getvalue()))
        table = doc.tables[0]
        texts = [c.text for row in table.rows for c in row.cells]
        assert any("Q1" in t for t in texts) and any("Q2" in t for t in texts)
        assert any("目的X" in t for t in texts)
        assert not any("{" in t for t in texts)  # 无残留标记

        # 无题：保留 5 个空白行
        doc2 = Document(BytesIO(generate_qa_record(training_content="GMP").getvalue()))
        texts2 = [c.text for row in doc2.tables[0].rows for c in row.cells]
        assert not any("{" in t for t in texts2)

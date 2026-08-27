"""bitable_client 兼容 shim：token/table_id 粘贴脏数据清理（防 TableIdNotFound）。"""

from app.modules.hr.title_review import bitable_client
from app.modules.hr.title_review.schemas import (
    TitleReviewActivityCreate,
    TitleReviewActivityUpdate,
)


async def test_list_fields_strips_pasted_whitespace(monkeypatch):
    """粘贴的 app_token/table_id 带首尾空格时，请求前去掉（修复线上存量脏数据）。"""
    captured: dict[str, str] = {}

    async def fake_list_fields(app_token, table_id, **kwargs):
        captured["app_token"] = app_token
        captured["table_id"] = table_id
        return []

    monkeypatch.setattr(
        "app.platform.integrations.feishu.bitable.list_fields", fake_list_fields
    )
    await bitable_client.list_fields(" HKb0bhufoab2wwsblj1c9qxgnPI ", " tblq63r6qdlICQaJ  ")
    assert captured == {
        "app_token": "HKb0bhufoab2wwsblj1c9qxgnPI",
        "table_id": "tblq63r6qdlICQaJ",
    }


def test_create_schema_strips_pasted_tokens():
    data = TitleReviewActivityCreate(
        name="2026年度技术职级评定",
        feishu_app_token=" HKb0bhufoab2wwsblj1c9qxgnPI ",
        apply_table_id=" tblq63r6qdlICQaJ  ",
        vote_table_id="\ttblv1234567890\n",
        approval_code=" 2026PJ ",
    )
    assert data.feishu_app_token == "HKb0bhufoab2wwsblj1c9qxgnPI"
    assert data.apply_table_id == "tblq63r6qdlICQaJ"
    assert data.vote_table_id == "tblv1234567890"
    assert data.approval_code == "2026PJ"


def test_update_schema_strips_pasted_tokens():
    data = TitleReviewActivityUpdate(apply_table_id=" tblq63r6qdlICQaJ ")
    assert data.apply_table_id == "tblq63r6qdlICQaJ"


def test_schema_rejects_malformed_table_id():
    """table_id 粘贴丢首字母（blq... 而非 tbl...）在入库前被拦截。"""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="table_id 格式不正确"):
        TitleReviewActivityCreate(name="x", apply_table_id="blq63r6qdlICQaJ")
    with pytest.raises(ValidationError, match="table_id 格式不正确"):
        TitleReviewActivityUpdate(vote_table_id=" bl1Pq5TUgZBgZ3 ")


def test_schema_rejects_malformed_app_token():
    """app_token 非字母数字或长度越界在入库前被拦截。"""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="app_token 格式不正确"):
        TitleReviewActivityCreate(name="x", feishu_app_token="HKb0b!")
    with pytest.raises(ValidationError, match="app_token 格式不正确"):
        TitleReviewActivityUpdate(feishu_app_token="HKb0")

"""底座附件能力单测（票据 08：从 legacy bitable_handler 迁移过来）。"""

from __future__ import annotations

import json
import urllib.parse

from app.modules.safety.service.bitable_direct import attachments


class TestBuildAttachmentExtra:
    def test_matches_feishu_required_shape(self) -> None:
        raw = attachments.build_attachment_extra("tblX", "recY", "fldZ", "tok1")

        decoded = json.loads(urllib.parse.unquote(raw))

        assert decoded == {
            "bitablePerm": {
                "tableId": "tblX",
                "attachments": {"fldZ": {"recY": ["tok1"]}},
            }
        }

    def test_is_url_encoded_without_spaces(self) -> None:
        raw = attachments.build_attachment_extra("t", "r", "f", "tok")

        assert " " not in raw
        assert "%" in raw

    def test_matches_legacy_implementation_byte_for_byte(self) -> None:
        """与 legacy 实现（json.dumps separators 紧凑 + quote）逐字节一致。"""
        expected = urllib.parse.quote(
            json.dumps(
                {
                    "bitablePerm": {
                        "tableId": "tbl1",
                        "attachments": {"fld1": {"rec1": ["tk"]}},
                    }
                },
                separators=(",", ":"),
            )
        )

        assert (
            attachments.build_attachment_extra("tbl1", "rec1", "fld1", "tk") == expected
        )
